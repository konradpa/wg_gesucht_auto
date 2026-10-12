"""Private ImmoScout browser-session cookies read from YAML."""

from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml

from .immoscout_contact import AUTH_COOKIES, HOST
from .immoscout_web_api import USER_AGENT


@dataclass(repr=False)
class ImmoScoutAuth:
    user_agent: str = USER_AGENT
    cookies: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_yaml(cls, path, require_login=False):
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict) or not isinstance(config.get("immoscout", {}), dict):
            raise ValueError("immoscout must be a mapping")
        auth = config.get("immoscout", {}).get("auth", {})
        if not isinstance(auth, dict):
            raise ValueError("immoscout.auth must be a mapping")
        user_agent = auth.get("user_agent") or USER_AGENT
        cookies = auth.get("cookies", {})
        if not isinstance(user_agent, str) or any(c in user_agent for c in "\r\n"):
            raise ValueError("immoscout.auth.user_agent must be a valid header value")
        if not isinstance(cookies, dict) or any(name not in AUTH_COOKIES for name in cookies):
            raise ValueError("immoscout.auth.cookies must contain only supported session cookie names")
        if any(not isinstance(value, str) or any(c in value for c in "\r\n;") for value in cookies.values()):
            raise ValueError("ImmoScout cookie values must be strings without header separators")
        cookies = {name: value for name, value in cookies.items() if value}
        if require_login and not {"SSO", "SSO-HMAC"}.issubset(cookies):
            raise ValueError("Contacting requires SSO and SSO-HMAC in immoscout.auth.cookies")
        return cls(user_agent, cookies)

    def session(self):
        session = requests.Session()
        for name, value in self.cookies.items():
            session.cookies.set(name, value, domain=HOST, path="/", secure=True)
        return session
