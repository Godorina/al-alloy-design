# Al Alloy Design

Inverse design of aluminium alloys with a **local LLM** and **Open WebUI**. Describe the requirements in a chat
("T6 extrusion, UTS at least 350 MPa, good corrosion resistance, density below 2.72"). The model reads measured
alloys, proposes candidate compositions, and the scripts score them (ICL + CatBoost strength, elongation,
density, corrosion rules) and attach corrosion evidence from a knowledge graph.

한 줄 요약: 내 컴퓨터 사양에 맞는 로컬 LLM을 `llmfit`으로 골라 받고, Open WebUI 채팅에서 알루미늄 합금 역설계를 실행합니다.

## Quick start

Needs macOS or Linux, [uv](https://docs.astral.sh/uv/), and enough free memory for a model (4 GB and up).

```bash
git clone https://github.com/Godorina/al-alloy-design.git
cd al-alloy-design
./setup.sh           # Python env, llmfit ranking, model download, model server, quality check
./webui.sh           # Open WebUI at http://127.0.0.1:3000 (second terminal; create the admin account)
.venv/bin/python openwebui/install.py --email YOU@EXAMPLE.COM --password '...'   # or --api-key KEY
```

Open WebUI, choose the model preset **Al Alloy Design**, and ask for an alloy.

## How the model is chosen

1. `llm/pick.py` runs [llmfit](https://github.com/AlexsJones/llmfit) (installed on request) to read your CPU, RAM and GPU.
2. It keeps only llama.cpp (GGUF) models with tool use and a 48K context that fit well, drops reasoning, coder,
   vision and fine-tuned variants, lists official model makers first, and downloads the one you pick.
3. `llm/serve.py start` runs it with `llama-server` (install llama.cpp: `brew install llama.cpp`) and writes
   `LLM_BASE_URL`, `LLM_MODEL`, `LLM_SLOTS`, `LLM_CTX_PER_SLOT` to `.env` (2 slots of 48K context each, q8 KV cache).
4. `llm/selfcheck.py` tests tool calling and predicts the UTS of measured 6xxx alloys the prompt does not contain.
   **FAIL** if the answers are not valid JSON or tools do not work, **WARN** if the model is worse than a
   nearest-neighbour baseline. The original development model (Qwen3.8-27B) reached a UTS MAE of about 23 MPa.
5. `llm/selfcheck.py --agent` (5 to 10 minutes) also runs a full design through the agent loop and FAILs unless it
   runs a successful `score.py --final` and returns a final answer.

Tested on one machine (Apple Silicon, 48 GB): both models passed the strength check (UTS MAE 20.9 MPa for
Qwen3-4B-Instruct, 19.3 to 19.4 MPa for Qwen3-30B-A3B-Instruct Q4_K_M, 10 queries), but the full design run
finished in 0 of 2 tries with the 4B and in 1 of 3 tries with the 30B (the other runs ended when one model reply
ran away and was cut off).
Prefer the largest model that fits (`python llm/pick.py --quant Q4_K_M` downloads a smaller quantization) and expect
to retry. Candidates from the 30B run missed the target for several requirements and its written rationale did not
always match the final composition, so read the scored table, not the prose.

Another OpenAI-compatible server (Ollama, LM Studio, vLLM) works too: set `LLM_BASE_URL` (no `/v1`) and
`LLM_MODEL` in `.env` (see `.env.example`), then run `openwebui/install.py`.

## What it can and cannot do

- Strength (UTS/YTS) and elongation are **predictions** from measured examples; each one carries support flags.
- Corrosion is **not predicted** for a new candidate. The result shows measured or nominal values of the nearest
  alloys with test conditions and sources.
- Series covered: 2xxx, 5xxx, 6xxx, 7xxx, Al-Li, cast Al-Si; 6xxx has the most data.
- Quality depends on the model. Always run `llm/selfcheck.py` after changing it.

## Layout

```
setup.sh, webui.sh        one-step setup, Open WebUI launcher
llm/                      pick.py (llmfit + download), serve.py (llama-server), selfcheck.py (quality gate)
openwebui/                al_alloy_design_tool.py (the tool), install.py (registers tool + preset)
src/mcp/host/             agent loop: model <-> skills <-> KG tools (OpenAI-compatible API)
src/mcp/servers/kg/       MCP server over the knowledge graphs
src/skills/               alloy-properties (multi-property design), alloy-strength (ICL engine, ML models)
data/alloy-properties/    strength tables (v1, v2, literature rows), JSM and Tamura 2020 data
ontology/al_alloy/        al6xxx and alml knowledge graphs (schema, shapes, competency queries, build/kg.ttl)
scripts/strip_quotes.py   removes verbatim paper quotes from a knowledge graph before it is published
```

Run the design loop without the web UI (after `serve.py start`):

```bash
set -a; . ./.env; set +a
.venv/bin/python src/mcp/host/mcp_host.py --server kg "6xxx T6 extrusion, UTS >= 330 MPa, corrosion resistant"
```

## Data and licenses

- Code: MIT (`LICENSE`).
- `data/alloy-properties/strength_unified` merges published strength datasets (Mendeley, Ji, Hu, Mo et al. and
  others, column `source`); `open_data/tamura_2020` is the supplementary data of Tamura et al. 2020
  (doi 10.1080/14686996.2020.1791676); `vehicle_al_mobo` is the JSM corrosion table. Check each source's terms
  before reusing the data outside this project.
- The knowledge graphs hold values extracted from papers with DOI and page. The verbatim quotes were removed
  (`scripts/strip_quotes.py`); open the DOI to read the source.
- Model weights are downloaded from Hugging Face under each model's own license; llmfit shows it in the list.
