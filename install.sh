#!/bin/sh
# orch installer (macOS / Linux): installs uv if missing, then orch.
# ORCH_REPO / ORCH_REF override the source (default: GitHub main).
set -eu
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
fi
REPO="${ORCH_REPO:-https://github.com/severinlindenmann/orch}"
REF="${ORCH_REF:-main}"
if [ -d "$REPO" ]; then
  SPEC="$REPO/workspace"
else
  SPEC="git+${REPO%.git}@${REF}#subdirectory=workspace"
fi
uv tool install --reinstall "$SPEC"
uv tool update-shell >/dev/null 2>&1 || true
echo "orch is installed. Open a new terminal, go to your project folder and run: orch init"
