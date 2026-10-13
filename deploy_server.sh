#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
platform="${1:-wg-gesucht}"
case "$platform" in
  wg-gesucht|immoscout) ;;
  *) echo "Usage: $0 [wg-gesucht|immoscout]"; exit 2 ;;
esac

if [ ! -f "/etc/os-release" ]; then
  echo "This script is intended to run on a Linux server."
  exit 1
fi

echo "$platform - Server Setup"
echo "============================="

echo "Installing system packages..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Installing Python dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ "$platform" = "immoscout" ]; then
  if ! command -v go >/dev/null 2>&1; then
    echo "Install Go 1.23.9 or newer on this server, then rerun: ./deploy_server.sh immoscout"
    exit 1
  fi
  echo "Building the ImmoScout helper for this server..."
  mkdir -p bin
  (cd tools/immoscout_waf && go build -o ../../bin/immoscout-waf .)
  if [ ! -f "config.immoscout.yaml" ]; then
    (umask 077; cp config.immoscout.example.yaml config.immoscout.yaml)
  fi
  if [ ! -f "message_immoscout.txt" ]; then
    (umask 077; cp message_immoscout.example.txt message_immoscout.txt)
  fi
  echo "Next steps:"
  echo "1) Edit config.immoscout.yaml and message_immoscout.txt; provide current SSO cookies and your LLM key"
  echo "2) Preview: .venv/bin/python run_immoscout.py --dry-run --no-llm"
  echo "3) Install immoscout-bot.service and immoscout-bot.timer (see README.md)"
  exit 0
fi

if [ ! -f "config.yaml" ]; then
  echo "Creating config.yaml from template..."
  cp config.example.yaml config.yaml
fi

if [ ! -f "message.txt" ]; then
  echo "Creating message.txt from template..."
  cp message.example.txt message.txt
fi

echo ""
echo "Next steps:"
echo "1) Edit config.yaml and message.txt"
echo "2) Test: python run.py --test-login"
echo "3) Start systemd service (see README.md)"
