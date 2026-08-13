#!/usr/bin/env bash
# PantryOS installer — see GETTING-STARTED.md for the full walkthrough.
#   git clone https://github.com/tjermann/PantryOS.git && cd PantryOS && ./install.sh
set -euo pipefail
cd "$(dirname "$0")/service"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m%s\033[0m\n' "$*"; }

say "PantryOS installer"

# 1. Python 3.11+ ------------------------------------------------------------
PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  fail "PantryOS needs Python 3.11 or newer, and I couldn't find it."
  case "$(uname -s)" in
    Darwin) echo "On a Mac: download the latest installer from https://www.python.org/downloads/" ;;
    *)      echo "On Ubuntu/Debian, run:"
            echo "    sudo apt update && sudo apt install python3 python3-venv" ;;
  esac
  exit 1
fi
say "Using $($PY --version)"

# 2. Private environment (never touches your system Python) -------------------
if [ ! -x .venv/bin/python ]; then
  say "Creating a private Python environment..."
  if ! "$PY" -m venv .venv 2>/dev/null; then
    fail "Your Python is missing the 'venv' piece."
    echo "On Ubuntu/Debian, run:  sudo apt install ${PY}-venv"
    echo "Then run ./install.sh again."
    exit 1
  fi
fi

say "Installing PantryOS..."
.venv/bin/pip -q install --upgrade pip
.venv/bin/pip -q install -e .

say "Downloading the browser used to fill grocery carts (~120 MB, one time)..."
if ! .venv/bin/playwright install chromium >/dev/null 2>&1; then
  echo "(Browser download failed — that's OK. Everything works except"
  echo " automatic cart filling; you'll get grocery lists by email.)"
fi

say "Installed."

# 3. Straight into setup ------------------------------------------------------
cat <<'EOF'

Next: a few questions about your household — who eats, any allergies, how many
dinners a week, which store, and where to email the plan. Everything can be
changed later, and nothing leaves this computer.

You'll need a Gmail address and a Google "app password" (GETTING-STARTED.md,
step 3 walks through making one — it takes about two minutes).

EOF
read -r -p "Run the setup questions now? [Y/n]: " answer
case "${answer:-Y}" in
  [Nn]*)
    echo
    echo "No problem. When you're ready:"
    echo "    service/.venv/bin/mealplanner setup"
    exit 0
    ;;
esac

.venv/bin/python -m mealplanner setup

# 4. Offer to schedule --------------------------------------------------------
cat <<'EOF'

One more thing: PantryOS can run itself on a schedule — recipes on Thursday,
a proposed menu Friday, your groceries Saturday, dinner reminders daily.

EOF
read -r -p "Turn on the automatic schedule? [Y/n]: " sched
case "${sched:-Y}" in
  [Nn]*) echo "Later, run:  service/.venv/bin/mealplanner install-cron" ;;
  *)     .venv/bin/python -m mealplanner install-cron ;;
esac

cat <<'EOF'

Done. Useful commands from here (run them from the PantryOS folder):

  service/.venv/bin/mealplanner doctor            check everything is healthy
  service/.venv/bin/mealplanner discover-recipes --user NAME --total 40
                                                  fill your recipe library
  service/.venv/bin/mealplanner login --user NAME --store STORE
                                                  sign in to your grocery store
  service/.venv/bin/mealplanner serve             start the family web page

Full walkthrough: GETTING-STARTED.md
EOF
