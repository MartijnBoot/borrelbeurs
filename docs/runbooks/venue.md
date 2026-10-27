# Runbook: the offline event at the venue

## Before: prepare the laptop

1. Windows laptop with Docker Desktop. In Docker Desktop, Settings, General, turn on **Use
   containerd for pulling and storing images** and Apply. `start.cmd` refuses to run without
   it (the classic store drops the pinned Postgres digest when loading `images.tar`).
2. Power plan: never sleep on AC. Closing the lid does nothing on AC (Power options, "When I
   close the lid", Plugged in: Do nothing). Keep it on the charger.
3. Copy the bundle from USB, for example to `C:\BorrelBeurs\bundle\`. Build it with
   `bash scripts/make_bundle.sh <sha>`; check it with `sha256sum -c SHA256SUMS` in that folder.
4. In the bundle folder: copy `.env.example` to `.env` (or let `start.cmd` do it). Set
   `BB_PUBLIC_URL` to the router address below. `JWT_SECRET` is generated on first start.
5. Run `start.cmd` once at home, with the internet off, and check the board loads.
6. Create keys and the run, with the bundle's own image. After step 5 the database is up and
   `.env` has its `JWT_SECRET`. Stop the app (`go-live` is refused while it runs):
   `docker compose -f compose.yml --env-file .env stop app`, then, for each command below,
   `docker compose -f compose.yml --env-file .env run --rm --no-deps app <command>`:
   - `python -m app.cli.keys create --role admin --label <who>` (roles `admin`, `bar`,
     `display`, `kassa`; the key, for example `K7M-4QX-9PR`, is shown once, write it down).
     The first start of a B-08 bundle revokes every older key, so after that update every key
     is minted again: your admin key here, then bar, display and kassa keys;
   - `python -m app.cli.import_v1 --config /seed/<name>` prints a `run_id` (the file must be
     mounted into the container with `-v <host path>:/seed/<name>:ro` before `app`);
   - `python -m app.cli.runs go-live <run_id>`.

   Then `start.cmd` again.

## Before: the router

1. A travel router with **no uplink** (no internet cable). Wi-Fi password set.
2. DHCP reservation: the laptop's MAC gets one fixed IP, `192.168.8.10` unless you chose
   another. Put that in `BB_PUBLIC_URL`.
3. Make a QR code of `http://192.168.8.10/` and print it. Check a phone joins and loads it.

## During

- Start: `start.cmd`. It prints the URL when ready.
- Check: `status.cmd` (all three up), `logs.cmd` (last 200 lines).
- Dumps run by themselves every 5 minutes; `backup-now.cmd` forces one. Excel exports of the
  live run appear in `data\exports\` every 15 minutes (`...-auto.xlsx`).
- "Sluit app" in admin stops the app for good (exit 0). Start it again with `start.cmd`.
- Wallets (B-05) at the venue are the venue database's own, not Render's: every player signs
  up again and starts at zero there. The venue is plain HTTP, so the kassa page offers no
  camera: type the short code under the player's QR code ("Code typen").
- Paying from a wallet at the bar (B-06): the bar page offers no camera here either; type the
  player's short code into "Code typen" and tap "Zoeken". A borrel imported with
  `app.cli.import_v1` starts with "Wallet verplicht" off, so the bar can still book without a
  wallet ("Afrekenen zonder wallet") while players top up at the kassa; turn it on in Globale
  instellingen once they have. A borrel made in admin starts with it on.
- Before rolling back past B-06 (an older image on this database): turn "Wallet verplicht"
  off first, and do not delete a wallet in debt until the newer image is back, since an older
  image neither checks the switch nor writes a debt off.
- Power cut: laptop on, Docker up, `start.cmd`. Everything acknowledged is there.

## After

1. Close the run in admin, download the final export.
2. Stop with `stop.cmd`.
3. Copy the whole `C:\BorrelBeurs\data\` to the USB stick (dumps and exports).
