#!/usr/bin/env python3
"""
WG-Gesucht Automation Bot
Run this script to start the bot with scheduled execution
"""

import argparse
import time
import sys
from pathlib import Path

import yaml
import schedule

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.bot import WgGesuchtBot


def load_config() -> dict:
    """Load configuration from config.yaml"""
    config_path = Path(__file__).parent / "config.yaml"
    
    if not config_path.exists():
        print("✗ config.yaml not found!")
        print("  Please copy config.yaml.example to config.yaml and fill in your details")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def run_once(config: dict, dry_run: bool = None) -> None:
    """Run the bot once"""
    if dry_run is not None:
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


def test_gemini(config: dict) -> None:
    """Test Gemini API"""
    from src.gemini_helper import test_gemini as _test
    
    api_key = config.get('gemini', {}).get('api_key')
    if not api_key:
        print("✗ No Gemini API key in config")
        return
    
    print("Testing Gemini API...")
    if _test(api_key):
        print("✓ Gemini API works!")
    else:
        print("✗ Gemini API test failed")


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
  python run.py --test-gemini    # Test Gemini API
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
        '--test-gemini',
        action='store_true',
        help='Test Gemini API only'
    )
    
    args = parser.parse_args()
    
    # Load config
    config = load_config()
    
    # Handle test modes
    if args.test_login:
        test_login(config)
        return
    
    if args.test_gemini:
        test_gemini(config)
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
