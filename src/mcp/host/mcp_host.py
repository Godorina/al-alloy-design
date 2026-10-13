#!/usr/bin/env python3
"""mcp_host.py -- connect local Qwen (llama-server) to MCP tool servers.

Usage:
  .venv/bin/python src/mcp/host/mcp_host.py                      # chat, default servers
  .venv/bin/python src/mcp/host/mcp_host.py "find recent papers on 6xxx IGC"
  .venv/bin/python src/mcp/host/mcp_host.py --server papers --server docs
  .venv/bin/python src/mcp/host/mcp_host.py --server all        # every servers/*/

--server takes a name under src/mcp/servers/ (e.g. papers), a .py path, or "all".

Loop: collect tools from every server -> expose to Qwen via OpenAI tools API ->
route each tool_call to the server that owns it -> feed results back ->
repeat until final answer.

Skills: src/skills/<name>/SKILL.md. Only name + description go into the system
prompt; the model calls the built-in use_skill(name) to load the full body.
Skill code lives in src/skills/<name>/<scripts_dir>/*.py (frontmatter `scripts_dir`,
default scripts) and runs through the built-in run_skill_script (no shell; only those
files). Other folders of a skill (e.g. validation experiments) are never runnable. Every session is logged to
runs/sessions/<start>-<pid>.jsonl for evaluation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
from contextlib import AsyncExitStack
from datetime import date, datetime
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[3]  # icl_design/
SERVERS = ROOT / "src" / "mcp" / "servers"
SKILLS_DIR = ROOT / "src" / "skills"  # <name>/SKILL.md with name/description frontmatter
DEFAULT_SERVERS = ["kg"]
LLM = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080") + "/v1/chat/completions"  # any OpenAI-compatible server
LLM_MODEL = os.environ.get("LLM_MODEL", "local")
MAX_STEPS = 12
MAX_TOKENS = 8192  # per reply; a 5-sample extraction record plus thinking overran 4096 (slot ctx 49152)
SCRIPT_TIMEOUT = 300       # seconds per skill script run
SCRIPT_OUT_CHARS = 20000   # max stdout returned to (and logged for) the model
SCRIPT_SLOTS = asyncio.Semaphore(1)  # one script at a time: they share CPUs with llama-server
SESSIONS = ROOT / "runs" / "sessions"


def _server_path(s: str) -> Path:
    if not s.endswith(".py"):
        return SERVERS / s / "server.py"
    p = Path(s)
    return p if p.is_absolute() else ROOT / p


def load_skills() -> dict[str, dict]:
    """name -> {description, body} from src/skills/*/SKILL.md."""
    skills = {}
    for f in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = f.read_text(encoding="utf-8")
        meta, body = {}, text
        if text.startswith("---"):
            head, _, body = text[3:].partition("\n---")
            for line in head.strip().splitlines():
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        name = f.parent.name  # directory name is the id used to build script paths
        run_dir = meta.get("scripts_dir", "scripts")
        if not run_dir.isidentifier():  # plain folder name only: no "..", "/" or absolute paths
            run_dir = "scripts"
        skills[name] = {"description": meta.get("description", ""), "body": body.strip(),
                        "scripts_dir": run_dir}
    return skills


def system_prompt(skills: dict) -> str:
    p = (f"Today's date: {date.today():%Y-%m-%d}\n"
         "Answer the user in Korean unless they ask otherwise.\n")
    if skills:
        p += ("\nAvailable skills. If the request matches a description below, call "
              "use_skill(name) BEFORE any other tool and follow its instructions exactly:\n"
              + "\n".join(f"- {n}: {v['description']}" for n, v in skills.items()))
    return p


def skill_tool(skills: dict) -> dict:
    return {"type": "function", "function": {
        "name": "use_skill",
        "description": "Load the full instructions of a skill listed in the system prompt.",
        "parameters": {"type": "object", "required": ["name"], "properties": {
            "name": {"type": "string", "enum": sorted(skills)}}}}}


def script_dir(skills: dict, name: str) -> Path:
    return SKILLS_DIR / name / skills[name].get("scripts_dir", "scripts")


def skills_with_scripts(skills: dict) -> list[str]:
    return sorted(n for n in skills if any(script_dir(skills, n).glob("*.py")))


def script_tool(names: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": "run_skill_script",
        "description": ("Run a Python script of a skill exactly as that "
                        "skill's SKILL.md documents it. No shell: args are passed as a list. "
                        "Returns JSON {exit_code, result (the script's JSON output), stderr}."),
        "parameters": {"type": "object", "required": ["skill", "script"], "properties": {
            "skill": {"type": "string", "enum": names},
            "script": {"type": "string", "description": "file name, e.g. predict.py"},
            "args": {"type": "array", "items": {"type": "string"},
                     "description": "command-line arguments, one list item per token"}}}}}


async def run_skill_script(skill: str, script: str, args: list | None = None) -> dict:
    """Run src/skills/<skill>/<scripts_dir>/<script> with the project venv, no shell.

    Only .py files that resolve inside that folder are allowed, so the
    model cannot reach arbitrary commands, paths outside the skill, or rm."""
    root = SKILLS_DIR.resolve()
    # skill must be a loaded skill directly under src/skills (no "../x" skill names)
    if skill not in SKILLS:
        return {"error": f"unknown skill: {skill}", "allowed": skills_with_scripts(SKILLS)}
    base = script_dir(SKILLS, skill).resolve()
    path = (base / script).resolve()
    if base.parent.parent != root:
        return {"error": f"unknown skill: {skill}", "allowed": skills_with_scripts(SKILLS)}
    if path.parent != base or path.suffix != ".py" or not path.is_file():
        return {"error": f"not an allowed script: {skill}/{base.name}/{script}",
                "allowed": sorted(p.name for p in base.glob("*.py")) if base.is_dir() else []}
    if args is None:
        args = []
    if not isinstance(args, list) or not all(isinstance(a, (str, int, float)) for a in args):
        return {"error": "args must be a list of strings"}
    async with SCRIPT_SLOTS:
        # own process group so a timeout/Ctrl-C also kills worker children (joblib etc.)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(path), *map(str, args), cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            start_new_session=sys.platform != "win32")
        try:
            out, err = await asyncio.wait_for(proc.communicate(), SCRIPT_TIMEOUT)
        except asyncio.TimeoutError:
            return {"error": f"timed out after {SCRIPT_TIMEOUT}s"}
        finally:
            if proc.returncode is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                else:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                await proc.wait()
    out, err = out.decode(errors="replace"), err.decode(errors="replace")
    res = {"exit_code": proc.returncode, "stderr": err[-2000:]}
    if len(out) > SCRIPT_OUT_CHARS:  # never hand the model a cut-off JSON document
        res["error"] = (f"output too large ({len(out)} chars > {SCRIPT_OUT_CHARS}); "
                        "narrow the request (fewer candidates, smaller --top-k)")
        return res
    try:  # scripts emit one JSON document: embed it as an object, not an escaped string
        res["result"] = json.loads(out)
    except json.JSONDecodeError:
        res["stdout"] = out
    return res


SKILLS: dict[str, dict] = {}
LOG = None  # session log file (JSONL), opened in main()


def log(kind: str, **kw) -> None:
    """Append one event to runs/sessions/<start>-<pid>.jsonl (evaluation evidence)."""
    if LOG is not None:
        LOG.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"),
                              "kind": kind, **kw}, ensure_ascii=False) + "\n")
        LOG.flush()


async def connect(stack: AsyncExitStack, servers: list[str]):
    """Start every server; return (tool name -> session, OpenAI tool specs)."""
    if "all" in servers:
        servers = sorted(p.parent.name for p in SERVERS.glob("*/server.py"))
    route, oai_tools = {}, []
    for s in servers:
        path = _server_path(s)
        if not path.is_file():
            sys.exit(f"MCP server not found: {path}")
        read, write = await stack.enter_async_context(stdio_client(
            StdioServerParameters(command=sys.executable, args=[str(path)])))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        for t in (await session.list_tools()).tools:
            if t.name in route:
                sys.exit(f"duplicate tool name '{t.name}' in {path}")
            route[t.name] = session
            oai_tools.append({"type": "function", "function": {
                "name": t.name, "description": t.description or "",
                "parameters": t.inputSchema}})
    return route, oai_tools


CTX = int(os.environ.get("LLM_CTX_PER_SLOT", "49152"))  # tokens per server slot


def near_full(prompt_n) -> bool:
    """The last prompt leaves too little room for a reply of MAX_TOKENS (plus the next tool results)."""
    return bool(prompt_n) and prompt_n + MAX_TOKENS + 6000 > CTX


TRIM_NOTE = "\n... [older tool result trimmed to fit the context; call the tool again if you need it]"


def trim_tool_results(messages: list) -> bool:
    """Shrink the oldest untrimmed tool result (never the newest one, never a skill's instructions: use_skill
    would be refused as a repeat); False when nothing is left to trim."""
    skills = {c["id"] for m in messages for c in m.get("tool_calls") or [] if c["function"].get("name") == "use_skill"}
    tools = [m for m in messages if m.get("role") == "tool" and m.get("tool_call_id") not in skills]
    for m in tools[:-1]:
        if not m["content"].endswith(TRIM_NOTE):
            m["content"] = m["content"][:300] + TRIM_NOTE
            return True
    return False


REPEAT_NOTE = ("You already made this exact call in this answer and got its result above. Do not repeat it: "
               "change the arguments, use another tool, or answer with what you have.")


def repeated(seen: set, c) -> bool:
    """True when this exact tool call (name and arguments, key order ignored) was already made in this answer."""
    f = c["function"]
    try:
        args = json.dumps(json.loads(f.get("arguments") or "{}"), sort_keys=True)
    except json.JSONDecodeError:
        args = f.get("arguments")
    key = (f.get("name"), args)
    if key in seen:
        return True
    seen.add(key)
    return False


def parseable(c) -> bool:
    """Tool-call arguments are JSON; a reply cut off at the slot's context is not, and llama-server refuses
    (HTTP 500) every later request whose history holds it."""
    try:
        json.loads(c["function"].get("arguments") or "{}")
        return True
    except json.JSONDecodeError:
        return False


async def _step_until_answer(http, route, messages, oai_tools, verbose):
    """Run tool-call rounds until the model returns a plain message. A cut-off tool call, or a repeat after
    REPEAT_NOTE was already given, ends the rounds early with a final answer, like the step budget."""
    seen: set = set()
    warned = False
    stop = "max steps"
    for _ in range(MAX_STEPS):
        while True:
            r = await http.post(LLM, json={
                "model": LLM_MODEL, "messages": messages,
                "tools": oai_tools, "tool_choice": "auto",
                "parallel_tool_calls": True,
                "temperature": 0.2, "max_tokens": MAX_TOKENS})
            # a long session outgrows the slot's context: drop old tool output (oldest first) and ask again
            if not (r.status_code == 400 and "exceeds the available context" in r.text and trim_tool_results(messages)):
                break
            log("trimmed")
        if r.status_code != 200:  # e.g. context overflow: keep the REPL alive
            err = r.json().get("error", {}).get("message", r.text[:300])
            return (f"[LLM error {r.status_code}] {err}\n"
                    "대화가 너무 길어졌을 수 있어요. /clear 후 다시 시도하세요.")
        body = r.json()
        msg = body["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        tm = body.get("timings", {})
        log("llm", prompt_n=tm.get("prompt_n"), predicted_n=tm.get("predicted_n"),
            predicted_ms=tm.get("predicted_ms"), tool_calls=len(calls))
        if not calls:
            return msg.get("content") or ""
        if not all(parseable(c) for c in calls):  # never keep it in the history
            stop = "reply cut off at the context limit"
            break
        again = [repeated(seen, c) for c in calls]
        if any(again) and warned:  # the note did not help: the model is looping on one refused call
            stop = "same call repeated"
            break
        warned = warned or any(again)
        if near_full((body.get("usage") or {}).get("prompt_tokens")):  # the whole prompt; prompt_n skips the cache  # make room before the reply is cut off mid-JSON
            while trim_tool_results(messages):
                pass
            log("trimmed", reason="near full")
        messages.append(msg)
        # independent calls from one turn run concurrently; results keep call order
        texts = await asyncio.gather(*(asyncio.sleep(0, REPEAT_NOTE) if rep else _call(route, c, verbose)
                                       for c, rep in zip(calls, again)))
        for c, text in zip(calls, texts):
            messages.append({"role": "tool",
                             "tool_call_id": c["id"], "content": text})
    # step budget spent, a cut-off call or a loop: force a final answer from what was gathered
    log("max_steps" if stop == "max steps" else "stopped", reason=stop)
    messages.append({"role": "user", "content":
        "도구 호출을 여기서 멈춥니다. 더 검색하지 말고 지금까지 얻은 결과만으로 "
        "답하세요. 요청을 완전히 충족하지 못한 부분은 무엇이 부족한지 밝히세요."})
    r = await http.post(LLM, json={
        "model": LLM_MODEL, "messages": messages, "tools": oai_tools,
        "tool_choice": "none", "temperature": 0.2, "max_tokens": MAX_TOKENS})
    if r.status_code != 200:
        return f"[stopped: {stop}; final answer failed: HTTP {r.status_code}]"
    return r.json()["choices"][0]["message"].get("content") or f"[stopped: {stop}]"


async def _call(route, c, verbose) -> str:
    text = await _dispatch(route, c, verbose)
    log("tool", name=c["function"].get("name"), arguments=c["function"].get("arguments"),
        result=text)
    return text


async def _dispatch(route, c, verbose) -> str:
    name = c["function"].get("name")
    if verbose:
        print(f"⚙ MCP 도구 사용: {name}({(c['function'].get('arguments') or '')[:200]})",
              file=sys.stderr)
    try:
        args = json.loads(c["function"]["arguments"] or "{}")
        if name == "use_skill":  # built-in, served by the host itself
            sk = SKILLS.get(args.get("name", ""))
            return sk["body"] if sk else json.dumps(
                {"error": f"unknown skill; available: {sorted(SKILLS)}"})
        if name == "run_skill_script":  # built-in, sandboxed to skill scripts
            res = await run_skill_script(args.get("skill", ""), args.get("script", ""),
                                         args.get("args"))
            return json.dumps(res, ensure_ascii=False)
        if name not in route:
            raise KeyError(f"unknown tool '{name}'")
        res = await route[name].call_tool(name, args)
        return "".join(b.text for b in res.content
                       if getattr(b, "type", "") == "text")
    except Exception as e:
        return json.dumps({"error": str(e)})


async def main(task: str | None, servers: list[str], verbose: bool = True):
    """One-shot when task is given, otherwise interactive REPL
    (conversation history persists across turns)."""
    async with AsyncExitStack() as stack:
        route, oai_tools = await connect(stack, servers)
        SKILLS.update(load_skills())
        if SKILLS:
            oai_tools.append(skill_tool(SKILLS))
        scripted = skills_with_scripts(SKILLS)
        if scripted:
            oai_tools.append(script_tool(scripted))
        global LOG
        SESSIONS.mkdir(parents=True, exist_ok=True)
        LOG = stack.enter_context(open(SESSIONS / f"{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.jsonl",
                                       "a", encoding="utf-8"))
        names = [t["function"]["name"] for t in oai_tools]
        system = {"role": "system", "content": system_prompt(SKILLS)}
        messages: list[dict] = [system]
        log("session", servers=servers, tools=names, skills=sorted(SKILLS),
            system=system["content"])
        # one reply may be MAX_TOKENS long; with both llama-server slots busy Qwen decodes ~8 tok/s, so 8192 tokens
        # take ~1000 s (a 5-sample corrosion record timed out at 600 s). Callers bound the whole run themselves.
        async with httpx.AsyncClient(timeout=1800.0) as http:
            if task is not None:
                if verbose:
                    print(f"tools: {names}", file=sys.stderr)
                messages.append({"role": "user", "content": task})
                log("user", content=task)
                answer = await _step_until_answer(http, route, messages, oai_tools, verbose)
                log("answer", content=answer)
                print(answer)
                return answer
            print(f"qwen chat — /quit to exit, /clear to reset "
                  f"(servers: {servers}, tools: {names}, skills: {sorted(SKILLS)})",
                  file=sys.stderr)
            while True:
                try:
                    user = input("\n> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not user:
                    continue
                if user in ("/quit", "/exit"):
                    break
                if user == "/clear":
                    messages[:] = [system]
                    log("clear")
                    print("[cleared]", file=sys.stderr)
                    continue
                messages.append({"role": "user", "content": user})
                log("user", content=user)
                answer = await _step_until_answer(
                    http, route, messages, oai_tools, verbose)
                log("answer", content=answer)
                messages.append({"role": "assistant", "content": answer})
                print(f"\n{answer}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task", nargs="?", default=None,
                    help="one-shot task; omit for interactive chat")
    ap.add_argument("--server", action="append",
                    help=f"server name under servers/, .py path, or 'all'; repeatable "
                         f"(default: {DEFAULT_SERVERS})")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS,
                    help=f"tool-call rounds per request (default {MAX_STEPS}; paper extraction needs ~24)")
    a = ap.parse_args()
    MAX_STEPS = a.max_steps
    answer = asyncio.run(main(a.task, a.server or DEFAULT_SERVERS, not a.quiet))
    sys.exit(1 if answer and answer.startswith(("[LLM error", "[stopped")) else 0)  # a queue sees the failure
