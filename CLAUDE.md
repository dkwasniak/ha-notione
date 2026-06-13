# ha-notione — project guide

Custom Home Assistant integration for **notiOne** GPS locators. Reverse-engineered
from the notiOne web panel's private API (no official API exists). Exposes each GPS
device as a `device_tracker` plus motion and telemetry sensors.

## Repository layout

This repo's **root is a valid HACS integration root** — that is mandatory: HACS
only finds integrations at the repo root.

```
ha-notione/                      <- GitHub repo root (= HACS root)
├── hacs.json                    # HACS manifest (name, min HA version)
├── README.md                    # public project docs
├── LICENSE                      # MIT
├── CLAUDE.md                    # this file
└── custom_components/notione/
    ├── __init__.py              # setup/unload entry, platform forwarding
    ├── manifest.json            # domain, version (drives HACS), config_flow
    ├── const.py                 # endpoints, client auth, defaults, conf keys
    ├── api.py                   # NotiOneApi: login + devicelist, re-auth
    ├── coordinator.py           # DataUpdateCoordinator + shared helpers
    ├── config_flow.py           # UI setup (email/pass/name) + options flow
    ├── device_tracker.py        # TrackerEntity (GPS position)
    ├── binary_sensor.py         # Moving sensor (device_class moving)
    ├── sensor.py                # telemetry sensors (battery, speed, ...)
    ├── strings.json             # source UI strings (config/options/entities)
    ├── icons.json               # entity icons (state-based where useful)
    ├── translations/{en,pl}.json
    └── tools/test_login.sh      # standalone API smoke test (curl)
```

### Monorepo relationship (important)

This is a **standalone git repo nested inside** the `embeded` monorepo at
`BTScannerGaraz/ha-notione/`. The monorepo's `.gitignore` ignores `/ha-notione/`,
so the two repos don't interfere (repo-in-repo). Always run git commands from
**inside `ha-notione/`** — its remote is `git@github.com:dkwasniak/ha-notione.git`
(SSH), independent of the monorepo's `dkwasniak/embeded`.

## notiOne API (private, reverse-engineered)

Hosts and the static OAuth client are the same ones the web panel ships (also used
by the legacy `n4ts/ha-notione`). All defined in `const.py`.

1. **Login** — `POST https://auth.notinote.me/public/user/authorize/login`
   - Headers: `Authorization: Basic <CLIENT_BASIC_AUTH>`, `Content-Type: application/json`
   - Body: `{"email", "password", "scope": "NOTI"}`
   - Response: `{ accessToken, refreshToken, expiresIn (~3600), tokenType }`
2. **Devices + position** — `GET https://api.notinote.me/secured/internal/devicelist`
   - Header: `Authorization: Bearer <accessToken>`
   - Response: `deviceList[]`. Per device of interest:
     - `deviceId`, `name`, `deviceType` (e.g. `GPS_CONNECT`), `deviceState`
     - `lastPosition`: `latitude`, `longitude`, `speed`, `gpstime` (ms epoch),
       `accelerometerStatusEnum` (`MOVE` when moving), `geocodeCity`,
       `geocodePlace`, `temperature`, `humidity`, `accuracy`
     - `gpsDetails`: `battery`, `imei`, `refreshIntervalSeconds`, ...
3. **History** (not used yet) — `GET /secured/internal/devicesamples?date=<ms_midnight>&deviceId=<id>&version=TUBE`
   → daily tracks with `gpsSamples[]`, distance, avg/max speed.

**Token strategy:** `NotiOneApi` caches the access token and re-logs in when it is
near expiry or when a request returns 401. We do **not** use the refresh-token
endpoint (its contract wasn't captured); re-login is simpler and reliable. The
password is kept in the config entry and never logged.

## Architecture

Standard modern HA integration: config flow + `DataUpdateCoordinator` + platforms.

- **`__init__.py`** — `async_setup_entry` builds `NotiOneApi` (shared aiohttp
  session via `async_get_clientsession`) and `NotiOneCoordinator`, does
  `async_config_entry_first_refresh`, stores the coordinator in
  `entry.runtime_data` (typed alias `NotiOneConfigEntry`), then forwards
  `PLATFORMS = [DEVICE_TRACKER, BINARY_SENSOR, SENSOR]`. An update listener
  reloads the entry when options change. If a connection-trigger entity is
  configured, it subscribes via `async_track_state_change_event` and maps
  `on`/`home` → `coordinator.set_connection(...)` (unsub registered with
  `entry.async_on_unload`).
- **`coordinator.py`** — polls `devicelist`, returns `{deviceId: device}`. Holds
  two shared helpers used across platforms:
  - `device_is_moving(device)` — `accelerometerStatusEnum == "MOVE"`, else
    `speed > 0`.
  - `device_display_name(device, device_id, override)` — name resolution order:
    user override → API `name` → `notiOne <id>`.
  - **Adaptive polling:** after each refresh it sets `self.update_interval` to the
    moving interval if fast-polling is active, else the idle interval. The
    coordinator reads `update_interval` when scheduling the next refresh, so this
    takes effect from the next cycle. Fast-polling is active when
    `api_moving OR self._connected OR bridge`, where `bridge` is
    `time.monotonic() < self._grace_until`.
  - **External connection trigger:** `set_connection(active)` feeds an optional
    "bike connected" entity into the cadence. On connect it forces the moving
    interval and requests an immediate refresh; on disconnect it opens a grace
    window (`_grace_until = now + grace_seconds`) so polling stays fast through
    the device's LTE warm-up until API motion takes over. The trigger entity and
    grace window affect cadence only — never the Moving binary sensor.
- **`device_tracker.py`** — one `NotiOneTracker` per device with a GPS position
  (`_has_position` filters out phones/beacons). Provides lat/lon, `battery_level`,
  `location_accuracy`. Defines `name_override(entry)` (options > data) reused by
  the other platforms. Icon `mdi:bike`.
- **`binary_sensor.py`** — `NotiOneMovingSensor`, `device_class = moving`,
  `translation_key = "moving"`, state from `device_is_moving`.
- **`sensor.py`** — description-driven (`NotiOneSensorDescription` with a
  `value_fn`). One entity per `(device, description)`: battery, speed,
  temperature, humidity, last_seen (timestamp), geocode_city, geocode_place,
  device_state.

### Entity naming convention

All entities use `_attr_has_entity_name = True`. The **device** name (set in each
entity's `DeviceInfo.name` via `device_display_name`) becomes the prefix; the
entity's own name comes from `translation_key` (looked up in
`translations/*.json` under `entity.<platform>.<key>.name`). The tracker uses
`_attr_name = None` so it shows just the device name. Result: `Zojowóz`,
`Zojowóz Bateria`, etc. `unique_id` pattern: `notione_<deviceId>[_<key>]`.

## How to add a new sensor

1. Add a `NotiOneSensorDescription` to `SENSORS` in `sensor.py` with a `key`,
   `translation_key`, optional `device_class`/unit/`state_class`, and a
   `value_fn(device)`.
2. Add the display name under `entity.sensor.<key>.name` in **all three** of
   `strings.json`, `translations/en.json`, `translations/pl.json`.
3. Optionally add an icon under `entity.sensor.<key>` in `icons.json` (only needed
   when there's no `device_class` to supply one).

Adding a whole new platform: create `<platform>.py` with `async_setup_entry`, add
`Platform.<X>` to `PLATFORMS` in `__init__.py`, and add entity strings/icons.

## Validation

No HA install is needed for a basic check (host Python is 3.11; avoid 3.12-only
syntax like the `type` statement — see `__init__.py` which uses a plain
`ConfigEntry[...]` alias instead):

```bash
cd custom_components/notione
python3 -m py_compile *.py
for f in manifest.json strings.json icons.json translations/*.json; do
  python3 -c "import json; json.load(open('$f'))"; done
find . -name __pycache__ -type d -exec rm -rf {} +
```

Smoke-test the live API for an account (prints device coordinates):

```bash
./custom_components/notione/tools/test_login.sh you@example.com 'password'
```

## Release process (so HACS shows a version, not a commit hash)

HACS reads **published GitHub Releases**. Without a release it tracks the default
branch and shows the commit SHA. For every user-facing change:

1. Bump `"version"` in `custom_components/notione/manifest.json` (semver).
2. Commit and push to `main`.
3. Tag and push: `git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`.
4. **Publish a Release** from that tag:
   `https://github.com/dkwasniak/ha-notione/releases/new?tag=vX.Y.Z`
   (a tag alone is not enough — it must be a published Release).
5. In HACS the integration then offers the update.

`manifest.json` `version` and the git tag should match.

## Branding / HACS icon

The integration logo in HACS/HA does **not** come from this repo. It must be a PR
to `home-assistant/brands` adding `custom_integrations/notione/icon.png` (256×256,
plus `icon@2x.png` 512×512, trimmed, transparent). Until then HACS shows a
placeholder — cosmetic only.

## Conventions / gotchas

- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Keep PL and EN translations in sync with `strings.json`.
- Don't commit `.har` captures anywhere — they contain the plaintext password and
  live tokens (the monorepo `.gitignore` blocks `*.har`).
- The default HA branch here is `main`; push over SSH.
- `manifest.json` `documentation` points at this GitHub repo.
