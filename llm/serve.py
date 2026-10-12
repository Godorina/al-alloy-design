#!/usr/bin/env python3
"""Run the selected model with llama-server and point the project at it.

  python llm/serve.py start [--slots 2] [--ctx-per-slot 32768] [--port 8080]
  python llm/serve.py status
  python llm/serve.py stop
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request

from common import MIN_CONTEXT, PORT, ROOT, SELECTION, SERVER_LOG, SERVER_PID, STATE, die, require, write_env

MODEL_ALIAS = "local"


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def running_pid() -> int | None:
    if not SERVER_PID.exists():
        return None
    pid = int(SERVER_PID.read_text())
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def start(args: argparse.Namespace) -> None:
    if running_pid() is not None:
        die(f"already running (pid {running_pid()}); `python llm/serve.py stop` first")
    if not SELECTION.exists():
        die("no model selected yet: run `python llm/pick.py` first")
    gguf = ROOT / json.loads(SELECTION.read_text())["gguf"]
    if not gguf.exists():
        die(f"{gguf} is missing; rerun `python llm/pick.py`")
    binary = require("llama-server", "Install llama.cpp: `brew install llama.cpp` (macOS) or see https://github.com/ggml-org/llama.cpp")
    ctx = max(args.ctx_per_slot, MIN_CONTEXT) * args.slots
    STATE.mkdir(exist_ok=True)
    command = [
        binary, "-m", str(gguf), "--alias", MODEL_ALIAS, "-c", str(ctx), "-np", str(args.slots),
        "-ngl", "999", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--jinja", "--reasoning", "off", "--cache-prompt",
        "--host", "127.0.0.1", "--port", str(args.port), "--no-webui",
    ]
    with SERVER_LOG.open("w") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
    SERVER_PID.write_text(str(proc.pid))
    print(f"starting llama-server (pid {proc.pid}), log: {SERVER_LOG.relative_to(ROOT)}")
    deadline = time.monotonic() + args.wait
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            SERVER_PID.unlink(missing_ok=True)
            die(f"llama-server exited with {proc.returncode}; see {SERVER_LOG}")
        if healthy(args.port):
            write_env({"LLM_BASE_URL": f"http://127.0.0.1:{args.port}", "LLM_MODEL": MODEL_ALIAS, "LLM_SLOTS": str(args.slots),
                       "LLM_CTX_PER_SLOT": str(ctx // args.slots)})
            print(f"ready on http://127.0.0.1:{args.port}; wrote LLM_* settings to .env")
            return
        time.sleep(1)
    die(f"not healthy after {args.wait}s; see {SERVER_LOG}")


def stop() -> None:
    pid = running_pid()
    if pid is None:
        print("not running")
    else:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        print(f"stopped pid {pid}")
    SERVER_PID.unlink(missing_ok=True)


def status() -> None:
    pid = running_pid()
    print(f"pid {pid}, healthy: {healthy(PORT)}" if pid else "not running")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["start", "stop", "status"])
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--ctx-per-slot", type=int, default=MIN_CONTEXT)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--wait", type=int, default=300)
    args = ap.parse_args()
    {"start": lambda: start(args), "stop": stop, "status": status}[args.action]()


if __name__ == "__main__":
    main()
