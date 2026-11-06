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
R="${REPO%.git}"
# A ref is a plain git ref name: in a zip URL a '../' or '#' could reach another repository or folder.
case "$REF" in
  *..*|-*|/*|*.lock|*/|"") echo "'$REF' is not a branch, tag or commit name (check ORCH_REF)." >&2; exit 1 ;;
esac
if printf '%s' "$REF" | grep -q '[^A-Za-z0-9._/-]'; then
  echo "'$REF' is not a branch, tag or commit name (check ORCH_REF)." >&2; exit 1
fi
if [ -d "$REPO" ]; then
  SPEC="$REPO/workspace"
else
  case "$R" in
    https://github.com/*) SPEC="$R/archive/$REF.zip#subdirectory=workspace" ;;  # a zip download: no git needed
    *) SPEC="git+$R@$REF#subdirectory=workspace" ;;
  esac
fi
uv tool install --reinstall --refresh "$SPEC"
BIN="$HOME/.local/bin"
# Put back the add-ons this machine had (the reinstall above drops them); nothing happens on a first install.
TOOL_BIN="$(uv tool dir --bin 2>/dev/null || echo "$BIN")"
"$TOOL_BIN/orch" update --after-install || echo "Note: your add-ons could not be installed again. Run: orch update"
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
