"""Verify nonce selection, applicant validation, and unambiguous delivery status."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import requests

from src.immoscout_contact import (
    ContactCapture, ContactForm, ImmoScoutContactClient, ImmoScoutContactError,
    ImmoScoutDeliveryUnknown, parse_contact_form, prepare_contact,
)


URL = "https://www.immobilienscout24.de/expose/123"
HTML = '''<script>IS24.expose = {nonceToken: "wrong-expose-nonce"};</script>
<script>IS24.contactLayerModel = {
 userProfile: { enabled: true, exists: true },
 extendedContactForm: { configuration: {"firstName":"MANDATORY", "lastName":"MANDATORY",
 "emailAddress":"MANDATORY", "salutation":"MANDATORY", "message":"OPTIONAL", "hasPets":"MANDATORY"} },
 contactForm: {"nonceToken":"fresh-contact-nonce", "suspiciousRequest":false,
 "captchaData":{"captchaId":null}, "personalData":{"firstName":"", "lastName":"",
 "emailAddress":"", "salutation":"", "hasPets":null, "profileType":"BASIC"}}
};</script>'''
PROFILE = {"firstname": "Test", "lastname": "Applicant", "email": "test@example.com",
           "salutation": "MALE", "pets": False}


class ContactTests(unittest.TestCase):
    def test_formal_salutation_requires_explicit_gender_and_last_name(self):
        form = parse_contact_form(HTML, URL)
        for last_name, gender, expected in [
            ("Müller", "Frau", "Sehr geehrte Frau Müller"),
            ("Schmidt", "Herr", "Sehr geehrter Herr Schmidt"),
            ("Schmidt", "MALE", "Sehr geehrter Herr Schmidt"),
            ("Müller", "", "Sehr geehrte Damen und Herren"),
            ("", "Frau", "Sehr geehrte Damen und Herren"),
            ("Example GmbH", "Herr", "Sehr geehrte Damen und Herren"),
        ]:
            form.recipient_last_name, form.recipient_salutation = last_name, gender
            self.assertEqual(form.formal_salutation(), expected)

    def test_realtor_full_name_and_salutation_are_parsed(self):
        html = HTML.replace(' userProfile:', ' realtor: {"firstName":"Test","lastName":"Müller","salutation":"Frau"}, userProfile:')
        form = parse_contact_form(html, URL)
        self.assertEqual(form.formal_salutation(), "Sehr geehrte Frau Müller")

    def prepared(self):
        return prepare_contact(parse_contact_form(HTML, URL), "Application text", PROFILE)

    def test_correct_contact_nonce_and_profile_aliases(self):
        prepared = self.prepared()
        self.assertEqual(prepared.payload["nonceToken"], "fresh-contact-nonce")
        self.assertEqual(prepared.payload["personalData"]["firstName"], "Test")
        self.assertFalse(prepared.payload["personalData"]["hasPets"])
        self.assertTrue(prepared.payload["userProfileExists"])
        self.assertFalse(prepared.payload["sendUserProfile"])

    def test_mandatory_fields_are_checked_before_sending(self):
        with self.assertRaisesRegex(ImmoScoutContactError, "lastName"):
            prepare_contact(parse_contact_form(HTML, URL), "Application", {**PROFILE, "lastname": ""})

    def test_description_excludes_style_and_script_content(self):
        html = HTML + '''<div id="is24-description-section"><style>.secret {color:red}</style>
        <h3>Objektbeschreibung</h3><p>Wohnung am Südkreuz.</p>
        <script>doNotIncludeThis()</script></div><p>Footer</p>'''
        form = parse_contact_form(html, URL)
        self.assertEqual(form.description, "Objektbeschreibung\nWohnung am Südkreuz.")

    def test_contact_verification_is_not_suppressed(self):
        with self.assertRaises(ImmoScoutContactError):
            parse_contact_form(HTML.replace('"suspiciousRequest":false', '"suspiciousRequest":true'), URL)

    def test_premium_contact_is_blocked_before_submission(self):
        for flag in ('isFreemium: true,', 'applyButtonFeatureSwitches: {ppaWithPremiumProfile: true},'):
            form = parse_contact_form(HTML.replace(' userProfile:', flag + ' userProfile:'), URL)
            self.assertTrue(form.premium_required)
            with self.assertRaisesRegex(ImmoScoutContactError, "Suchen\\+"):
                prepare_contact(form, "Application", PROFILE)

    def test_privacy_acceptance_is_not_inferred(self):
        form = parse_contact_form(HTML, URL)
        form.defaults["showPrivacyPolicyAcceptanceCheckbox"] = True
        with self.assertRaises(ImmoScoutContactError):
            prepare_contact(form, "Application", PROFILE)

    def test_authenticated_profile_hydrates_html_defaults(self):
        session = Mock()
        html = Mock(status_code=200, headers={"Content-Type": "text/html"}, text=HTML)
        profile = Mock(status_code=200)
        profile.json.return_value = {"profileType": "BASIC", "firstName": "FromProfile"}
        session.get.side_effect = [html, profile]
        form = ImmoScoutContactClient(session, "UA").get_form(URL)
        self.assertTrue(form.user_profile_exists)
        self.assertEqual(form.defaults["personalData"]["firstName"], "FromProfile")
        self.assertEqual(session.get.call_args.args[0], "https://www.immobilienscout24.de/expose/profile")
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_rejection_diagnostic_is_private(self):
        session = Mock()
        response = Mock(status_code=400)
        response.json.return_value = {"private": "sensitive-response"}
        session.post.return_value = response
        with self.assertRaises(ImmoScoutContactError) as caught:
            ImmoScoutContactClient(session, "UA").send(self.prepared())
        self.assertEqual(caught.exception.response_data, {"private": "sensitive-response"})
        self.assertNotIn("sensitive-response", str(caught.exception))
        self.assertNotIn("sensitive-response", repr(caught.exception))

    def test_confirmed_send_is_single_attempt(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"successful": True, "shortlistServiceResult": {"markAsContacted": True}}
        session.post.return_value = response
        client = ImmoScoutContactClient(session, "UA")
        prepared = self.prepared()
        self.assertTrue(client.send(prepared))
        with self.assertRaises(ImmoScoutContactError):
            client.send(prepared)
        session.post.assert_called_once()
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])

    def test_http_success_without_successful_true_is_not_delivery(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"successful": False}
        session.post.return_value = response
        with self.assertRaises(ImmoScoutContactError):
            ImmoScoutContactClient(session, "UA").send(self.prepared())

    def test_timeout_is_unknown_delivery_and_not_retried(self):
        session = Mock()
        session.post.side_effect = requests.Timeout()
        client = ImmoScoutContactClient(session, "UA")
        prepared = self.prepared()
        with self.assertRaises(ImmoScoutDeliveryUnknown):
            client.send(prepared)
        with self.assertRaises(ImmoScoutContactError):
            client.send(prepared)
        session.post.assert_called_once()

    def test_curl_is_parsed_without_execution_and_nonce_is_discarded(self):
        curl = '''curl --url 'https://www.immobilienscout24.de/expose/123' \
 -H 'user-agent: UA' -b 'SSO=session; SSO-HMAC=signature; _ga=advertising; aws-waf-token=generated; websessionid=unused; AWSALB=unused; X-XSRF-TENANT-NETWORK-TOKEN=unused' \
 --data-raw '{"personalData":{"message":"Test"},"nonceToken":"stale"}' '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.curl"
            path.write_text(curl)
            capture = ContactCapture.from_curl_file(path)
        self.assertEqual(set(capture.cookies), {"SSO", "SSO-HMAC"})
        self.assertFalse(hasattr(capture, "nonceToken"))
        self.assertNotIn("session", repr(capture))


if __name__ == "__main__":
    unittest.main()
