#!/bin/sh
# A demo orch workspace on this machine, connected to a relay, for trying workspace-to-workspace features.
# Guide: docs/demo-workspace-to-workspace.md
set -eu

usage() {
  cat <<'EOF'
Usage:
  scripts/demo-workspace.sh setup --prompt-file <file> | --relay <url> --workspace <id> (--token-file <file> | --token -) [--name Demo]
  scripts/demo-workspace.sh status    is the demo running, connected, what waits for a person
  scripts/demo-workspace.sh stop      stop only the demo's own services
  scripts/demo-workspace.sh remove [--yes]   stop it and delete the demo folders
Environment: DEMO_HOME (~/orch-demo/home), DEMO_DIR (~/orch-demo/work/demo), DEMO_PORT (first free 8780-8799),
ORCH_REF (main), ORCH_REPO, ORCH_INSTALL_KIND (normal).
DEMO_TEST_PROOF=1: test installs under ~/.orch-test only (orch refuses elsewhere): the e2e test human clicks instead of a person.
EOF
}

die() { echo "demo-workspace: $*" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
DEMO_HOME="${DEMO_HOME:-$HOME/orch-demo/home}"
DEMO_DIR="${DEMO_DIR:-$HOME/orch-demo/work/demo}"
PUBLIC_HOST="develop.netbird.cloud"
DESCRIPTION="Demo workspace: plans a team lunch, books tables, answers questions"

check_paths() {
  for v in "$DEMO_HOME" "$DEMO_DIR"; do
    case "$v" in /*) ;; *) die "DEMO_HOME and DEMO_DIR must be full paths (start with /)." ;; esac
    case "$v" in *..*) die "DEMO_HOME and DEMO_DIR must not contain '..'." ;; esac
  done
  h="${HOME%/}"; d="${DEMO_HOME%/}"; w="${DEMO_DIR%/}"
  [ -n "$d" ] && [ "$d" != "/" ] || die "DEMO_HOME is empty or /."
  [ -n "$w" ] && [ "$w" != "/" ] || die "DEMO_DIR is empty or /."
  [ "$d" != "$h" ] || die "DEMO_HOME must not be your own home folder ($HOME)."
  [ "$w" != "$h" ] || die "DEMO_DIR must not be your own home folder ($HOME)."
  case "$h" in "$d"/*) die "DEMO_HOME must not contain your home folder." ;; esac
  for v in "$d" "$w"; do
    case "$v" in
      "$h/.config/orch"|"$h/.config/orch"/*|"$h/.orch-tool"|"$h/.orch-tool"/*)
        die "$v is inside your own orch settings; pick another folder." ;;
    esac
  done
}

# Every orch call: a clean environment, the demo's HOME, nothing ORCH_*/XDG_* from the caller.
DEMO_PATH() { echo "$DEMO_HOME/.local/bin:$DEMO_HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"; }
# orch finds its own folder from the account, not $HOME: ORCH_HOME keeps every piece of orch state inside the demo
# HOME, and ORCH_HOME_STRICT makes orch refuse instead of falling back to the machine's own ~/.orch-tool.
denv() { env -i HOME="$DEMO_HOME" ORCH_HOME="$DEMO_HOME/.orch-tool" ORCH_HOME_STRICT=1 PATH="$(DEMO_PATH)" \
  LANG="${LANG:-en_US.UTF-8}" TERM=dumb "$@"; }
orch_demo() { (cd "$DEMO_DIR" && denv orch "$@"); }

STATE="$DEMO_HOME/.orch-demo"     # the script's own notes: ref, port, workspace id
installed() { [ -x "$DEMO_HOME/.local/bin/orch" ]; }

pick_port() {
  if [ -n "${DEMO_PORT:-}" ]; then
    case "$DEMO_PORT" in *[!0-9]*|'') die "DEMO_PORT must be a number." ;; esac
    echo "$DEMO_PORT"; return
  fi
  p=8780
  while [ "$p" -le 8799 ]; do
    if ! nc -z 127.0.0.1 "$p" >/dev/null 2>&1; then echo "$p"; return; fi
    p=$((p + 1))
  done
  die "No free port between 8780 and 8799 (set DEMO_PORT)."
}

print_where() {
  port="$(cat "$STATE/port" 2>/dev/null || true)"
  [ -n "$port" ] && echo "Dashboard: http://$PUBLIC_HOST:$port/   (on this machine: http://127.0.0.1:$port/)"
  if [ -f "$STATE/workspace" ]; then
    echo "Demo workspace id: $(cat "$STATE/workspace")  (in your directory it shows with the name the admin gave it, e.g. Demo)"
  fi
}

# ---- setup -------------------------------------------------------------------------------------------

cmd_setup() {
  PROMPT_FILE=""; RELAY=""; WS=""; TOKEN_FILE=""; NAME="Demo"
  while [ $# -gt 0 ]; do
    case "$1" in
      --prompt-file) PROMPT_FILE="${2:?}"; shift 2 ;;
      --relay) RELAY="${2:?}"; shift 2 ;;
      --workspace) WS="${2:?}"; shift 2 ;;
      --token-file) TOKEN_FILE="${2:?}"; shift 2 ;;
      --token)
        [ "${2:-}" = "-" ] || die "Give the token with --token - (read from stdin) or --token-file <file>, not on the command line."
        TOKEN_FILE="-"; shift 2 ;;
      --name) NAME="${2:?}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown option: $1 (see --help)" ;;
    esac
  done
  check_paths

  TOKEN=""
  if [ -n "$PROMPT_FILE" ]; then
    [ -r "$PROMPT_FILE" ] || die "Cannot read $PROMPT_FILE."
    line="$(grep -o 'orch relay connect [^`]*' "$PROMPT_FILE" | head -n 1 || true)"
    [ -n "$line" ] || die "No 'orch relay connect' line in $PROMPT_FILE. Copy the whole text from Add workspace."
    # shellcheck disable=SC2086
    set -- $line
    shift 3
    RELAY="${1:-}"
    [ $# -gt 0 ] && shift
    while [ $# -gt 1 ]; do
      case "$1" in
        --workspace) WS="$2"; shift 2 ;;
        --token) TOKEN="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
  elif [ "$TOKEN_FILE" = "-" ]; then
    IFS= read -r TOKEN || true
  elif [ -n "$TOKEN_FILE" ]; then
    [ -r "$TOKEN_FILE" ] || die "Cannot read $TOKEN_FILE."
    TOKEN="$(head -n 1 "$TOKEN_FILE" | tr -d '\r\n ')"
  fi
  [ -n "$RELAY" ] && [ -n "$WS" ] && [ -n "$TOKEN" ] || die "Need the relay address, workspace id and token (--prompt-file, or --relay/--workspace/--token-file)."
  case "$RELAY" in http://*|https://*) ;; *) die "The relay address must start with https:// or http://." ;; esac
  case "$WS" in ws_*) ;; *) die "The workspace id should start with ws_ (got '$WS')." ;; esac

  mkdir -p "$DEMO_HOME" "$STATE"
  chmod 700 "$DEMO_HOME" "$STATE"

  # 1. install orch into the demo HOME
  REF="${ORCH_REF:-main}"
  if installed && [ "$(cat "$STATE/ref" 2>/dev/null)" = "$REF" ]; then
    echo "orch is already installed in the demo ($REF)."
  else
    echo "Installing orch ($REF) into $DEMO_HOME ..."
    denv ORCH_REF="$REF" ORCH_INSTALL_KIND="${ORCH_INSTALL_KIND:-normal}" ${ORCH_REPO:+ORCH_REPO="$ORCH_REPO"} \
      sh "$REPO_ROOT/install.sh"
    installed || die "The install did not leave $DEMO_HOME/.local/bin/orch."
    echo "$REF" > "$STATE/ref"
  fi

  # 2. the demo folder
  mkdir -p "$DEMO_DIR"
  if [ ! -d "$DEMO_DIR/.git" ]; then
    (cd "$DEMO_DIR" && denv git init -q)
  fi
  if [ ! -f "$DEMO_DIR/README.md" ]; then
    printf '# %s\n\nA demo orch workspace for trying workspace-to-workspace messages, tasks, groups and files.\n' "$NAME" \
      > "$DEMO_DIR/README.md"
  fi
  home_check
  orch_demo init --yes >/dev/null
  if [ "${DEMO_TEST_PROOF:-}" = 1 ]; then
    # TEST installs under ~/.orch-test only: mark it for the e2e test human right after creating it (orch refuses later)
    orch_demo dev-mark >/dev/null 2>&1 || echo "Note: test marking refused (already marked, or not a test folder)."
  fi
  echo "Workspace folder ready: $DEMO_DIR"

  # 3. add-ons and services (the dashboard must run before connecting: connecting needs a person's click there)
  orch_demo addon add dashboard --yes >/dev/null
  orch_demo addon add relay --yes >/dev/null
  cmd_start
  port="$(cat "$STATE/port")"

  # 4. relay connection: a person's action (proof)
  if relay_connected; then
    echo "Already connected to the relay."
  else
    echo "Connecting to the relay ..."
    if [ "${DEMO_TEST_PROOF:-}" = 1 ]; then
      # TEST installs under ~/.orch-test only (orch refuses everywhere else): the e2e test human's proof.
      target="$(tool_py -c 'import sys; from orch import humanproof as h; print(h.server_address(sys.argv[1]))' "$RELAY")"
      tool_py -c 'import sys; from pathlib import Path; from orch import humanproof as h
print(h.mint_dev(Path(sys.argv[1]), "relay.connect", sys.argv[2]))' "$DEMO_DIR" "$target" \
        | orch_demo relay connect "$RELAY" --workspace "$WS" --token "$TOKEN" --proof-stdin >/dev/null \
        || die "Could not connect to the relay (test proof)."
    else
      # The CLI hands the connect to the dashboard; it opens the browser on THIS machine when it runs in a terminal.
      if command -v script >/dev/null 2>&1; then
        (cd "$DEMO_DIR" && denv script -q /dev/null orch relay connect "$RELAY" --workspace "$WS" --token "$TOKEN" >/dev/null 2>&1) || true
      else
        orch_demo relay connect "$RELAY" --workspace "$WS" --token "$TOKEN" >/dev/null 2>&1 || true
      fi
      echo "On this machine's screen, the demo dashboard (http://127.0.0.1:$port/) asks you to press Continue."
      echo "Waiting up to 10 minutes for that click ..."
      i=0
      until relay_connected; do
        i=$((i + 1)); [ $i -le 120 ] || die "Not connected after 10 minutes. Run setup again to retry."
        sleep 5
      done
    fi
  fi
  TOKEN=""
  echo "$WS" > "$STATE/workspace"
  orch_demo relay profile --description "$DESCRIPTION" --tags demo,lunch,booking >/dev/null \
    || echo "Note: the description could not be sent; try again later with: orch relay profile"
  orch_demo relay refresh >/dev/null || echo "Note: refresh failed (relay offline?)."

  # 5. seed tickets (only those not there yet)
  existing="$(orch_demo ticket list --json 2>/dev/null || true)"
  for title in "Team lunch 20 Nov: collect who joins" "Book a table for 8" "Answer questions about the lunch menu"; do
    if ! printf '%s' "$existing" | grep -qF "\"$title\""; then
      orch_demo ticket new "$title" >/dev/null
    fi
  done

  echo
  echo "The demo is ready."
  print_where
  echo "The admin must approve the demo's description on the relay page before others see it."
}

# Refuse unless orch itself resolves its folder inside the demo HOME (never the machine's own ~/.orch-tool).
home_check() {
  got="$(tool_py -c 'from orch import addons; print(addons.home())' 2>/dev/null || true)"
  want="$(cd "$DEMO_HOME" && pwd -P)/.orch-tool"
  [ -n "$got" ] && [ "$(cd "$(dirname "$got")" 2>/dev/null && pwd -P)/$(basename "$got")" = "$want" ] \
    || die "orch would keep its files in '${got:-?}', not in the demo ($want). Nothing was changed."
}

relay_connected() {  # connected to this relay as this workspace (orch relay status --json: configured, url, workspace)
  st="$(orch_demo relay status --json 2>/dev/null || true)"
  printf '%s' "$st" | grep -Eq '"configured": *true' && printf '%s' "$st" | grep -Fq "\"workspace\": \"$WS\"" \
    && printf '%s' "$st" | grep -Fq "\"url\": \"${RELAY%/}\""
}
tool_py() { (cd "$DEMO_DIR" && denv "$(denv uv tool dir)/orch-workspace/bin/python" -I "$@"); }

cmd_start() {
  # orch start would put the dashboard on 8420 (else any free port). The demo wants a known port in 8780-8799
  # and must never take 8420, so its dashboard is started first on that port; orch start then finds it running.
  port="$(cat "$STATE/port" 2>/dev/null || true)"
  if [ -z "$port" ]; then
    port="$(pick_port)"
  elif nc -z 127.0.0.1 "$port" >/dev/null 2>&1 && ! dash_ours "$port"; then
    port="$(pick_port)"  # someone else took the old port meanwhile
  fi
  tool_py -c 'import sys; from pathlib import Path
from orch_dashboard import service
service.start(Path(sys.argv[1]), int(sys.argv[2]))' "$DEMO_DIR" "$port" >/dev/null \
    || die "The dashboard did not start on port $port; see $DEMO_DIR/.orch/run/dashboard/server.log"
  echo "$port" > "$STATE/port"
  orch_demo start --no-open >/dev/null || echo "Note: orch start reported a problem; see: scripts/demo-workspace.sh status"
}

dash_ours() {  # is the dashboard on this port the demo's own?
  (cd "$DEMO_DIR" 2>/dev/null && denv orch dashboard status --json 2>/dev/null) | grep -Eq "\"running\": *true.*\"url\": *\"http://127\\.0\\.0\\.1:$1\""
}

# ---- status / stop / remove --------------------------------------------------------------------------

cmd_status() {
  check_paths
  if ! installed || [ ! -d "$DEMO_DIR/.orch" ]; then
    echo "No demo workspace set up (run: scripts/demo-workspace.sh setup ...)."; exit 1
  fi
  home_check
  if dash_ours "$(cat "$STATE/port" 2>/dev/null || echo 0)"; then echo "Dashboard: running"; else echo "Dashboard: not running"; fi
  print_where
  echo; echo "Services:"; orch_demo status || true
  echo; echo "Relay:"; orch_demo relay status || true
  echo; echo "Waiting for a person (allows, questions):"; orch_demo needs || true
}

cmd_stop() {
  check_paths
  if installed && [ -d "$DEMO_DIR/.orch" ]; then
    home_check
    orch_demo stop >/dev/null 2>&1 || true
    echo "Demo services stopped (dashboard included)."
  fi
}

cmd_remove() {
  YES=""
  [ "${1:-}" = "--yes" ] && YES=1
  check_paths
  cmd_stop
  echo "This deletes:"
  echo "  $DEMO_HOME"
  echo "  $DEMO_DIR"
  if [ -z "$YES" ]; then
    printf 'Type yes to delete them: '
    read -r ans || ans=""
    [ "$ans" = "yes" ] || die "Nothing deleted."
  fi
  # No relay disconnect command exists; the admin removes the workspace on the relay page.
  [ -e "$DEMO_HOME" ] && rm -rf -- "$DEMO_HOME"
  [ -e "$DEMO_DIR" ] && rm -rf -- "$DEMO_DIR"
  echo "Deleted. Ask the admin to remove the Demo workspace on the relay page."
}

case "${1:-}" in
  setup) shift; cmd_setup "$@" ;;
  status) cmd_status ;;
  stop) cmd_stop ;;
  remove) shift; cmd_remove "$@" ;;
  -h|--help|help) usage ;;
  *) usage >&2; exit 1 ;;
esac
