# notiOne — Home Assistant custom integration

Reads live GPS position from [notiOne](https://notione.com/) locators (the same
unofficial API the official web panel uses) and exposes each device as a
`device_tracker` entity — so it shows up on the HA Map and supports location
history via the recorder.

Scope: **live position only** (latitude/longitude + battery, speed, last-seen as
attributes). No MQTT required — the integration creates the entity natively.

## Install via HACS (recommended)

This repository already has the layout HACS expects: `hacs.json` and
`custom_components/notione/` at the root. Push it to its own GitHub repo, then in
Home Assistant:

1. **HACS → ⋮ (top right) → Custom repositories**.
2. Add the repo URL, category **Integration**, and confirm.
3. Find **notiOne** in HACS, click **Download**.
4. Restart Home Assistant.
5. **Settings → Devices & Services → Add Integration → "notiOne"** → enter
   email + password.

HACS also handles updates: bump `version` in `manifest.json`, tag a release, and
HACS will offer the update.

## Install manually (HA OS)

1. Copy `custom_components/notione/` into your HA config:
   `/config/custom_components/notione/`
   (use the Samba share, the File editor add-on, or `scp` via the SSH add-on).
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → "notiOne"**.
4. Enter your notiOne email and password.

A `device_tracker.<device_name>` entity appears per GPS device (e.g.
`device_tracker.zojowoz`). Add it to a Map card or assign it to a person.

## Options

Polling adapts to motion: it runs at the **idle** interval while the device is
parked and switches to the faster **moving** interval as soon as the device
reports motion (notiOne's accelerometer status, with GPS speed as fallback).

Click **Configure** on the integration to set both:
- **Idle polling interval** — default 30 s (the bike reports ~every 60 s parked).
- **Moving polling interval** — default 10 s (the bike reports ~every 10 s moving).

Each device also gets a **Moving** binary sensor (device class `moving`) and the
tracker exposes a `moving` attribute — either can drive automations.

## How it works

- `POST auth.notinote.me/public/user/authorize/login` → access token (1 h).
- `GET api.notinote.me/secured/internal/devicelist` (Bearer) → positions.
- The token is cached and refreshed by re-login on expiry or HTTP 401.

Credentials are stored encrypted in the HA config entry (never in YAML or logs).

## Test the API without HA (optional)

```bash
./custom_components/notione/tools/test_login.sh you@example.com 'your-password'
```

Prints whether login + device list succeed and shows each device's coordinates.
