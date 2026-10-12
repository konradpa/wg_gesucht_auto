"""Persistent per-platform daily send-attempt limits, in Europe/Berlin time."""

from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import yaml


DEFAULT_LIMIT = 5
STATE_PATH = Path(__file__).resolve().parent.parent / "daily_message_counts.json"


class DailyMessageLimitReached(RuntimeError):
    pass


class DailyMessageLimit:
    def __init__(self, platform, limit=DEFAULT_LIMIT, path=STATE_PATH, clock=None):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("max_messages_per_day must be an integer >= 0 (0 disables sending)")
        self.platform = platform
        self.limit = limit
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(ZoneInfo("Europe/Berlin")))

    @classmethod
    def from_yaml(cls, path, platform):
        config = yaml.safe_load(Path(path).read_text()) or {}
        block = config.get("immoscout", {}) if platform == "immoscout" else config
        limit = block.get("settings", {}).get("max_messages_per_day", DEFAULT_LIMIT)
        return cls(platform, limit)

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if self.path.exists():
                    try:
                        state = json.loads(self.path.read_text())
                    except (ValueError, OSError):
                        raise ValueError("Cannot read daily message counter; sending stopped") from None
                    if not isinstance(state, dict) or any(
                        not isinstance(counts, dict) or any(
                            isinstance(v, bool) or not isinstance(v, int) or v < 0
                            for v in counts.values()) for counts in state.values()
                    ):
                        raise ValueError("Invalid daily message counter; sending stopped")
                else:
                    state = {}
                yield state
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _day(self):
        return self.clock().astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()

    def remaining(self):
        with self._locked() as state:
            return max(0, self.limit - state.get(self._day(), {}).get(self.platform, 0))

    def reserve(self):
        """Consume before POST, retaining the slot on rejection or unknown delivery."""
        with self._locked() as state:
            day = self._day()
            counts = state.setdefault(day, {})
            used = counts.get(self.platform, 0)
            if used >= self.limit:
                raise DailyMessageLimitReached(f"Daily limit reached: {self.limit} send attempts for {self.platform}")
            counts[self.platform] = used + 1
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as output:
                    temporary = Path(output.name)
                    json.dump(state, output, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
