#!/usr/bin/env python3
"""Register the alloy-design tool and a model preset in a running Open WebUI.

  python openwebui/install.py [--webui-url http://127.0.0.1:3000] [--api-key KEY | --email E --password P]

Needs the local model server to be running (python llm/serve.py start). Creates or updates:
  1. an OpenAI connection to the local llama-server (added only if missing)
  2. the tool `al_alloy_design` (this project's path is written into the tool code)
  3. the model preset "Al Alloy Design" with native function calling and the tool enabled
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
TOOL_ID = "al_alloy_design"
MODEL_ID = "al-alloy-design"
DESCRIPTION = "Inverse design of aluminium alloys with a local model: measured examples, candidate search, scoring, corrosion evidence."


class WebUI:
    def __init__(self, base: str, token: str | None) -> None:
        self.base = base.rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def call(self, method: str, path: str, body: object = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data, self.headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read() or "null")
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{method} {path} -> HTTP {error.code}: {error.read().decode()[:400]}") from error

    def exists(self, path: str) -> bool:
        try:
            urllib.request.urlopen(urllib.request.Request(self.base + path, headers=self.headers), timeout=30)
            return True
        except urllib.error.HTTPError:
            return False


def sign_in(base: str, email: str, password: str) -> str:
    result = WebUI(base, None).call("POST", "/api/v1/auths/signin", {"email": email, "password": password})
    return result["token"]


def dotenv() -> dict[str, str]:
    path = PROJECT_DIR / ".env"
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else ()
    return {k.strip(): v.strip() for k, v in pairs}


def ensure_connection(ui: WebUI, llm_url: str) -> None:
    config = ui.call("GET", "/openai/config")
    urls = list(config["OPENAI_API_BASE_URLS"])
    if llm_url in urls:
        print(f"connection exists: {llm_url}")
        return
    config["OPENAI_API_BASE_URLS"] = [*urls, llm_url]
    config["OPENAI_API_KEYS"] = [*config["OPENAI_API_KEYS"], "none"]
    config["OPENAI_API_CONFIGS"] = {**config.get("OPENAI_API_CONFIGS", {}), str(len(urls)): {"enable": True}}
    config["ENABLE_OPENAI_API"] = True
    ui.call("POST", "/openai/config/update", config)
    print(f"connection added: {llm_url}")


def upsert_tool(ui: WebUI) -> None:
    source = (PROJECT_DIR / "openwebui" / "al_alloy_design_tool.py").read_text()
    form = {
        "id": TOOL_ID,
        "name": "Al Alloy Design",
        "content": source.replace("__PROJECT_DIR__", str(PROJECT_DIR)),
        "meta": {"description": DESCRIPTION},
    }
    if ui.exists(f"/api/v1/tools/id/{TOOL_ID}"):
        ui.call("POST", f"/api/v1/tools/id/{TOOL_ID}/update", form)
        print(f"tool updated: {TOOL_ID}")
    else:
        ui.call("POST", "/api/v1/tools/create", form)
        print(f"tool created: {TOOL_ID}")


def base_model_id(ui: WebUI, alias: str) -> str:
    models = ui.call("GET", "/api/models")["data"]
    ids = [m["id"] for m in models]
    matches = [i for i in ids if i == alias or i.endswith(f".{alias}")]
    if not matches:
        raise SystemExit(f"Open WebUI does not list a model named '{alias}'. Is the model server running and the connection enabled?")
    return matches[0]


def upsert_model(ui: WebUI, base_id: str) -> None:
    form = {
        "id": MODEL_ID,
        "base_model_id": base_id,
        "name": "Al Alloy Design",
        "meta": {"description": DESCRIPTION, "toolIds": [TOOL_ID], "capabilities": {"citations": False}},
        "params": {"function_calling": "native"},
        "is_active": True,
    }
    if ui.exists(f"/api/v1/models/model?id={MODEL_ID}"):
        ui.call("POST", "/api/v1/models/model/update", form)
        print(f"model preset updated: {MODEL_ID}")
    else:
        ui.call("POST", "/api/v1/models/create", form)
        print(f"model preset created: {MODEL_ID}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--webui-url", default="http://127.0.0.1:3000")
    ap.add_argument("--api-key", default=os.environ.get("OPENWEBUI_API_KEY"))
    ap.add_argument("--email")
    ap.add_argument("--password")
    args = ap.parse_args()

    settings = dotenv()
    llm_url = settings.get("LLM_BASE_URL") or raise_missing()
    token = args.api_key or (sign_in(args.webui_url, args.email, args.password) if args.email and args.password else None)
    ui = WebUI(args.webui_url, token)
    ensure_connection(ui, f"{llm_url}/v1")
    upsert_tool(ui)
    upsert_model(ui, base_model_id(ui, settings.get("LLM_MODEL", "local")))
    print(f"done: open {args.webui_url} and choose the model 'Al Alloy Design'")


def raise_missing() -> str:
    raise SystemExit("no LLM_BASE_URL in .env: run `python llm/serve.py start` first")


if __name__ == "__main__":
    main()
