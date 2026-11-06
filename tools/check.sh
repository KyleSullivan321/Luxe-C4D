#!/usr/bin/env bash
# Luxe checks: core unit tests, then compile and lint the Cinema 4D code. One exit code.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
FAIL=0
PY=""
for c in python3 python py; do  # Windows can have a broken Store python3 stub; verify it runs
    if command -v "$c" >/dev/null 2>&1 && "$c" -V >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
[ -n "$PY" ] || { echo "✗ no Python found"; exit 1; }

echo "── core tests"
"$PY" -m unittest discover -s core/tests || FAIL=1

echo "── compile C4D code"
"$PY" - <<'PY' || FAIL=1
import pathlib
for p in sorted(pathlib.Path("c4d").rglob("*")):
    if p.suffix in (".py", ".pyp"):
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
print("ok")
PY

echo "── lint"
if "$PY" -m pyflakes --version >/dev/null 2>&1; then
    tmp="$(mktemp -d)"; cp c4d/Luxe/Luxe.pyp "$tmp/Luxe_pyp.py"
    "$PY" -m pyflakes core c4d "$tmp/Luxe_pyp.py" && echo "ok" || FAIL=1
    rm -rf "$tmp"
else
    echo "pyflakes not installed: skipped (pip install pyflakes)"
fi

find . -name __pycache__ -prune -exec rm -rf {} +
[ "$FAIL" -eq 0 ] && echo "✓ all checks passed" || echo "✗ checks failed"
exit "$FAIL"
