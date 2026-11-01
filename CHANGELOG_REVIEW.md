# Code review changelog

The original review had to rely on compilation and static checks for some FastAPI paths. The current
CI workflow installs `.[test]`, runs HTTP-level tests, and includes a real two-node localhost sync.
Run `python tools/build_ui.py --check` and `python -m unittest discover -s tests -v` to reproduce it.

## Follow-up hardening and maintainability

* Mutating cookie-authenticated HTTP requests reject a mismatched `Origin`; bearer and P2P flows keep
  their existing authentication behavior.
* `trusted_proxies` accepts validated IP/CIDR networks. Client IP and local-token trust use forwarded
  headers only for configured proxy peers; unconfigured peers remain fail-closed.
* Cloud operations invoked by async routes run in worker threads. SSE events now use the hub's single
  broadcast path, and webhook delivery uses a module-level worker.
* Files above 2 GiB are explicitly marked unsupported, skipped by scan/signature, and ignored during
  peer reconciliation so they cannot trigger a propagated deletion or stale-hash overwrite.
* `integrations.py` is now the `integrations/` package with a compatibility export surface. UI sources
  live under `superior_sync/ui_src/` and are bundled into the packaged self-contained HTML by
  `tools/build_ui.py`.
* Configuration updates no longer rewrite `config.json` when persisted values are unchanged. Session
  cleanup is stopped during application shutdown, and the workspace no longer auto-approves the test
  command.

## Critical (feature was broken)
| File | Problem | Fix |
|---|---|---|
| `routers/p2p.py` | Server verified the HMAC without the nonce the client signs with → every `/p2p/*` request got 401 | Include `X-SS-Nonce` in verification; reject replays |
| `routers/p2p.py` | `/inbox` required multipart; client sends a raw body → always 422 | Stream the raw body, size cap, temp-file cleanup, PathError → 400 |
| `integrations.py` | Pinned HTTPS connection verified the certificate against the IP → every HTTPS call failed | Connect to the pinned IP, verify + SNI on the real hostname |
| `ui.py` | `if` block placed inside an object literal → JS syntax error, UI dead | Moved after the object |
| `config.py` | Wrong master password regenerated and overwrote the group key | `GroupKeyError`, file untouched |

## Data safety
* Cloud backup recorded failed uploads as done and never retried → state kept, retry in 15 min, `failed_files` / `last_error` recorded.
* `restore_version` could delete the version being restored (prune) → copy first.
* Engine temp files (`name.sync-tmp-<id>`, `*.restore-*`, `.p2p_tmp`) were indexed and advertised to peers → added to ignore patterns.
* `index_path` used unescaped, case-insensitive `LIKE` → exact range queries (`_prefix_range`).
* An unreadable directory during a scan marked everything under it as deleted → such paths are excluded from deletion detection.
* Upload with `overwrite` destroyed the old content → a version is saved first.

## Security
* `GET /` embedded the local admin token for any visitor (reverse proxy without `X-Forwarded-*`, SSH tunnel, other local users) → token only when the caller supplies it (`/?lt=`), from direct loopback.
* Plaintext frames were accepted while encryption was enabled; zlib bomb (299 KB → 300 MB) → rejected / capped at 128 MB.
* `add_sync_folder` allowed `/etc` or a folder containing `data_dir` → `validate_sync_folder`.
* Signature is verified before the body is read (no unauthenticated large-body memory use); per-path body limits.
* Last-admin deletion guard moved inside the lock; constant-time compare no longer raises on non-ASCII.
* Cloud listing now needs the `share` permission; replay window (300 s) now exceeds the timestamp window.

## Usability / correctness
* `--show-group-key` (there was no way to read the key to pair a device).
* `receive_folder` schema rejected every absolute path; `/register` accepted 1-char passwords at schema level.
* `/root` (when it is `$HOME`) and `/var/<x>` receive folders are allowed (Docker / NAS).
* `config.update()` is atomic (rolls back on validation failure).
* Polling watcher detected only new files in the root directory.

## Performance
* KDF results cached (signing: 120 ms → <1 ms).
* `manifest()` and ZIP creation run off the event loop; ZIP now includes folders.
* `PRAGMA quick_check` instead of `integrity_check` every minute.
* Delta stops byte-wise rolling after 4 MB without a match (output stays byte-exact).

## Known limitations (not changed)
* Share ids are positional: removing the first folder named `X` renames the second `X-2`.
* P2P JSON calls (`call_json`) are not frame-encrypted and responses are not signed; use TLS on untrusted networks.
* Empty directories are not synced.
