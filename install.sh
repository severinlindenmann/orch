#!/bin/sh
# orch installer (macOS / Linux): installs uv if missing, then orch.
# ORCH_REPO / ORCH_REF override the source (default: GitHub main).
set -eu
ORIG_PATH="$PATH"
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
BIN="$HOME/.local/bin"
case "$(basename "${SHELL:-sh}")" in
  zsh)  RC="~/.zshrc";  LINE="export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  bash) RC="~/.bashrc"; LINE="export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  fish) RC="~/.config/fish/config.fish"; LINE="fish_add_path \$HOME/.local/bin" ;;
  *)    RC="your shell start file"; LINE="export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
echo "orch is installed."
case ":$ORIG_PATH:" in
  *":$BIN:"*) echo "Open a new terminal, go to your project folder and run: orch init" ;;
  *)
    echo "Add this line to $RC, then open a new terminal:"
    echo "  $LINE"
    echo "Then go to your project folder and run: orch init"
    ;;
esac
