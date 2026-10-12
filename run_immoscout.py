#!/usr/bin/env python3
"""One ImmoScout search/personalization/contact run; no scheduler."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shlex
import tempfile
import time

import yaml

from src.daily_message_limit import DailyMessageLimit, DailyMessageLimitReached
from src.immoscout_auth import ImmoScoutAuth
from src.immoscout_contact import (ImmoScoutContactClient, ImmoScoutContactError,
                                 ImmoScoutDeliveryUnknown, prepare_contact)
from src.immoscout_settings import ImmoScoutSettings
from src.immoscout_waf import GoWafTokenProvider
from src.immoscout_web_api import ImmoScoutWebClient, ImmoScoutWebError
from src.llm_helper import LLMHelper


ROOT = Path(__file__).resolve().parent


def load_config(path):
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Config must be a YAML mapping")
    llm = config.get("llm", {})
    if not isinstance(llm, dict):
        raise ValueError("llm must be a mapping")
    # Read referenced local environment values as data, never execute a shell file.
    local = {}
    env_path = Path(path).resolve().parent / ".env.local"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            for item in shlex.split(line):
                key, separator, value = item.partition("=")
                if separator:
                    local[key] = value
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")
    for key, value in list(llm.items()):
        if isinstance(value, str):
            llm[key] = pattern.sub(lambda m: os.environ.get(m[1]) or local.get(m[1]) or m[2] or "", value)
    return config


def needs_wbs(form, title):
    text = title + "\n" + form.description
    text = re.sub(r"(?:ohne|kein(?:en)?)\s+(?:WBS|Wohnberechtigungsschein)", "", text, flags=re.I)
    return form.wbs_required or bool(re.search(r"\bWBS\b|Wohnberechtigungsschein", text, re.I))


class ContactHistory:
    """Crash-safe ledger. Pending/unknown attempts are never retried automatically."""
    def __init__(self, root):
        self.path = Path(root) / "immoscout_contacts.json"
        try:
            self.entries = json.loads(self.path.read_text()) if self.path.exists() else {}
            legacy_path = Path(root) / "contacted.json"
            legacy = json.loads(legacy_path.read_text()) if legacy_path.exists() else {}
        except (ValueError, OSError):
            raise ValueError("Cannot read contact history; run stopped") from None
        if not isinstance(self.entries, dict) or not isinstance(legacy, dict):
            raise ValueError("Invalid contact history; run stopped")
        for key, value in legacy.items():
            if key.startswith("is24:"):
                self.entries.setdefault(key[5:], {"status": "sent", "legacy": True})
        for key in legacy.get("contacted_ids", []):
            if isinstance(key, str) and key.startswith("is24:"):
                self.entries.setdefault(key[5:], {"status": "sent", "legacy": True})

    def record(self, listing, status):
        self.entries[listing["id"]] = {"status": status, "url": listing["url"],
                                       "timestamp": datetime.now(timezone.utc).isoformat()}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(self.entries, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


@contextmanager
def run_lock(root):
    descriptor = os.open(Path(root) / "immoscout_run.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another ImmoScout run is already active") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_once(config_path, send=False, no_llm=False, root=ROOT):
    root = Path(root)
    config = load_config(config_path)
    block = config.get("immoscout", {})
    options = block.get("settings", {})
    max_run = options.get("max_messages_per_run", 1)
    delay = options.get("delay_between_messages", 20)
    skip_wbs = options.get("skip_wbs", True)
    if isinstance(max_run, bool) or not isinstance(max_run, int) or max_run < 0:
        raise ValueError("max_messages_per_run must be an integer >= 0")
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
        raise ValueError("delay_between_messages must be a finite number >= 0")
    if not isinstance(skip_wbs, bool):
        raise ValueError("skip_wbs must be true or false")
    settings = ImmoScoutSettings.from_yaml(config_path)
    quota = DailyMessageLimit("immoscout", options.get("max_messages_per_day", 5), root / "daily_message_counts.json")
    history = ContactHistory(root)
    maximum = min(max_run, quota.remaining()) if send else max_run
    if maximum == 0:
        print("No send slots available; run finished.")
        return 0
    auth = ImmoScoutAuth.from_yaml(config_path, require_login=True)
    template_path = Path(block.get("message_file", "message_immoscout.txt"))
    if not template_path.is_absolute():
        template_path = Path(config_path).resolve().parent / template_path
    template = template_path.read_text(encoding="utf-8")
    if not template.strip():
        raise ValueError("Message template is empty")
    llm_config = config.get("llm", {})
    if llm_config.get("enabled") and not no_llm and not llm_config.get("api_key"):
        raise ValueError("LLM enabled but API key is missing")
    llm = LLMHelper.from_config(config) if not no_llm else None
    web = ImmoScoutWebClient(session=auth.session(), user_agent=auth.user_agent,
                            token_provider=GoWafTokenProvider())
    contacted = 0
    attempts = 0
    previews = 0
    seen = set()
    next_url = None
    print("SEND: one run" if send else "DRY RUN: no messages will be submitted")
    try:
        for page_number in range(1, settings.max_pages + 1):
            page = web.search_url(next_url, skip_paywalled=False) if next_url else web.search(
                settings.region, sorting=2, max_price=settings.max_warm_rent,
                min_size=settings.min_size or None, min_rooms=settings.min_rooms or None,
                skip_paywalled=False)
            settings.filter_page(page)
            client = ImmoScoutContactClient(web.session, web.headers["User-Agent"])
            print(f"Page {page.page}: {len(page.listings)} matches")
            for listing in page.listings:
                identifier = listing["id"]
                if identifier in seen or identifier in history.entries:
                    continue
                seen.add(identifier)
                form = client.get_form(listing["url"])
                if form.premium_required or (skip_wbs and needs_wbs(form, listing["title"])):
                    print(f"Skip {identifier}: premium or WBS requirement")
                    continue
                if re.search(r"Wohnungstausch|Tauschwohnung|nur\s+(?:im\s+)?Tausch", listing["title"] + form.description, re.I):
                    print(f"Skip {identifier}: apartment exchange")
                    continue
                # Validate required applicant fields before any LLM request.
                try:
                    prepare_contact(form, template.replace("{name}", form.recipient_name), {})
                except ImmoScoutContactError as error:
                    print(f"Skip {identifier}: {error}")
                    continue
                if llm:
                    details = {**listing, "listing_type": "Wohnung", "description": form.description}
                    try:
                        message = llm._generate_text(llm._build_prompt(template, details, form.recipient_name))
                    except Exception:
                        raise ValueError("Gemini/LLM personalization failed; nothing further sent") from None
                    if len(message) < 50 or re.search(r"\{\w+\}", message):
                        raise ValueError("Invalid personalized message; run stopped")
                    if skip_wbs and re.search(r"\bWBS\b|Wohnberechtigungsschein", message, re.I):
                        raise ValueError("Personalized message contains an unsupported WBS claim")
                else:
                    message = template.replace("{name}", form.recipient_name)
                print(f"{identifier}: {listing['title']} | {listing['warm_rent']} EUR warm | {listing['url']}")
                if not send:
                    print(message)
                    previews += 1
                    if previews >= maximum:
                        return 0
                    continue
                # Reload nonce and eligibility immediately before POST.
                if attempts:
                    time.sleep(delay)
                form = client.get_form(listing["url"])
                if form.premium_required or (skip_wbs and needs_wbs(form, listing["title"])):
                    continue
                prepared = prepare_contact(form, message, {})
                quota.reserve()
                history.record(listing, "pending")
                attempts += 1
                try:
                    client.send(prepared)
                except ImmoScoutDeliveryUnknown:
                    history.record(listing, "unknown")
                    raise
                except ImmoScoutContactError:
                    history.record(listing, "rejected")
                    raise
                history.record(listing, "sent")
                contacted += 1
                print("ImmoScout confirmed successful submission")
                if attempts >= maximum:
                    return contacted
            next_url = page.next_url
            if not next_url:
                break
        print(f"Finished: {contacted} sent, {previews} previews")
        return contacted
    finally:
        web.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.immoscout.yaml")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true", help="Submit applications once")
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    parser.add_argument("--no-llm", action="store_true", help="Use the template without external personalization")
    args = parser.parse_args()
    try:
        with run_lock(ROOT):
            run_once(args.config, send=args.send, no_llm=args.no_llm)
        return 0
    except (OSError, ValueError, yaml.YAMLError, DailyMessageLimitReached,
            ImmoScoutContactError, ImmoScoutWebError) as error:
        # YAML errors may quote private source lines.
        print("ImmoScout run stopped: " + ("Invalid YAML config" if isinstance(error, yaml.YAMLError) else str(error)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
