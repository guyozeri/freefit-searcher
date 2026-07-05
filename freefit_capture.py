"""
mitmproxy addon to capture and pretty-print FreeFit API traffic.

Usage:
    mitmweb -s freefit_capture.py

Then browse the decrypted requests at http://127.0.0.1:8081
Captured FreeFit calls are also printed to the terminal and appended
to freefit_calls.log as JSON lines you can paste back to Claude.

Once you see the app's real domain in the output, tighten HOST_FILTER
to just that domain to cut out third-party noise (analytics, crash
reporting, etc.).
"""

import json
from mitmproxy import http

# Substrings matched against the request host. Start broad, then narrow
# to the real FreeFit API host once you spot it (e.g. "api.freefit.com").
HOST_FILTER = ("freefit",)

# Hosts to always ignore (common analytics / crash / ad SDKs).
NOISE = (
    "google", "facebook", "crashlytics", "sentry", "segment",
    "amplitude", "mixpanel", "appsflyer", "branch.io", "doubleclick",
    "gstatic", "firebase", "bugsnag", "datadoghq",
)

LOG_FILE = "freefit_calls.log"

# Header names worth highlighting for auth reverse-engineering.
INTERESTING_HEADERS = (
    "authorization", "cookie", "x-auth-token", "x-api-key",
    "x-access-token", "token", "x-session", "x-csrf-token",
)


def _matches(host: str) -> bool:
    host = host.lower()
    if any(n in host for n in NOISE):
        return False
    return any(f in host for f in HOST_FILTER)


def _truncate(body: bytes, limit: int = 4000) -> str:
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return f"<{len(body)} bytes binary>"
    if len(text) > limit:
        return text[:limit] + f"\n... [truncated, {len(text)} chars total]"
    return text


def response(flow: http.HTTPFlow) -> None:
    if not _matches(flow.request.pretty_host):
        return

    req = flow.request
    resp = flow.response

    auth_headers = {
        k: v for k, v in req.headers.items()
        if k.lower() in INTERESTING_HEADERS
    }

    print("\n" + "=" * 70)
    print(f"{req.method} {req.pretty_url}")
    print(f"-> {resp.status_code if resp else '(no response)'}")
    if auth_headers:
        print("AUTH HEADERS:")
        for k, v in auth_headers.items():
            print(f"  {k}: {v}")
    if req.content:
        print("REQUEST BODY:")
        print("  " + _truncate(req.content).replace("\n", "\n  "))
    if resp and resp.content:
        print("RESPONSE BODY:")
        print("  " + _truncate(resp.content).replace("\n", "\n  "))
    print("=" * 70)

    record = {
        "method": req.method,
        "url": req.pretty_url,
        "status": resp.status_code if resp else None,
        "request_headers": dict(req.headers),
        "request_body": _truncate(req.content) if req.content else None,
        "response_body": _truncate(resp.content) if (resp and resp.content) else None,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
