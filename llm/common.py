from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".llm"
MODELS = ROOT / "models"
ENV_FILE = ROOT / ".env"
SELECTION = STATE / "selection.json"
SERVER_PID = STATE / "server.pid"
SERVER_LOG = STATE / "server.log"

MIN_CONTEXT = 49152
PORT = 8080


def die(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def require(binary: str, hint: str) -> str:
    path = shutil.which(binary)
    if path is None:
        die(f"`{binary}` not found. {hint}")
    return path


def run_json(cmd: list[str]) -> dict:
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        die(f"{' '.join(cmd)} failed:\n{done.stderr.strip() or done.stdout.strip()}")
    return json.loads(done.stdout)


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    pairs = (line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def write_env(updates: dict[str, str]) -> None:
    env = read_env() | updates
    ENV_FILE.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
