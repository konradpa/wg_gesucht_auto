WG-Gesucht Automation Bot
=========================

Automate inquiry messages on WG-Gesucht based on your search criteria. Uses the web API flow (no browser automation) and supports filters like Bezirk and time-limited offers.

Features
--------
- Web API auth (no browser automation)
- Scheduled runs
- Duplicate prevention
- Bezirk filtering (with pagination to avoid missing matches)
- Optional Gemini personalization of messages
- Exclude time-limited offers (Zwischenmiete)
- Run logging and status tracking

Requirements
------------
- Python 3.9+
- WG-Gesucht account

Local Setup
-----------
1) Create venv and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Create config and message template

```bash
cp config.example.yaml config.yaml
cp message.example.txt message.txt
```

3) Edit `config.yaml` and `message.txt`

Quick Run
---------
```bash
# Test login
python run.py --test-login

# Dry run
python run.py --once --dry-run

# Send messages
python run.py --once --send

# Scheduled run
python run.py
```

Config Notes
------------
- `bezirk`: list of districts to include.
- `limit`, `max_pages`: increase if you filter heavily and only get a few matches.
- `target_filtered_offers`: how many filtered offers to collect before stopping (0 = auto).
- `contact_zwischenmiete`: set false to exclude time-limited offers.
- `mark_contacted_in_dry_run`: keep false to avoid polluting `contacted.json`.

Deployment (Server + systemd)
-----------------------------
1) Upload to server (from local)

```bash
rsync -avz --exclude='.venv' --exclude='__pycache__' \
  --exclude='session.json' --exclude='contacted.json' \
  ./ your_user@your_server_ip:~/wg_gesucht_auto/
```

2) SSH and install

```bash
ssh your_user@your_server_ip
cd ~/wg_gesucht_auto
./deploy_server.sh
```

Or manually:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3) Create config and message on the server

```bash
cp config.example.yaml config.yaml
cp message.example.txt message.txt
nano config.yaml
nano message.txt
```

4) Install systemd service

```bash
sudo cp wg-gesucht-bot.service /etc/systemd/system/
sudo sed -i 's/YOUR_USERNAME/your_user/g' /etc/systemd/system/wg-gesucht-bot.service
sudo systemctl daemon-reload
sudo systemctl enable wg-gesucht-bot
sudo systemctl start wg-gesucht-bot
```

5) Logs and Status

```bash
# View systemd logs
sudo journalctl -u wg-gesucht-bot -f

# Check bot status and history
python3 status.py

# View detailed log file
cat logs/bot.log
```


Use `config.example.yaml` and `message.example.txt` as templates for publishing.

Disclaimer
----------
This is an unofficial client. Use at your own risk and respect WG-Gesucht terms.
