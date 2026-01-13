"""
Logging utilities for WG-Gesucht Bot
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class BotLogger:
    """Logger that writes to both console and file with structured run tracking"""
    
    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or Path(__file__).parent.parent / "logs"
        self.log_dir.mkdir(exist_ok=True)
        
        # Log file paths
        self.log_file = self.log_dir / "bot.log"
        self.runs_file = self.log_dir / "runs.json"
        
        # Setup Python logger
        self.logger = logging.getLogger("wg-gesucht-bot")
        self.logger.setLevel(logging.DEBUG)
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter('%(message)s')
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)
        
        # File handler
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', 
                                         datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(file_format)
        self.logger.addHandler(file_handler)
        
        # Current run stats
        self.current_run: Dict[str, Any] = {}
    
    def start_run(self) -> None:
        """Start a new run and initialize stats"""
        self.current_run = {
            "timestamp": datetime.now().isoformat(),
            "status": "started",
            "offers_found": 0,
            "offers_filtered": 0,
            "offers_new": 0,
            "messages_sent": 0,
            "dry_run": False,
            "errors": [],
            "contacted_offers": []
        }
        self.info("=" * 50)
        self.info(f"🏠 WG-Gesucht Bot Run - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.info("=" * 50)
    
    def end_run(self, success: bool = True) -> None:
        """End the current run and save stats"""
        self.current_run["status"] = "success" if success else "failed"
        self.current_run["end_timestamp"] = datetime.now().isoformat()
        self._save_run()
        
        self.info("=" * 50)
        status = "✓" if success else "✗"
        self.info(f"{status} Run complete. Messages sent: {self.current_run['messages_sent']}")
        self.info(f"  Offers found: {self.current_run['offers_found']}, "
                  f"Filtered: {self.current_run['offers_filtered']}, "
                  f"New: {self.current_run['offers_new']}")
    
    def _save_run(self) -> None:
        """Save the current run to runs.json"""
        runs = self._load_runs()
        runs.append(self.current_run)
        
        # Keep only last 100 runs
        runs = runs[-100:]
        
        with open(self.runs_file, 'w', encoding='utf-8') as f:
            json.dump({"runs": runs}, f, indent=2, ensure_ascii=False)
    
    def _load_runs(self) -> list:
        """Load previous runs from runs.json"""
        if self.runs_file.exists():
            try:
                with open(self.runs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("runs", [])
            except Exception:
                pass
        return []
    
    def set_stats(self, **kwargs) -> None:
        """Update current run stats"""
        self.current_run.update(kwargs)
    
    def log_contacted(self, offer_id: str, title: str, success: bool) -> None:
        """Log a contacted offer"""
        self.current_run["contacted_offers"].append({
            "offer_id": offer_id,
            "title": title[:50],
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        if success:
            self.current_run["messages_sent"] += 1
    
    def log_error(self, error: str) -> None:
        """Log an error"""
        self.current_run["errors"].append({
            "error": error,
            "timestamp": datetime.now().isoformat()
        })
        self.error(error)
    
    # Convenience methods
    def info(self, msg: str) -> None:
        self.logger.info(msg)
    
    def debug(self, msg: str) -> None:
        self.logger.debug(msg)
    
    def warning(self, msg: str) -> None:
        self.logger.warning(msg)
    
    def error(self, msg: str) -> None:
        self.logger.error(msg)
    
    def get_last_runs(self, n: int = 10) -> list:
        """Get the last N runs for display"""
        runs = self._load_runs()
        return runs[-n:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of recent activity"""
        runs = self._load_runs()
        if not runs:
            return {"total_runs": 0, "message": "No runs yet"}
        
        last_24h = [r for r in runs if self._within_hours(r.get("timestamp", ""), 24)]
        
        return {
            "total_runs": len(runs),
            "runs_last_24h": len(last_24h),
            "messages_last_24h": sum(r.get("messages_sent", 0) for r in last_24h),
            "last_run": runs[-1].get("timestamp", "unknown"),
            "last_run_status": runs[-1].get("status", "unknown"),
            "last_run_messages": runs[-1].get("messages_sent", 0)
        }
    
    def _within_hours(self, timestamp: str, hours: int) -> bool:
        """Check if timestamp is within the last N hours"""
        try:
            dt = datetime.fromisoformat(timestamp)
            diff = datetime.now() - dt
            return diff.total_seconds() < hours * 3600
        except Exception:
            return False


# Global logger instance
_logger: Optional[BotLogger] = None


def get_logger() -> BotLogger:
    """Get or create the global logger instance"""
    global _logger
    if _logger is None:
        _logger = BotLogger()
    return _logger
