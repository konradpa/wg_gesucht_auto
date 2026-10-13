# Wohnungssuche Bot

Search and send personalized applications on **WG-Gesucht** and **ImmoScout**.
Each platform has its own command, configuration, message template and server service.

| Platform | Entry point | Configuration | Template |
| --- | --- | --- | --- |
| WG-Gesucht | `run.py` | `config.yaml` | `message.txt` |
| ImmoScout | `run_immoscout.py` | `config.immoscout.yaml` | `message_immoscout.txt` |

## Install

Requires Python 3.10+; ImmoScout also requires Go 1.23.9+ to build its token helper.
Run from the repository directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Create files only for the platforms you want to use:
cp config.example.yaml config.yaml
cp message.example.txt message.txt
cp config.immoscout.example.yaml config.immoscout.yaml
cp message_immoscout.example.txt message_immoscout.txt

# ImmoScout: build on the machine that will run the bot:
mkdir -p bin
(cd tools/immoscout_waf && go build -o ../../bin/immoscout-waf .)
```

Edit the private configs and message templates before running. They are ignored by Git.
`python setup.py` is also available as an interactive setup wizard.

## Run

### WG-Gesucht

Set `WG_GESUCHT_EMAIL` and `WG_GESUCHT_PASSWORD` in the environment, or replace
those placeholders in your private config. Configure search filters under `search`.

```bash
.venv/bin/python run.py --test-login
.venv/bin/python run.py --once --dry-run  # Preview
.venv/bin/python run.py --once --send     # Send once
.venv/bin/python run.py --send            # Scheduled; settings.interval_minutes
```

### ImmoScout

Put current browser cookies `SSO` and `SSO-HMAC` under `immoscout.auth.cookies`.
The Go helper generates WAF tokens automatically; replace SSO cookies manually
when login expires.

```bash
.venv/bin/python run_immoscout.py --dry-run --no-llm  # Preview with template
.venv/bin/python run_immoscout.py --dry-run           # Preview with configured LLM
.venv/bin/python run_immoscout.py --send              # Send once, then exit
```

ImmoScout defaults to preview mode. Search settings go under `immoscout.search`:

```yaml
region: /de/berlin/berlin
bezirk: []                              # Empty = all districts
ortsteil: [Prenzlauer Berg, Kreuzberg]   # Empty = all neighborhoods
max_warm_rent: 1500                     # Inclusive EUR; unknown warm rent excluded
min_size: 0                             # m²; 0 = no minimum
min_rooms: 0
max_pages: 5
skip_paywalled: true
```

Berlin district and neighborhood filters use bundled official polygons and listing
coordinates, with exact neighborhood-name fallback when coordinates are absent.
If both lists are populated, both must match. Unknown locations are excluded when
geo filters are active; approximate advertiser coordinates can affect results.
See [geodata provenance](data/berlin/SOURCE.md).

The runner checks premium restrictions, WBS requirements (`settings.skip_wbs`)
and apartment exchanges before sending. ImmoScout uses verified formal salutations.
These checks cannot detect every eligibility requirement. API details and the
read-only search probe are documented in [IMMOSCOUT_WEB_API.md](IMMOSCOUT_WEB_API.md).

## Personalization and limits

Both configs support `llm.enabled`, `provider`, `model` and `api_key`.
Providers: Gemini, Anthropic, OpenAI, OpenRouter, Groq, Together and OpenAI-compatible
endpoints. Set `LLM_API_KEY` for the example placeholder. ImmoScout also reads it
from the adjacent private `.env.local`. Personalization sends your template and
listing context to the configured provider. WG-Gesucht falls back to its template
on LLM failure; ImmoScout stops the run.

Sending limits live under `settings` for WG-Gesucht and `immoscout.settings` for
ImmoScout: `max_messages_per_run`, `max_messages_per_day` and
`delay_between_messages`. Daily limits reset at midnight **Europe/Berlin**.
Failed and uncertain send attempts count; previews do not. A daily limit of `0`
disables sending.

Keep `contacted.json`, `immoscout_contacts.json` and `daily_message_counts.json`
when updating or moving to a server. ImmoScout never automatically retries pending,
rejected or uncertain contacts. Run each platform on one machine at a time;
locks and counters are local.

## Linux server

The deployment script targets Debian/Ubuntu and prepares each platform separately.
It does not start services:

```bash
./deploy_server.sh wg-gesucht
./deploy_server.sh immoscout  # Install Go first; builds the Linux helper
```

Fill in your configs and templates. Protect private files with `chmod 600`.
For WG-Gesucht environment placeholders, add an `EnvironmentFile=` pointing to a
protected file in its service, or use values in the private config.

Service templates assume `/home/YOUR_USERNAME/wg_gesucht_auto`; replace the user
and adjust `WorkingDirectory` and `ExecStart` if your checkout is elsewhere.
After a successful preview, install the services you want:

```bash
sudo cp wg-gesucht-bot.service immoscout-bot.service immoscout-bot.timer /etc/systemd/system/
sudo sed -i "s/YOUR_USERNAME/$USER/g" /etc/systemd/system/wg-gesucht-bot.service /etc/systemd/system/immoscout-bot.service
sudo systemctl daemon-reload

# Independent start commands; these enable actual sending:
sudo systemctl enable --now wg-gesucht-bot.service
sudo systemctl enable --now immoscout-bot.timer
```

WG-Gesucht schedules internally. ImmoScout runs once per timer invocation,
then waits five minutes after completion; runs do not overlap.
WG-Gesucht still respects `settings.dry_run` in its config.

```bash
# Logs:
sudo journalctl -u wg-gesucht-bot.service -f
sudo journalctl -u immoscout-bot.service -f

# Stop independently:
sudo systemctl disable --now wg-gesucht-bot.service
sudo systemctl disable --now immoscout-bot.timer
sudo systemctl stop immoscout-bot.service  # Stop any active invocation too
```

## Checks

```bash
.venv/bin/python -m unittest discover -s tests -q
(cd tools/immoscout_waf && go test ./...)
```

Unofficial project; not affiliated with either platform. [MIT license](LICENSE).
