#!/usr/bin/env bash
#
# Run every test in api/tests/. Exit 0 only if all pass.
#
#   ./scripts/run_tests.sh          # the gate: offline tests only
#   ./scripts/run_tests.sh -q       # same, only failures and the summary
#   ./scripts/run_tests.sh --all    # also run the ones needing live services
#
# Most tests are standalone scripts, not pytest cases: each sets up its own
# in-memory SQLite, exercises the real engine classes, and exits non-zero on a
# failed assertion. They need PYTHONPATH=api and the venv interpreter, which is
# the whole reason this wrapper exists — running them by hand gets that wrong.
#
# TWO of them need live services and are EXCLUDED from the default run:
#   test_api       -> HTTP against localhost:8000, fails whenever the app is down
#   test_database  -> connects to the real RDS instance
# They are integration checks, not unit tests. Gating commits on them would mean
# a red suite every time the engine is stopped — and a gate that fails for
# unrelated reasons gets bypassed, then ignored. Run them with --all when you
# actually want them.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

PY=./venv/bin/python
[ -x "$PY" ] || { echo "run_tests: $PY not found — is the venv built?"; exit 1; }

QUIET=0
ALL=0
for arg in "$@"; do
    case "$arg" in
        -q) QUIET=1 ;;
        --all) ALL=1 ;;
    esac
done

# Excluded from the gate — see the header.
NEEDS_LIVE_SERVICES="test_api test_database"

export PYTHONPATH=api

pass=0
fail=0
failed=()
out=$(mktemp)
trap 'rm -f "$out"' EXIT

# A file counts as a real test only if it can report a WRONG VALUE, i.e. it has
# an explicit non-zero exit or an assert. The rest (test_api, test_database,
# test_market_hours, test_position_contract_isolation) are diagnostic scripts
# that print observations and always exit 0 — they fail only if they crash.
# Labelling those PASS would inflate the green count and give false confidence,
# so they are reported separately and excluded from the pass total. See TODO E10.
smoke=0
skipped=0
smoke_names=()

for f in api/tests/test_*.py; do
    name=$(basename "$f" .py)
    if [ "$ALL" -eq 0 ] && [[ " $NEEDS_LIVE_SERVICES " == *" $name "* ]]; then
        skipped=$((skipped + 1))
        [ "$QUIET" -eq 1 ] || printf '  \033[90mSKIP\033[0m  %s  (needs live services; --all to run)\n' "$name"
        continue
    fi
    if grep -qE 'sys\.exit\([^)]*1|sys\.exit\(0 if|raise SystemExit|^[[:space:]]*assert |exit\(1\)' "$f"; then
        asserts=1
    else
        asserts=0
    fi
    if timeout 180 "$PY" "$f" >"$out" 2>&1; then
        if [ "$asserts" -eq 0 ]; then
            smoke=$((smoke + 1)); smoke_names+=("$name")
            [ "$QUIET" -eq 1 ] || printf '  \033[33mSMOKE\033[0m %s  (no assertions — fails only on a crash)\n' "$name"
            continue
        fi
        pass=$((pass + 1))
        [ "$QUIET" -eq 1 ] || printf '  \033[32mPASS\033[0m  %s\n' "$name"
    else
        fail=$((fail + 1))
        failed+=("$name")
        printf '  \033[31mFAIL\033[0m  %s\n' "$name"
        sed 's/^/        /' "$out" | tail -15
    fi
done

echo
smoke_note=""
[ "$smoke" -gt 0 ] && smoke_note=$(printf ', %d smoke (no assertions): %s' "$smoke" "${smoke_names[*]}")
[ "$skipped" -gt 0 ] && smoke_note="$smoke_note$(printf ', %d skipped (need live services)' "$skipped")"

if [ "$fail" -eq 0 ]; then
    printf '  \033[32m%d passed\033[0m%s\n' "$pass" "$smoke_note"
    exit 0
fi
printf '  \033[31m%d passed, %d FAILED:\033[0m %s\n' "$pass" "$fail" "${failed[*]}"
exit 1
