# ImmoScout website contact

Contact endpoint and payload were captured by the user on 2026-10-12. The
authenticated exposé GET and preparation flow were verified live. No contact
POST was replayed or sent by the implementation during development.

## Observed request

```http
POST https://www.immobilienscout24.de/expose/<id>?<current listing query>
Content-Type: application/json
Accept: */*
Cookie: <authenticated ImmoScout session>
```

The supplied request contained:

```json
{
  "suspiciousRequest": false,
  "sendUserProfile": true,
  "userProfileExists": true,
  "privacyPolicyAccepted": false,
  "sendButtonDelay": 0,
  "personalData": {
    "firstName": "...",
    "lastName": "...",
    "emailAddress": "...",
    "salutation": "MALE",
    "message": "..."
  },
  "nonceToken": "<per-form token>",
  "isFromCounterOfferModal": false,
  "isTenantNetworkListing": false,
  "requestedDocuments": []
}
```

The actual capture also included address and optional applicant fields. The
two earlier `/abjfo/as/...` requests were advertising conversion tracking.

The user supplied this success response:

```json
{
  "shortlistServiceResult": {"markAsContacted": true, "addedToShortlist": true},
  "successful": true
}
```

The contact client requires a successful HTTP response and the strict JSON
boolean `successful: true`; an HTTP success alone does not confirm delivery.

## Fresh form data

Before preparing an application, GET the target exposé using the authenticated
session. The HTML script assigning `IS24.contactLayerModel` contains:

- `contactForm`: fresh `nonceToken`, `personalData` defaults, verification flags,
  and privacy-checkbox state.
- `extendedContactForm.configuration`: mandatory/optional applicant fields.
- `userProfile.exists`: current saved-profile state.

The outer assignment is JavaScript with unquoted keys, while these nested
objects are JSON. The parser reads those objects without evaluating scripts.
The contact nonce is distinct from the other `IS24.expose.nonceToken`.

The browser subsequently fetches `GET /expose/profile`. The client now follows
this authenticated flow: successful profile data hydrate the HTML placeholders
(including `profileType`) and set `userProfileExists: true`. Unexpected profile
responses stop preparation; a 404 leaves the HTML defaults. Premium-restricted
exposés are rejected before submission.

For the captured listing, the verified required fields were `emailAddress`,
`firstName`, `lastName`, and `salutation`. The client validates the target's own
configuration for each prepared request rather than assuming those four fields
are universal. Verification/captcha flags cause an explicit failure.

Only SSO and SSO-HMAC are imported from cURL. WAF, load-balancer, websessionid,
XSRF, advertising cookies, the captured nonce, and the captured outer send flags
are discarded. The Go helper generates the WAF token in memory.
The capture supplies applicant data and base text; profile forwarding defaults
to false and requires `--share-profile` to enable it.

## Prepare without sending

Both probes now use `config.immoscout.yaml` by default. Browser cookies and
User-Agent live under `immoscout.auth`; values are private, never hardcoded in
source. Only SSO and SSO-HMAC are configured. Other cookie names are rejected
in config, and omitted by the legacy cURL importer.
The original user-supplied capture remains an optional legacy input, but is no
longer required. The authenticated profile endpoint supplies applicant fields.

```bash
.venv/bin/python probe_immoscout_contact.py --refresh-waf \
  --listing-url 'https://www.immobilienscout24.de/expose/LISTING_ID' \
  --message-file message_immoscout.txt
```

This only prepares a draft. No application is submitted without `--send`.
WAF renewal is enabled by default. It performs a read-only search to generate or renew the WAF token
in the same session before loading the contact form; the new token stays in
memory. It does not refresh SSO. Config-based live verification confirmed that
the imported SSO session still loads its saved profile after WAF renewal; the
old captured WAF token alone produced HTTP 401. A later read-only check verified
that only SSO and SSO-HMAC plus a generated token were sufficient for both
search and authenticated form/profile loading. POST with this reduced cookie
set has not been tested. `--no-refresh-waf` disables renewal for diagnostics.

Keep the private copied cURL command in `contact_request.curl` (gitignored):

```bash
.venv/bin/python probe_immoscout_contact.py \
  --curl-file contact_request.curl \
  --listing-url 'https://www.immobilienscout24.de/expose/LISTING_ID' \
  --message-file message_immoscout.txt \
  --output /tmp/immoscout_contact_draft.json
```

Replace `LISTING_ID` with a numeric listing ID. Omitting `--listing-url` prepares
the captured listing. Omitting `--message-file` uses the captured message.
`message_immoscout.example.txt` provides a starting point for an apartment
application; replace its placeholders before using it.

`--profile-file applicant.json` optionally overrides captured applicant fields.
Both native names (`firstName`) and aliases (`firstname`, `lastname`, `email`,
`phone`, `house_number`, `residents`, `pets`, etc.) are accepted. The private
draft contains personal information and a nonce; output is written with mode
0600, while console output shows only listing ID, field names, and message length.

## Explicit submission

For a complete configured search/personalization/send cycle, use
`.venv/bin/python run_immoscout.py --send`. It runs once, observes both daily
and per-run limits, skips previously recorded attempts, and exits. Use
`--dry-run` to preview, or add `--no-llm` to avoid external personalization.
The low-level probe below remains useful for an explicit single listing.

`immoscout.settings.max_messages_per_day` (default 5, 0 disables sending)
limits the contact probe's actual send attempts per Europe/Berlin calendar day.
Slots are reserved persistently before POST, including rejected or uncertain
attempts. Draft preparation does not consume slots. The shared ignored counter
file is `daily_message_counts.json`, with separate counters for each platform
and a lock for concurrent local processes. API callers using the contact client
directly must also reserve a slot; the guard is in the probe, not inside the
low-level client. Keep the counter file across deployments/restarts.

Adding `--send` submits once. It requires an explicit `--listing-url` so the
already-contacted captured listing is not replayed by default. Preparation
always loads fresh form data. Forwarding the saved profile and accepting a
required privacy checkbox have separate explicit options.

Each prepared application can only be attempted once. Timeouts, server errors,
and non-JSON success responses are treated as unknown delivery; check the
account's messages before considering a new attempt. POST is never retried or
redirected automatically.

## Remaining work

- Automatic authenticated-session login/refresh; the current client imports an
  existing browser session. Account passwords alone are not yet sufficient.
- Integration into the generic bot, platform-prefixed contact history, per-platform
  message templates, config, and scheduling.
- Additional flow variants such as tenant-network listings or requested documents.

Verification: 30 regression tests pass. On 2026-10-12, a single authorized live
application to Berlin exposé 117982738 (“Singleapartment”, €378.93 warm,
no premium/WBS requirement) returned `successful: true` after Gemini
personalization and fresh form/profile loading. It was recorded as
`is24:117982738` in the contact history. The earlier premium-listing attempt
171717545 returned HTTP 400 and was not recorded as sent.
