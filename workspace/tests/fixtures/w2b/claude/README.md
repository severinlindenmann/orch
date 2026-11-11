# claude -p --output-format stream-json captures (W2b 1.8)

- `read-and-fail.jsonl`: REAL capture (claude code, model haiku, 11 Nov 2026), run as
  `claude -p --output-format stream-json --verbose --model haiku --allowedTools "Bash,Read" -- "Read notes.txt, then run the
  shell command 'cat does-not-exist.txt', then say in one sentence what happened."` in a temp dir holding `notes.txt`.
  Contains a Read step, a failing Bash step (`is_error: true`), a rate_limit_event, thinking/hook `system` lines (unknown to
  the mapper) and the final `result` line. Scrubbed: paths -> `/work/proj`, session and message uuids replaced, thinking
  signatures, tool/slash-command/agent/mcp lists and hook outputs emptied (only a single hook pair kept).
- `helper-denial.jsonl`: SYNTHETIC, same line shapes: a `Task` helper with a child step (`parent_tool_use_id`), an MCP call, a
  Skill call, a result with `permission_denials` and `is_error: true`. Built by hand from the Focus adapter fixture
  (`workspace-addons/focus/tests/fixtures/claude-run.jsonl`) and the real shape above.
