from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from run_immoscout import run_once, run_lock, needs_wbs, formal_message
from src.immoscout_contact import ContactForm, ImmoScoutDeliveryUnknown
from src.immoscout_web_api import SearchPage


def listing(identifier="new", **values):
    return {"id": identifier, "title": "Wohnung mit Balkon", "url": "https://www.immobilienscout24.de/expose/123",
            "city": "Berlin", "district": "Mitte (Mitte)", "warm_rent": 1000,
            "rent": 1000, "size": 50, "rooms": 2, "paywall_active": False, **values}


def form(**values):
    return ContactForm("https://www.immobilienscout24.de/expose/123",
                       {"nonceToken": "fresh", "personalData": {"profileType": "BASIC"}},
                       {"message": "OPTIONAL"}, True, "Test", "Wohnung mit Balkon", **values)


class OneRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "config.yaml"
        self.config = {"immoscout": {"search": {"max_pages": 2},
                                     "settings": {"max_messages_per_day": 5, "max_messages_per_run": 2,
                                                  "delay_between_messages": 0}}, "llm": {"enabled": False}}
        self.write_config()
        (self.root / "message_immoscout.txt").write_text("Hallo {name}, ich interessiere mich für die Wohnung. Liebe Grüße Test")
        self.auth = Mock(user_agent="UA")
        self.web = Mock()
        self.web.headers = {"User-Agent": "refreshed-UA"}
        self.web.search.side_effect = lambda *args, **kwargs: SearchPage([listing()], 1, 20, 1, 1, None)
        self.client = Mock()
        self.client.get_form.side_effect = lambda *args: form()
        for name, value in [("ImmoScoutAuth.from_yaml", self.auth),
                            ("ImmoScoutWebClient", self.web),
                            ("ImmoScoutContactClient", self.client),
                            ("LLMHelper.from_config", None)]:
            p = patch("run_immoscout." + name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def write_config(self):
        self.config_path.write_text(yaml.safe_dump(self.config))

    def run_bot(self, send=True):
        with redirect_stdout(io.StringIO()):
            return run_once(self.config_path, send=send, root=self.root)

    def test_success_records_and_skips_on_restart_without_touching_wg_history(self):
        original = {"contacted_ids": ["wg123"]}
        (self.root / "contacted.json").write_text(json.dumps(original))
        self.assertEqual(self.run_bot(), 1)
        self.assertEqual(self.run_bot(), 0)
        self.client.send.assert_called_once()
        self.assertEqual(json.loads((self.root / "immoscout_contacts.json").read_text())["new"]["status"], "sent")
        self.assertEqual(json.loads((self.root / "contacted.json").read_text()), original)

    def test_existing_live_application_is_imported_and_skipped(self):
        (self.root / "contacted.json").write_text(json.dumps({"contacted_ids": [], "is24:new": {"sent_at": "old"}}))
        self.assertEqual(self.run_bot(), 0)
        self.client.send.assert_not_called()

    def test_unknown_delivery_is_not_retried_and_consumes_daily_slot(self):
        self.client.send.side_effect = ImmoScoutDeliveryUnknown("Unknown delivery")
        with self.assertRaises(ImmoScoutDeliveryUnknown):
            self.run_bot()
        self.assertEqual(json.loads((self.root / "immoscout_contacts.json").read_text())["new"]["status"], "unknown")
        self.assertEqual(self.run_bot(), 0)
        self.client.send.assert_called_once()
        counts = json.loads((self.root / "daily_message_counts.json").read_text())
        self.assertEqual(sum(day["immoscout"] for day in counts.values()), 1)

    def test_dry_run_does_not_send_record_or_consume_quota(self):
        self.assertEqual(self.run_bot(send=False), 0)
        self.client.send.assert_not_called()
        self.assertFalse((self.root / "immoscout_contacts.json").exists())
        self.assertFalse((self.root / "daily_message_counts.json").exists())

    def test_filter_empty_page_continues_to_next_page(self):
        self.web.search.side_effect = None
        self.web.search.return_value = SearchPage([listing(warm_rent=2000)], 1, 20, 2, 2, "next")
        self.web.search_url.return_value = SearchPage([listing()], 2, 20, 2, 2, None)
        self.assertEqual(self.run_bot(), 1)
        self.web.search_url.assert_called_once_with("next", skip_paywalled=False)

    def test_wbs_premium_and_tausch_are_skipped_before_personalization(self):
        self.web.search.side_effect = None
        self.web.search.return_value = SearchPage([listing("wbs", title="WBS 220 erforderlich"),
            listing("premium"), listing("tausch", title="Tauschwohnung"), listing()], 1, 20, 1, 4, None)
        self.client.get_form.side_effect = [form(), form(premium_required=True), form(), form(), form()]
        self.assertEqual(self.run_bot(), 1)
        self.client.send.assert_called_once()
        self.assertFalse(needs_wbs(form(), "Wohnung ohne WBS"))
        self.assertTrue(needs_wbs(form(wbs_required=True), "Wohnung"))

    def test_daily_limit_caps_run_and_blocks_next_run_before_network(self):
        self.config["immoscout"]["settings"]["max_messages_per_day"] = 1
        self.write_config()
        self.web.search.side_effect = lambda *a, **k: SearchPage([listing("first"), listing("second")], 1, 20, 1, 2, None)
        self.assertEqual(self.run_bot(), 1)
        self.assertEqual(self.run_bot(), 0)
        self.client.send.assert_called_once()
        self.web.search.assert_called_once()

    def test_gemini_personalization_is_used_and_nonce_reloaded(self):
        self.config["llm"] = {"enabled": True, "api_key": "fake", "provider": "gemini"}
        self.write_config()
        llm = Mock()
        llm._generate_text.return_value = "Hallo Test, ich interessiere mich für die Wohnung mit Balkon. Liebe Grüße Test"
        with patch("run_immoscout.LLMHelper.from_config", return_value=llm):
            self.assertEqual(self.run_bot(), 1)
        payload = self.client.send.call_args.args[0].payload
        self.assertEqual(payload["personalData"]["message"], formal_message(llm._generate_text.return_value, form()))
        self.assertEqual(self.client.get_form.call_count, 2)

    def test_llm_failure_stops_without_post_or_quota(self):
        llm = Mock()
        llm._generate_text.side_effect = RuntimeError("private provider error")
        with patch("run_immoscout.LLMHelper.from_config", return_value=llm), self.assertRaisesRegex(ValueError, "personalization failed"):
            self.run_bot()
        self.client.send.assert_not_called()
        self.assertFalse((self.root / "daily_message_counts.json").exists())

    def test_parallel_runs_are_blocked(self):
        with run_lock(self.root):
            with self.assertRaisesRegex(ValueError, "already active"):
                with run_lock(self.root):
                    pass

    def test_formal_greeting_keeps_single_line_body_and_does_not_duplicate_greetings(self):
        person = form(recipient_last_name="Müller", recipient_salutation="Frau")
        self.assertEqual(formal_message("Moin Test, ich suche eine Wohnung.", person),
                         "Sehr geehrte Frau Müller,\nich suche eine Wohnung.")
        message = "Sehr geehrte Frau Müller,\n\nich suche eine Wohnung."
        self.assertEqual(formal_message(message, person), message)


if __name__ == "__main__":
    unittest.main()
