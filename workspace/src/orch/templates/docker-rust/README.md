# {{name}}

A Rust app for orch publish (stack `docker`): the host builds the `Dockerfile` and runs the image. No crates needed.

- Listens on `$HOST:$PORT`, answers `GET /health` with `ok`.
- Writes only to `$DATA_DIR` (the root is read-only); with `store = "none"` it writes nothing.
- Use relative links in pages; `$BASE_PATH` only where an absolute path is unavoidable.
- `test` runs `/app/server --check` inside the built image (it must exit 0 before the switch).

Edit `src/main.rs`; add crates to `Cargo.toml` (keep the binary name `server`). Then: `orch publish app .`
