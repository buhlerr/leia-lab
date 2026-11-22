#!/usr/bin/env bash
# Every check the repo has, in one command. DSR runs it from its registry:
#   required_checks: ["scripts/ci.sh"]
# Needs a disposable Postgres with pgvector in TEST_DATABASE_URL (or in .env); the name must end in _test.
set -euo pipefail
cd "$(dirname "$0")/.."

export OPENROUTER_API_KEY="" TYPESAFE_API_KEY="" LEIA_API_TOKEN="" MLFLOW_TRACKING_URI="" \
    LANGSMITH_API_KEY="" LANGSMITH_TRACING="false" LANGCHAIN_TRACING_V2="false"

uv sync --frozen --quiet
py() { uv run --frozen --no-sync python "$@"; }

TEST_DATABASE_URL="$(py -c 'from tests._db_guard import SuiteSettings; print(SuiteSettings().TEST_DATABASE_URL)')"
export TEST_DATABASE_URL

failed=()
step() {
    local name="$1"
    shift
    echo "==> $name"
    if "$@"; then echo "ok  $name"; else echo "FAIL $name"; failed+=("$name"); fi
}

step pytest py -m pytest -q -p no:cacheprovider
step django env DATABASE_URL="$TEST_DATABASE_URL" DJANGO_DEBUG="false" \
    uv run --frozen --no-sync python -m src.management.manage test src.management.domain --noinput

if ((${#failed[@]})); then
    echo "ci.sh: failed: ${failed[*]}"
    exit 1
fi
echo "ci.sh: all checks passed"
