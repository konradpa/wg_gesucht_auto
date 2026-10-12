"""Regression checks for the captured website-search schema and failure modes."""

from copy import deepcopy
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from src.immoscout_web_api import (
    ImmoScoutWebClient, ImmoScoutSessionRequired, ImmoScoutWebError, ImmoScoutCaptchaRequired,
    build_search_url, parse_search_response, validate_search_url,
)
from src.immoscout_waf import WafRefreshError


def captured_shape():
    # Minimal, anonymized projection of the observed 2026-10-12 response.
    return {"searchResponseModel": {
        "additional": {
            "lastSearchApiUrl": "/region?pagenumber=1",
            "resultListUrl": "/Suche/de/berlin/berlin/wohnung-mieten?sorting=2&pagenumber=2",
            "queryModel": '{"query":{"priceRangeWithType":{"type":"CALCULATED_TOTAL_RENT"}}}',
        },
        "resultlist.resultlist": {
            "paging": {"pageNumber": 2, "pageSize": 20, "numberOfPages": 3,
                       "numberOfHits": 41, "next": {"@xlink.href":
                           "/Suche/de/berlin/berlin/wohnung-mieten?sorting=2&pagenumber=3"}},
            "resultlistEntries": [{"@realEstateType": "0", "resultlistEntry": [
                {"@id": "123", "@publishDate": "2026-10-12T15:01:27+02:00",
                 "resultlist.realEstate": {
                     "@id": "123", "@xsi.type": "search:ApartmentRent", "title": "Testwohnung",
                     "address": {"quarter": "Mitte", "city": "Berlin",
                                 "description": {"text": "Mitte, Berlin"}},
                     "privateOffer": "false", "paywallListing": {"active": "false"},
                     "price": {"value": 655.75}, "livingSpace": 50, "numberOfRooms": 2,
                     "calculatedTotalRent": {"totalRent": {"value": 818.75},
                                             "calculationMode": "SUMMARIZED"},
                 }},
            ]}],
        },
    }}


class SearchResponseTests(unittest.TestCase):
    def test_page_two_uses_paging_instead_of_stale_last_search_url(self):
        page = parse_search_response(captured_shape())
        self.assertEqual((page.page, page.total_pages, page.total_hits), (2, 3, 41))
        self.assertEqual(parse_qs(urlsplit(page.next_url).query)["pagenumber"], ["3"])

    def test_warm_rent_and_string_booleans(self):
        listing = parse_search_response(captured_shape()).listings[0]
        self.assertEqual(listing["rent"], 818.75)
        self.assertEqual(listing["cold_rent"], 655.75)
        self.assertFalse(listing["paywall_active"])
        self.assertFalse(listing["is_private"])
        self.assertNotIn("contactDetails", listing)

    def test_missing_warm_rent_does_not_silently_substitute_cold_rent(self):
        data = captured_shape()
        real = data["searchResponseModel"]["resultlist.resultlist"]["resultlistEntries"][0]["resultlistEntry"][0]["resultlist.realEstate"]
        real.pop("calculatedTotalRent")
        self.assertIsNone(parse_search_response(data).listings[0]["rent"])

    def test_singleton_and_duplicate_entries(self):
        data = captured_shape()
        result = data["searchResponseModel"]["resultlist.resultlist"]
        group = result["resultlistEntries"][0]
        group["resultlistEntry"] = group["resultlistEntry"][0]
        result["resultlistEntries"] = [group, deepcopy(group)]
        self.assertEqual(len(parse_search_response(data).listings), 1)

    def test_bad_schema_is_a_failure_not_an_empty_search(self):
        with self.assertRaises(ImmoScoutWebError):
            parse_search_response({"error": "not a result"})

    def test_empty_search(self):
        data = captured_shape()
        result = data["searchResponseModel"]["resultlist.resultlist"]
        result["resultlistEntries"] = []
        result["paging"] = {"pageNumber": 1, "pageSize": 20, "numberOfPages": 0, "numberOfHits": 0}
        page = parse_search_response(data)
        self.assertEqual(page.listings, [])
        self.assertIsNone(page.next_url)


class RequestTests(unittest.TestCase):
    def test_premium_filter_keeps_pagination_even_when_page_is_empty(self):
        data = captured_shape()
        real = data["searchResponseModel"]["resultlist.resultlist"]["resultlistEntries"][0]["resultlistEntry"][0]["resultlist.realEstate"]
        real["paywallListing"]["active"] = "true"
        response = Mock(status_code=200, headers={"Content-Type": "application/json"})
        response.json.return_value = data
        session = Mock()
        session.get.return_value = response
        client = ImmoScoutWebClient(session=session)
        page = client.search("/de/berlin/berlin", page=2)
        self.assertEqual(page.listings, [])
        self.assertEqual(page.skipped_paywalled, 1)
        self.assertEqual(page.total_hits, 41)
        self.assertIsNotNone(page.next_url)
        included = client.search("/de/berlin/berlin", page=2, skip_paywalled=False)
        self.assertEqual(len(included.listings), 1)
        self.assertEqual(included.skipped_paywalled, 0)

    def test_filter_url(self):
        url = build_search_url("/de/berlin/berlin", max_price=900, min_size=40, min_rooms=2, page=2)
        parts = urlsplit(url)
        self.assertEqual(parts.path, "/Suche/de/berlin/berlin/wohnung-mieten")
        self.assertEqual(parse_qs(parts.query), {
            "sorting": ["2"], "pagenumber": ["2"], "price": ["-900.0"],
            "livingspace": ["40.0-"], "numberofrooms": ["2.0-"],
            "pricetype": ["calculatedtotalrent"],
        })

    def test_first_page_uses_the_canonical_website_url(self):
        url = build_search_url("/de/hamburg/hamburg", page=1, max_price=900)
        self.assertNotIn("pagenumber", parse_qs(urlsplit(url).query))

    def test_visible_captcha_does_not_invoke_token_only_helper(self):
        response = Mock(status_code=401, headers={"Content-Type": "text/html"},
                        text='<script src="https://example.edge.captcha-sdk.awswaf.com/jsapi.js"></script>')
        session = Mock()
        session.get.return_value = response
        provider = Mock()
        with self.assertRaises(ImmoScoutCaptchaRequired):
            ImmoScoutWebClient(session=session, token_provider=provider).search("/de/hamburg/hamburg")
        provider.assert_not_called()

    def test_pagination_cannot_send_session_to_another_host(self):
        for url in ("https://example.com/Suche/foo", "//example.com/Suche/foo",
                    "http://www.immobilienscout24.de/Suche/foo"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_search_url(url)

    def test_challenge_is_not_reported_as_zero_hits(self):
        for status in (401, 403, 202, 200):
            response = Mock(status_code=status, headers={"Content-Type": "text/html"}, text="token challenge")
            session = Mock()
            session.get.return_value = response
            with self.subTest(status=status), self.assertRaises(ImmoScoutSessionRequired):
                ImmoScoutWebClient(session=session).search("/de/berlin/berlin")

    def test_client_parses_json_and_avoids_redirects(self):
        response = Mock(status_code=200, headers={"Content-Type": "application/json;charset=utf-8"})
        response.json.return_value = captured_shape()
        session = Mock()
        session.get.return_value = response
        client = ImmoScoutWebClient(session=session)
        self.assertEqual(client.search("/de/berlin/berlin", page=2).page, 2)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_rejected_token_is_renewed_once_and_retained(self):
        rejected = Mock(status_code=401, headers={"Content-Type": "text/html"}, text="token challenge")
        accepted = Mock(status_code=200, headers={"Content-Type": "application/json"})
        accepted.json.return_value = captured_shape()
        session = Mock()
        session.get.side_effect = [rejected, accepted, accepted]
        provider = Mock(return_value={"token": "replacement", "user_agent": "Go-helper-UA"})
        client = ImmoScoutWebClient(session=session, token_provider=provider)
        self.assertEqual(client.search("/de/berlin/berlin", page=2).page, 2)
        client.search("/de/berlin/berlin", page=2)
        provider.assert_called_once()
        self.assertEqual(client.headers["User-Agent"], "Go-helper-UA")
        session.cookies.set.assert_called_once_with(
            "aws-waf-token", "replacement", domain="www.immobilienscout24.de", path="/", secure=True,
        )
        rejected.close.assert_called_once()

    def test_rejected_replacement_does_not_loop(self):
        rejected = Mock(status_code=401, headers={"Content-Type": "text/html"}, text="token challenge")
        session = Mock()
        session.get.return_value = rejected
        provider = Mock(return_value={"token": "replacement", "user_agent": "UA"})
        with self.assertRaises(ImmoScoutSessionRequired):
            ImmoScoutWebClient(session=session, token_provider=provider).search("/de/berlin/berlin")
        self.assertEqual(session.get.call_count, 2)
        provider.assert_called_once()

    def test_provider_failure_does_not_retry_search(self):
        rejected = Mock(status_code=401, headers={"Content-Type": "text/html"}, text="token challenge")
        session = Mock()
        session.get.return_value = rejected
        provider = Mock(side_effect=WafRefreshError("Go token renewal failed"))
        with self.assertRaisesRegex(ImmoScoutSessionRequired, "Go token renewal failed"):
            ImmoScoutWebClient(session=session, token_provider=provider).search("/de/berlin/berlin")
        session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
