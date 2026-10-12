#!/usr/bin/env python3
"""Inspect one ImmoScout website-search page, live or from a saved response."""

import argparse
from dataclasses import asdict
import json
import getpass
import os
from pathlib import Path

from src.immoscout_web_api import ImmoScoutWebClient, ImmoScoutWebError, parse_search_response
from src.immoscout_waf import GoWafTokenProvider
from src.immoscout_settings import ImmoScoutSettings
from src.immoscout_auth import ImmoScoutAuth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config.immoscout.yaml",
                        help="ImmoScout config (default: config.immoscout.yaml)")
    parser.add_argument("--region")
    parser.add_argument("--bezirk", action="append", help="Berlin district; repeat for several districts")
    parser.add_argument("--ortsteil", action="append", help="Berlin neighborhood; repeat for several neighborhoods")
    parser.add_argument("--max-pages", type=int, help="Override immoscout.search.max_pages")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--sorting", type=int, default=2, help="2 = newest first")
    parser.add_argument("--include-premium", action="store_true",
                        help="Include Suchen+ listings (excluded by default)")
    parser.add_argument("--max-price", type=float)
    parser.add_argument("--min-size", type=float)
    parser.add_argument("--min-rooms", type=float)
    parser.add_argument("--price-type", choices=("calculatedtotalrent",),
                        default="calculatedtotalrent")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--url", help="Use an exact /Suche/... URL instead of building one")
    inputs.add_argument("--from-json", type=Path, help="Parse a saved JSON response offline")
    parser.add_argument("--output", type=Path, help="Write normalized listings and pagination as JSON")
    parser.add_argument("--prompt-waf-token", action="store_true",
                        help="Read the browser's aws-waf-token using a hidden prompt")
    parser.add_argument("--refresh-waf", action=argparse.BooleanOptionalAction, default=True,
                        help="Renew a rejected WAF token with the Go-only helper (enabled by default)")
    parser.add_argument("--waf-helper", type=Path,
                        help="Path to the Go helper (default: bin/immoscout-waf)")
    args = parser.parse_args()
    client = None
    try:
        settings = ImmoScoutSettings.from_yaml(args.config)
        overrides = {key: value for key, value in {
            "region": args.region, "bezirk": args.bezirk, "ortsteil": args.ortsteil, "max_warm_rent": args.max_price,
            "min_size": args.min_size, "min_rooms": args.min_rooms, "max_pages": args.max_pages,
        }.items() if value is not None}
        if args.include_premium:
            overrides["skip_paywalled"] = False
        settings = ImmoScoutSettings(**{**asdict(settings), **overrides})
        pages = []
        if args.from_json:
            page = parse_search_response(json.loads(args.from_json.read_text(encoding="utf-8")))
            pages.append(page)
        else:
            auth = ImmoScoutAuth.from_yaml(args.config)
            client = ImmoScoutWebClient(
                session=auth.session(),
                token_provider=GoWafTokenProvider(args.waf_helper) if args.refresh_waf else None,
                waf_token=(getpass.getpass("aws-waf-token: ") if args.prompt_waf_token
                           else os.environ.get("IMMOSCOUT_WAF_TOKEN", "")),
                user_agent=os.environ.get("IMMOSCOUT_USER_AGENT") or auth.user_agent,
            )
            page = client.search_url(args.url, skip_paywalled=False) if args.url else client.search(
                settings.region, page=args.page, sorting=args.sorting, max_price=settings.max_warm_rent,
                min_size=settings.min_size or None, min_rooms=settings.min_rooms or None,
                price_type="calculatedtotalrent", skip_paywalled=False,
            )
            pages.append(page)
            while page.next_url and len(pages) < settings.max_pages:
                page = client.search_url(page.next_url, skip_paywalled=False)
                pages.append(page)
        for page in pages:
            counts = settings.filter_page(page)
            print(f"Page {page.page}/{page.total_pages}: {len(page.listings)} matches, {page.total_hits} unfiltered total hits")
            print("Excluded on this page: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
            for listing in page.listings:
                paywall = " [Suchen+]" if listing["paywall_active"] else ""
                print(f"  {listing['id']}: {listing['title']}{paywall}")
                print(f"    {listing['warm_rent']} EUR warm, {listing['size']} m², {listing['rooms']} rooms; district: {listing['berlin_district'] or 'unknown'}; neighborhood: {listing['berlin_ortsteil'] or 'unknown'}")
        if args.output:
            with args.output.open("w", encoding="utf-8") as handle:
                os.chmod(args.output, 0o600)
                output = asdict(pages[0]) if len(pages) == 1 else {"pages": [asdict(page) for page in pages]}
                json.dump(output, handle, ensure_ascii=False, indent=2)
            print(f"Saved: {args.output}")
        return 0
    except (ImmoScoutWebError, ValueError, OSError) as exc:
        print(f"Search failed: {exc}")
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
