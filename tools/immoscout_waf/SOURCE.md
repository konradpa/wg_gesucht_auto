# Token helper source provenance

The `internal/aws` Go token library and embedded `webgl.json` are derived from:

- https://github.com/xKiian/awswaf at `0b7d9eb673daa50577453926576e0c9274f9dc75`
- https://github.com/xKiian/awswaf/pull/11 at `fa70827a44be8078385569f25e5d31ac61b40d77`

The MIT license is retained in `LICENSE.upstream`. The upstream CAPTCHA and
Gemini components, demonstration program, and Python implementation are not
included. The `mp_verify` patch is necessary for the challenge type observed
from ImmoScout on 2026-10-12.

Local adaptations:

- Embed the WebGL dataset so the binary runs from any working directory.
- Reject unknown bandwidth difficulty values instead of guessing a size.
- Validate verification response HTTP status and non-empty tokens.
- Add a helper entrypoint that discovers the SDK prefix from an ImmoScout
  search response (received over stdin from the Python client when available),
  acquires a token, and validates search JSON before returning
  it through a private JSON stdout protocol. It uses certificate validation,
  limits response sizes, rejects redirects, and has a 90-second deadline.

Build from this folder with Go 1.23.9 or later:

```bash
go build -o ../../bin/immoscout-waf .
```

Run through `probe_immoscout_web.py --refresh-waf` so the token response is
captured in memory instead of being displayed in the terminal.
