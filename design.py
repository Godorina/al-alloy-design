#!/usr/bin/env python3
"""요구사항 하나로 알루미늄 합금 설계를 실행하고 결과를 results/ 에 저장합니다 (Open WebUI 불필요).

  .venv/bin/python design.py "6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상, 내식성 좋게"
  .venv/bin/python design.py -f 요구사항.txt        파일에서 요구사항 읽기
  .venv/bin/python design.py --chat                 대화형 모드 (/quit 로 종료)
  .venv/bin/python design.py -v "..."               도구 호출 과정을 화면에 표시

모델 서버가 켜져 있어야 합니다: .venv/bin/python llm/serve.py start
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = ROOT / "src" / "mcp" / "host" / "mcp_host.py"
RESULTS = ROOT / "results"
DEFAULT_MAX_STEPS = 24

TASK = (
    "Answer in the language of the user's request. If the request evaluates strength together with other "
    "properties, read the alloy-properties skill first and follow it exactly. State every assumption for a "
    "missing condition. Always run score.py --final on the rounded candidates and use only that result in the "
    "candidate table. For corrosion requests run corrosion.py and report test conditions and sources. Never "
    "present the measured value of a neighbouring alloy as a prediction for a candidate. Do not hide failed "
    "runs or unevaluated conditions.\n\nUser requirements:\n"
)


def load_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        sys.exit("오류: .env 가 없습니다. 모델 서버를 먼저 켜세요: python llm/serve.py start (venv 의 파이썬으로)")
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def check_server(base: str) -> None:
    try:
        urllib.request.urlopen(f"{base}/v1/models", timeout=5)
    except (urllib.error.URLError, OSError):
        sys.exit(f"오류: 모델 서버({base})가 응답하지 않습니다. 켜는 방법: python llm/serve.py start (venv 의 파이썬으로)")


def read_request(args: argparse.Namespace) -> str:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else (args.request or "")
    if not text.strip():
        sys.exit("오류: 요구사항이 비어 있습니다. 문장으로 주거나 -f 파일을 쓰세요. 도움말: design.py -h")
    if len(text) > 12000:
        sys.exit("오류: 요구사항은 12000자 이하여야 합니다.")
    return text.strip()


def unfinished(answer: str) -> bool:
    return not answer.strip() or answer.lstrip().startswith("<tool_call>")


def run_host(command: list[str], env: dict[str, str]) -> tuple[int, str]:
    proc = subprocess.Popen(command, cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1", **env}, stdout=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        lines.append(line)
    return proc.wait(), "".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("request", nargs="?", help="합금 요구사항 (문장)")
    ap.add_argument("-f", "--file", help="요구사항이 적힌 텍스트 파일")
    ap.add_argument("--chat", action="store_true", help="대화형 모드")
    ap.add_argument("-v", "--verbose", action="store_true", help="도구 호출 과정을 표시")
    ap.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS, help="도구 호출 라운드 상한")
    args = ap.parse_args()

    env = load_env()
    request = "" if args.chat else read_request(args)
    check_server(env.get("LLM_BASE_URL", "http://127.0.0.1:8080"))
    command = [sys.executable, str(HOST), "--server", "kg", "--max-steps", str(args.max_steps)]

    if args.chat:
        raise SystemExit(subprocess.call(command, cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1", **env}))

    if not args.verbose:
        command.append("--quiet")
    code, answer = run_host([*command, TASK + request], env)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    out.write_text(f"# 요청\n\n{request}\n\n# 결과\n\n{answer}", encoding="utf-8")
    print(f"\n저장: {out.relative_to(ROOT)}", file=sys.stderr)
    if answer.lstrip().startswith("[LLM error timeout]"):
        print("경고: 설계가 끝나지 않았습니다 (모델 서버 응답 시간 초과). .env 의 LLM_TIMEOUT 을 늘리거나(0 = 무제한) "
              "GPU 를 쓰세요. README 5장 참고.", file=sys.stderr)
        code = code or 2
    elif unfinished(answer):
        print("경고: 설계가 끝나지 않았습니다 (모델이 도구 호출 형식을 맞추지 못함). 같은 명령을 다시 실행하거나 "
              "더 큰 모델을 쓰세요. README 5장 참고.", file=sys.stderr)
        code = code or 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
