"""
title: Al Alloy Design
description: Inverse design of aluminium alloys. Finds measured examples and searches candidate compositions that meet strength, elongation, density and corrosion requirements with the local LLM.
version: 2.0.0
"""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path("__PROJECT_DIR__")


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    dotenv = PROJECT_DIR / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.startswith("#"):
                env[key.strip()] = value.strip()
    return env


def _python() -> str:
    venv = PROJECT_DIR / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return str(venv) if venv.exists() else sys.executable


async def _run(arguments: list[str], seconds: int) -> str:
    process = await asyncio.create_subprocess_exec(
        _python(), *arguments, cwd=PROJECT_DIR, env=_environment(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return "Tool error: the run exceeded its time limit. Do not guess results."
    output = stdout.decode("utf-8", errors="replace").strip()
    if process.returncode:
        return f"Tool error: exit code {process.returncode}\n{stderr.decode('utf-8', errors='replace')[-2000:]}\n{output}"
    return output


class Tools:
    async def alloy_examples(self, target_uts: float = 300, k: int = 8) -> str:
        """
        Look up measured 6xxx T6 extrusion alloys (strength, elongation, corrosion rules). Returns data only, no candidates.

        :param target_uts: UTS used to pick nearby examples, in MPa. Default 300; it is not the user's minimum strength.
        :param k: number of examples, 1 to 16.
        """
        if not 0 < target_uts < 1000 or not 1 <= k <= 16:
            return "Input error: target_uts must be between 0 and 1000 MPa and k between 1 and 16."
        spec = {
            "series": "6xxx",
            "temper": "T6",
            "route": "extrusion",
            "objectives": [{"property": "UTS", "direction": "maximize", "target": target_uts}],
            "constraints": {"EL_min": 10},
            "corrosion": True,
        }
        script = PROJECT_DIR / "src" / "skills" / "alloy-properties" / "scripts" / "examples.py"
        return await _run([str(script), "--spec", json.dumps(spec), "--k", str(k)], 300)

    async def design_alloy(self, requirements: str, __event_emitter__=None) -> str:
        """
        Run a real candidate search for the user's aluminium alloy requirements. The local LLM reads the alloy-properties skill, looks up measured examples, proposes and scores candidates, runs the final scoring and checks corrosion evidence in the knowledge graph. It can take several minutes.

        :param requirements: the user's full requirements: alloy series, environment, strength, elongation, density and corrosion. Do not invent numbers the user did not give.
        """
        if not requirements.strip() or len(requirements) > 12000:
            return "Input error: requirements must be a non-empty text of at most 12000 characters."
        if __event_emitter__ is not None:
            await __event_emitter__({"type": "status", "data": {"description": "Searching and scoring alloy candidates with the local model...", "done": False}})
        task = (
            "Answer in the language of the user's request. If the request evaluates strength together with other "
            "properties, read the alloy-properties skill first and follow it exactly. State every assumption for a "
            "missing condition. Always run score.py --final on the rounded candidates and use only that result in the "
            "candidate table. For corrosion requests run corrosion.py and report test conditions and sources. Never "
            "present the measured value of a neighbouring alloy as a prediction for a candidate. Do not hide failed "
            "runs or unevaluated conditions.\n\nUser requirements:\n" + requirements
        )
        host = PROJECT_DIR / "src" / "mcp" / "host" / "mcp_host.py"
        output = await _run([str(host), "--server", "kg", "--max-steps", "24", "--quiet", task], 3600)
        if __event_emitter__ is not None:
            await __event_emitter__({"type": "status", "data": {"description": "The search finished. Check the returned result.", "done": True}})
        return output
