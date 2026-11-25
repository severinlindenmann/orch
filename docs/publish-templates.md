# Publish: host it yourself, and start a Rust app (ORCH-1487, scoping)

Wish: "for publish, a framework so a user can host, plus easy templates to publish Rust apps."
Rules: R1.1, R4.2, R5.1, R9.4. Nothing here adds a noun, a stack, a setting or an endpoint.

## What already covers it

- **Host it yourself.** The publish server is one Rust binary plus `publish/deploy/install.sh` (user, folders, admin token,
  service) and `publish/deploy/publish.caddy`. See `docs/publish.md` (Deploy) and `relay/deploy/MOVE.md`. Servers run on Linux only (R1.6).
- **Any language.** The stack `docker` (`contracts/app.toml.md`) builds the `Dockerfile` in the app folder and runs the
  image in the sandbox: own network, read-only root, 128 MB, user 61000, listens on `$HOST:$PORT`, writes to `$DATA_DIR`.
  A Rust app needs no new stack.

## First slice (shipped)

`orch publish new docker --lang rust <folder> [--store none|json]` copies `workspace/src/orch/templates/docker-rust/`:
`app.toml` (stack `docker`), a two-step `Dockerfile` (`rust:1-slim` builds, `debian:bookworm-slim` runs), `Cargo.toml`
without crates (builds offline), `src/main.rs` (`/health`, a start page, a visit counter in `$DATA_DIR`), a short README.
`test = "/app/server --check"` runs inside the built image before the switch. Then `orch publish app <folder>` as for any app.
`--lang` is a template choice, not a new object: it only picks which folder is copied. It is refused for other stacks.

Tests: `workspace/tests/test_templates.py` (valid manifest, no leftover placeholders, the bundle contains Dockerfile,
Cargo.toml and src/main.rs, refusals, the CLI).
Not tested in CI: a real `cargo build` (no Rust or container engine in the light job); the e2e on the server builds it.

## Left out on purpose

- A `rust` stack in `app.toml` (contract change, new word for users).
- A web framework in the template (axum and friends): crates need network in the build step, and the choice is the user's.
- A "hosting framework" beyond the install script: a managed multi-tenant offer would be a new object.

## Question for the owner (on the ticket)

Is a per-language template flag (`--lang`) fine as the way to add more starters (Go, Deno), or should each language
become a stack in `app.toml`? Recommended: keep `--lang` on the `docker` stack; no contract change.
