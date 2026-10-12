from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.daily_message_limit import DailyMessageLimit, DailyMessageLimitReached
from src.bot import WgGesuchtBot
import probe_immoscout_contact


class DailyLimitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "counts.json"

    def quota(self, platform="immoscout", limit=2, clock=None):
        return DailyMessageLimit(platform, limit, self.path, clock)

    def test_limit_persists_across_new_instances_and_is_platform_specific(self):
        self.quota().reserve()
        self.quota().reserve()
        self.assertEqual(self.quota().remaining(), 0)
        with self.assertRaises(DailyMessageLimitReached):
            self.quota().reserve()
        self.assertEqual(self.quota("wg_gesucht").remaining(), 2)

    def test_resets_at_berlin_midnight_not_utc_midnight(self):
        before = lambda: datetime(2026, 10, 12, 21, 59, tzinfo=timezone.utc)
        after = lambda: datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc)
        self.quota(limit=1, clock=before).reserve()
        self.assertEqual(self.quota(limit=1, clock=before).remaining(), 0)
        self.assertEqual(self.quota(limit=1, clock=after).remaining(), 1)

    def test_parallel_reservations_cannot_exceed_limit(self):
        def reserve(_):
            try:
                self.quota().reserve()
                return True
            except DailyMessageLimitReached:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(8)))
        self.assertEqual(sum(results), 2)

    def test_zero_invalid_limits_and_corrupt_state_fail_closed(self):
        with self.assertRaises(DailyMessageLimitReached):
            self.quota(limit=0).reserve()
        for limit in (-1, True, "5"):
            with self.assertRaises(ValueError):
                self.quota(limit=limit)
        self.path.write_text("invalid JSON")
        with self.assertRaises(ValueError):
            self.quota().reserve()
        self.assertEqual(self.path.read_text(), "invalid JSON")

    def test_wg_send_loop_stops_at_daily_limit(self):
        bot = WgGesuchtBot.__new__(WgGesuchtBot)
        bot.config = {"settings": {"dry_run": False, "max_messages_per_run": 3,
                                   "max_messages_per_day": 1, "delay_between_messages": 0}}
        bot.login = Mock(return_value=True)
        bot._find_city_id = Mock(return_value="city")
        bot._collect_filtered_offers = Mock(return_value=[{"id": str(i)} for i in range(3)])
        bot._prepare_message = Mock(return_value="Test")
        bot._save_contacted = Mock()
        bot.contacted_ids = set()
        bot.llm = None
        bot.client = Mock()
        bot.client.contact_offer.return_value = True
        quota = self.quota("wg_gesucht", 1)
        with patch("src.bot.DailyMessageLimit", return_value=quota), patch("src.bot.get_logger", return_value=Mock()):
            self.assertEqual(bot.run(), 1)
        bot.client.contact_offer.assert_called_once()
        self.assertEqual(quota.remaining(), 0)

    def test_contact_probe_blocks_before_network_when_limit_is_reached(self):
        with patch("sys.argv", ["probe", "--send", "--listing-url", "https://www.immobilienscout24.de/expose/123"]), \
             patch("probe_immoscout_contact.DailyMessageLimit.from_yaml", return_value=self.quota(limit=0)), \
             patch("probe_immoscout_contact.ImmoScoutAuth.from_yaml") as auth, redirect_stdout(io.StringIO()):
            self.assertEqual(probe_immoscout_contact.main(), 1)
            auth.assert_not_called()
