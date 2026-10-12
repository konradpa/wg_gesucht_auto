"""Read-only ImmoScout website search, observed on 2026-10-12.

The /Suche/... route returns JSON when Accept is application/json. Requests
may require a valid aws-waf-token. An optional Go-only provider can renew a
rejected token, after which the search is retried once.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit

import requests

from .immoscout_waf import WafRefreshError


BASE_URL = "https://www.immobilienscout24.de"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)


class ImmoScoutWebError(RuntimeError):
    """Search failed or returned an unexpected response."""


class ImmoScoutSessionRequired(ImmoScoutWebError):
    """The website rejected the request or returned an HTML challenge."""


class ImmoScoutCaptchaRequired(ImmoScoutSessionRequired):
    """A visible CAPTCHA is required rather than the token-only SDK flow."""


def _boolean(value: Any) -> bool:
    # Web responses use strings, including "false" (which bool() misreads).
    return value is True or str(value).lower() == "true"


def _list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def validate_search_url(url: str) -> str:
    """Limit caller-supplied URLs and pagination links to the search host."""
    if url.startswith("/Suche/"):
        url = BASE_URL + url
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "www.immobilienscout24.de"
            or not parts.path.startswith("/Suche/") or parts.fragment):
        raise ValueError("Expected an https://www.immobilienscout24.de/Suche/... URL")
    return url


def build_search_url(region: str, max_price: Optional[float] = None,
                     min_size: Optional[float] = None, min_rooms: Optional[float] = None,
                     price_type: str = "calculatedtotalrent", page: int = 1,
                     sorting: int = 2) -> str:
    """Build the apartment-rental route; filters were verified against queryModel."""
    if (not region.startswith("/de/") or any(c in region for c in "?#\\")
            or any(p in ("", ".", "..") for p in region.strip("/").split("/"))):
        raise ValueError("region must be a /de/... geographical path")
    if page < 1:
        raise ValueError("page must be >= 1")
    if price_type not in ("calculatedtotalrent", "rentpermonth"):
        raise ValueError("price_type must be calculatedtotalrent or rentpermonth")
    # The website omits pagenumber on its first-page URLs. The explicit =1
    # variant also triggered a CAPTCHA on a verified Hamburg request.
    params = {"sorting": sorting}
    if page > 1:
        params["pagenumber"] = page
    for value, key, pattern in (
        (max_price, "price", "-{}"), (min_size, "livingspace", "{}-"),
        (min_rooms, "numberofrooms", "{}-"),
    ):
        if value is not None:
            if value < 0:
                raise ValueError(f"{key} must be non-negative")
            params[key] = pattern.format(float(value))
    if max_price is not None:
        params["pricetype"] = price_type
    return BASE_URL + "/Suche" + region.rstrip("/") + "/wohnung-mieten?" + urlencode(params)


@dataclass
class SearchPage:
    listings: List[Dict]
    page: int
    page_size: int
    total_pages: int
    total_hits: int
    next_url: Optional[str]
    search_url: str = ""
    skipped_paywalled: int = 0


def parse_search_response(data: dict, source_url: str = "") -> SearchPage:
    """Flatten the website's XML-shaped JSON without retaining account metadata."""
    try:
        model = data["searchResponseModel"]
        result = model["resultlist.resultlist"]
        paging = result["paging"]
        page = int(paging["pageNumber"])
        page_size = int(paging["pageSize"])
        total_pages = int(paging["numberOfPages"])
        total_hits = int(paging["numberOfHits"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ImmoScoutWebError("Unexpected ImmoScout search response schema") from exc

    additional = model.get("additional") or {}
    # additional.lastSearchApiUrl can still say pagenumber=1 on page 2.
    # Use resultlist.paging and its links as the authoritative pagination data.
    search_url = source_url or additional.get("resultListUrl") or ""
    next_url = (paging.get("next") or {}).get("@xlink.href")
    if next_url:
        next_url = validate_search_url(next_url)

    query_model = additional.get("queryModel") or {}
    if isinstance(query_model, str):
        import json
        try:
            query_model = json.loads(query_model)
        except ValueError as exc:
            raise ImmoScoutWebError("Invalid queryModel in search response") from exc
    price_type = ((query_model.get("query") or {}).get("priceRangeWithType") or {}).get("type")
    warm_search = price_type == "CALCULATED_TOTAL_RENT"
    listings = []
    seen = set()
    for group in _list(result.get("resultlistEntries")):
        for entry in _list(group.get("resultlistEntry")):
            real = entry.get("resultlist.realEstate") or {}
            listing_id = str(real.get("@id") or entry.get("@id") or "")
            if not listing_id or listing_id in seen or not real:
                continue
            seen.add(listing_id)
            address = real.get("address") or {}
            coordinates = address.get("wgs84Coordinate") or {}
            paywall = real.get("paywallListing") or {}
            cold_rent = (real.get("price") or {}).get("value")
            total = real.get("calculatedTotalRent") or {}
            warm_rent = (total.get("totalRent") or {}).get("value")
            description = address.get("description") or {}
            address_line = description.get("text") if isinstance(description, dict) else description
            if not address_line:
                address_line = ", ".join(str(address[k]) for k in
                                         ("street", "houseNumber", "postcode", "quarter", "city")
                                         if address.get(k))
            listings.append({
                "platform": "immoscout", "id": listing_id,
                "title": real.get("title", ""),
                "url": BASE_URL + "/expose/" + listing_id,
                "address": address_line, "district": address.get("quarter", ""),
                "city": address.get("city", ""),
                "latitude": coordinates.get("latitude"),
                "longitude": coordinates.get("longitude"),
                "rent": warm_rent if warm_search else cold_rent,
                "rent_type": "warm" if warm_search else "cold",
                "cold_rent": cold_rent, "warm_rent": warm_rent,
                "warm_rent_calculation": total.get("calculationMode"),
                "size": real.get("livingSpace"), "rooms": real.get("numberOfRooms"),
                "published": entry.get("@publishDate", ""),
                "modified": entry.get("@modification", ""),
                "is_private": _boolean(real.get("privateOffer")),
                "paywall_active": _boolean(paywall.get("active")),
                "paywall_expires": paywall.get("endDate"),
                "real_estate_type": real.get("@xsi.type", ""),
            })
    return SearchPage(listings, page, page_size, total_pages, total_hits, next_url, search_url)


class ImmoScoutWebClient:
    """A requests-based search client with explicit session failure handling."""

    def __init__(self, waf_token: str = "", user_agent: str = USER_AGENT,
                 session: Optional[requests.Session] = None, token_provider=None):
        self.session = session if session is not None else requests.Session()
        self.headers = {"Accept": "application/json", "User-Agent": user_agent}
        self.token_provider = token_provider
        if waf_token:
            self.session.cookies.set("aws-waf-token", waf_token,
                                     domain="www.immobilienscout24.de", path="/", secure=True)

    def _request(self, url):
        try:
            return self.session.get(url, headers=self.headers, timeout=30, allow_redirects=False)
        except requests.RequestException as exc:
            # Do not include request headers, cookies, or response bodies in errors.
            raise ImmoScoutWebError(f"Search network error: {type(exc).__name__}") from exc

    @staticmethod
    def _needs_token(response):
        content_type = response.headers.get("Content-Type", "").lower()
        return response.status_code in (401, 403, 202) or (
            response.status_code == 200 and "application/json" not in content_type
        )

    def search_url(self, url: str, skip_paywalled: bool = True) -> SearchPage:
        url = validate_search_url(url)
        response = self._request(url)
        if self._needs_token(response) and "edge.captcha-sdk.awswaf.com" in response.text:
            response.close()
            raise ImmoScoutCaptchaRequired(
                "ImmoScout requires a CAPTCHA for this request. "
                "The Go-only token helper cannot complete a visible CAPTCHA."
            )
        if self._needs_token(response) and self.token_provider:
            bootstrap_html = response.text
            response.close()
            try:
                credentials = self.token_provider(url, bootstrap_html=bootstrap_html)
            except WafRefreshError as exc:
                raise ImmoScoutSessionRequired(str(exc)) from None
            self.headers["User-Agent"] = credentials["user_agent"]
            self.session.cookies.set("aws-waf-token", credentials["token"],
                                     domain="www.immobilienscout24.de", path="/", secure=True)
            response = self._request(url)
        if self._needs_token(response):
            status = response.status_code
            captcha_required = "edge.captcha-sdk.awswaf.com" in response.text
            response.close()
            if captcha_required:
                raise ImmoScoutCaptchaRequired(
                    "ImmoScout requires a CAPTCHA even with the renewed token."
                )
            raise ImmoScoutSessionRequired(
                f"ImmoScout returned HTTP {status} without usable search JSON. "
                "Use --refresh-waf with the Go helper, or supply a current aws-waf-token."
            )
        if response.status_code != 200:
            response.close()
            raise ImmoScoutWebError(f"ImmoScout search returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ImmoScoutWebError("Search returned invalid JSON") from exc
        finally:
            response.close()
        page = parse_search_response(data, source_url=url)
        if skip_paywalled:
            accessible = [listing for listing in page.listings if not listing["paywall_active"]]
            page.skipped_paywalled = len(page.listings) - len(accessible)
            page.listings = accessible
        # Pagination and hit counts describe the server's unfiltered result.
        # Even an entirely excluded page can have a usable next page.
        return page

    def search(self, region: str, skip_paywalled: bool = True, **kwargs) -> SearchPage:
        return self.search_url(build_search_url(region, **kwargs), skip_paywalled=skip_paywalled)

    def close(self):
        self.session.close()
