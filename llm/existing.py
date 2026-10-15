#!/usr/bin/env python3
"""Find GGUF models that are already on this PC (Ollama, LM Studio, Hugging Face / llama.cpp caches) so the
project can run one of them with its own llama-server instead of downloading a new one.

  python llm/existing.py [--budget 20] [--search DIR ...]   list what was found and whether it is usable

On WSL the Windows side (/mnt/c/Users/*) is searched too. Standard library only (bootstrap.py imports it
before the virtual environment exists).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
from pathlib import Path

MIN_PARAMS_B = 7.0  # smaller models rarely finish the design loop (README 2.5)
# same exclusions as llm/pick.py: reasoning/thinking/coder/vision/embedding variants
EXCLUDE = re.compile(
    r"abliterat|heretic|uncensor|reasoning|distill|thinking|coder|vision|embed|guard|tts|mlx|nvfp4|bnb|awq|gptq|reap"
    r"|(?<![a-z0-9])(vl|r1)(?![a-z0-9])",
    re.I,
)
EMBEDDING_ARCHS = {"bert", "nomic-bert", "nomic-bert-moe", "jina-bert-v2", "t5encoder", "modern-bert", "neo-bert"}
OLLAMA_MODEL_LAYER = "application/vnd.ollama.image.model"
WINDOWS_SKIP_USERS = {"public", "default", "default user", "all users"}
QUANT = re.compile(r"(?<![A-Za-z0-9])(UD-)?(I?Q\d(_[0-9A-Z]+)*|BF16|F16|F32)(?![A-Za-z0-9])", re.I)
FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S",
              12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 32: "BF16"}
SHARD = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)

# GGUF value types -> struct format (strings and arrays are handled separately)
_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9


def _read(f, fmt: str):
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) != size:
        raise EOFError
    return struct.unpack(fmt, data)[0]


def _string(f) -> str:
    n = _read(f, "<Q")
    if n > 1 << 24:
        raise ValueError("string too long")
    return f.read(n).decode("utf-8", "replace")


def _skip_value(f, vtype: int) -> None:
    if vtype in _SCALAR:
        f.seek(struct.calcsize(_SCALAR[vtype]), 1)
    elif vtype == _STRING:
        f.seek(_read(f, "<Q"), 1)
    elif vtype == _ARRAY:
        etype, count = _read(f, "<I"), _read(f, "<Q")
        if etype in _SCALAR:
            f.seek(struct.calcsize(_SCALAR[etype]) * count, 1)
        else:
            for _ in range(count):
                _skip_value(f, etype)
    else:
        raise ValueError(f"unknown GGUF value type {vtype}")


def gguf_metadata(path: Path) -> dict | None:
    """Scalar and string metadata of a GGUF file (arrays such as the vocabulary are skipped); None if not GGUF."""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF" or _read(f, "<I") < 2:
                return None
            _read(f, "<Q")  # tensor count
            meta = {}
            for _ in range(_read(f, "<Q")):
                key, vtype = _string(f), _read(f, "<I")
                if vtype in _SCALAR:
                    meta[key] = _read(f, _SCALAR[vtype])
                elif vtype == _STRING:
                    meta[key] = _string(f)
                else:
                    _skip_value(f, vtype)
            return meta
    except (OSError, EOFError, ValueError, struct.error):
        return None


def params_from(*texts: str) -> float | None:
    """Parameter count in billions from a name or size label: '14B', 'qwen3:14b', '8x7B', '600M'."""
    for text in texts:
        m = re.search(r"(?<![A-Za-z0-9.])(\d+x)?(\d+(?:\.\d+)?)\s*([BM])(?![A-Za-z])", text or "", re.I)
        if m:
            value = float(m.group(2)) * (int(m.group(1)[:-1]) if m.group(1) else 1)
            return value / 1000 if m.group(3).lower() == "m" else value
    return None


def describe(path: Path, source: str, name: str) -> dict | None:
    """One candidate: name, size, parameters, tool-call support (from the file's own chat template)."""
    meta = gguf_metadata(path)
    if meta is None:
        return None
    arch = meta.get("general.architecture", "")
    shards = [path]
    shard = SHARD.search(path.name)
    if shard:
        shards = sorted(path.parent.glob(SHARD.sub("-*-of-" + shard.group(2) + ".gguf", path.name)))
    size_gb = round(sum(p.stat().st_size for p in shards) / 2**30, 1)
    params = params_from(name, meta.get("general.size_label", ""), meta.get("general.name", ""), path.name)
    template = meta.get("tokenizer.chat_template", "")
    quant = QUANT.search(name.rsplit("/", 1)[-1].replace(":", "-") + " " + path.name)
    return {
        "source": source, "name": name, "path": str(path), "size_gb": size_gb,
        "params_b": params if params is not None else round(size_gb * 1.65, 1),  # ~4.8 bits per weight
        "params_known": params is not None, "arch": arch,
        "quant": quant.group(0).upper() if quant else FILE_TYPES.get(meta.get("general.file_type"), ""),
        "tools": "tool" in template, "has_template": bool(template),
        "embedding": arch in EMBEDDING_ARCHS or f"{arch}.pooling_type" in meta,
        "not_a_model": meta.get("general.type", "model") != "model" or "mmproj" in path.name.lower(),
        "context_train": meta.get(f"{arch}.context_length"),
        "on_windows_drive": str(path).startswith("/mnt/"),
    }


def windows_homes() -> list[Path]:
    """C:\\Users\\* seen from WSL."""
    users = Path("/mnt/c/Users")
    try:
        return [p for p in users.iterdir() if p.is_dir() and p.name.lower() not in WINDOWS_SKIP_USERS]
    except OSError:
        return []


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def search_roots(extra: list[str] | None = None) -> dict[str, list[Path]]:
    homes = [Path.home()] + (windows_homes() if is_wsl() else [])
    env = os.environ
    ollama = [Path(env["OLLAMA_MODELS"])] if env.get("OLLAMA_MODELS") else []
    ollama += [h / ".ollama" / "models" for h in homes]
    ollama += [Path("/usr/share/ollama/.ollama/models"), Path("/var/lib/ollama/.ollama/models")]
    lmstudio = [p for h in homes for p in (h / ".lmstudio" / "models", h / ".cache" / "lm-studio" / "models")]
    hf = [Path(env["HF_HUB_CACHE"])] if env.get("HF_HUB_CACHE") else []
    hf += [Path(env["HF_HOME"]) / "hub"] if env.get("HF_HOME") else []
    hf += [h / ".cache" / "huggingface" / "hub" for h in homes]
    llamacpp = [Path(env["LLAMA_CACHE"])] if env.get("LLAMA_CACHE") else []
    llamacpp += [p for h in homes for p in (h / ".cache" / "llama.cpp", h / "AppData" / "Local" / "llama.cpp",
                                            h / "Library" / "Caches" / "llama.cpp")]
    return {"Ollama": ollama, "LM Studio": lmstudio, "Hugging Face": hf, "llama.cpp": llamacpp,
            "폴더": [Path(p).expanduser() for p in extra or []]}


def ollama_models(root: Path) -> list[tuple[Path, str]]:
    """(blob, 'model:tag') pairs from an Ollama models directory."""
    manifests, found = root / "manifests", {}
    for manifest in sorted(manifests.rglob("*")) if manifests.is_dir() else []:
        parts = manifest.relative_to(manifests).parts
        if not manifest.is_file() or len(parts) != 4:
            continue
        registry, namespace, model, tag = parts
        name = (f"{model}:{tag}" if (registry, namespace) == ("registry.ollama.ai", "library")
                else f"{namespace}/{model}:{tag}" if registry == "registry.ollama.ai" else f"{registry}/{namespace}/{model}:{tag}")
        try:
            layers = json.loads(manifest.read_text(encoding="utf-8")).get("layers", [])
        except (OSError, ValueError):
            continue
        digest = next((l["digest"] for l in layers if l.get("mediaType") == OLLAMA_MODEL_LAYER), None)
        if digest:
            blob = root / "blobs" / digest.replace(":", "-")
            # several tags can share one blob (qwen3:latest, qwen3:8b): keep the more telling name
            if blob.is_file() and (blob not in found or found[blob].endswith(":latest")):
                found[blob] = name
    return [(blob, name) for blob, name in found.items()]


def gguf_files(root: Path, source: str) -> list[tuple[Path, str]]:
    out = []
    for path in sorted(root.rglob("*.gguf")) if root.is_dir() else []:
        shard = SHARD.search(path.name)
        if shard and shard.group(1) != "00001":
            continue
        if source == "Hugging Face":  # hub/models--org--repo/snapshots/<rev>/file.gguf
            repo = next((p.name[len("models--"):].replace("--", "/") for p in path.parents if p.name.startswith("models--")), "")
            name = f"{repo}/{path.name}" if repo else path.name
        elif source == "LM Studio":  # models/<publisher>/<repo>/file.gguf
            name = "/".join(path.relative_to(root).parts)
        else:
            name = path.name
        out.append((path.resolve(), name))
    return out


def find(extra: list[str] | None = None) -> list[dict]:
    """Every GGUF model found on this PC, deduplicated by file."""
    seen, found = set(), []
    for source, roots in search_roots(extra).items():
        for root in roots:
            try:
                # a folder given with --search may be an Ollama models folder (OLLAMA_MODELS)
                ollama = source == "Ollama" or (root / "manifests").is_dir()
                pairs = ollama_models(root) if ollama else gguf_files(root, source)
            except OSError:
                continue
            for path, name in pairs:
                key = str(path.resolve()) if path.exists() else str(path)
                if key in seen:
                    continue
                seen.add(key)
                item = describe(path, "Ollama" if ollama else source, name)
                if item:
                    found.append(item)
    return found


def judge(item: dict, budget_gb: float | None) -> str | None:
    """Why this model should not be used automatically, or None if it is fine."""
    if item["not_a_model"] or item["embedding"]:
        return "채팅 모델이 아님"
    if EXCLUDE.search(item["name"]):
        return "추론/코딩/비전 등 특수 모델"
    if not item["tools"]:
        return "도구 호출(tool call) 템플릿이 없음"
    if item["params_b"] < MIN_PARAMS_B:
        return f"너무 작음 (약 {item['params_b']:g}B, {MIN_PARAMS_B:g}B 이상 필요)"
    if budget_gb and item["size_gb"] > budget_gb * 0.9:
        return f"메모리 예산({budget_gb:g}GB)에 비해 큼"
    return None


def usable(found: list[dict], budget_gb: float | None) -> list[dict]:
    good = [m for m in found if judge(m, budget_gb) is None]
    return sorted(good, key=lambda m: (-m["params_b"], -m["size_gb"]))


def label(item: dict) -> str:
    params = f"{item['params_b']:g}B" + ("" if item["params_known"] else "?")
    quant = f" {item['quant']}" if item["quant"] else ""
    where = ", Windows 쪽" if item["on_windows_drive"] else ""
    return f"{item['name']} ({item['source']}{where}, {params}{quant}, {item['size_gb']:g}GB)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, help="memory a model can use in GB (bootstrap.py prints it)")
    ap.add_argument("--search", action="append", default=[], help="another folder with .gguf files (repeatable)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    found = find(args.search)
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
        return
    if not found:
        print("이 PC 에서 GGUF 모델을 찾지 못했습니다.")
    for item in found:
        reason = judge(item, args.budget)
        print(f"  {'O' if reason is None else '-'} {label(item)}" + (f"  [{reason}]" if reason else ""))
        print(f"      {item['path']}")


if __name__ == "__main__":
    main()
