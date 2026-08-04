"""M0 feasibility smoke — OpenAI Responses API (throwaway; not production).

Validates, using YOUR key from .env (never printed):
  1. auth + which models the account actually exposes (GET /v1/models);
  2. a Responses call with the CONFIGURED model (DEC-OQ-04 gpt-5.6-terra),
     `store:false` + Structured Outputs + the hosted `web_search` tool — the exact
     combo M0 needs (DEC-OQ-07);
  3. if the configured model or the combined call fails, isolates which piece works
     against a detected real model.

Usage:  PYTHONPATH=src python3 scripts/openai_smoke.py
Cost: a few cents (tiny max_output_tokens). Makes at most ~4 small calls.
Stdlib only (urllib). No key value is ever printed or written.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "src")
from elly.dotenv import load_dotenv  # noqa: E402

API = "https://api.openai.com/v1"
CONFIGURED_MODEL = os.environ.get("ELLY_OPENAI_SPECIALIST_MODEL", "gpt-5.6-terra")
TIMEOUT = 40


def _redact(text: str, key: str) -> str:
    return text.replace(key, "***REDACTED***") if key else text


def _call(method: str, path: str, key: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
            return {"ok": True, "status": resp.status, "ms": int((time.monotonic() - t0) * 1000), "json": payload}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            err = json.loads(raw).get("error", {})
        except json.JSONDecodeError:
            err = {"message": raw[:300]}
        return {"ok": False, "status": exc.code, "ms": int((time.monotonic() - t0) * 1000),
                "error_type": err.get("type") or err.get("code"), "error_msg": (err.get("message") or "")[:300]}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status": None, "ms": int((time.monotonic() - t0) * 1000),
                "error_type": "network", "error_msg": str(exc)[:300]}


def _responses_body(model: str, *, web_search: bool, structured: bool) -> dict:
    body: dict = {"model": model, "input": "Reply with the single word: pong.",
                  "store": False, "max_output_tokens": 64}
    if web_search:
        body["input"] = "In one short sentence, what is today's date according to the web?"
        body["tools"] = [{"type": "web_search"}]
    if structured:
        body["text"] = {"format": {"type": "json_schema", "name": "smoke",
                                    "schema": {"type": "object", "properties": {"answer": {"type": "string"}},
                                               "required": ["answer"], "additionalProperties": False},
                                    "strict": True}}
    return body


def main() -> int:
    load_dotenv()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("FAIL: OPENAI_API_KEY not set (put it in .env).")
        return 2
    print(f"key: present (len={len(key)}, value hidden)")
    print(f"configured model (DEC-OQ-04): {CONFIGURED_MODEL}\n")

    findings: list[str] = []

    # 1) auth + model inventory
    r = _call("GET", "/models", key)
    if not r["ok"]:
        print(f"[1] GET /models -> FAIL status={r['status']} type={r.get('error_type')} "
              f"msg={_redact(r.get('error_msg',''), key)}")
        if r["status"] == 401:
            findings.append("AUTH FAILED (401) — key invalid/rotated-but-not-updated.")
        elif r.get("error_type") == "network":
            findings.append("NETWORK BLOCKED — could not reach api.openai.com from this environment; run the script yourself.")
        print("\nSUMMARY:\n- " + "\n- ".join(findings))
        return 1
    ids = sorted(m.get("id", "") for m in r["json"].get("data", []))
    print(f"[1] GET /models -> OK ({r['ms']} ms): {len(ids)} models")
    configured_present = CONFIGURED_MODEL in ids
    gpt56 = [m for m in ids if "gpt-5.6" in m]
    print(f"    configured '{CONFIGURED_MODEL}' present: {configured_present}")
    print(f"    gpt-5.6* ids present: {gpt56 or 'NONE'}")
    sample = [m for m in ids if m.startswith(("gpt-", "o1", "o3", "o4"))][:12]
    print(f"    sample chat/reasoning ids: {sample}")
    findings.append(f"Auth OK. Configured '{CONFIGURED_MODEL}' present={configured_present}. gpt-5.6*={gpt56 or 'none'}.")

    # pick a target for the mechanics test
    target = CONFIGURED_MODEL if configured_present else next(
        (m for m in ids if m.startswith(("gpt-4o", "gpt-4.1", "gpt-4", "gpt-"))), None)
    if target != CONFIGURED_MODEL:
        print(f"    -> configured model absent; using detected '{target}' for mechanics test")

    # 2) combined: store:false + structured + web_search
    if target:
        c = _call("POST", "/responses", key, _responses_body(target, web_search=True, structured=True))
        print(f"\n[2] POST /responses (model={target}, store:false + web_search + structured) -> "
              f"{'OK' if c['ok'] else 'FAIL'} status={c['status']} {c['ms']}ms")
        if c["ok"]:
            usage = c["json"].get("usage", {})
            findings.append(f"COMBINED store:false+web_search+structured OK on '{target}' (usage={usage}).")
        else:
            print(f"    type={c.get('error_type')} msg={_redact(c.get('error_msg',''), key)}")
            findings.append(f"COMBINED failed on '{target}': {c.get('error_type')} — {c.get('error_msg')}")
            # 3) isolate
            for label, ws, st in (("structured-only", False, True), ("web_search-only", True, False)):
                iso = _call("POST", "/responses", key, _responses_body(target, web_search=ws, structured=st))
                print(f"[3] isolate {label} -> {'OK' if iso['ok'] else 'FAIL'} status={iso['status']} "
                      f"type={iso.get('error_type')} msg={_redact(iso.get('error_msg',''), key)}")
                findings.append(f"{label}: {'OK' if iso['ok'] else 'FAIL — ' + str(iso.get('error_type'))}")

    print("\n================ SUMMARY (copy to docs) ================")
    for f in findings:
        print("- " + f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
