#!/usr/bin/env bash
# PantryOS one-command installer.
#   git clone https://github.com/tjermann/PantryOS.git && cd PantryOS && ./install.sh
set -euo pipefail
cd "$(dirname "$0")/service"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "PantryOS installer"

# 1. Find a modern Python.
PY=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      PY="$candidate"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "PantryOS needs Python 3.11 or newer. On Ubuntu/Debian:"
  echo "    sudo apt install python3.12 python3.12-venv"
  exit 1
fi
say "Using $($PY --version)"

# 2. Private virtual environment (never touches your system Python).
if [ ! -x .venv/bin/python ]; then
  say "Creating a private Python environment..."
  "$PY" -m venv .venv 2>/dev/null || {
    echo "Your system is missing the venv module. On Ubuntu/Debian:"
    echo "    sudo apt install ${PY}-venv"
    exit 1
  }
fi

say "Installing PantryOS (into its own environment only)..."
.venv/bin/pip -q install --upgrade pip
.venv/bin/pip -q install -e .

say "Downloading the browser used for cart loading (~120 MB, one time)..."
.venv/bin/playwright install chromium >/dev/null

say "Installed."
echo
echo "Next: answer the setup questionnaire (your household, stores, email)."
read -r -p "Run it now? [Y/n]: " answer
case "${answer:-Y}" in
  [Yy]*|"") exec .venv/bin/python -m mealplanner setup ;;
  *) echo "Later, run:  service/.venv/bin/mealplanner setup" ;;
esac
