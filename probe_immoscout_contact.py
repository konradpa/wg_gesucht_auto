#!/usr/bin/env python3
"""Prepare an ImmoScout application from a capture; default is read-only."""

import argparse
import json
import os
from pathlib import Path

from src.immoscout_contact import (
    ContactCapture, ImmoScoutContactClient, ImmoScoutContactError,
    prepare_contact, validate_expose_url,
)
from src.immoscout_auth import ImmoScoutAuth
from src.immoscout_settings import ImmoScoutSettings
from src.immoscout_web_api import ImmoScoutWebClient, ImmoScoutWebError
from src.immoscout_waf import GoWafTokenProvider
from src.daily_message_limit import DailyMessageLimit, DailyMessageLimitReached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config.immoscout.yaml")
    parser.add_argument("--curl-file", type=Path, help="Optional legacy copied contact cURL request")
    parser.add_argument("--refresh-waf", action=argparse.BooleanOptionalAction, default=True,
                        help="Validate/renew WAF token before loading contact form (enabled by default)")
    parser.add_argument("--listing-url", help="Listing to prepare (default: captured listing)")
    parser.add_argument("--message-file", type=Path, help="Application text (default: captured message)")
    parser.add_argument("--profile-file", type=Path, help="Optional JSON applicant fields overriding the capture")
    parser.add_argument("--share-profile", action="store_true", help="Forward the saved ImmoScout applicant profile")
    parser.add_argument("--accept-privacy-policy", action="store_true", help="Explicit acceptance if this form requires it")
    parser.add_argument("--output", type=Path, help="Private prepared payload JSON; includes personal information")
    parser.add_argument("--send", action="store_true", help="Submit this application once instead of preparing only")
    args = parser.parse_args()
    client = None
    try:
        if args.send and not args.listing_url:
            raise ValueError("--send requires an explicit --listing-url; the captured listing was already contacted")
        daily_limit = DailyMessageLimit.from_yaml(args.config, "immoscout")
        if args.send and daily_limit.remaining() == 0:
            raise DailyMessageLimitReached("ImmoScout daily message limit reached; no contact request submitted")
        if args.curl_file:
            capture = ContactCapture.from_curl_file(args.curl_file)
            url = args.listing_url or capture.url
            profile = dict(capture.personal_data)
            client = ImmoScoutContactClient.from_capture(capture)
            message = args.message_file.read_text(encoding="utf-8") if args.message_file else profile.get("message", "")
        else:
            if not args.listing_url:
                raise ValueError("Config-based contact preparation requires --listing-url")
            auth = ImmoScoutAuth.from_yaml(args.config, require_login=True)
            client = ImmoScoutContactClient(auth.session(), auth.user_agent)
            url = args.listing_url
            profile = {}
            message_path = args.message_file or Path(__file__).parent / "message_immoscout.txt"
            message = message_path.read_text(encoding="utf-8")
        listing_id = validate_expose_url(url)
        if args.profile_file:
            overrides = json.loads(args.profile_file.read_text(encoding="utf-8"))
            if not isinstance(overrides, dict):
                raise ValueError("Applicant profile must be a JSON object")
            profile.update(overrides)
        if args.refresh_waf:
            settings = ImmoScoutSettings.from_yaml(args.config)
            web = ImmoScoutWebClient(session=client.session, user_agent=client.headers["User-Agent"],
                                    token_provider=GoWafTokenProvider())
            web.search(settings.region, max_price=settings.max_warm_rent)
            client.headers["User-Agent"] = web.headers["User-Agent"]
        form = client.get_form(url)
        prepared = prepare_contact(form, message, profile, args.share_profile, args.accept_privacy_policy)
        print(f"Prepared application for listing {listing_id}; fresh nonce obtained.")
        print("Required fields: " + ", ".join(k for k, v in form.configuration.items() if v == "MANDATORY"))
        print(f"Message length: {len(message)} characters; profile forwarding: {args.share_profile}")
        if args.output:
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump({"url": url, "payload": prepared.payload}, handle, ensure_ascii=False, indent=2)
            print(f"Private draft saved: {args.output}")
        if args.send:
            daily_limit.reserve()
            client.send(prepared)
            print("ImmoScout confirmed successful contact submission.")
        else:
            print("DRY RUN: no contact request submitted.")
        return 0
    except (DailyMessageLimitReached, ImmoScoutContactError, ImmoScoutWebError, ValueError, OSError) as exc:
        print(f"Contact preparation failed: {exc}")
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
