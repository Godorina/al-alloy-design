#!/usr/bin/env python3
"""이 PC 를 감지(macOS / Linux / WSL / Windows, GPU, 메모리, 설치된 도구)하고, 빠진 것을 설치한 뒤 프로젝트를 설정합니다.

  python3 bootstrap.py                 감지 -> 할 일 표시 -> 확인 후 진행
  python3 bootstrap.py --detect-only   감지 결과만 출력
  python3 bootstrap.py --yes           묻지 않고 진행
  python3 bootstrap.py --rebuild-llama llama.cpp 를 다시 빌드 (Linux/WSL, CUDA toolkit 을 나중에 설치했을 때)

그 밖의 옵션은 llm/pick.py 로 넘어갑니다 (예: --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M, --auto).
표준 라이브러리만 씁니다. Windows 에 파이썬이 없으면: winget install astral-sh.uv 후 `uv run bootstrap.py`.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import platform
import shlex
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
WIN = platform.system() == "Windows"
PORT = 8080
MODEL_REPO, MODEL_QUANT, MODEL_NEEDS_GB = "unsloth/Qwen3.8-27B-GGUF", "Q4_K_M", 20
EXTRA_PATHS = [HOME / ".local" / "bin", HOME / ".cargo" / "bin", HOME / "llama.cpp" / "build" / "bin", Path("/usr/local/cuda/bin")]
TOOLS = ["git", "curl", "cmake", "g++", "uv", "llmfit", "llama-server", "nvcc", "brew", "winget", "apt-get"]


def q(value: object) -> str:
    return subprocess.list2cmdline([str(value)]) if WIN else shlex.quote(str(value))


def sh(cmd: list[str]) -> str:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def classify(system: str, release: str, proc_version: str = "") -> tuple[str, int]:
    if system == "Darwin":
        return "macos", 0
    if system == "Windows":
        return "windows", 0
    text = (release + " " + proc_version).lower()
    if "microsoft" in text:
        return "wsl", 2 if "wsl2" in text else 1
    return "linux", 0


def parse_nvidia(out: str) -> dict[str, Any] | None:
    """First line of `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`."""
    rows = [line.rsplit(",", 1) for line in out.splitlines() if "," in line]
    if not rows:
        return None
    try:
        vram = round(int(rows[0][1].strip()) / 1024, 1)
    except ValueError:
        return None
    return {"kind": "nvidia", "name": rows[0][0].strip(), "vram_gb": vram, "count": len(rows)}


def ram_gb(system: str) -> float:
    if system == "Linux":
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 2**20, 1)
    if system == "Darwin":
        return round(int(sh(["sysctl", "-n", "hw.memsize"]) or 0) / 2**30, 1)
    if system == "Windows":
        class MemStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong),
                        ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong), ("aext", ctypes.c_ulonglong)]
        status = MemStatus(length=ctypes.sizeof(MemStatus))
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
        return round(status.total / 2**30, 1)
    return 0.0


def detect_gpu(system: str, machine: str, ram: float) -> dict[str, Any]:
    nvidia = parse_nvidia(sh(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]))
    if nvidia:
        return nvidia
    if system == "Darwin" and machine == "arm64":
        return {"kind": "apple", "name": "Apple Silicon (통합 메모리)", "vram_gb": ram}
    if system == "Windows":
        names = sh(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"])
        if names:
            return {"kind": "other", "name": names.splitlines()[0].strip(), "vram_gb": None}
    return {"kind": "none", "name": "감지 안 됨", "vram_gb": None}


def detect() -> dict[str, Any]:
    for extra in EXTRA_PATHS:
        os.environ["PATH"] = str(extra) + os.pathsep + os.environ.get("PATH", "")
    system, machine = platform.system(), platform.machine().lower()
    proc_version = Path("/proc/version").read_text() if Path("/proc/version").exists() else ""
    kind, wsl = classify(system, platform.release(), proc_version)
    ram = ram_gb(system)
    return {
        "kind": kind, "wsl": wsl, "machine": machine, "ram_gb": ram, "gpu": detect_gpu(system, machine, ram),
        "tools": {name: shutil.which(name) for name in TOOLS},
        "on_windows_drive": kind == "wsl" and str(ROOT).startswith("/mnt/"),
        "cpus": os.cpu_count() or 1,
    }


def budget_gb(env: dict[str, Any]) -> float:
    """Memory a model can use: VRAM for NVIDIA, unified memory on Apple Silicon, ~60% of RAM on CPU."""
    gpu = env["gpu"]
    if gpu["kind"] in ("nvidia", "apple") and gpu["vram_gb"]:
        return gpu["vram_gb"]
    return round(env["ram_gb"] * 0.6, 1)


def venv_python() -> Path:
    return ROOT / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")


def tool_plan(env: dict[str, Any], rebuild_llama: bool) -> tuple[list[tuple[str, list[str]]], list[str]]:
    kind, tools, gpu = env["kind"], env["tools"], env["gpu"]
    steps: list[tuple[str, list[str]]] = []
    notes: list[str] = []

    if kind in ("linux", "wsl"):
        missing = [pkg for pkg, binary in (("git", "git"), ("curl", "curl"), ("cmake", "cmake"), ("build-essential", "g++")) if not tools[binary]]
        if missing and tools["apt-get"]:
            steps.append((f"필수 패키지 설치 ({', '.join(missing)})", [f"sudo apt-get update && sudo apt-get install -y {' '.join(missing)}"]))
        elif missing:
            notes.append(f"apt 가 없는 배포판입니다. 직접 설치하세요: {', '.join(missing)}")
    if kind == "macos" and not tools["git"]:
        steps.append(("git 설치 (Xcode 명령줄 도구)", ["xcode-select --install"]))
    if kind == "windows" and not tools["git"]:
        steps.append(("git 설치", ["winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements"]))

    if not tools["uv"]:
        if kind == "windows":
            steps.append(("uv 설치", ["winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements"]))
        else:
            steps.append(("uv 설치", ["curl -LsSf https://astral.sh/uv/install.sh | sh"]))

    if not tools["llama-server"] or (rebuild_llama and kind in ("linux", "wsl")):
        if kind == "macos":
            if tools["brew"]:
                steps.append(("llama.cpp 설치 (brew)", ["brew install llama.cpp"]))
            else:
                notes.append("Homebrew 가 없습니다. https://brew.sh 로 설치한 뒤 다시 실행하세요.")
        elif kind == "windows":
            if tools["winget"]:
                steps.append(("llama.cpp 설치 (winget)", ["winget install --id ggml.llamacpp -e --accept-source-agreements --accept-package-agreements"]))
            else:
                notes.append("winget 이 없습니다. https://github.com/ggml-org/llama.cpp/releases 에서 Windows 빌드를 받아 PATH 에 넣으세요.")
        else:
            use_cuda = gpu["kind"] == "nvidia" and bool(tools["nvcc"])
            if gpu["kind"] == "nvidia" and not use_cuda:
                notes.append("NVIDIA GPU 는 보이지만 CUDA toolkit(nvcc)이 없어 CPU 용으로 빌드합니다. CUDA toolkit 설치 후 `--rebuild-llama` 로 다시 실행하면 GPU 를 씁니다.")
            if gpu["kind"] != "nvidia":
                notes.append("GPU 가 감지되지 않아 CPU 용으로 빌드합니다 (큰 모델은 매우 느립니다)."
                             + (" WSL 에서 GPU 를 쓰려면 윈도우에 NVIDIA 드라이버를 설치하고 WSL 안에서 `nvidia-smi` 가 보이는지 확인하세요." if kind == "wsl" else ""))
            jobs = max(1, min(env["cpus"], int(env["ram_gb"] // 2) or 1))
            src, build = HOME / "llama.cpp", HOME / "llama.cpp" / "build"
            steps.append((f"llama.cpp 빌드 ({'CUDA' if use_cuda else 'CPU'}, 수 분 걸립니다)", [
                f"if [ -d {q(src / '.git')} ]; then git -C {q(src)} pull --ff-only; else git clone --depth 1 https://github.com/ggml-org/llama.cpp {q(src)}; fi",
                f"cmake -S {q(src)} -B {q(build)} -DLLAMA_CURL=OFF" + (" -DGGML_CUDA=ON" if use_cuda else ""),
                f"cmake --build {q(build)} --config Release -j {jobs} --target llama-server",
                f"mkdir -p {q(HOME / '.local' / 'bin')} && ln -sf {q(build / 'bin' / 'llama-server')} {q(HOME / '.local' / 'bin' / 'llama-server')}",
            ]))
    return steps, notes


def project_plan(env: dict[str, Any], pick_args: list[str], server_up: bool) -> tuple[list[tuple[str, list[str]]], list[str]]:
    py = q(venv_python())
    steps: list[tuple[str, list[str]]] = []
    notes: list[str] = []
    if not venv_python().exists():
        steps.append(("파이썬 환경 만들기 (.venv)", ["uv venv --python 3.12 .venv"]))
    steps.append(("의존 패키지 설치", [f"uv pip install --python {py} -r requirements.txt"]))
    if not env["tools"]["llmfit"]:
        steps.append(("llmfit 설치 (모델 추천·다운로드용)", ["uv tool install -U llmfit"]))
    if pick_args or not (ROOT / ".llm" / "selection.json").exists():
        args = pick_args
        if not args:
            if budget_gb(env) >= MODEL_NEEDS_GB:
                args = ["--repo", MODEL_REPO, "--quant", MODEL_QUANT]
            else:
                notes.append(f"모델에 쓸 수 있는 메모리가 약 {budget_gb(env)}GB 라서 권장 27B(약 15GB + 컨텍스트)는 무겁습니다. "
                             "llmfit 순위에서 직접 고르세요. 작은 모델은 설계 루프가 끝까지 안 돌 수 있습니다.")
        steps.append(("모델 선택·다운로드", [f"{py} llm/pick.py {' '.join(map(q, args))}".strip()]))
    if not server_up:
        steps.append(("모델 서버 켜기", [f"{py} llm/serve.py start"]))
    steps.append(("품질 점검 (selfcheck)", [f"{py} llm/selfcheck.py"]))
    return steps, notes


def server_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def show_detection(env: dict[str, Any]) -> None:
    gpu = env["gpu"]
    label = {"macos": "macOS", "windows": "Windows (네이티브)", "linux": "Linux",
             "wsl": f"WSL{env['wsl']} 의 Linux"}[env["kind"]]
    vram = f", VRAM {gpu['vram_gb']}GB" if gpu.get("vram_gb") and gpu["kind"] == "nvidia" else ""
    print("감지 결과")
    print(f"  환경      {label} ({env['machine']})")
    print(f"  메모리    {env['ram_gb']}GB" + (" (WSL 에 할당된 양)" if env["kind"] == "wsl" else ""))
    print(f"  GPU       {gpu['name']}{vram}")
    print(f"  모델 예산 약 {budget_gb(env)}GB")
    print("  도구      " + ", ".join(f"{n} {'O' if p else 'X'}" for n, p in env["tools"].items()))
    if env["wsl"] == 1:
        print("  경고      WSL1 입니다. WSL2 로 바꾸세요: wsl --set-version <배포판> 2")
    if env["on_windows_drive"]:
        print("  경고      /mnt/ (윈도우 드라이브) 아래에 있습니다. I/O 가 매우 느리니 ~/ 아래로 옮기세요.")


def run(steps: list[tuple[str, list[str]]], start: int = 1) -> None:
    for i, (title, cmds) in enumerate(steps, start):
        print(f"\n[{i}] {title}")
        for cmd in cmds:
            print(f"    $ {cmd}")
            if subprocess.run(cmd, shell=True, cwd=ROOT).returncode != 0:
                sys.exit(f"\n실패: {cmd}\n위 오류 메시지와 함께 알려 주세요. 같은 명령을 다시 실행하면 이어서 진행됩니다.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detect-only", action="store_true")
    ap.add_argument("-y", "--yes", action="store_true")
    ap.add_argument("--rebuild-llama", action="store_true")
    args, pick_args = ap.parse_known_args()

    os.environ["PYTHONUTF8"] = "1"
    path_before = os.environ.get("PATH", "")
    env = detect()
    show_detection(env)
    if args.detect_only:
        return

    tool_steps, notes = tool_plan(env, args.rebuild_llama)
    proj_steps, proj_notes = project_plan(env, pick_args, server_healthy())
    notes += proj_notes
    print("\n할 일")
    for i, (title, cmds) in enumerate(tool_steps + proj_steps, 1):
        print(f"  {i}. {title}")
    for note in notes:
        print(f"  ! {note}")
    if not env["tools"]["llama-server"] and not any(title.startswith("llama.cpp") for title, _ in tool_steps):
        sys.exit("\nllama-server 를 설치할 방법이 없어 중단합니다. 위 안내대로 설치한 뒤 다시 실행하세요.")
    if not args.yes and input("\n진행할까요? [Y/n] ").strip().lower() in ("n", "no"):
        return

    run(tool_steps)
    if WIN and tool_steps:  # winget 이 PATH 를 바꿨지만 이 프로세스에는 반영되지 않습니다
        print("\n도구를 설치했습니다. PATH 갱신을 위해 새 PowerShell 을 열고 같은 명령을 다시 실행하세요.")
        return
    run(proj_steps, len(tool_steps) + 1)
    if not WIN and str(HOME / ".local" / "bin") not in path_before:
        print('\n새 터미널에서 llama-server/uv 가 안 잡히면: export PATH="$HOME/.local/bin:$PATH"  (~/.profile 에 추가)')
    print(f"\n끝났습니다. 설계 실행: {venv_python()} design.py \"6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상, 내식성 좋게\"")


if __name__ == "__main__":
    main()
