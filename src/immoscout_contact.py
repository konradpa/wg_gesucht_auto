"""ImmoScout contact-form preparation and explicit, single-attempt submission."""

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shlex
from html.parser import HTMLParser
from urllib.parse import urlsplit

import requests


HOST = "www.immobilienscout24.de"
AUTH_COOKIES = {"SSO", "SSO-HMAC"}
PROFILE_FIELDS = {
    "firstname": "firstName", "lastname": "lastName", "email": "emailAddress",
    "phone": "phoneNumber", "salutation": "salutation", "street": "street",
    "house_number": "houseNumber", "postcode": "postcode", "city": "city",
    "residents": "numberOfPersons", "move_in_date_type": "moveInDateType",
    "move_in_date": "moveInDate", "pets": "hasPets", "income": "income",
    "employment": "employmentRelationship",
}
ADMIN_FIELDS = {"dataProtectionAlreadyAccepted", "image", "profileType",
                "promotionCode", "registrationDisabled"}


class ImmoScoutContactError(RuntimeError):
    def __init__(self, message, response_data=None):
        super().__init__(message)
        # Private diagnostic data: never include response bodies in logs or repr.
        self.response_data = response_data


class ImmoScoutDeliveryUnknown(ImmoScoutContactError):
    """Submission might have reached the server; callers must not retry it."""


def validate_expose_url(url):
    parts = urlsplit(url)
    match = re.fullmatch(r"/expose/([0-9]+)", parts.path)
    if (parts.scheme != "https" or parts.netloc != HOST or parts.fragment or not match):
        raise ValueError("Expected an https://www.immobilienscout24.de/expose/<id> URL")
    return match.group(1)


@dataclass(repr=False)
class ContactCapture:
    url: str
    user_agent: str
    cookies: dict = field(repr=False)
    personal_data: dict = field(repr=False)

    @classmethod
    def from_curl_file(cls, path):
        # Parse text only. Never execute the pasted command or load shell files.
        args = shlex.split(Path(path).read_text(encoding="utf-8"))
        if not args or args[0] != "curl" or args.count("curl") != 1:
            raise ValueError("Expected one copied cURL request")
        url = None
        cookie_text = ""
        body_text = None
        headers = {}
        method = None
        for i, argument in enumerate(args[:-1]):
            value = args[i + 1]
            if argument == "--url":
                url = value
            elif argument in ("-X", "--request"):
                method = value.upper()
            elif argument in ("-H", "--header"):
                name, separator, content = value.partition(":")
                if separator:
                    headers[name.lower()] = content.strip()
            elif argument in ("-b", "--cookie"):
                if value.startswith("@") or "=" not in value:
                    raise ValueError("Cookie files are not supported; copy the request's cookie header")
                cookie_text = value
            elif argument in ("--data-raw", "--data", "--data-binary", "--json", "-d"):
                if value.startswith("@"):
                    raise ValueError("Request-body files are not supported")
                body_text = value
        if not url or body_text is None:
            raise ValueError("Capture must contain the expose URL and JSON request body")
        if method and method != "POST":
            raise ValueError("Expected a POST contact capture")
        cookie_text = cookie_text or headers.get("cookie", "")
        validate_expose_url(url)
        try:
            body = json.loads(body_text)
        except ValueError:
            raise ValueError("Captured contact body is not JSON") from None
        if not isinstance(body, dict) or not isinstance(body.get("personalData"), dict):
            raise ValueError("Capture has no personalData contact payload")
        cookies = {}
        for part in cookie_text.split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name in AUTH_COOKIES:
                cookies[name] = value
        if not {"SSO", "SSO-HMAC"}.issubset(cookies):
            raise ValueError("Captured request lacks the ImmoScout login session cookies")
        user_agent = headers.get("user-agent", "")
        if not user_agent or any(c in user_agent for c in "\r\n"):
            raise ValueError("Capture has no valid User-Agent")
        # Discard the captured nonce, advertising cookies, and outer send flags.
        return cls(url, user_agent, cookies, body["personalData"])


@dataclass(repr=False)
class ContactForm:
    url: str
    defaults: dict = field(repr=False)
    configuration: dict
    user_profile_exists: bool
    recipient_name: str = "zusammen"
    description: str = ""
    premium_required: bool = False
    wbs_required: bool = False


@dataclass(repr=False)
class PreparedContact:
    url: str
    payload: dict = field(repr=False)
    attempted: bool = field(default=False, repr=False)


def _json_property(script, name):
    for match in re.finditer(r"\b" + re.escape(name) + r"\s*:\s*", script):
        try:
            value, _ = json.JSONDecoder().raw_decode(script[match.end():].lstrip())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ImmoScoutContactError(f"Expose has no readable {name} data")


class _DescriptionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.target = None
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.depth += 1
        if dict(attrs).get("id") == "is24-description-section":
            self.target = self.depth
        if tag in ("style", "script"):
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.ignored = max(0, self.ignored - 1)
        if self.target == self.depth:
            self.target = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.target and not self.ignored and data.strip():
            self.parts.append(data.strip())


def parse_contact_form(html, url):
    validate_expose_url(url)
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)
    script = next((s for s in scripts if re.search(r"IS24\.contactLayerModel\s*=", s)), None)
    if script is None:
        raise ImmoScoutContactError("Contact form unavailable; check the login session and listing access")
    form = _json_property(script, "contactForm")
    configuration = _json_property(script, "configuration")
    nonce = form.get("nonceToken")
    if not isinstance(nonce, str) or not nonce:
        raise ImmoScoutContactError("Expose contact form has no fresh nonceToken")
    if form.get("suspiciousRequest") or (form.get("captchaData") or {}).get("captchaId"):
        raise ImmoScoutContactError("Contact form requires additional verification")
    if not isinstance(form.get("personalData"), dict):
        raise ImmoScoutContactError("Contact form has no personalData defaults")
    profile_match = re.search(r"\buserProfile\s*:\s*\{(.*?)\bextendedContactForm\s*:", script, re.DOTALL)
    exists = bool(profile_match and re.search(r"\bexists\s*:\s*true\b", profile_match.group(1)))
    try:
        realtor = _json_property(script, "realtor")
        name = realtor.get("firstName") or realtor.get("lastName") or "zusammen"
    except ImmoScoutContactError:
        name = "zusammen"
    description = _DescriptionParser()
    description.feed(html)
    premium_required = bool(re.search(r"\bisFreemium\s*:\s*true\b", script)
                            or re.search(r"\bppaWithPremiumProfile\s*:\s*true\b", script))
    return ContactForm(url, form, configuration, exists, name,
                       "\n".join(description.parts), premium_required,
                       bool(re.search(r"\bcertificateOfEligibilityNeeded\s*:\s*true\b", script)))


def prepare_contact(form, message, profile, share_profile=False, privacy_policy_accepted=False):
    if form.premium_required:
        raise ImmoScoutContactError("Listing requires Suchen+; select a listing without premium access restrictions")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Application message must not be empty")
    if form.defaults.get("showPrivacyPolicyAcceptanceCheckbox") and not privacy_policy_accepted:
        raise ImmoScoutContactError("The form requires explicit privacy-policy acceptance")
    fields = {key for key, mode in form.configuration.items() if mode in ("OPTIONAL", "MANDATORY")}
    defaults = form.defaults["personalData"]
    personal = {key: deepcopy(value) for key, value in defaults.items() if key in fields | ADMIN_FIELDS}
    for name, value in profile.items():
        key = PROFILE_FIELDS.get(name, name)
        if key in fields and key != "message":
            personal[key] = value
    personal["message"] = message
    missing = [key for key, mode in form.configuration.items() if mode == "MANDATORY"
               and (personal.get(key) is None or personal.get(key) == "")]
    if missing:
        raise ImmoScoutContactError("Missing required applicant fields: " + ", ".join(sorted(missing)))
    return PreparedContact(form.url, {
        "suspiciousRequest": False,
        "sendUserProfile": bool(share_profile),
        "userProfileExists": form.user_profile_exists,
        "privacyPolicyAccepted": bool(privacy_policy_accepted),
        "sendButtonDelay": form.defaults.get("sendButtonDelay", 0),
        "personalData": personal,
        "isFromCounterOfferModal": False,
        "nonceToken": form.defaults["nonceToken"],
        "isTenantNetworkListing": False,
        "requestedDocuments": [],
    })


class ImmoScoutContactClient:
    def __init__(self, session, user_agent):
        self.session = session
        self.headers = {"User-Agent": user_agent, "Origin": "https://" + HOST}

    @classmethod
    def from_capture(cls, capture):
        session = requests.Session()
        for name, value in capture.cookies.items():
            session.cookies.set(name, value, domain=HOST, path="/", secure=True)
        return cls(session, capture.user_agent)

    def get_form(self, url):
        validate_expose_url(url)
        try:
            response = self.session.get(url, headers={**self.headers, "Accept": "text/html"},
                                        timeout=30, allow_redirects=False)
        except requests.RequestException:
            raise ImmoScoutContactError("Cannot load the expose contact form") from None
        try:
            if response.status_code != 200 or "text/html" not in response.headers.get("Content-Type", ""):
                raise ImmoScoutContactError(f"Contact form GET returned HTTP {response.status_code}")
            form = parse_contact_form(response.text, url)
        finally:
            response.close()
        if form.premium_required:
            return form
        # The browser hydrates the profile asynchronously; HTML contains empty
        # placeholders even for logged-in users. Use the authenticated endpoint.
        try:
            response = self.session.get("https://" + HOST + "/expose/profile",
                                        headers={**self.headers, "Accept": "application/json"},
                                        timeout=30, allow_redirects=False)
        except requests.RequestException:
            raise ImmoScoutContactError("Cannot load the authenticated applicant profile") from None
        try:
            if response.status_code == 404:
                return form
            if response.status_code != 200:
                raise ImmoScoutContactError(f"Applicant profile GET returned HTTP {response.status_code}")
            try:
                profile = response.json()
            except ValueError:
                raise ImmoScoutContactError("Applicant profile response was not JSON") from None
            if not isinstance(profile, dict) or profile.get("profileType") not in ("BASIC", "PREMIUM"):
                raise ImmoScoutContactError("Applicant profile response has an unexpected schema")
            form.defaults["personalData"].update(profile)
            form.user_profile_exists = True
            return form
        finally:
            response.close()

    def send(self, prepared):
        validate_expose_url(prepared.url)
        if prepared.attempted:
            raise ImmoScoutContactError("This prepared application has already been submitted or attempted")
        prepared.attempted = True
        try:
            response = self.session.post(
                prepared.url, json=prepared.payload,
                headers={**self.headers, "Accept": "application/json", "Referer": prepared.url},
                timeout=30, allow_redirects=False,
            )
        except requests.RequestException:
            raise ImmoScoutDeliveryUnknown("Contact submission result unknown; do not retry automatically") from None
        try:
            if response.status_code >= 500:
                raise ImmoScoutDeliveryUnknown("Server error after submission; check messages before retrying")
            if response.status_code not in range(200, 300):
                try:
                    diagnostic = response.json()
                except ValueError:
                    diagnostic = None
                raise ImmoScoutContactError(f"Contact submission returned HTTP {response.status_code}", diagnostic)
            try:
                result = response.json()
            except ValueError:
                raise ImmoScoutDeliveryUnknown("Contact response was not JSON; check messages before retrying") from None
            if not isinstance(result, dict) or result.get("successful") is not True:
                raise ImmoScoutContactError("ImmoScout did not confirm successful contact submission", result)
            return True
        finally:
            response.close()

    def close(self):
        self.session.close()
