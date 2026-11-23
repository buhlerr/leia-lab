#!/usr/bin/env bash
# Every check the repo has, in one command. DSR runs it from its registry:
#   required_checks: ["scripts/ci.sh"]
# Needs a disposable Postgres with pgvector in TEST_DATABASE_URL (or in .env); the name must end in _test,
# and java 11+ (on PATH or JAVA_HOME) for the TLA+ model of the analysis lifecycle.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --frozen --quiet
py() { uv run --frozen --no-sync python "$@"; }

TEST_DATABASE_URL="$(py -c '
from tests._db_guard import SuiteSettings, assert_safe_test_database
s = SuiteSettings()
assert_safe_test_database(s.TEST_DATABASE_URL, s.DATABASE_URL)
print(s.TEST_DATABASE_URL)
')"
export TEST_DATABASE_URL

failed=()
step() {
    local name="$1"
    shift
    echo "==> $name"
    if "$@"; then echo "ok  $name"; else echo "FAIL $name"; failed+=("$name"); fi
}

django_tests() { DATABASE_URL="$TEST_DATABASE_URL" DJANGO_DEBUG="false" py -m src.management.manage test src.management.domain --noinput; }

step pytest py -m pytest -q -p no:cacheprovider
step docs-caminhos py -m pytest -q tests/test_repo_hygiene.py::test_no_broken_cited_path_in_docs -p no:cacheprovider
step django django_tests
step analysis-lifecycle bash .claude/skills/verify-analysis-lifecycle/scripts/check.sh

if ((${#failed[@]})); then
    echo "ci.sh: failed: ${failed[*]}"
    exit 1
fi
echo "ci.sh: all checks passed"
