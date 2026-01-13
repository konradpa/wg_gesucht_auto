#!/usr/bin/env python3
"""
Check WG-Gesucht Bot status and recent activity
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.logger import get_logger


def main():
    logger = get_logger()
    summary = logger.get_summary()
    
    print("\n" + "=" * 50)
    print("🏠 WG-Gesucht Bot Status")
    print("=" * 50)
    
    if summary.get("total_runs", 0) == 0:
        print("\n⚠ No runs recorded yet")
        return
    
    print(f"\n📊 Summary:")
    print(f"   Total runs: {summary['total_runs']}")
    print(f"   Runs (last 24h): {summary['runs_last_24h']}")
    print(f"   Messages sent (last 24h): {summary['messages_last_24h']}")
    print(f"\n🕐 Last run:")
    print(f"   Time: {summary['last_run']}")
    print(f"   Status: {summary['last_run_status']}")
    print(f"   Messages: {summary['last_run_messages']}")
    
    # Show last 5 runs
    runs = logger.get_last_runs(5)
    if runs:
        print(f"\n📋 Recent runs:")
        for run in reversed(runs):
            ts = run.get('timestamp', 'unknown')[:19]
            status = "✓" if run.get('status') == 'success' else "✗"
            dry = " [DRY]" if run.get('dry_run') else ""
            msgs = run.get('messages_sent', 0)
            found = run.get('offers_found', 0)
            new = run.get('offers_new', 0)
            print(f"   {status} {ts}{dry} - Found: {found}, New: {new}, Sent: {msgs}")
    
    # Check log file
    log_file = Path(__file__).parent / "logs" / "bot.log"
    if log_file.exists():
        print(f"\n📁 Log file: {log_file}")
        print(f"   Size: {log_file.stat().st_size / 1024:.1f} KB")
    
    print()


if __name__ == "__main__":
    main()
