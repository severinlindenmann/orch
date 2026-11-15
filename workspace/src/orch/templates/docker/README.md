# {{name}}

A docker app: the host builds the `Dockerfile` in this folder and runs the image. Any language works.

Rules for the app:
- Listen on `$HOST:$PORT` (the host sets both).
- Write only to `$DATA_DIR` (the root is read-only).
- Pages and links live under `$BASE_PATH`.
- Answer `GET /health` with 200.

To change the language, replace `main.py` and the `Dockerfile`, for example `FROM golang:1.23` with a build step,
or `FROM node:22-slim` with `CMD ["node", "server.js"]`. Keep `stack = "docker"` and `health` in `app.toml`;
`start` is optional and overrides the image CMD.
Change or remove `test` in `app.toml` too: it runs `python3` inside your image.
