# Handoff: ImmoScout24 support

## Goal

Extend this bot, which currently searches WG-Gesucht and messages matching listings, so it does the same for ImmoScout24 (immobilienscout24.de). Keep it in this repo and share the LLM, config, logger, scheduler, and deployment code between platforms.

## Repo overview

| File | Role |
| --- | --- |
| `run.py` | CLI (`--once`, `--dry-run`, `--send`, `--test-login`, `--test-llm`), `schedule` loop, `${ENV}` / `${ENV:-default}` expansion in `config.yaml` |
| `src/wg_api.py` | `WgGesuchtClient`: unofficial WG-Gesucht web JSON API (login via `/ajax/sessions.php`, `find_city`, `get_offers`, `get_offer_detail`, `contact_offer`) |
| `src/bot.py` | `WgGesuchtBot.run()`: restore `session.json` or log in, resolve city, paginate, filter (Bezirk, time-limited), skip IDs in `contacted.json`, build message, send |
| `src/llm_helper.py` | `LLMHelper`: message personalization (Gemini, Anthropic, OpenAI-compatible). The prompt in `_build_prompt` is hard-coded to "WG-Bewerber" / "WG-ANZEIGE" |
| `src/logger.py`, `status.py` | Run logging and the status view |
| `src/immoscout_api.py` | **New, uncommitted.** `ImmoScoutClient` for search and exposé (see below) |
| `setup.py`, `deploy_server.sh`, `wg-gesucht-bot.service` | Setup wizard, server deploy, systemd unit |

`src/bot.py` reads WG-Gesucht field names directly (`offer_title`, `district_custom`, `freetext_flatshare`, `available_to_date`, `user_data.public_name`, ...). Each filter also exists twice, with and without logging (`_filter_by_bezirk` / `_filter_by_bezirk_silent`, `_filter_time_limited` / `_filter_time_limited_silent`).

## Current state

`src/immoscout_api.py` is implemented and was tested live on 2026-10-12:

- `search(geocode, real_estate_type, max_price, min_size, min_rooms, price_type, page)` returns flattened listings (`id`, `title`, `url`, `address`, `rent`, `size`, `rooms`, `published`, `is_private`, `paywall_active`, `raw`). Hamburg, ≤ 900 € warm, ≥ 40 m², ≥ 2 rooms returned 39 results. Page 2 works.
- `get_expose(expose_id)` returns `description`, `top_attributes` (Kaltmiete, Warmmiete, Zimmer, Wohnfläche), `attributes`, `contact_name`, `contact_company`, `can_message`, `premium_required`, `form_fields`, `raw`.

Nothing in `bot.py` or `run.py` uses it yet.

## ImmoScout API reference

### Mobile API (works with plain `requests`)

Host: `https://api.mobile.immobilienscout24.de`. Undocumented. Endpoints and user agents come from Fredy (`orangecoding/fredy`, `lib/services/immoscout/mobileApi.js`, `param-support.js`). Fredy is licensed Apache-2.0 + Commons Clause, so port the knowledge rather than copying code.

| Endpoint | User-Agent | Notes |
| --- | --- | --- |
| `POST /search/list?{params}` with body `{"supportedResultListTypes": [], "userData": {}}` | `ImmoScout_28.1_26.5.2_._` | Results in `resultListItems[]`. Keep entries with `type == "EXPOSE_RESULT"` and read `.item`. Up to 50 per page. Pagination info is in `numberOfPages`. |
| `GET /search/total?{params}` | same | `{"totalResults": n, ...}`. Cheap way to validate parameters. |
| `GET /expose/{id}` | `ImmoScout_27.3_26.0_._` | Keys: `header`, `sections`, `contact`, `tracking`, `adTargetingParameters` |

Search parameters:

- `searchType=region`
- `geocodes=/de/hamburg/hamburg`. Districts work as `/de/hamburg/hamburg/eimsbuettel` or `/de/hamburg/hamburg/altona-altstadt` (`/de/hamburg/hamburg/altona/altona-altstadt` returns the same results).
- `realestatetype=apartmentrent | houserent | flatshareroom | ...`
- `pricetype=calculatedtotalrent` (warm, `apartmentrent` only) or `rentpermonth` (cold, all rent types)
- `price=-900.0` (max), `livingspace=40.0-` (min), `numberofrooms=2.0-` (min). Ranges use the form `min-max` and either side may be empty.
- `sorting=-firstactivation` (newest first), `pagenumber=N`
- Parameters are validated per type. An unsupported parameter or value returns `412` with the reason in the body. See Fredy's `param-support.js` for the full table.

Search item fields:

- `attributes` is `[{label: "", value: "572 €"}, {value: "53 m²"}, {value: "2 Zi."}]`. Labels are empty, so identify each value by its unit.
- `address.line`, `address.lat`, `address.lon`
- `published` (for example "vor 2 Stunden"), `isPrivate`
- `paywallListing.active` / `earlyAccessExpiresAt`. "Noch exklusiv für Suchen+" marks early access listings that only a paid Suchen+ account can contact during roughly the first 48 hours.

Exposé `sections[].type` values include `TOP_ATTRIBUTES`, `ATTRIBUTE_LIST` (labels end in `:`), `TEXT_AREA` (description texts), and `CONTACT`. `contact` looks like this:

```json
{
  "mailButtonState": "active",
  "premiumProfileRequiredForContacting": "false",
  "freemiumSettings": {"duration": 48, "freemiumPeriodActive": true, "dateEnding": "..."},
  "contactData": {
    "agent": {"name": "...", "company": "..."},
    "formFieldConfig": {
      "salutationField": "OPTIONAL", "firstnameField": "MANDATORY", "lastnameField": "MANDATORY",
      "emailAddressField": "MANDATORY", "phoneNumberField": "OPTIONAL", "addressField": "MANDATORY",
      "numberOfResidentsField": "OPTIONAL", "incomeAmountField": "OPTIONAL",
      "petsInHouseholdField": "OPTIONAL", "messageField": "OPTIONAL"
    }
  }
}
```

### Website

`https://www.immobilienscout24.de/Suche/...` returns `401` (server `CloudFront`, HTML challenge page) to a plain `requests`/curl call with a browser User-Agent. The web search and contact endpoints have not been mapped.

### Contacting

The website contact endpoint has now been captured: `POST /expose/{id}` with
`personalData`, a fresh `nonceToken`, and authenticated SSO cookies. A success
response has `successful: true`. Before preparing an application, an authenticated
GET supplies the contact nonce and per-listing required fields inside
`IS24.contactLayerModel`. See `IMMOSCOUT_CONTACT_API.md`.

Implemented in `src/immoscout_contact.py` and `probe_immoscout_contact.py`:
read-only preparation, explicit single-attempt submission, mandatory-field
validation, and success detection. The supplied capture was verified through
GET and draft preparation initially. A new, authorized listing was successfully
contacted on 2026-10-12 (117982738); the original captured POST was not replayed. Session login/refresh
and integration into the scheduled bot remain open. These API alternatives
are still relevant:

- The mobile API has no known contact endpoint. Fredy only reads data.
- The official REST API (`rest.immobilienscout24.de`) has `POST /restapi/api/search/v1.0/expose/{id}/contact`. It requires OAuth 1.0a consumer credentials with contact permission granted by ImmoScout (request via service@immobilienscout24.de). Required fields come from `contactFormConfiguration` in the exposé.
- Any contact implementation must fill the form fields from `formFieldConfig`, so it needs an applicant profile in the config.

## Planned design

1. Add `src/core/models.py` with a `Listing` dataclass: `platform`, `id`, `title`, `url`, `rent`, `size`, `rooms`, `district`/`address`, `description`, `contact_name`, `available_from`, `available_to`, `raw`.
2. Add `src/platforms/base.py` with a `Platform` interface: `login()`, `search(page) -> list[Listing]`, `detail(listing) -> Listing`, `contact(listing, message, profile) -> bool`.
3. Move `src/wg_api.py` behind `src/platforms/wg_gesucht.py`, mapping WG-Gesucht fields to `Listing`. Change nothing else and compare `python run.py --once --dry-run` output before and after.
4. Make `bot.py` generic: run each enabled platform through search → filter → dedupe → message → contact. Keep one version of each filter and drop the `_silent` duplicates.
5. Change the config shape:
   ```yaml
   platforms:
     wg_gesucht: {enabled: true, email: ..., password: ..., search: {...}}
     immoscout:
       enabled: true
       geocodes: ["/de/hamburg/hamburg/eimsbuettel"]
       real_estate_type: apartmentrent
       price_type: calculatedtotalrent
       max_price: 900
       min_size: 40
       min_rooms: 2
       skip_paywalled: true
   applicant_profile:
     salutation: ...
     firstname: ...
     lastname: ...
     email: ...
     phone: ...
     street: ...
     postcode: ...
     city: ...
     residents: 1
     income: ...
     pets: false
   llm: {...}       # unchanged
   settings: {...}  # unchanged
   ```
   Keep reading the old flat config (`wg_gesucht` / `search` at top level) as WG-Gesucht for backward compatibility.
6. Prefix IDs in `contacted.json` (`wg:<id>`, `is24:<id>`) and migrate existing IDs to `wg:` once.
7. Use one message template per platform (`message.txt` for WG-Gesucht, `message_immoscout.txt` for ImmoScout). Pass a platform and listing-type context into `LLMHelper._build_prompt` instead of the hard-coded WG wording, so ImmoScout produces an apartment application.
8. In `run.py`, generalize `--test-login` per platform and add a `--platform` filter.
9. Update the README, `config.example.yaml`, and the `setup.py` wizard.

## Open tasks

### Complete ImmoScout one-shot runner

`run_immoscout.py --send` now performs one complete website search/filter/detail/
LLM/contact run and exits; `--dry-run` is the default. `--no-llm` previews or
sends the unchanged template. It loads its own config and `message_immoscout.txt`,
using an optional `message_file` relative to that config. The private ImmoScout
config now includes the existing Gemini settings, max one message/run, a
20-second delay, and `skip_wbs: true`, alongside the existing five/day limit.
Environment placeholders for LLM settings resolve from environment/adjacent
`.env.local` as data only.

The runner checks premium and WBS flags/text, skips exchange advertisements,
validates applicant fields before LLM, reloads a fresh form before POST, and
reserves quota before sending. Search pagination continues across empty filtered
pages. Dedicated crash-safe `immoscout_contacts.json` preserves pending,
rejected, unknown and confirmed results; prior `is24:` entries are read from
WG history without rewriting it. Nonblocking `immoscout_run.lock` serializes
runs. Unknown results stop the run and are not retried. LLM failures stop too.
64 tests pass, with mocked full send flows covering success, duplicates,
unknown delivery, dry runs, pagination, eligibility, daily limits, Gemini,
failure handling and concurrent-run exclusion. No live POST was made during
implementation. `run.py` remains WG-only; an ImmoScout scheduler is not added.
Live verification with `run_immoscout.py --dry-run --no-llm` succeeded using
current config/session: skipped WBS listing 171719127 and prepared listing
171719045 (716 EUR warm, Wilmersdorf). No POST and no LLM transfer occurred
in this read-only check.

### Daily send limits

Both private configs and their examples now set `max_messages_per_day: 5`:
root `settings` for WG-Gesucht and `immoscout.settings` for ImmoScout. Enforced
in `WgGesuchtBot.run()` and `probe_immoscout_contact.py`; 0 disables sending.
`src/daily_message_limit.py` reserves a persistent slot before POST, counts
rejections/unknown outcomes too, and uses Europe/Berlin calendar days. Dry runs
do not reserve slots. Counter file `daily_message_counts.json` and its lock are
ignored; writes are atomic and concurrent local processes serialize through
flock. Invalid state stops sending rather than clearing counts. Separate
machines need a shared quota service; direct low-level contact calls must
explicitly reserve slots. 54 tests pass, including persistence, midnight,
concurrent reservations, zero/corrupt state and both runtime enforcement paths.

### Session cookies in private config

`immoscout.auth.user_agent` and `immoscout.auth.cookies` now hold the session
formerly read from the supplied cURL attachment. The private live config was
reduced to only SSO and SSO-HMAC after a successful read-only verification;
WAF is generated in code. No cookie values are
hardcoded in source. `src/immoscout_auth.py` validates values and builds a
host-scoped secure cookie jar. Both probes read it by default. The contact
probe retains optional `--curl-file` compatibility and hydrates applicant fields
from ImmoScout; config-based mode requires an explicit listing URL. Go token
renewal remains in memory, and automatic SSO refresh remains unimplemented.
Never print or commit cookie values. The example config contains blanks only.
48 tests pass. Read-only live verification: config-based search succeeded with
Go WAF renewal; contact form GET initially returned HTTP 401 using the old
captured token, but form/profile loading succeeded in the same session after
renewal. SSO is still valid. A fresh read-only check using only SSO and SSO-HMAC
plus the generated WAF token succeeded for search and authenticated form/profile
loading. Reduced-cookie POST has not been tested. Both probes enable WAF renewal
by default (`--no-refresh-waf` to disable). Config and legacy cURL cookie
allowlists now accept/import only SSO and SSO-HMAC.

### Config and local district filter

Ortsteil filtering is now supported through `immoscout.search.ortsteil` and
repeatable `--ortsteil` arguments. Bundled official neighborhood geometries
(`data/berlin/neighborhoods.geojson`) come from the same cached WFS response as
the district fallback mapping. Coordinates take precedence, then exact official
neighborhood names when coordinates are absent. Output includes
`berlin_ortsteil`/`ortsteil_source`. Bezirke and Ortsteile are AND-combined;
`bezirk: []` enables neighborhood-only selection. Private config keeps the
user's seven districts with `ortsteil: []`, so adding the feature does not alter
their current area selection.

`config.immoscout.yaml` and `config.immoscout.example.yaml` have an `immoscout.search` block
with `region`, `bezirk`, `max_warm_rent`, `min_size`, `min_rooms`, `max_pages`,
and `skip_paywalled`. These are used by `probe_immoscout_web.py` through
`src/immoscout_settings.py`; `run.py` still runs WG-Gesucht only. The private
config defaults to all Berlin districts and €1,500 warm, without premium.
The ImmoScout probe reads `config.immoscout.yaml` by default. `config.yaml` is
WG-Gesucht only; the ImmoScout block was moved without changing its values.

The website parser retains coordinates and city. The resolver uses bundled
official Berlin ALKIS district polygons (12 districts), falling back to exact
official neighborhood names for listings without coordinates. Provenance and
license: `data/berlin/SOURCE.md`. It annotates `berlin_district` and
`district_source`. Unknown locations cannot pass a district whitelist. The
probe scans through locally empty pages up to `max_pages`. CLI overrides and
JSON export formats are documented in README. Nine new tests cover real
district coordinates, official neighborhood mappings, conflicting/invalid
coordinates, geometry holes, config validation, rent and pagination.
39 tests pass. Live read-only check on two Berlin pages with Pankow/Neukölln
selected returned seven matching listings, all <= €1,500 warm and non-premium.

### Premium exclusion and live contact attempt

The website search client now defaults to `skip_paywalled=True`, filtering the
fresh `paywall_active` flag locally. The probe exposes `--include-premium` for
inspection. Pagination remains the unfiltered server pagination, so an empty
filtered page must not stop iteration. Contact preparation rejects premium
restrictions too. Berlin <= €1,500 warm: 6 of 20 first-page listings excluded;
30 regression tests pass.

The authorized personalized application attempt for exposé 171717545 returned
HTTP 400; it is **not confirmed sent** and was not added to `contacted.json`.
The private attempt record is `logs/immoscout_live_send_171717545.json`.
That listing is premium-only and must not be retried. The user requires a
listing without WBS requirement, strictly below €1,500 warm, and now also
without premium restriction. Gemini personalization and one actual application
are authorized within those constraints.

Read-only frontend investigation found that `GET /expose/profile` loads the
authenticated applicant profile after the initial HTML. The HTML defaults have
`profileType: null` and `userProfile.exists: false`; the profile endpoint returned
`profileType: BASIC` and the same applicant fields as the supplied contact
capture. The contact client now implements this hydration and updates the
saved-profile flag. Rejection JSON is retained privately on the exception and
excluded from its string/repr. The exact cause of HTTP 400 is not known; do not claim it was solely
the premium restriction or repeat the rejected submission.

Successful live test on 2026-10-12: newest eligible first-page Berlin listing
117982738, “Singleapartment”, Seegefelder Str. 38, Spandau, 30.84 m² and
€378.93 warm. Search paywall flag, exposé premium flags, WBS flag and description
were checked. Gemini personalized the user's template, then one fresh-form POST
returned `successful: true`. `contacted.json` contains `is24:117982738`; the
private attempt record is `logs/immoscout_live_send_117982738.json`. Do not resend.

### Website search investigation (2026-10-12)

The user requested reverse engineering the website search first. This now has
a separate read-only client in `src/immoscout_web_api.py` and CLI probe in
`probe_immoscout_web.py`. See `IMMOSCOUT_WEB_API.md` for the observed requests,
response schema, verification, and remaining limitations.

- The `/Suche/de/.../wohnung-mieten` website route returns JSON with
  `Accept: application/json`; no mobile endpoint is involved.
- A supplied browser `aws-waf-token` plus `Accept` and `User-Agent` was sufficient
  for successful Python replays. Login credentials and other cookies were not
  needed for those requests. WAF rejection still occurred on one filtered request.
- Berlin page 2 and newest-first sorting (`sorting=2`) were verified directly.
  Warm rent <= 900, area >= 40, and rooms >= 2 were confirmed in `queryModel`.
- `resultlist.resultlist.paging` is authoritative; `lastSearchApiUrl` can still
  say page 1 on a page-2 response.
- Go-only token renewal now works. The initial missing-`gokuProps` diagnosis
  was incomplete: ImmoScout uses the SDK endpoint and its `mp_verify` challenge.
  Upstream main rejects this challenge type; PR #11 supplies the missing flow.
  The token-only library with that patch is vendored under `tools/immoscout_waf`,
  with MIT license and pinned provenance. The helper dynamically discovers the
  SDK prefix, acquires a token, and verifies search JSON. `--refresh-waf` uses it
  on token rejection and retries once. Tested end-to-end without a supplied
  cookie: 20 filtered listings on Berlin page 2, plus 20 each on Hamburg pages
  1 and 2 with exactly one Go renewal. The rejected response is passed to Go
  over stdin for SDK discovery. The canonical first-page URL omits
  `pagenumber=1`; visible CAPTCHA pages raise `ImmoScoutCaptchaRequired`.
  Fifteen regression tests pass. See `IMMOSCOUT_WEB_API.md`.
- The initial generic-bot refactor was parked in
  `/tmp/immoscout-integration-wip.tar.gz` while this first step is investigated.
  Existing WG-Gesucht runtime files were restored; the refactor is not shipped.

- [ ] Steps 1–4: refactor with no behavior change for WG-Gesucht.
- [ ] ImmoScout search and detail in dry-run mode, using `src/immoscout_api.py`.
- [x] ImmoScout website contact: identify endpoint and implement standalone preparation/submission.
- [x] Verify live contact to a new authorized listing (117982738).
- [ ] Integrate adapter and authenticated session refresh.
- [ ] Polling: new apartment listings get many replies within minutes, so consider a shorter interval for ImmoScout plus random jitter.
- [ ] Steps 5–9: config, migration, templates, CLI, docs.

## Verify

```bash
source .venv/bin/activate
python -c "from src.immoscout_api import ImmoScoutClient as C; r=C().search('/de/hamburg/hamburg', max_price=900); print(len(r), r[0]['id'])"
python run.py --once --dry-run
```
