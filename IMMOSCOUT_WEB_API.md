# ImmoScout website search: reverse engineering

Verified on 2026-10-12 using Chrome's Network panel and direct Python requests.
This is the first investigation step; the existing WG-Gesucht runtime is unchanged.

## Working search endpoint

The website route itself also serves the search JSON:

```http
GET https://www.immobilienscout24.de/Suche/de/berlin/berlin/wohnung-mieten?sorting=2&pagenumber=2
Accept: application/json
User-Agent: <browser user agent>
Cookie: aws-waf-token=<current browser token>
```

The user-supplied Berlin page-2 request was replayed successfully with `requests`:
HTTP 200, `application/json;charset=utf-8`, 20 listings, page number 2.
The minimal request needed only `Accept`, `User-Agent`, and the supplied
`aws-waf-token` cookie. Account credentials and the other copied cookies were
not needed for those successful searches. This does not establish that the
token is always required, portable across machines, or sufficient indefinitely.

An earlier request without the cookie received HTTP 401 and an HTML response
from CloudFront. One filtered page-1 request also received HTTP 401 with the
cookie, while the following filtered page-2 request succeeded. A browser token
therefore makes the observed requests reproducible, but is not a reliable
unattended authentication solution. The client can now use the optional
Go-only helper to acquire a fresh token on rejection and retry the search once.

## Verified filters

| Website query parameter | Meaning | Verified value |
| --- | --- | --- |
| `sorting` | Newest first | `2` |
| `pagenumber` | Page, starting at 1 | `2` |
| `price` | Maximum monthly rent | `-900.0` |
| `pricetype` | Warm-rent search | `calculatedtotalrent` |
| `livingspace` | Minimum area | `40.0-` |
| `numberofrooms` | Minimum rooms | `2.0-` |

The website's canonical first-page URL omits `pagenumber`; the client does the
same. In a live Hamburg check, the otherwise equivalent explicit
`pagenumber=1` request returned a CAPTCHA page while the canonical route
returned search JSON with the same fresh Go token. This is an observed
route-specific difference, not a guarantee that canonical routes never
require a CAPTCHA.

Example:

```text
/Suche/de/berlin/berlin/wohnung-mieten?sorting=2&pagenumber=2&price=-900.0&pricetype=calculatedtotalrent&livingspace=40.0-&numberofrooms=2.0-
```

The successful filtered response's `additional.queryModel` confirmed
`priceRangeWithType.type=CALCULATED_TOTAL_RENT`, maximum 900, minimum area 40,
and minimum rooms 2. It contained 20 entries on page 2. Counts change as
listings are added and removed; the test returned 2,056 total hits.

The UI also uses SEO routes such as `/wohnung-bis-900-euro-warm`; the generic
`/wohnung-mieten` route with explicit parameters worked in the direct replay.
`enteredFrom` is UI tracking metadata and was omitted in successful tests.
District paths can be obtained from the website's search links. Other rental
types, multi-region requests, and cold-rent filtering still need live checks.

## Response fields

```text
searchResponseModel
  additional
    queryModel                         JSON-encoded query and sorting model
    resultListUrl                      website URL
    lastSearchApiUrl                    internal /region?... URL, can be stale!
  resultlist.resultlist
    paging
      pageNumber, pageSize, numberOfPages, numberOfHits
      next.@xlink.href                  next website search URL
    resultlistEntries[]
      resultlistEntry[]
        @id, @publishDate, @modification
        resultlist.realEstate
          title, address, livingSpace, numberOfRooms
          address.wgs84Coordinate.latitude / longitude  optional
          price.value                  cold rent
          calculatedTotalRent.totalRent.value
          calculatedTotalRent.calculationMode
          privateOffer                 string "true" / "false"
          paywallListing.active        string "true" / "false"
          paywallListing.endDate
```

### Excluding Suchen+ listings

`ImmoScoutWebClient.search()` and `search_url()` now exclude listings with
`paywall_active: true` by default. This is a local filter of the returned JSON;
no server-side parameter for excluding premium listings has been verified.
Use `skip_paywalled=False` or the probe's `--include-premium` to inspect all
results. `skipped_paywalled` counts exclusions on the current page. Server hit
counts and pagination remain unchanged: continue to `next_url` even if a page
has no remaining listings. Expired restrictions are evaluated from the fresh
server `active` flag on subsequent searches.

Live check: Berlin, newest first, up to €1,500 warm returned 20 raw listings;
6 Suchen+ listings were excluded and 14 remained. WBS requirements are a
separate eligibility check. Contact preparation also rejects exposés marked
`isFreemium` or `ppaWithPremiumProfile`; paid-account contact support is not
implemented.

### Configured warm rent and Berlin districts

The probe reads `immoscout.search` from `config.immoscout.yaml`; `--config` selects another
file. `max_warm_rent` always refers to warm rent and is checked locally in
addition to the server query. Missing warm rent is excluded. Defaults are all
Berlin districts, €1,500 warm, five pages, and premium exclusion. CLI overrides
include `--bezirk` (repeatable), `--max-price`, and `--max-pages`.

Normalized listings now retain `city`, `latitude`, and `longitude`. In the
verified Berlin first page, 17/20 listings had WGS84 coordinates. The local
resolver in `src/immoscout_settings.py` uses official Berlin ALKIS district
polygons and supports Polygon/MultiPolygon geometries and holes. Without
coordinates, exact official neighborhood names map to current districts.
The source data are bundled in `data/berlin`; provenance and license are in
`data/berlin/SOURCE.md`. Filtering annotates `berlin_district` and
`district_source` (`coordinates`, `neighborhood`, `district_name`, `unknown`).
Unresolvable locations do not pass an active district filter. No external
geocoding is performed. Coordinates may be approximate, especially near district
boundaries. Other cities can still be searched, but the district whitelist
currently supports Berlin only.

`ortsteil` adds a neighborhood whitelist, using the official bundled Ortsteile
polygons in `data/berlin/neighborhoods.geojson`. Coordinates take precedence;
without them, the exact normalized advertised neighborhood name is used.
Invalid/outside coordinates never fall back to conflicting text. Both filters
are combined with AND; set `bezirk: []` for neighborhood-only selection.
`--ortsteil` can be repeated. Normalized exports now include `berlin_ortsteil`
and `ortsteil_source`. A selected name such as `Neukölln` refers to that specific
neighborhood, rather than the entire Neukölln district.

Use `paging` for pagination. On the verified Berlin page-2 response,
`additional.lastSearchApiUrl` still contained `pagenumber=1` and lacked sorting.
Treat that URL as auxiliary metadata, not as a URL for fetching the current page.

Warm rent may be calculated by ImmoScout; the normalized output retains the
calculation mode. A missing warm-rent value stays null rather than being
replaced with cold rent. The parser handles string booleans explicitly and
excludes contact details, account metadata, tracking fields, and embedded keys
from its output.

## Other observed website endpoints

| Method and path | Input | Response |
| --- | --- | --- |
| `POST /Suche/controller/search/resultCountWithModel` | JSON `{query, nonQueryData}` | `{model, resultCount}` |
| `POST /Suche/controller/search/change.go?otpEnabled=true` | Query model, `Content-Type: text/plain;charset=UTF-8` | `{url}` for the website search |
| `POST /Suche/controller/search/resultsCountAndSearchUrl?shapeIds=...&otpEnabled=true` | Query model | Region IDs, counts, and search URLs |
| `POST /Suche/controller/filtersuggestions` | `{apiUrl, totalHits, searchId}` | UI filter suggestions |

These endpoints were observed returning HTTP 200 in the browser; direct
requests to them have not yet been validated. They are not needed to fetch a
result page when its geographical route and filters are known.

Observed query-model fields:

```json
{
  "realEstateTypes": ["APARTMENT_RENT"],
  "realEstateType": "APARTMENT_RENT",
  "locationSelectionType": "GEO_HIERARCHY",
  "shapeInformations": ["1276003001"],
  "priceRangeWithType": {
    "type": "CALCULATED_TOTAL_RENT",
    "range": {"min": null, "max": 900.0}
  },
  "netAreaRange": {"min": 40.0, "max": null},
  "numberOfRoomsRange": {"min": 2.0, "max": null}
}
```

This excerpt describes relevant fields; it is not a validated minimal body for
the POST endpoints. Berlin's region ID is `1276003001`; Hamburg's observed ID
is `1276006001`. Website sorting options included codes 0 (standard),
2 (newest), 36/37 (warm rent descending/ascending), 5/6 (rooms), and 7/8 (area).
Only sorting code 2 was directly verified in the Python replay.

## Try the client

Automatic Go-only token renewal:

```bash
cd tools/immoscout_waf
go build -o ../../bin/immoscout-waf .
cd ../..
source .venv/bin/activate
python probe_immoscout_web.py --refresh-waf --region /de/berlin/berlin --page 2 --max-price 900 --min-size 40 --min-rooms 2
```

Go 1.23.9 or later is required to build the helper. The binary is self-contained
and does not need Go installed to run. This workspace already has a compiled
macOS ARM64 helper at `bin/immoscout-waf`. Rebuild for your deployment platform.
Use `--waf-helper /path/to/immoscout-waf` to select another binary.

The helper discovers the SDK prefix from the rejected Python response passed
privately over stdin, obtains and
validates a token, and passes it privately to the Python client. Both use the
same token User-Agent. Tokens are held in memory; later searches in the same
client reuse them. A rejected token causes one renewal and one search retry.
Renewal failures terminate that search with an explicit error. A visible
CAPTCHA page is reported separately as `ImmoScoutCaptchaRequired` and does not
invoke the token-only helper. No browser,
CAPTCHA service, account login, or API key is required for the verified flow.

Manual token entry remains available:

Read the current `aws-waf-token` value from the ImmoScout request's Cookies
section in browser DevTools. Enter only its value using the probe's hidden
prompt; it is kept in process memory and not saved in shell history:

```bash
source .venv/bin/activate
python probe_immoscout_web.py --prompt-waf-token --region /de/berlin/berlin --page 2 --max-price 900 --min-size 40 --min-rooms 2
```

Alternatively, export `IMMOSCOUT_WAF_TOKEN` through your normal secret-management
workflow. If needed, set `IMMOSCOUT_USER_AGENT` to the browser's actual user agent.
No password or WAF token belongs in an example config, captured fixture, or log.

Offline verification from a saved response body:

```bash
python probe_immoscout_web.py --from-json /path/to/search-response.json --output /tmp/immoscout-listings.json
python -m unittest discover -s tests -v
```

The new client and probe are isolated from `run.py`. Exposé details, account
login, contacting, and integration into the scheduled bot remain subsequent work.

Validation: 15 offline regression tests passed, including token renewal, retained
credentials, a rejected replacement, renewal failure, canonical first-page
URLs, and visible CAPTCHA detection. The client was also
tested live against the same filtered Berlin page-2 URL: without a token it
reported HTTP 401 as `ImmoScoutSessionRequired`; with the supplied token it
parsed 20 listings, all satisfying the three requested numeric filters, and
returned the next-page URL. No messages were sent.

## Go token renewal: failure cause and working adaptation

The original Go experiment stopped at `aws.Extract` because the ImmoScout page
had no `window.gokuProps` marker. Further inspection showed this is an AWS SDK
integration page, which references `challenge.js` and uses `AwsWafIntegration`.
Its SDK `/inputs?client=browser` endpoint is reachable and returns the
`mp_verify` challenge ID. A retry against those inputs reproduced the actual
upstream failure: `BuildPayload` returned `unknown challengeType`.

The missing implementation exists in [upstream PR #11](https://github.com/xKiian/awswaf/pull/11).
The helper now includes that reviewed patch, plus SDK-prefix discovery and
token validation, with the MIT license and exact source commits recorded in
[tools/immoscout_waf/SOURCE.md](tools/immoscout_waf/SOURCE.md). The fingerprint
dataset is embedded into the binary to remove the upstream working-directory
requirement. Unsupported difficulty levels are rejected; HTTP errors and
empty tokens are reported as failures.

Live validation on 2026-10-12:

- Patched Go library acquired a fresh token and fetched Berlin page 2 as HTTP 200 JSON.
- Existing Python search accepted the Go token and returned 20 filtered listings.
- The final `--refresh-waf` CLI started with no supplied token, acquired one
  automatically, and returned 20 matching listings (warm rent <= 900, area >=
  40, rooms >= 2). Search counts were 2,061 at that time and will change.
- The final Hamburg client check started with no supplied token, returned 20
  matching listings on both pages 1 and 2, and invoked Go renewal exactly once.
  Both pages satisfied warm rent <= 900, area >= 40, and rooms >= 2. Passing the
  rejected Python response to Go avoids differing bootstrap responses between
  the Python and Go HTTP clients.

This confirms the current SDK flow, not indefinite compatibility with future
AWS challenge changes. Both probes now enable the helper by default; use
`--no-refresh-waf` to disable it. It renews only on rejection and holds tokens
in memory. The private auth config contains only SSO and SSO-HMAC.
