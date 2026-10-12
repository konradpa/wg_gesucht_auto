"""Invoke the Go-only token helper without logging or persisting its token."""

import json
from pathlib import Path
import subprocess


class WafRefreshError(RuntimeError):
    pass


class GoWafTokenProvider:
    def __init__(self, executable=None):
        self.executable = Path(executable) if executable else (
            Path(__file__).resolve().parent.parent / "bin" / "immoscout-waf"
        )

    def __call__(self, search_url, bootstrap_html=None):
        if not self.executable.is_file():
            raise WafRefreshError(
                "Go token helper not built. Run: "
                "cd tools/immoscout_waf && go build -o ../../bin/immoscout-waf ."
            )
        try:
            command = [str(self.executable.resolve()), "-url", search_url]
            if bootstrap_html:
                command.append("-bootstrap-stdin")
            result = subprocess.run(
                command, input=bootstrap_html,
                capture_output=True, text=True, timeout=100, check=False,
            )
        except subprocess.TimeoutExpired:
            raise WafRefreshError("Go token renewal timed out") from None
        except OSError:
            raise WafRefreshError("Cannot execute Go token helper") from None
        if result.returncode:
            # Child output can contain credentials; never echo it into logs.
            raise WafRefreshError(f"Go token renewal failed (exit {result.returncode})")
        try:
            data = json.loads(result.stdout)
            token, user_agent = data["token"], data["user_agent"]
        except (ValueError, KeyError, TypeError):
            raise WafRefreshError("Go token helper returned invalid JSON") from None
        if not all(isinstance(value, str) and value and not any(c in value for c in "\r\n")
                   for value in (token, user_agent)):
            raise WafRefreshError("Go token helper returned an invalid token or User-Agent")
        return {"token": token, "user_agent": user_agent}
