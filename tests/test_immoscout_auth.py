from pathlib import Path
import tempfile
import unittest

import yaml

from src.immoscout_auth import ImmoScoutAuth


class AuthTests(unittest.TestCase):
    def load(self, auth, require_login=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump({"immoscout": {"auth": auth}}))
            return ImmoScoutAuth.from_yaml(path, require_login=require_login)

    def test_login_cookies_are_private_and_host_scoped(self):
        auth = self.load({"cookies": {"SSO": "private-session", "SSO-HMAC": "signature"}}, True)
        self.assertNotIn("private-session", repr(auth))
        session = auth.session()
        try:
            self.assertEqual({c.name for c in session.cookies}, {"SSO", "SSO-HMAC"})
            self.assertTrue(all(c.domain == "www.immobilienscout24.de" and c.secure for c in session.cookies))
        finally:
            session.close()

    def test_empty_auth_is_valid_for_public_search_only(self):
        self.assertEqual(self.load({"cookies": {"SSO": "", "SSO-HMAC": ""}}).cookies, {})
        with self.assertRaisesRegex(ValueError, "SSO"):
            self.load({}, True)

    def test_bad_headers_and_tracking_cookies_are_rejected(self):
        for auth in [{"cookies": {"SSO": "bad;value"}}, {"cookies": {"SSO": 123}},
                     {"cookies": {"_ga": "tracking"}}, {"user_agent": "bad\r\nheader"}]:
            with self.subTest(auth=auth), self.assertRaises(ValueError):
                self.load(auth)

    def test_generated_and_unnecessary_cookies_are_not_configurable(self):
        for name in ("aws-waf-token", "websessionid", "AWSALB", "AWSALBCORS",
                     "X-XSRF-CONSUMER_ENTITLEMENT-TOKEN", "X-XSRF-TENANT-NETWORK-TOKEN"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.load({"cookies": {name: "value"}})


if __name__ == "__main__":
    unittest.main()
