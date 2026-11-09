# codex exec --json captures (W2b)

codex-cli 0.163.0. Each run: `codex exec --json -s read-only --skip-git-repo-check -C <tmpdir> "<task>" > <file>.jsonl`
in a fresh temp dir holding `notes.txt`, `readme.txt` and `sub/a.py`.

- `list-files.jsonl`: "List the files in this directory (recursively) and answer with the file names in one sentence."
- `failing-command.jsonl`: "Run the shell command 'cat does-not-exist.txt' and tell me in one sentence what happened."
  (command_execution with exit_code 1, status failed)
- `read-summarise.jsonl`: "Read readme.txt and summarise it in one sentence."

The two `error` items about `--dangerously-bypass-hook-trust` come from the local Codex setup and are kept as emitted.
Scrubbed: the `thread_id` values were replaced by `00000000-0000-0000-0000-00000000000N`. No home paths or account data occur.
