#!/usr/bin/env bash
set -euo pipefail

if [ ! -f "/etc/os-release" ]; then
  echo "This script is intended to run on a Linux server."
  exit 1
fi

echo "WG-Gesucht Bot - Server Setup"
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
