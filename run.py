#!/usr/bin/env python
"""Start the SyberLabs demonstration platform.

Brings up the Relay Node 24 sidecar and the orchestration backend, waits for
both to answer, and prints where to look. Ctrl-C stops both.

  python run.py                 # start everything
  python run.py --check         # verify prerequisites and exit
  python run.py --no-relay      # skip the sidecar (Relay shows as unavailable)
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Windows consoles default to cp1252; keep output legible regardless.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PY.exists():
    VENV_PY = ROOT / ".venv" / "bin" / "python"
BACKEND = ROOT / "platform" / "backend"
SIDECAR = ROOT / "platform" / "relay-sidecar" / "server.mjs"
RELAY_ROOT = ROOT / "systems" / "relay"

BACKEND_PORT = int(os.environ.get("SYBER_DEMO_PORT", "8765"))
SIDECAR_PORT = int(os.environ.get("RELAY_SIDECAR_PORT", "8766"))


def find_node24() -> str | None:
    """Relay needs Node >= 24 for native TypeScript type stripping."""
    bundled = list((ROOT / ".tooling").glob("node-v2[4-9]*/node.exe")) + \
        list((ROOT / ".tooling").glob("node-v2[4-9]*/bin/node"))
    if bundled:
        return str(bundled[0])
    which = shutil.which("node")
    if which:
        try:
            version = subprocess.run([which, "--version"], capture_output=True, text=True, timeout=20).stdout
            if int(version.strip().lstrip("v").split(".")[0]) >= 24:
                return which
        except Exception:
            pass
    return None


def wait_for(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def check() -> int:
    ok = True
    print(f"python          {VENV_PY if VENV_PY.exists() else 'MISSING (.venv not created)'}")
    ok &= VENV_PY.exists()
    for mod in ("syberruntime", "bough", "osahr", "barn", "fastapi"):
        r = subprocess.run([str(VENV_PY), "-c", f"import {mod}"], capture_output=True)
        print(f"  import {mod:<14} {'ok' if r.returncode == 0 else 'MISSING'}")
        ok &= r.returncode == 0
    node = find_node24()
    print(f"node >= 24      {node or 'MISSING (Relay will be unavailable)'}")
    for name, path in [("relay", RELAY_ROOT), ("syber_runtime", ROOT / "systems" / "syber_runtime"),
                       ("bough_and_barn", ROOT / "systems" / "bough_and_barn"), ("osahr", ROOT / "systems" / "osahr")]:
        print(f"  checkout {name:<14} {'ok' if path.is_dir() else 'MISSING'}")
        ok &= path.is_dir()
    print(f"GOOGLE_API_KEY  {'set (live inference available)' if os.environ.get('GOOGLE_API_KEY') else 'not set (live inference disabled)'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-relay", action="store_true")
    args = ap.parse_args()

    if args.check:
        return check()

    if not VENV_PY.exists():
        print("No .venv found. See README.md for setup.", file=sys.stderr)
        return 2

    procs: list[subprocess.Popen] = []

    if not args.no_relay:
        node = find_node24()
        if node is None:
            print("! Node >= 24 not found — Relay will report itself unavailable in the UI.")
        else:
            env = dict(os.environ, RELAY_ROOT=str(RELAY_ROOT).replace("\\", "/"),
                       RELAY_SIDECAR_PORT=str(SIDECAR_PORT))
            procs.append(subprocess.Popen([node, str(SIDECAR)], env=env))
            if wait_for(f"http://127.0.0.1:{SIDECAR_PORT}/health", 30):
                print(f"  relay sidecar   http://127.0.0.1:{SIDECAR_PORT}  (node {node})")
            else:
                print("! relay sidecar did not become healthy")

    env = dict(os.environ, PYTHONPATH=str(BACKEND))
    procs.append(subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(BACKEND_PORT), "--log-level", "warning"],
        cwd=str(BACKEND), env=env))

    if wait_for(f"http://127.0.0.1:{BACKEND_PORT}/api/systems", 60):
        print(f"\n  SyberLabs instrument panel → http://127.0.0.1:{BACKEND_PORT}/")
        print(f"  Barn's own API (unmodified) → http://127.0.0.1:{BACKEND_PORT}/systems/barn/docs")
        print("\n  Ctrl-C to stop.\n")
    else:
        print("! backend did not start", file=sys.stderr)

    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    raise KeyboardInterrupt
            time.sleep(0.6)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            try:
                p.send_signal(signal.SIGTERM)
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=8)
            except Exception:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
