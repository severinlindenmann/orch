# Crypto (one page)

Prototype rule: standard pieces only, no own crypto. AES-256-GCM everywhere; random from the OS.

## 1. Publish files: end to end

The server stores only ciphertext. The key never reaches the server.

- The CLI (`orch publish file`) encrypts: a new random 32-byte key and a random 12-byte IV per file. The browser decrypts.
- Blob format v1 (`OPF1`), exact byte slices:

```
blob[0:4]    = "OPF1"                        magic, ASCII
blob[4:16]   = IV, 12 bytes
blob[16:-16] = AES-256-GCM ciphertext
blob[-16:]   = GCM tag, 16 bytes (128 bit)
AAD          = the 4 bytes "OPF1"
plaintext    = u32 big-endian header length N | header JSON, N bytes UTF-8 | file bytes
header JSON  = {"name": "report.pdf", "type": "application/pdf", "size": 12345}
```

- WebCrypto, Python `AESGCM.decrypt(iv, blob[16:], aad)` and Rust `aes-gcm` all take ciphertext and tag joined (`blob[16:]`), as above.
- Reader rules: magic must be `OPF1`; blob at least 32 bytes; decrypt and check the tag **before** using any byte;
  then `1 <= N <= 65536`, header is valid UTF-8 JSON, and `size` equals the bytes left after the header. Any failure = "wrong key or broken file".
- The file name is inside the ciphertext, so the server and the admin see only id, size and expiry.
- Link: `https://publish.severin.io/f/<id>#k=<key as base64url, no padding, 43 chars>`. Browsers never send the `#` part to the server.
- The browser page fetches `/f/<id>/blob`, decrypts with WebCrypto (`importKey("raw")` + `decrypt({name: "AES-GCM", iv, additionalData, tagLength: 128})`), then offers the download.
- Cap: 100 MB = 100 × 1024 × 1024 bytes of **file content** (env `PUBLISH_MAX_FILE_MB`, default 100). The server accepts blobs up to cap + 64 KiB + 36 bytes (header + overhead). One-shot GCM in memory is fine at this size.
- Test vectors: `vectors/publish-blob-v1.json` (one good blob, plus `wrong key` and `truncated` cases that must fail). Python, Rust (tests only) and the browser JS must all pass them.
- Apps are **not** encrypted.
- Folder bundle (`orch publish file <folder>`, a small site of html + css + js + json): the OPF1 header has
  `"type": "application/vnd.orch.bundle"` and `"name": "<folder name>"`; the file bytes are a bundle:

```
bundle = u32 big-endian index length M | index JSON, M bytes UTF-8 | the files' bytes, one after another, in index order
index  = {"v": 1, "entry": "index.html", "files": [{"path": "index.html", "type": "text/html", "size": 120}, ...]}
```

  Reader rules (any failure = "broken file"): `1 <= M <= 1 MiB`; `v` is 1; 1 to 2000 files; each `path` is
  1 to 255 chars, `/`-separated, no leading `/`, no `\`, no NUL, no empty, `.` or `..` segment, unique; `size` is an
  integer >= 0; the sizes add up to exactly the bytes left after the index; `entry` is `index.html` and is in `files`.
  Writer: files sorted by path, compact JSON (`,` `:`), skips dot files and folders (`.env`, `.git`), `node_modules`,
  `__pycache__` and symlinks. The whole bundle counts against the same 100 MB cap.
  Vector: `vectors/publish-bundle-v1.json` (the bundle bytes, not encrypted; plus `must_fail` cases).

## 2. Relay: TLS + encrypted at rest + admin can read

Not end to end, on purpose: the admin must be able to read agent communication.

| Key | Where | Encrypts |
|---|---|---|
| TLS certificate | Caddy (Let's Encrypt) | everything on the wire |
| Master key, 32 random bytes | `/etc/orch-relay/master.key`, mode 0600, owner `orch-relay`; copy in the owner's password manager | every message `body`, every blob, every shared credential and MCP config, the Deepgram voice key (AAD `setting:deepgram`), in SQLite and on disk |

- One key, AES-256-GCM, a new random 12-byte nonce per item. Stored as `nonce | ciphertext+tag`.
  AAD = the item id (message id, blob id, credential name; `setting:deepgram` for the voice key), so items can't be swapped.
- Envelope fields (`id, from, to, type, created_at, ticket, reply_to`) stay plain so the relay can route.
- The relay decrypts when it delivers a message, and when the admin reads it in the portal.
- What it protects against: a leaked database file or backup. It does not protect against someone who has root on the VPS (they have the key too). That is accepted for the prototype.
- Lost master key = all stored messages are lost. No rotation in the prototype.

## 3. Tokens

| Token | Format | Made by | Stored on the server |
|---|---|---|---|
| publish workspace token | `orp_` + 32 random bytes base64url (43 chars) | publish admin | SHA-256 hash only |
| relay workspace / phone token | `orn_` + 43 chars | relay admin / pairing | SHA-256 hash only |
| app view token | `apv_` + 22 chars (16 bytes) | publish, per private app | SHA-256 hash only |
| webhook token | `whk_` + 22 chars | relay | SHA-256 hash only |
| allow token | `ora_` + 22 chars | the receiving workspace | not on the server; in both workspaces' `.orch/secrets/allows.json` |
| phone pairing code | `pc_` + 22 chars, 24 h, one use | relay admin | SHA-256 hash only |
| admin token | 43 chars | install script | file `/etc/orch-{publish,relay}/admin-token`, 0600 |

- Tokens are compared in constant time. A token shown once is never shown again; lost → the admin makes a new one.
- On the workspace, tokens live only in `.orch/secrets/` (gitignored, see local-files.md). On the phone, in the iOS Keychain.
- Tokens never go into tickets, messages (except `allow_token`), logs or URLs, except the public `?token=` of private apps and webhooks.
