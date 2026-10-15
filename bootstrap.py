#!/usr/bin/env python3
"""이 PC 를 감지(macOS / Linux / WSL / Windows, GPU, 메모리, 설치된 도구)하고, 빠진 것을 설치한 뒤 프로젝트를 설정합니다.

  python3 bootstrap.py                 감지 -> 할 일 표시 -> 확인 후 진행
  python3 bootstrap.py --detect-only   감지 결과만 출력
  python3 bootstrap.py --yes           묻지 않고 진행
  python3 bootstrap.py --rebuild-llama llama.cpp 를 다시 빌드 (Linux/WSL, CUDA toolkit 을 나중에 설치했을 때)
  python3 bootstrap.py --slots 1       모델 서버의 동시 요청 수 (기본: 메모리가 작으면 1, 아니면 2)
  python3 bootstrap.py --cpu           NVIDIA GPU 가 있어도 CPU 로 (Windows 드라이버가 오래됐을 때)
  python3 bootstrap.py --no-existing   이 PC 에 이미 있는 모델(Ollama, LM Studio 등)을 쓰지 않고 새로 다운로드
  python3 bootstrap.py --search DIR    .gguf 파일이 있는 다른 폴더도 찾기 (여러 번 가능)

이 PC 에 이미 받아 둔 GGUF 모델(Ollama, LM Studio, Hugging Face/llama.cpp 캐시, WSL 이면 Windows 쪽 포함)이
있으면 다운로드 대신 그 파일을 이 프로젝트의 llama-server 로 실행합니다 (llm/existing.py).

그 밖의 옵션은 llm/pick.py 로 넘어갑니다 (예: --repo unsloth/Qwen3.8-27B-GGUF --quant Q4_K_M, --auto).
표준 라이브러리만 씁니다. Windows 에 파이썬이 없으면: winget install astral-sh.uv 후 `uv run bootstrap.py`.
WSL 자체가 없으면 Windows 에서 install-wsl.ps1 을 먼저 실행하세요 (WSL 설치 → Ubuntu → 이 스크립트까지 한 번에).
"""
from __future__ import annotations

import argparse
import ctypes
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "llm"))
import existing  # noqa: E402  (llm/existing.py, standard library only)

HOME = Path.home()
WIN = platform.system() == "Windows"
PORT = 8080
MODEL_REPO, MODEL_QUANT, MODEL_NEEDS_GB = "unsloth/Qwen3.8-27B-GGUF", "Q4_K_M", 24
# 예산이 24GB 미만일 때의 기본 모델: 도구 호출이 되는 가장 작은 현실적인 크기 (Q4_K_M 약 9GB)
SMALL_REPO, SMALL_NEEDS_GB = "unsloth/Qwen3-14B-GGUF", 10
# 일부 Ubuntu 미러는 Release 파일 날짜가 몇 분~몇십 분 미래로 찍혀 "not valid yet" 으로 apt update 가 실패합니다
APT_OPTS = "-o Acquire::Max-FutureTime=86400"
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


def driver_cuda(out: str) -> str | None:
    """Highest CUDA version the installed driver supports, from the `nvidia-smi` banner ("CUDA Version: 13.1")."""
    m = re.search(r"CUDA Version:\s*([0-9]+\.[0-9]+)", out)
    return m.group(1) if m else None


def llama_has_cuda() -> bool | None:
    """Whether ~/llama.cpp was configured with CUDA; None when it was never built here."""
    cache = HOME / "llama.cpp" / "build" / "CMakeCache.txt"
    return "GGML_CUDA:BOOL=ON" in cache.read_text(errors="replace") if cache.exists() else None


def detect_gpu(system: str, machine: str, ram: float) -> dict[str, Any]:
    nvidia = parse_nvidia(sh(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]))
    if nvidia:
        nvidia["cuda"] = driver_cuda(sh(["nvidia-smi"]))
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

    nvidia = gpu["kind"] == "nvidia"
    # WSL 에서는 NVIDIA 의 WSL 전용 저장소에서 빌드 도구만 받습니다 (scripts/install-cuda-wsl.sh: 드라이버 없음, 버전은 드라이버에 맞춤)
    auto_cuda = nvidia and not tools["nvcc"] and kind == "wsl" and bool(tools["apt-get"])
    if kind in ("linux", "wsl"):
        missing = [pkg for pkg, binary in (("git", "git"), ("curl", "curl"), ("cmake", "cmake"), ("build-essential", "g++")) if not tools[binary]]
        if missing and tools["apt-get"]:
            steps.append((f"필수 패키지 설치 ({', '.join(missing)})", [f"sudo apt-get {APT_OPTS} update && sudo apt-get install -y {' '.join(missing)}"]))
        elif missing:
            notes.append(f"apt 가 없는 배포판입니다. 직접 설치하세요: {', '.join(missing)}")
        if auto_cuda:
            steps.append(("CUDA 빌드 도구 설치 (nvcc, cuBLAS 약 1GB, 드라이버는 설치하지 않음)", [
                f"sudo bash scripts/install-cuda-wsl.sh {q(gpu.get('cuda') or '')}"
                " || echo 'CUDA 도구를 설치하지 못해 CPU 로 빌드합니다. 위 안내를 확인하세요.'"]))
        if nvidia and tools["llama-server"] and llama_has_cuda() is False:
            rebuild_llama = True
            notes.append("CPU 용으로 빌드된 llama.cpp 를 GPU(CUDA) 용으로 다시 빌드합니다.")
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
            use_cuda = nvidia and (bool(tools["nvcc"]) or auto_cuda)
            if nvidia and not use_cuda:
                notes.append("NVIDIA GPU 는 보이지만 CUDA toolkit(nvcc)이 없어 CPU 용으로 빌드합니다. CUDA toolkit 설치 후 `--rebuild-llama` 로 다시 실행하면 GPU 를 씁니다.")
            if not nvidia:
                notes.append("NVIDIA GPU 가 감지되지 않아 CPU 용으로 빌드합니다 (큰 모델은 매우 느립니다)."
                             + (" WSL 에서 GPU 를 쓰려면 윈도우에 NVIDIA 드라이버를 설치하고 WSL 안에서 `nvidia-smi` 가 보이는지 확인하세요." if kind == "wsl" else ""))
            jobs = max(1, min(env["cpus"], int(env["ram_gb"] // 2) or 1))
            src, build = HOME / "llama.cpp", HOME / "llama.cpp" / "build"
            # CUDA 는 실행 시점에 nvcc 가 실제로 있을 때만 켭니다: 위의 CUDA 설치가 실패하면 CPU 빌드로 이어집니다
            cuda_flags = (' $(NVCC=$(command -v nvcc || echo /usr/local/cuda/bin/nvcc); '
                          '[ -x "$NVCC" ] && echo "-DGGML_CUDA=ON -DCMAKE_CUDA_COMPILER=$NVCC" || echo "-DGGML_CUDA=OFF")') if use_cuda else ""
            steps.append((f"llama.cpp 빌드 ({'CUDA, 10~30분' if use_cuda else 'CPU, 수 분'} 걸립니다)", [
                f"if [ -d {q(src / '.git')} ]; then git -C {q(src)} pull --ff-only; else git clone --depth 1 https://github.com/ggml-org/llama.cpp {q(src)}; fi",
                f"cmake -S {q(src)} -B {q(build)} -DLLAMA_CURL=OFF" + cuda_flags,
                f"cmake --build {q(build)} --config Release -j {jobs} --target llama-server",
                f"mkdir -p {q(HOME / '.local' / 'bin')} && ln -sf {q(build / 'bin' / 'llama-server')} {q(HOME / '.local' / 'bin' / 'llama-server')}",
            ]))
    return steps, notes


def default_slots(env: dict[str, Any]) -> int:
    """동시 요청 수. 슬롯마다 컨텍스트(KV 캐시) 메모리가 따로 잡히므로 메모리가 작으면 1 개만 씁니다."""
    return 2 if budget_gb(env) >= MODEL_NEEDS_GB else 1


def default_pick_args(env: dict[str, Any]) -> tuple[list[str], str | None]:
    """Model to download when none is chosen: by memory budget, with a note when it is not the recommended 27B."""
    budget = budget_gb(env)
    if budget >= MODEL_NEEDS_GB:
        return ["--repo", MODEL_REPO, "--quant", MODEL_QUANT], None
    if budget >= SMALL_NEEDS_GB:
        return ["--repo", SMALL_REPO, "--quant", MODEL_QUANT], (
            f"모델 예산이 약 {budget}GB 라서 권장 27B 대신 Qwen3-14B(Q4_K_M, 약 9GB)를 받습니다. "
            "설계 품질은 27B 보다 낮을 수 있으니 selfcheck 결과를 확인하세요.")
    return ["--auto"], (
        f"모델 예산이 약 {budget}GB 라서 llmfit 이 이 PC 에 맞다고 고른 1순위 모델을 받습니다. "
        "작은 모델은 설계 루프가 끝까지 안 돌 수 있으니 selfcheck 결과를 확인하세요."
        + (" WSL 이면 .wslconfig 의 memory 를 늘리면 예산이 커집니다." if env["kind"] == "wsl" else ""))


def project_plan(env: dict[str, Any], pick_args: list[str], server_up: bool, slots: int,
                 local: dict[str, Any] | None = None) -> tuple[list[tuple[str, list[str]]], list[str]]:
    py = q(venv_python())
    steps: list[tuple[str, list[str]]] = []
    notes: list[str] = []
    if not venv_python().exists():
        steps.append(("파이썬 환경 만들기 (.venv)", ["uv venv --python 3.12 .venv"]))
    steps.append(("의존 패키지 설치", [f"uv pip install --python {py} -r requirements.txt"]))
    if not env["tools"]["llmfit"]:
        steps.append(("llmfit 설치 (모델 추천·다운로드용)", ["uv tool install -U llmfit"]))
    fallback = ""
    if local:
        # Windows 드라이브(/mnt/c)에서 직접 읽으면 서버를 켤 때마다 매우 느려서 WSL 쪽으로 한 번 복사합니다
        copy = env["kind"] == "wsl" and local["on_windows_drive"]
        steps.append((f"이미 있는 모델 사용: {existing.label(local)}" + (" (WSL 안으로 복사)" if copy else ""),
                      [f"{py} llm/pick.py --gguf {q(local['path'])} --name {q(local['name'])}" + (" --copy" if copy else "")]))
        # 이 llama.cpp 로 열리지 않는 파일이면(일부 Ollama 전용 형식) 원래대로 권장 모델을 받아서 다시 켭니다
        args, _ = default_pick_args(env)
        fallback = (f" || (echo 이 모델로 서버를 켜지 못해 권장 모델을 새로 받습니다 && {py} llm/pick.py {' '.join(map(q, args))}"
                    f" && {py} llm/serve.py start --slots {slots})")
        if local["source"] == "Ollama":
            notes.append(f"Ollama 가 같은 모델을 메모리에 올려 두고 있으면 메모리를 두 배로 씁니다. 필요하면 먼저: ollama stop {local['name']}")
        if budget_gb(env) >= MODEL_NEEDS_GB and local["params_b"] < 27:
            notes.append("이 PC 는 권장 모델(Qwen3.8-27B)도 돌릴 수 있습니다. 기존 모델 대신 새로 받으려면 --no-existing 을 붙이세요.")
    elif pick_args or not (ROOT / ".llm" / "selection.json").exists():
        args = pick_args
        if not args:
            args, note = default_pick_args(env)
            notes += [note] if note else []
        steps.append(("모델 선택·다운로드", [f"{py} llm/pick.py {' '.join(map(q, args))}".strip()]))
    if not server_up:
        steps.append((f"모델 서버 켜기 (동시 요청 {slots})", [f"{py} llm/serve.py start --slots {slots}{fallback}"]))
    # 점검 결과(FAIL/WARN)는 모델 품질 문제라 설치 실패로 치지 않습니다. 결과는 화면에 그대로 나옵니다
    steps.append(("품질 점검 (selfcheck)", [f"{py} llm/selfcheck.py || echo \"품질 점검이 통과하지 못했습니다. README 2.4, 2.5 를 보고 더 큰 모델을 고르세요.\""]))
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
    vram += f", 드라이버 CUDA {gpu['cuda']}" if gpu.get("cuda") else ""
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


def find_existing(env: dict[str, Any], search: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(everything found, usable ones best first). Never stops the install: on any error nothing is found."""
    try:
        found = existing.find(search)
    except Exception as exc:  # noqa: BLE001
        print(f"  (기존 모델 찾기 실패, 건너뜀: {exc})")
        return [], []
    return found, existing.usable(found, budget_gb(env))


def show_existing(found: list[dict[str, Any]], good: list[dict[str, Any]], env: dict[str, Any]) -> None:
    if not found:
        print("  기존 모델 없음 (Ollama, LM Studio, Hugging Face/llama.cpp 캐시)")
        return
    print(f"  기존 모델 {len(found)}개 발견, 그중 쓸 수 있는 것 {len(good)}개")
    for item in found:
        reason = existing.judge(item, budget_gb(env))
        print(f"    {'O' if reason is None else '-'} {existing.label(item)}" + (f"  [{reason}]" if reason else ""))


def choose_existing(good: list[dict[str, Any]], ask: bool) -> dict[str, Any] | None:
    if not good:
        return None
    if not ask:
        return good[0]
    print("\n이 PC 에 이미 있는 모델을 쓸 수 있습니다 (다운로드 생략).")
    for i, item in enumerate(good, 1):
        print(f"  {i}. {existing.label(item)}")
    print("  0. 쓰지 않고 권장 모델을 새로 다운로드")
    answer = input("어느 것을 쓸까요? [1] ").strip() or "1"
    return good[int(answer) - 1] if answer.isdigit() and 1 <= int(answer) <= len(good) else None


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
    ap.add_argument("--slots", type=int, help="모델 서버 동시 요청 수 (기본: 메모리가 작으면 1, 아니면 2)")
    ap.add_argument("--cpu", action="store_true", help="NVIDIA GPU 가 있어도 CPU 로 빌드·설정 (드라이버가 오래됐을 때)")
    ap.add_argument("--no-existing", action="store_true", help="이 PC 에 이미 있는 모델을 쓰지 않고 새로 다운로드")
    ap.add_argument("--search", action="append", default=[], help=".gguf 파일이 있는 다른 폴더도 찾기 (여러 번 가능)")
    args, pick_args = ap.parse_known_args()

    os.environ["PYTHONUTF8"] = "1"
    path_before = os.environ.get("PATH", "")
    env = detect()
    if args.cpu and env["gpu"]["kind"] == "nvidia":  # 모델 예산도 VRAM 대신 메모리로 계산합니다
        env["gpu"] = {"kind": "none", "name": f"{env['gpu']['name']} (쓰지 않음: --cpu)", "vram_gb": None}
    show_detection(env)
    # 모델을 직접 지정했거나(--repo 등) 이미 골라 둔 모델이 있으면 기존 모델을 찾지 않습니다
    look = not args.no_existing and not pick_args and not (ROOT / ".llm" / "selection.json").exists()
    found, good = find_existing(env, args.search) if look else ([], [])
    if look:
        show_existing(found, good, env)
    if args.detect_only:
        return
    local = choose_existing(good, ask=not args.yes)

    tool_steps, notes = tool_plan(env, args.rebuild_llama)
    proj_steps, proj_notes = project_plan(env, pick_args, server_healthy(), args.slots or default_slots(env), local)
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
