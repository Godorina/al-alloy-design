#!/usr/bin/env python3
"""Check that the running model is good enough for alloy design.

  python llm/selfcheck.py [--queries 12] [--agent]

1. tool calling: the model must answer a function-call request with a tool call.
2. ICL strength prediction: 6xxx UTS of measured alloys the context does not contain
   (icl/validate.py). FAIL when too many answers are not the exact JSON the pipeline needs,
   WARN when the model predicts worse than the nearest-neighbour baseline.
3. --agent (several minutes): a full design run through the agent loop; FAIL unless it runs a successful
   `score.py --final` and then returns a final answer.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

from common import ROOT, STATE, die, read_env

VALIDATE = ROOT / "src" / "skills" / "alloy-strength" / "icl" / "validate.py"
HOST = ROOT / "src" / "mcp" / "host" / "mcp_host.py"
SESSIONS = ROOT / "runs" / "sessions"
AGENT_TASK = (
    "6xxx T6 extrusion alloy, UTS at least 330 MPa, elongation at least 10 %, corrosion resistant. "
    "Read the alloy-properties skill first and follow it. Run score.py --final on the rounded candidates."
)
AGENT_SECONDS = 3600
MAX_FAILED_FRACTION = 0.2

TOOL_REQUEST = {
    "messages": [{"role": "user", "content": "What is the density of a 6xxx series aluminium alloy? Use the tool."}],
    "tools": [{
        "type": "function",
        "function": {
            "name": "lookup_density",
            "description": "Look up the density of an alloy series in g/cm3.",
            "parameters": {"type": "object", "properties": {"series": {"type": "string"}}, "required": ["series"]},
        },
    }],
    "tool_choice": "auto",
    "temperature": 0,
    "max_tokens": 256,
}


def tool_call_ok(base: str, model: str) -> bool:
    req = urllib.request.Request(
        f"{base}/v1/chat/completions", json.dumps({"model": model, **TOOL_REQUEST}).encode(),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        message = json.loads(r.read())["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    return bool(calls) and calls[0]["function"]["name"] == "lookup_density"


def validate(step: list[str], env: dict[str, str]) -> None:
    done = subprocess.run([sys.executable, str(VALIDATE), *step], cwd=ROOT, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        die(f"validate.py {step[0]} failed:\n{done.stderr[-1500:]}")


def agent_ok(env: dict[str, str]) -> bool:
    before = set(SESSIONS.glob("*.jsonl"))
    command = [sys.executable, str(HOST), "--server", "kg", "--max-steps", "24", "--quiet", AGENT_TASK]
    try:
        subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=AGENT_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    fresh = sorted(set(SESSIONS.glob("*.jsonl")) - before)
    if not fresh:
        return False
    return session_succeeded([json.loads(line) for line in fresh[-1].read_text().splitlines()])


def session_succeeded(events: list[dict]) -> bool:
    final_at = next(
        (i for i, e in enumerate(events)
         if e["kind"] == "tool" and e.get("name") == "run_skill_script"
         and "score.py" in e["arguments"] and "--final" in e["arguments"] and '"exit_code": 0' in e["result"]),
        None,
    )
    return final_at is not None and any(e["kind"] == "answer" and e.get("content") for e in events[final_at:])


def icl_report(base: str, env: dict[str, str], queries: int) -> dict:
    out = STATE / "selfcheck"
    shutil.rmtree(out, ignore_errors=True)
    common = ["--tag", "check", "--out-dir", str(out)]
    validate(["plan", *common, "--limit", str(queries), "--draws", "1", "--conditions", "B", "--hint", "catboost"], env)
    validate(["run", *common, "--url", base, "--force"], env)
    validate(["report", *common], env)
    return json.loads((out / "check" / "report.json").read_text())["conditions"]["B"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", type=int, default=12)
    ap.add_argument("--agent", action="store_true", help="also run a full design through the agent loop")
    args = ap.parse_args()

    settings = read_env()
    base = settings.get("LLM_BASE_URL") or die("no LLM_BASE_URL in .env: run `python llm/serve.py start` first")
    model = settings.get("LLM_MODEL", "local")
    env = {**os.environ, **settings}
    STATE.mkdir(exist_ok=True)

    started = time.monotonic()
    tools_ok = tool_call_ok(base, model)
    print(f"tool calling: {'ok' if tools_ok else 'FAILED'}")
    report = icl_report(base, env, args.queries)
    planned, failed = report["planned"], report["failed"]
    answered = report.get("complete_queries", planned - failed)
    if not answered:
        verdict, reason = "FAIL", "no complete answers"
        mae = knn = None
    else:
        mae = report["llm_mean_of_draws"]["MAE"]
        knn = report["knn"]["MAE"]
        if failed / planned > MAX_FAILED_FRACTION:
            verdict, reason = "FAIL", f"{failed}/{planned} answers were not the required JSON"
        elif mae > knn:
            verdict, reason = "WARN", f"UTS MAE {mae} MPa is worse than the nearest-neighbour baseline {knn} MPa"
        else:
            verdict, reason = "PASS", f"UTS MAE {mae} MPa vs nearest-neighbour {knn} MPa"
    if not tools_ok:
        verdict, reason = "FAIL", f"no tool call returned; {reason}"
    if args.agent:
        agent = agent_ok(env)
        print(f"agent loop: {'ok' if agent else 'FAILED'}")
        if not agent:
            verdict, reason = "FAIL", f"the design run did not reach a successful score.py --final; {reason}"
    result = {"verdict": verdict, "reason": reason, "tool_calling": tools_ok, "uts_mae": mae, "knn_mae": knn,
              "planned": planned, "failed": failed, "seconds": round(time.monotonic() - started)}
    (STATE / "selfcheck.json").write_text(json.dumps(result, indent=1))
    print(f"{verdict}: {reason} ({result['seconds']}s). Reference: Qwen3.8-27B reached about 23 MPa on 6xxx UTS.")
    raise SystemExit(1 if verdict == "FAIL" else 0)


if __name__ == "__main__":
    main()
