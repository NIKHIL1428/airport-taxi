#!/usr/bin/env bash
# Runs all backend (pytest) and frontend (vitest) tests. Run ./setup.sh once first.
cd "$(dirname "$0")"
echo "===== Backend tests (pytest) ====="
(cd backend && .venv/bin/python -m pytest -v); BACK=$?
echo; echo "===== Frontend tests (vitest) ====="
(cd frontend && npm test); FRONT=$?
echo
if [ $BACK -eq 0 ] && [ $FRONT -eq 0 ]; then echo "ALL TESTS PASSED"; else echo "SOME TESTS FAILED (backend=$BACK, frontend=$FRONT)"; exit 1; fi
