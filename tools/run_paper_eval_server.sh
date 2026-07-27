#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${BENCHMARK_PYTHON:-$ROOT/.venv/bin/python}"
EXPERIMENT="${EXPERIMENT:-$ROOT/configs/benchmark.yaml}"
MODELS="${MODELS:-$ROOT/configs/models.example.yaml}"
STAGES="${STAGES:-validate,run,collect,score,judge,report}"

cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export NANOBOT_LLM_TIMEOUT_S="${NANOBOT_LLM_TIMEOUT_S:-600}"

if [[ ! -x "$PY" ]]; then
  echo "[fatal] Python not executable: $PY" >&2
  exit 2
fi

"$PY" -B -m benchmark_eval.cli pipeline \
  --experiment "$EXPERIMENT" \
  --models-config "$MODELS" \
  --stages "$STAGES" \
  "$@"
