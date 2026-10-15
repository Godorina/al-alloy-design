#!/usr/bin/env python3
"""Pick a local model that fits this machine (llmfit), download it, and remember the choice.

  python llm/pick.py                 show the ranked list and ask which one to download
  python llm/pick.py --auto         download the top pick without asking
  python llm/pick.py --list-only    only show the list
  python llm/pick.py --quant Q4_K_M download a smaller quantization than llmfit proposes
  python llm/pick.py --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M   a model that is not in the llmfit list
  python llm/pick.py --gguf PATH    use a GGUF file already on this PC (see llm/existing.py) instead of downloading
  python llm/pick.py --gguf PATH --copy   copy it into models/ first (e.g. from /mnt/c on WSL, which loads slowly)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from common import MIN_CONTEXT, MODELS, ROOT, SELECTION, STATE, die, run_json
from existing import describe

OFFICIAL = ("Qwen/", "google/", "meta-llama/", "mistralai/", "microsoft/", "openai/", "ibm-granite/", "nvidia/")
EXCLUDE = re.compile(
    r"abliterat|heretic|uncensor|reasoning|distill|thinking|coder|vision|embed|guard|tts|mlx|nvfp4|bnb|awq|gptq|reap"
    r"|(?<![a-z0-9])(vl|r1)(?![a-z0-9])",
    re.I,
)
MIN_PARAMS_B = 3.0
SMALL_MODEL_B = 7.0


def ensure_llmfit() -> str:
    path = shutil.which("llmfit")
    if path:
        return path
    print("llmfit is not installed (https://github.com/AlexsJones/llmfit).")
    if shutil.which("brew"):
        install = ["brew", "install", "AlexsJones/llmfit/llmfit"]
    elif shutil.which("uv"):
        install = ["uv", "tool", "install", "-U", "llmfit"]
    else:
        die("install it with `brew install AlexsJones/llmfit/llmfit` or `uv tool install llmfit`, then rerun.")
    if input(f"Install it now with `{' '.join(install)}`? [Y/n] ").strip().lower() in ("n", "no"):
        die("llmfit is required to rank models for this machine.")
    subprocess.run(install, check=True)
    path = shutil.which("llmfit")
    return path or die("llmfit was installed but is not on PATH; open a new shell and rerun.")


def candidates(llmfit: str) -> list[dict]:
    data = run_json(
        [llmfit, "--max-context", str(MIN_CONTEXT), "recommend", "-n", "400", "--no-dashboard",
         "--force-runtime", "llamacpp", "--capability", "tool_use", "--min-fit", "good"]
    )
    usable = [
        m for m in data["models"]
        if m["gguf_sources"] and m["params_b"] >= MIN_PARAMS_B and not EXCLUDE.search(m["name"])
    ]
    return sorted(usable, key=lambda m: (not m["name"].startswith(OFFICIAL), -m["score"]))


def show(models: list[dict]) -> None:
    print(f"{'#':>2}  {'model':52} {'params':>7} {'quant':>7} {'size GB':>8} {'tok/s':>6}  fit")
    for i, m in enumerate(models, 1):
        warn = "  (small: weaker design quality)" if m["params_b"] < SMALL_MODEL_B else ""
        print(f"{i:>2}  {m['name'][:52]:52} {m['parameter_count']:>7} {m['best_quant']:>7} "
              f"{m['disk_size_gb']:>8.1f} {m['estimated_tps']:>6.0f}  {m['fit_level']}{warn}")


def download(m: dict, quant: str | None = None) -> None:
    repo = m["gguf_sources"][0]["repo"]
    quant = quant or m["best_quant"]
    MODELS.mkdir(exist_ok=True)
    before = set(MODELS.glob("*.gguf"))
    subprocess.run(
        [shutil.which("llmfit") or "llmfit", "download", repo, "--quant", quant,
         "--output-dir", str(MODELS), "--no-dashboard"],
        check=True,
    )
    fresh = sorted(set(MODELS.glob("*.gguf")) - before) or sorted(MODELS.glob("*.gguf"), key=lambda p: p.stat().st_mtime)
    if not fresh:
        die("download finished but no .gguf file was found in models/")
    STATE.mkdir(exist_ok=True)
    SELECTION.write_text(json.dumps(
        {"name": m["name"], "repo": repo, "quant": quant, "params_b": m["params_b"],
         "gguf": str(fresh[-1].relative_to(ROOT))}, indent=1))
    print(f"saved {fresh[-1].name}; next: python llm/serve.py start")


def use_local(path: str, name: str | None, copy: bool) -> None:
    """Register a GGUF file that is already on this PC; with --copy, copy it into models/ first."""
    src = Path(path).expanduser().resolve()
    item = describe(src, "local", name or src.name) if src.is_file() else None
    if item is None:
        die(f"{src} is not a readable GGUF file")
    gguf = src
    if copy:
        MODELS.mkdir(exist_ok=True)
        gguf = MODELS / (re.sub(r"[^A-Za-z0-9._-]+", "-", item["name"]).strip("-.").removesuffix(".gguf") + ".gguf")
        if not (gguf.exists() and gguf.stat().st_size == src.stat().st_size):
            if shutil.disk_usage(MODELS).free < src.stat().st_size + 2 * 2**30:
                die(f"not enough free disk space to copy {item['size_gb']} GB; rerun without --copy")
            print(f"copying {item['size_gb']} GB to {gguf.relative_to(ROOT)} (once; loading from here is faster)")
            shutil.copyfile(src, gguf)
    STATE.mkdir(exist_ok=True)
    SELECTION.write_text(json.dumps(
        {"name": item["name"], "repo": f"local: {item['name']}", "quant": item["quant"], "params_b": item["params_b"],
         "gguf": str(gguf.relative_to(ROOT)) if gguf.is_relative_to(ROOT) else str(gguf), "source": str(src)},
        indent=1, ensure_ascii=False), encoding="utf-8")
    if not item["tools"]:
        print("warning: this file's chat template has no tool-call support; the design loop needs tool calls")
    print(f"using {gguf}; next: python llm/serve.py start")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--quant", help="download this quantization (e.g. Q4_K_M) instead of the one llmfit proposes")
    ap.add_argument("--repo", help="Hugging Face GGUF repository to download directly, skipping the llmfit list (needs --quant)")
    ap.add_argument("--gguf", help="use this GGUF file already on the PC instead of downloading")
    ap.add_argument("--name", help="with --gguf: name to show (e.g. the Ollama model name)")
    ap.add_argument("--copy", action="store_true", help="with --gguf: copy the file into models/ first")
    args = ap.parse_args()

    if args.gguf:
        use_local(args.gguf, args.name, args.copy)
        return
    if args.repo:
        if not args.quant:
            die("--repo needs --quant, e.g. --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M")
        ensure_llmfit()
        download({"name": args.repo, "gguf_sources": [{"repo": args.repo}], "best_quant": args.quant, "params_b": 0}, args.quant)
        return
    models = candidates(ensure_llmfit())[: args.top]
    if not models:
        die("llmfit found no GGUF model with tool use that fits this machine. Free memory or add RAM/VRAM.")
    show(models)
    if args.list_only:
        return
    if args.auto:
        choice = 1
    else:
        answer = input("Download which one? [1] ").strip() or "1"
        choice = int(answer) if answer.isdigit() and 1 <= int(answer) <= len(models) else die("pick a number from the list")
    download(models[choice - 1], args.quant)


if __name__ == "__main__":
    main()
