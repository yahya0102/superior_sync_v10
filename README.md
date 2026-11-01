# Superior Sync

Peer-to-peer file synchronisation (delta transfer, conflict handling, versions, trash) with a web UI.

```bash
pip install .
python -m superior_sync --add-folder ~/Documents --no-browser   # web UI at http://localhost:8080
python -m superior_sync --mode cli                               # interactive shell
```

For development and tests, install the test extra and validate the bundled UI:

```bash
python -m pip install -e ".[test]"
python tools/build_ui.py
python -m unittest discover -s tests -v
```

The GitHub Actions workflow installs the test extra, verifies the UI bundle, and runs the HTTP
and sync tests; missing `httpx` is therefore a CI setup failure rather than a silently skipped test.

The first start prints the initial admin password (also saved in `<data-dir>/security/initial_admin_password.txt`;
delete that file after you have changed the password). Use `--tls-cert/--tls-key` whenever the server is reachable
from other machines.

## Pairing a second device

```bash
# on device A: print the group key (it is never shown by the API)
python -m superior_sync --show-group-key
# on device B: start with the same key
python -m superior_sync --group-key <KEY> --add-folder ~/Documents
```

## Notes

* The browser opened at start-up carries a one-time local token (`/?lt=...`) that logs you in automatically.
  Opening `http://localhost:8080` by hand shows the normal login screen (use the admin account).
* If the master password (`--master-password` or `SS_MASTER_PASSWORD`) is wrong, start-up stops with an explicit
  message; the stored group key is never regenerated or overwritten.
* Both peers must use the same `enable_encryption` setting; unencrypted frames are rejected when encryption is on.
* Local files larger than 2 GiB are marked unsupported by the scanner and are not hashed or synced. Other peers
  running this version ignore those entries rather than interpreting them as deletions.
* To trust a reverse proxy's client address, add its IP/CIDR to the admin `POST /api/config` field
  `trusted_proxies` (for example `["127.0.0.1/32", "10.0.0.0/8"]`). Forwarded headers from any other source
  are ignored. Configure the proxy to overwrite or append a valid `X-Forwarded-For` chain.
* See `CHANGELOG_REVIEW.md` for the full list of fixes from the code review.
