# 🏠 WG-Gesucht Bot

**Automatically send messages to WG-Gesucht listings that match your search criteria.**

![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)

Stop refreshing WG-Gesucht every 20 minutes — let the bot do it for you. It searches for new listings, filters them by your preferences (district, price, room type), and sends your message automatically. Optionally uses **AI personalization** (Gemini, Anthropic, OpenAI, OpenRouter, Groq, Together, or any OpenAI-compatible endpoint) to tailor messages based on the listing description.

---

## What It Does

- 🔍 **Searches** WG-Gesucht for new listings matching your criteria
- 📬 **Sends messages** to new listings automatically
- 🏘️ **Filters by district** — only contact listings in your preferred Bezirke
- 🚫 **Skips Zwischenmiete** — optionally exclude time-limited offers
- 🤖 **AI personalization** — use Gemini or other LLM providers (optional)
- 🔁 **Runs on a schedule** — checks every X minutes so you never miss a listing
- 📋 **Tracks contacted listings** — never sends duplicate messages

---

## Quick Start

Choose your preferred setup method:

### 🐍 Option A: Python

**1. Requirements:** Python 3.9 or newer. Check with `python3 --version`.

**2. Clone and install**

```bash
git clone https://github.com/konradpa/wg_gesucht_auto.git
cd wg_gesucht_auto
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Run the setup wizard**

```bash
python setup.py
```

This walks you through creating `config.yaml` and `message.txt` interactively.

Or create them manually:

```bash
cp config.example.yaml config.yaml
cp message.example.txt message.txt
```

**4. Test your login**

```bash
python run.py --test-login
```

**5. Do a dry run** (searches but doesn't send messages)

```bash
python run.py --once --dry-run
```

**6. Send messages**

```bash
# Send once
python run.py --once --send

# Run on a schedule (keeps checking for new listings)
python run.py
```

---

### 🖥️ Option B: Server Deployment (24/7)

To run the bot continuously without keeping your laptop open, deploy it to a cheap Linux server (e.g. [Hetzner](https://www.hetzner.com/cloud/) at ~€4/month).

**1. Upload to your server**

```bash
rsync -avz --exclude='.venv' --exclude='__pycache__' \
  --exclude='session.json' --exclude='contacted.json' \
  ./ your_user@your_server_ip:~/wg_gesucht_auto/
```

**2. SSH in and run the deploy script**

```bash
ssh your_user@your_server_ip
cd ~/wg_gesucht_auto
./deploy_server.sh
```

**3. Create your config** (if not uploaded)

```bash
cp config.example.yaml config.yaml
cp message.example.txt message.txt
nano config.yaml
nano message.txt
```

**4. Install as a system service** (auto-starts on boot)

```bash
sudo cp wg-gesucht-bot.service /etc/systemd/system/
sudo sed -i "s/YOUR_USERNAME/$USER/g" /etc/systemd/system/wg-gesucht-bot.service
sudo systemctl daemon-reload
sudo systemctl enable wg-gesucht-bot
sudo systemctl start wg-gesucht-bot
```

**5. View logs**

```bash
sudo journalctl -u wg-gesucht-bot -f    # live system logs
python3 status.py                         # bot status summary
cat logs/bot.log                          # detailed log file
```

---

## Configuration

All settings live in `config.yaml`. Here's what each option does:

### WG-Gesucht Account

| Option | Description |
|--------|-------------|
| `email` | Your WG-Gesucht login email |
| `password` | Your WG-Gesucht password |

### Search Settings

| Option | Default | Description |
|--------|---------|-------------|
| `city` | `"Hamburg"` | City to search in |
| `bezirk` | `[]` | List of districts to include. Leave empty `[]` for all districts |
| `max_price` | `650` | Maximum monthly rent in € |
| `min_size` | `0` | Minimum room size in m² |
| `categories` | `"0"` | What to search for: `0` = WG room, `1` = studio, `2` = apartment, `3` = house |
| `limit` | `20` | Listings per page (increase if you filter heavily) |
| `max_pages` | `5` | Pages to scan per run |
| `target_filtered_offers` | `0` | How many filtered results to collect before stopping. `0` = automatic |
| `contact_zwischenmiete` | `false` | Set `true` to include time-limited/sublet offers |

### LLM Personalization (Optional)

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Set `true` to enable AI message personalization |
| `provider` | `"gemini"` | `gemini`, `anthropic`, `openai`, `openrouter`, `groq`, `together`, or `openai_compatible` |
| `api_key` | `""` | API key for the selected provider |
| `model` | `"gemini-1.5-flash"` | Model name to use |
| `base_url` | `""` | Optional custom endpoint for OpenAI-compatible providers |

Example providers:
- Gemini: `provider: "gemini"` (get key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- Anthropic (Claude): `provider: "anthropic"`
- OpenAI: `provider: "openai"`
- OpenRouter: `provider: "openrouter"` (base URL auto-fills)
- Groq/Together: `provider: "groq"` or `provider: "together"` (base URL auto-fills)
- Custom/local endpoint: `provider: "openai_compatible"` + set `base_url`

### Bot Settings

| Option | Default | Description |
|--------|---------|-------------|
| `interval_minutes` | `20` | How often the bot checks for new listings |
| `max_messages_per_run` | `2` | Max messages to send per check |
| `delay_between_messages` | `20` | Seconds to wait between sending messages |
| `dry_run` | `true` | When `true`, the bot searches but doesn't actually send messages. Set to `false` when ready |
| `mark_contacted_in_dry_run` | `false` | Track listings as contacted even during dry runs |
| `contact_email` | `""` | Your email — included in messages only if the listing asks for it |
| `contact_phone` | `""` | Your phone — included in messages only if the listing asks for it |

---

## Message Template

Your message template lives in `message.txt`. Use `{name}` as a placeholder for the listing contact's name:

```
Hallo {name},

ich habe eure Anzeige gesehen und bin sehr interessiert an dem Zimmer.

Kurz zu mir: Ich bin 25, studiere Informatik und suche ein Zimmer ab März.

Ich freue mich über eine Rückmeldung!

Liebe Grüße,
Max
```

**With AI personalization enabled**, the bot takes this template and personalizes it for each listing — adding references to the specific district, something from the description, etc. The tone and length stay similar to your template.

**Without AI personalization**, the bot sends your template as-is, replacing `{name}` with the contact name.

---

## AI Personalization

AI personalization is **completely optional** but can increase your response rate by making messages feel personal rather than copy-pasted.

**How to set it up:**

1. Pick a provider (`gemini`, `anthropic`, `openai`, `openrouter`, `groq`, `together`, or `openai_compatible`)
2. Add your API key to `config.yaml` under `llm.api_key`
3. Set `llm.enabled` to `true`
4. Set `llm.provider`, `llm.model`, and optionally `llm.base_url`
5. Test it: `python run.py --test-llm`

Legacy `gemini:` configs are still supported for compatibility.

---

## FAQ & Troubleshooting

**"Login failed!"**
- Double-check your email and password in `config.yaml`
- Make sure you can log in on [wg-gesucht.de](https://www.wg-gesucht.de) with those credentials
- Try `python run.py --test-login` for details

**"Bot runs but sends 0 messages"**
- This usually means all found listings were already contacted or filtered out
- Check `contacted.json` — if you're just testing, delete it to reset
- Make sure `dry_run` is set to `false` (or use `--send` flag)
- Try widening your filters (add more districts, increase `max_price`)

**"No offers found"**
- Verify the city name matches WG-Gesucht exactly
- Try different categories (e.g. `"0"` for WG rooms)
- Increase `max_pages` if you have strict filters

**"AI/LLM error"**
- Test your API key/config: `python run.py --test-llm`
- Double-check `llm.provider`, `llm.model`, and `llm.base_url` (if using OpenRouter/Groq/Together/custom endpoint)
- The bot falls back to your template message if AI personalization fails, so messages still get sent

---

## Commands Reference

| Command | What it does |
|---------|-------------|
| `python run.py` | Start the bot on a schedule |
| `python run.py --once --dry-run` | Search once, don't send messages |
| `python run.py --once --send` | Search once, send messages |
| `python run.py --test-login` | Test your WG-Gesucht login |
| `python run.py --test-llm` | Test your configured AI provider |
| `python run.py --test-gemini` | Alias for `--test-llm` (legacy name) |
| `python status.py` | Show bot status and recent activity |
| `python setup.py` | Run the interactive setup wizard |

---

## Disclaimer

This is an **unofficial** tool and is not affiliated with WG-Gesucht. Use it at your own risk and be mindful of WG-Gesucht's terms of service. Be reasonable with check intervals — don't spam the platform.

## License

[MIT](LICENSE) — feel free to use, modify, and share.
