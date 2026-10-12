"""Make sure apartment applications receive the right personalization context."""

import unittest

from src.llm_helper import LLMHelper


class ContextTests(unittest.TestCase):
    def test_apartment_context_keeps_user_facts_and_recipient(self):
        helper = object.__new__(LLMHelper)
        template = "Moin {name}, mein Job beginnt am 1. Februar 2027."
        prompt = helper._build_prompt(template, {
            "platform": "ImmoScout24", "listing_type": "Wohnung", "title": "Neubau am Südkreuz",
        }, "Torben")
        self.assertIn("Wohnungsbewerber", prompt)
        self.assertIn("ImmoScout24", prompt)
        self.assertIn(template, prompt)
        self.assertIn("EMPFÄNGER: Torben", prompt)
        self.assertNotIn("WG-Bewerber", prompt)

    def test_existing_wg_context_remains_default(self):
        helper = object.__new__(LLMHelper)
        prompt = helper._build_prompt("Hallo {name}", {"title": "WG-Zimmer"}, "Alex")
        self.assertIn("WG-Bewerber", prompt)
        self.assertIn("WG-ANZEIGE", prompt)


if __name__ == "__main__":
    unittest.main()
