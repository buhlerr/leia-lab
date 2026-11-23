#!/usr/bin/env bash
# Model-checks the lifecycle of an `analyses` row (model/AnalysisLifecycle.tla) with TLC.
#   check.sh            the fixed design passes and every broken variant fails on its own property
#   check.sh <config>   full TLC output for one config in model/, e.g. `current` (the PR #31 bug)
# Needs java 11+ on PATH (or JAVA_HOME). Downloads tla2tools.jar once, pinned and sha256-checked.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
TLA_VERSION="1.7.4"
TLA_SHA256="936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
jar="${XDG_CACHE_HOME:-$HOME/.cache}/leia-lab/tla2tools-$TLA_VERSION.jar"

java_bin="java"
if [[ -n "${JAVA_HOME:-}" ]]; then java_bin="$JAVA_HOME/bin/java"; fi
if ! command -v "$java_bin" >/dev/null 2>&1; then
    echo "check.sh: java not found. Install JDK 21 (Temurin: https://adoptium.net/temurin/releases/?version=21)" \
        "and put its bin/ on PATH, or set JAVA_HOME." >&2
    exit 2
fi

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

if [[ ! -f "$jar" || "$(sha256_of "$jar")" != "$TLA_SHA256" ]]; then
    mkdir -p "$(dirname "$jar")"
    curl -fsSL -A "leia-lab-verify-analysis-lifecycle" -o "$jar.part" \
        "https://github.com/tlaplus/tlaplus/releases/download/v$TLA_VERSION/tla2tools.jar"
    got="$(sha256_of "$jar.part")"
    if [[ "$got" != "$TLA_SHA256" ]]; then
        echo "check.sh: tla2tools.jar sha256 is $got, expected $TLA_SHA256; not using it ($jar.part)." >&2
        exit 2
    fi
    mv "$jar.part" "$jar"
fi

meta="$(mktemp -d)"
trap 'rm -rf "$meta"' EXIT
tlc() {
    (cd "$here/model" && "$java_bin" -XX:+UseParallelGC -cp "$jar" tlc2.TLC -nowarning -workers 1 \
        -metadir "$meta/$1" -config "$1.cfg" AnalysisLifecycle.tla)
}

if (($#)); then
    tlc "$1"
    exit
fi

# config:expected. "pass", or the property TLC must report as violated.
checks=(
    "fixed:pass"
    "current:NoRunEndsRunning"
    "current_terminal:TerminalNeverChanges"
    "fixed_catches_exception_only:NoRunEndsRunning"
    "fixed_split_iniciar:TrailStartsWithIniciar"
    "fixed_unguarded_failure:TerminalNeverChanges"
    "fixed_no_defer:NoRunEndsRunning"
    "fixed_no_unique_key:OneRowPerKey"
    "fixed_conflict_not_raised:NoWorkWithoutRow"
)
bad=0
for c in "${checks[@]}"; do
    cfg="${c%%:*}" want="${c#*:}"
    if out="$(tlc "$cfg" 2>&1)"; then got="pass"; else
        got="$(grep -oE '(Invariant|Action property) [A-Za-z]+ is violated' <<<"$out" | head -1 | awk '{print $(NF-2)}')"
        got="${got:-error}"
    fi
    if [[ "$got" == "$want" ]]; then
        echo "ok   $cfg: $want"
    else
        echo "FAIL $cfg: expected $want, got $got (run: $0 $cfg)"
        bad=1
    fi
done
exit "$bad"
