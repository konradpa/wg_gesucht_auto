# WG-Gesucht Bot

A Python bot that finds WG-Gesucht listings matching your criteria and sends a message to new matches.

It can filter listings by district, price, size, category, and rental type. Message personalization with Gemini, Anthropic, OpenAI, OpenRouter, Groq, Together, or another OpenAI-compatible endpoint is optional.

## Setup

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
