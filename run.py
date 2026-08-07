#!/usr/bin/env python3
"""
WG-Gesucht Automation Bot
Run this script to start the bot with scheduled execution
"""

import argparse
import os
import re
import time
import sys
from pathlib import Path

import yaml
import schedule

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.bot import WgGesuchtBot


ENV_PLACEHOLDER = re.compile(
    r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}'
)


def expand_environment_variables(config_text: str) -> str:
    """Expand ${VAR} and ${VAR:-default} placeholders in config text."""
    missing = set()

    def replace(match: re.Match) -> str:
        name, default = match.group(1), match.group(2)
        value = os.environ.get(name)
        if value:
            return value
        if default is not None:
            return default
        missing.add(name)
        return match.group(0)

    expanded = ENV_PLACEHOLDER.sub(replace, config_text)
    if missing:
        names = ', '.join(sorted(missing))
        print(f"✗ Missing environment variable(s): {names}")
        print("  Set them before starting the bot, for example: export WG_GESUCHT_EMAIL=...")
        sys.exit(1)
    return expanded


def load_config() -> dict:
    """Load config.yaml, expanding ${ENV_VAR} placeholders from the environment."""
    config_path = Path(__file__).parent / "config.yaml"
    
    if not config_path.exists():
        print("✗ config.yaml not found!")
        print("  Please copy config.example.yaml to config.yaml and fill in your details")
        sys.exit(1)
    
    config_text = config_path.read_text(encoding='utf-8')
    return yaml.safe_load(expand_environment_variables(config_text))


def run_once(config: dict, dry_run: bool = None) -> None:
    """Run the bot once"""
    if dry_run is not None:
        config.setdefault('settings', {})
        config['settings']['dry_run'] = dry_run
    
    bot = WgGesuchtBot(config)
    bot.run()


def run_scheduled(config: dict) -> None:
    """Run the bot on a schedule"""
    interval = config.get('settings', {}).get('interval_minutes', 5)
    
    print(f"\n🚀 Starting WG-Gesucht Bot (every {interval} minutes)")
    print("   Press Ctrl+C to stop\n")
    
    # Run immediately first
    bot = WgGesuchtBot(config)
    bot.run()
    
    # Schedule future runs
    schedule.every(interval).minutes.do(bot.run)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped by user")


def test_login(config: dict) -> None:
    """Test login only"""
    from src.wg_api import WgGesuchtClient
    
    client = WgGesuchtClient()
    email = config['wg_gesucht']['email']
    password = config['wg_gesucht']['password']
    
    print(f"Testing login for: {email}")
    
    if client.login(email, password):
        print("✓ Login successful!")
        print(f"  User ID: {client.user_id}")
        
        # Test city lookup
        city = config['search']['city']
        cities = client.find_city(city)
        if cities:
            print(f"✓ City lookup works: {cities[0].get('city_name')}")
        
        # Test conversations
        conversations = client.get_conversations()
        if conversations is not None:
            print("✓ Conversations access works")
    else:
        print("✗ Login failed!")


def test_llm(config: dict) -> None:
    """Test the configured AI provider."""
    from src.llm_helper import LLMHelper, resolve_llm_config

    resolved = resolve_llm_config(config, require_enabled=False)
    if not resolved:
        print("✗ No LLM API key/config found")
        print("  Add an enabled `llm:` block with an API key to config.yaml")
        return

    provider_name = resolved.get("source") or resolved.get("provider")
    print(f"Testing AI provider: {provider_name}")
    try:
        helper = LLMHelper.from_config(config, require_enabled=False)
        if helper and helper.test_connection():
            print(f"✓ {helper.display_name} API works!")
        else:
            print("✗ LLM API test failed")
    except Exception as e:
        print(f"✗ LLM API test failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="WG-Gesucht Automation Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                  # Run scheduled (default)
  python run.py --once           # Run once only
  python run.py --once --dry-run # Run once in dry-run mode
  python run.py --test-login     # Test login only
  python run.py --test-llm       # Test configured AI provider
        """
    )
    
    parser.add_argument(
        '--once', 
        action='store_true',
        help='Run once and exit (no scheduling)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run - don\'t actually send messages'
    )
    parser.add_argument(
        '--send',
        action='store_true',
        help='Actually send messages (override config dry_run)'
    )
    parser.add_argument(
        '--test-login',
        action='store_true',
        help='Test login only'
    )
    parser.add_argument(
        '--test-llm',
        action='store_true',
        help='Test configured AI provider'
    )
    
    args = parser.parse_args()
    
    # Load config
    config = load_config()
    
    # Handle test modes
    if args.test_login:
        test_login(config)
        return
    
    if args.test_llm:
        test_llm(config)
        return
    
    # Determine dry_run setting
    dry_run = None
    if args.dry_run:
        dry_run = True
    elif args.send:
        dry_run = False
    
    # Run bot
    if args.once:
        run_once(config, dry_run)
    else:
        run_scheduled(config)


if __name__ == "__main__":
    main()
