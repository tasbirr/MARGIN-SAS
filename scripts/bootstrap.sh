#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_CMD=""
RUN_AFTER_SETUP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_CMD="$2"
      shift 2
      ;;
    --run)
      RUN_AFTER_SETUP=1
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -n "$PYTHON_CMD" ]]; then
  if ! command -v "$PYTHON_CMD" >/dev/null 2>&1 && [[ ! -x "$PYTHON_CMD" ]]; then
    echo "Python binary not found: $PYTHON_CMD"
    exit 1
  fi
  version="$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
  if [[ "$version" != "3.10" && "$version" != "3.11" && "$version" != "3.12" && "$version" != "3.13" ]]; then
    echo "Python 3.10-3.13 is required. Install Python 3.13 and retry."
    exit 1
  fi
else
  for candidate in python3.11 python3.12 python3.13 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      version="$($candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
      if [[ "$version" == "3.10" || "$version" == "3.11" || "$version" == "3.12" || "$version" == "3.13" ]]; then
        PYTHON_CMD="$candidate"
        break
      fi
    fi
  done
fi

if [[ -z "$PYTHON_CMD" ]]; then
  echo "Python 3.10-3.13 is required. Install Python 3.13 and retry, or pass --python /path/to/python3.13."
  exit 1
fi

VENV_PY="$ROOT_DIR/.venv/bin/python"
RECREATE_VENV=0

if [[ -x "$VENV_PY" ]]; then
  venv_version="$($VENV_PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
  if [[ "$venv_version" != "3.10" && "$venv_version" != "3.11" && "$venv_version" != "3.12" && "$venv_version" != "3.13" ]]; then
    RECREATE_VENV=1
  fi
fi

if [[ ! -d ".venv" || "$RECREATE_VENV" == "1" ]]; then
  if [[ "$RECREATE_VENV" == "1" ]]; then
    rm -rf .venv
  fi
  "$PYTHON_CMD" -m venv .venv
fi

"$ROOT_DIR/.venv/bin/python" -m pip install -r requirements.txt
"$ROOT_DIR/.venv/bin/python" scripts/doctor.py

if [[ "$RUN_AFTER_SETUP" == "1" ]]; then
  "$ROOT_DIR/.venv/bin/python" run_server.py
fi
