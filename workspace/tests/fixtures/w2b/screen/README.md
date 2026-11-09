# tmux control-mode captures (W2b)

Made with tmux 3.8 on macOS, own private server (`tmux -L w2b-fx-<random>`), session 120x40, `TERM=xterm-256color`,
`LANG=en_US.UTF-8`, status line off, shell `bash --norc --noprofile`, prompt `$ `.

- `control-mode.raw`: the output of a read-only control client, `tail -f /dev/null | tmux -u -L <srv> -C attach -r -t fx`
  (the pipe keeps stdin open). Raw tmux control-mode lines: `%output %0 <data>` (bytes below 0x20 and `\` are octal
  escapes like `\015`, `\033`; UTF-8 is raw), `%layout-change`, `%window-renamed`, `%begin/%end`. A read-only client cannot
  send keys, so a second, non-read-only control client (stdin from a fifo, output discarded) typed the keys and
  issued `resize-window`; it is not part of the file.
- What the stream contains, in order: ANSI colours (16, 256 and truecolor, bold, underline); output split over
  several `%output` chunks (`part1` / ` part2` / ` part3`); unicode (umlauts, emoji, a ZWJ emoji, box drawing, CJK);
  a 300-character line that wraps; `less` on a 200-line file: enters the alt screen (`\033[?1049h`), scrolls,
  is resized 120x40 -> 90x30 -> 120x40 (`%layout-change`), and leaves it (`\033[?1049l`); then `echo after-less`.
- `final-capture-pane.txt`: `tmux -L <srv> capture-pane -p -e -t fx` taken at the end (the visible 120x40 screen with
  SGR escapes; trailing blank lines are as tmux printed them).
- Scrubbed: the temp directory the home-based temp directory became `/tmp/fx`. The server was killed with
  `tmux -L <srv> kill-server`.
