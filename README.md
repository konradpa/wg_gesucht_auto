# WG-Gesucht Bot

A Python bot that finds WG-Gesucht listings matching your criteria and sends a message to new matches.

It can filter listings by district, price, size, category, and rental type. Message personalization with Gemini, Anthropic, OpenAI, OpenRouter, Groq, Together, or another OpenAI-compatible endpoint is optional.

ImmoScout website search is being investigated separately. The working JSON
endpoint, session requirements, and standalone search probe are documented in
[IMMOSCOUT_WEB_API.md](IMMOSCOUT_WEB_API.md). It is not yet integrated into `run.py`.
The standalone probe supports automatic token renewal with a Go-only helper:
`python probe_immoscout_web.py --refresh-waf --region /de/hamburg/hamburg`.
Build instructions are in the linked document.
ImmoScout now has a complete one-shot runner, `run_immoscout.py`, using its
own config and template. `run.py` still handles WG-Gesucht.

```bash
# Preview once, including configured personalization:
.venv/bin/python run_immoscout.py --dry-run
# Search, personalize and send once, then exit:
.venv/bin/python run_immoscout.py --send
# Preview without transferring the template to an LLM:
.venv/bin/python run_immoscout.py --dry-run --no-llm
```

The runner reads `config.immoscout.yaml` (override with `--config`) and
`message_immoscout.txt`. Add `llm` settings in that config; `${LLM_API_KEY:-}`
is resolved from the process environment or the adjacent private `.env.local`.
Preview mode is the default and sends no contact requests. No scheduler is
started. ImmoScout runtime settings:

```yaml
immoscout:
  settings:
    max_messages_per_run: 1
    max_messages_per_day: 5
    delay_between_messages: 20
    skip_wbs: true
```

Premium restrictions, WBS indicators, and apartment-exchange advertisements
are checked before personalization. This is conservative screening, not a
guarantee that all eligibility requirements are detected. The fresh form/profile
is validated and its nonce reloaded immediately before submission. Invalid LLM
output or API errors stop the run rather than silently sending the template.

Confirmed contacts and pending/rejected/unknown attempts are kept separately in
`immoscout_contacts.json`; the runner also recognizes previous `is24:` contacts
in `contacted.json`. It does not overwrite WG-Gesucht history. Attempts are
recorded before POST, so an interrupted or uncertain submission is never
retried automatically. Review account messages before manually clearing such
entries. A local run lock prevents concurrent runners from duplicating sends.
The low-level contact probe is still available; see
[IMMOSCOUT_CONTACT_API.md](IMMOSCOUT_CONTACT_API.md).

### ImmoScout search configuration

The standalone website probe reads `immoscout.search` from its own
`config.immoscout.yaml`. `config.yaml` configures WG-Gesucht.
Create the ImmoScout config with:

```bash
cp config.immoscout.example.yaml config.immoscout.yaml
```

Browser session cookies can be stored under `immoscout.auth.cookies` in this
ignored private file: only `SSO` and `SSO-HMAC` are needed in the verified
search/form/profile flow. The generated WAF token is never configured or stored.
The contact probe now
reads these cookies by default (the legacy `--curl-file` input is optional).
It fetches the saved applicant profile directly from ImmoScout. Search also
reads the configured session and User-Agent; `IMMOSCOUT_WAF_TOKEN`, the hidden
token prompt, and `IMMOSCOUT_USER_AGENT` override their corresponding values.
WAF generation/renewal is enabled by default in both probes; `--no-refresh-waf`
disables it for diagnostics. It does not refresh SSO
login or rewrite cookies in the config. Copy new SSO cookies when login expires.
The contact probe validates/generates the token in its own session before
preparing a draft. Reduced-cookie POST delivery has not yet been tested.

```yaml
immoscout:
  search:
    region: "/de/berlin/berlin"
    bezirk: ["Pankow", "Friedrichshain-Kreuzberg"]  # [] = all districts
    ortsteil: []  # e.g. ["Prenzlauer Berg", "Kreuzberg"]
    max_warm_rent: 1500  # inclusive EUR; unknown warm rent is excluded
    min_size: 0
    min_rooms: 0
    max_pages: 5
    skip_paywalled: true
```

```bash
.venv/bin/python probe_immoscout_web.py --refresh-waf
# Optional overrides; --bezirk can be repeated:
.venv/bin/python probe_immoscout_web.py --refresh-waf --bezirk Pankow --max-price 1200 --max-pages 2
```

Berlin districts are assigned locally using listing coordinates and bundled
official district polygons. Missing coordinates fall back to an exact official
neighborhood-to-district mapping (e.g. Prenzlauer Berg → Pankow). Advertiser
coordinates may be approximate. Invalid or outside coordinates and unknown
locations are excluded when a district filter is set. Postal codes and
substring matches are not used. No addresses are sent to a geocoding service.

Supported districts: Mitte, Friedrichshain-Kreuzberg, Pankow,
Charlottenburg-Wilmersdorf, Spandau, Steglitz-Zehlendorf, Tempelhof-Schöneberg,
Neukölln, Treptow-Köpenick, Marzahn-Hellersdorf, Lichtenberg, Reinickendorf.
Umlaut spellings such as `Neukoelln` are also accepted. Unknown names fail with
an error. The data and provenance are in [data/berlin/SOURCE.md](data/berlin/SOURCE.md).

`ortsteil` filters exact official Berlin neighborhoods using the bundled ALKIS
neighborhood polygons, with exact neighborhood-name fallback if coordinates
are absent. Use `bezirk: []` to filter by neighborhoods alone. When both lists
are populated, both must match. For example:

```yaml
    bezirk: []
    ortsteil: ["Prenzlauer Berg", "Kreuzberg", "Neukölln"]
```

Here `Neukölln` refers to the neighborhood, excluding other neighborhoods of the
Neukölln district such as Britz or Buckow. The probe also accepts repeatable
`--ortsteil` arguments. Exports include `berlin_ortsteil` and `ortsteil_source`.

Local exclusions leave server pagination intact; the probe continues scanning
up to `max_pages` even when a page has no matches. A single-page JSON export
contains the normalized page; multiple pages export `{"pages": [...]}`.
`--include-premium` overrides premium exclusion for inspection. These settings
control the read-only probe and `run_immoscout.py`, not WG-Gesucht's `run.py`.
The one-shot runner checks contact requirements in the exposé before sending.

## Setup

Daily sending limits are configured separately for each platform:

```yaml
# config.yaml (WG-Gesucht)
settings:
  max_messages_per_day: 5

# config.immoscout.yaml
immoscout:
  settings:
    max_messages_per_day: 5
```

The WG-Gesucht bot, ImmoScout one-shot runner and contact probe enforce these limits. Each actual
send attempt consumes a slot before POST; failures and uncertain outcomes also
count. Read-only searches and draft preparation consume no slots. `0` disables
sending. The existing WG-Gesucht `max_messages_per_run` still applies too.
Counts are stored in the ignored `daily_message_counts.json`, survive restarts,
and reset by calendar day in Europe/Berlin. A separate file lock prevents
parallel local processes from exceeding the quota. Keep this file when
deploying or restarting; multiple machines with separate counters are not
coordinated. A daily cap does not guarantee avoidance of bot detection.

Requires Python 3.9 or newer.

### Local installation

1. Clone the repository and install the dependencies.

```bash
git clone https://github.com/konradpa/wg_gesucht_auto.git
cd wg_gesucht_auto
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the setup wizard.

```bash
python setup.py
```

The wizard creates `config.yaml` and `message.txt`. To create them manually instead:

```bash
cp config.example.yaml config.yaml
cp message.example.txt message.txt
```

3. Test the login.

```bash
export WG_GESUCHT_EMAIL='you@example.com'
read -rsp 'WG-Gesucht password: ' WG_GESUCHT_PASSWORD; export WG_GESUCHT_PASSWORD; echo
read -rsp 'LLM API key (optional): ' LLM_API_KEY; export LLM_API_KEY; echo
python run.py --test-login
```

The example config uses `${WG_GESUCHT_EMAIL}`, `${WG_GESUCHT_PASSWORD}`, and `${LLM_API_KEY}` placeholders.
They are read from environment variables at startup, so the actual credentials do not need
to be stored in `config.yaml`. These `export` values apply only to the current shell session;
use a protected service environment file for a persistent systemd setup.

4. Search without sending messages.

```bash
python run.py --once --dry-run
```

5. Send messages once or start the scheduled process.

```bash
python run.py --once --send
python run.py
```

### Server installation

To run the bot continuously, copy it to a Linux server:

```bash
rsync -avz --exclude='.venv' --exclude='__pycache__' \
  --exclude='session.json' --exclude='contacted.json' \
  ./ your_user@your_server_ip:~/wg_gesucht_auto/
```

Connect to the server and run the deployment script:

```bash
ssh your_user@your_server_ip
cd ~/wg_gesucht_auto
./deploy_server.sh
```

The deployment script creates `config.yaml` and `message.txt` from the example files when they do not already exist. Edit them before starting the service:

```bash
nano config.yaml
nano message.txt
```

Install the systemd service:

```bash
sudo cp wg-gesucht-bot.service /etc/systemd/system/
sudo sed -i "s/YOUR_USERNAME/$USER/g" /etc/systemd/system/wg-gesucht-bot.service
sudo systemctl daemon-reload
sudo systemctl enable wg-gesucht-bot
sudo systemctl start wg-gesucht-bot
```

View logs and status:

```bash
sudo journalctl -u wg-gesucht-bot -f
python3 status.py
cat logs/bot.log
```

## Configuration

All settings are stored in `config.yaml`.

### Account

| Option | Description |
| --- | --- |
| `email` | WG-Gesucht login email |
| `password` | WG-Gesucht password |

### Search

| Option | Default | Description |
| --- | --- | --- |
| `city` | `"Hamburg"` | City to search |
| `bezirk` | `[]` | Districts to include. An empty list includes all districts |
| `max_price` | `650` | Maximum monthly rent in euros |
| `min_size` | `0` | Minimum room size in m² |
| `categories` | `"0"` | `0` for a WG room, `1` for a studio, `2` for an apartment, `3` for a house |
| `limit` | `20` | Listings loaded per page |
| `max_pages` | `5` | Pages scanned per run |
| `target_filtered_offers` | `0` | Number of matching results to collect before stopping. `0` selects this automatically |
| `contact_zwischenmiete` | `false` | Whether to include temporary rentals and sublets |

### Message personalization

| Option | Default | Description |
| --- | --- | --- |
| `enabled` | `false` | Enables LLM-based message personalization |
| `provider` | `"gemini"` | `gemini`, `anthropic`, `openai`, `openrouter`, `groq`, `together`, or `openai_compatible` |
| `api_key` | `""` | API key for the selected provider |
| `model` | `"gemini-1.5-flash"` | Model name |
| `base_url` | `""` | Custom endpoint for an OpenAI-compatible provider |

Provider examples:

```yaml
provider: "gemini"
provider: "anthropic"
provider: "openai"
provider: "openrouter"
provider: "groq"
provider: "together"
provider: "openai_compatible"
```

Gemini API keys are available from [Google AI Studio](https://aistudio.google.com/apikey). OpenRouter, Groq, and Together use their default base URLs. Set `base_url` when using a custom or local endpoint.

To enable personalization, set `llm.enabled` to `true`, configure the provider, API key, and model, then run:

```bash
python run.py --test-llm
```

### Bot

| Option | Default | Description |
| --- | --- | --- |
| `interval_minutes` | `20` | Time between searches |
| `max_messages_per_run` | `2` | Maximum messages sent per search |
| `delay_between_messages` | `20` | Delay between messages in seconds |
| `dry_run` | `true` | Searches without sending messages |
| `mark_contacted_in_dry_run` | `false` | Records listings as contacted during dry runs |
| `contact_email` | `""` | Email added when a listing asks for it |
| `contact_phone` | `""` | Phone number added when a listing asks for it |

## Message template

The message template is stored in `message.txt`. Use `{name}` for the contact name.

```text
Hallo {name},

ich habe eure Anzeige gesehen und bin sehr interessiert an dem Zimmer.

Kurz zu mir: Ich bin 25, studiere Informatik und suche ein Zimmer ab März.

Ich freue mich über eine Rückmeldung!

Liebe Grüße,
Max
```

Without personalization, the bot sends the template after replacing `{name}`. When personalization is enabled, it adapts the message to the listing while keeping the template's tone and length. If personalization fails, the original template is used.

## Commands

| Command | Description |
| --- | --- |
| `python run.py` | Start the scheduled process |
| `python run.py --once --dry-run` | Search once without sending messages |
| `python run.py --once --send` | Search once and send messages |
| `python run.py --test-login` | Test the WG-Gesucht login |
| `python run.py --test-llm` | Test the configured LLM provider |
| `python status.py` | Show recent activity |
| `python setup.py` | Run the setup wizard |

## Troubleshooting

### Login fails

Check the email and password in `config.yaml`, confirm that the same credentials work on [WG-Gesucht](https://www.wg-gesucht.de), then run `python run.py --test-login`.

### No messages are sent

The listings may already be recorded in `contacted.json` or excluded by the filters. Confirm that `dry_run` is `false`, or use the `--send` option. If needed, widen the districts or increase `max_price`.

Delete `contacted.json` only when you intentionally want to reset the contact history.

### No listings are found

Check that the city name matches WG-Gesucht, review the selected categories, and increase `max_pages` if the filters are strict.

### Personalization fails

Run `python run.py --test-llm` and check `llm.provider`, `llm.model`, `llm.api_key`, and `llm.base_url`. The bot uses the original message template if personalization is unavailable.

## Disclaimer

This is an unofficial project and is not affiliated with WG-Gesucht. Use it responsibly and follow the platform's terms of service.

## License

[MIT](LICENSE)
