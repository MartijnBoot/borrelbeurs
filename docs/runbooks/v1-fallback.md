# Runbook: fall back to v1

The decision: v2 cannot serve the bar and `rollback.md` did not help. Target: five minutes
from the decision to the bar taking orders on v1. v1 runs from its own saved image, never
rebuilt from `legacy/v1/` (SD17).

## Prerequisites (H5)

The folder `borrelbeurs-v1-fallback\`, on the USB stick and on the laptop, holding
`bierbeurs-image.tar` (v1 at `b617a56`), that commit's `run.bat`, `static/` and
`config/exchange_config.json`, a `config/keys.json` generated on the laptop (never committed,
never copied from the repository), and `SHA256SUMS`. Check it once:
`sha256sum -c SHA256SUMS`.

## Steps

1. Stop v2's app: double-click `stop.cmd` (Postgres and `backup` may keep running).
2. In `borrelbeurs-v1-fallback\`, double-click `run.bat`. It runs `docker load` on
   `bierbeurs-image.tar` when present and publishes port 8000.
3. Open `http://<fixed-ip>:8000/` on a phone (the same fixed IP, port 8000). Log in with a key
   from that folder's `config/keys.json`.
4. Tell the bar to use the new address.

## Verify

`http://<fixed-ip>:8000/healthz` answers 200, and a bar key logs in.

## What is lost

Live prices start over: v1 has no copy of v2's state. Revenue so far is in v2's database; take
a dump (`backup-now.cmd`) before anything else, and read the totals from the newest
`-auto.xlsx` in `data\exports\`. When the borrel is over, v2 starts again with `start.cmd`;
its data is untouched.
