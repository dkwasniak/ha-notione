# notiOne for Home Assistant

A custom [Home Assistant](https://www.home-assistant.io/) integration for
[notiOne](https://notione.com/) GPS locators. It logs in with your notiOne
account and exposes each GPS device as a `device_tracker`, so it appears on the
HA map with location history, plus a motion binary sensor.

notiOne has no official API — this integration uses the same private endpoints
as the notiOne web panel. See the [disclaimer](#disclaimer).

## Features

- **Live location** — each GPS locator becomes a `device_tracker` entity
  (latitude/longitude), shown on the HA map with history via the recorder.
- **Motion sensor** — a `binary_sensor` (device class `moving`) per device.
- **Telemetry sensors** — battery, speed, temperature, humidity, last-seen time,
  device state, and reverse-geocoded city/place as individual sensor entities
  (with history and proper units).
- **Adaptive polling** — polls slowly while parked and speeds up automatically
  while the device reports motion.
- **UI configuration** — set up and configure entirely from the HA UI; no YAML.

## Entities

For each notiOne GPS device:

| Entity | Type | Notes |
| --- | --- | --- |
| `device_tracker.<name>` | Device tracker | GPS position (lat/lon), `battery_level`, accuracy |
| `binary_sensor.<name>_moving` | Binary sensor (`moving`) | `on` while the device reports motion |
| `sensor.<name>_battery` | Sensor (battery, %) | Locator battery level |
| `sensor.<name>_speed` | Sensor (speed, km/h) | Current speed |
| `sensor.<name>_temperature` | Sensor (temperature, °C) | Reported temperature |
| `sensor.<name>_humidity` | Sensor (humidity, %) | Reported humidity |
| `sensor.<name>_last_seen` | Sensor (timestamp) | Time of the last GPS fix |
| `sensor.<name>_city` | Sensor (text) | Reverse-geocoded city |
| `sensor.<name>_place` | Sensor (text) | Reverse-geocoded place/street |
| `sensor.<name>_device_state` | Sensor (text) | e.g. `ONLINE` / `OFFLINE` |

Phones and Bluetooth beacons in the account are ignored — only GPS locators are
added.

## Installation

### HACS (recommended)

1. In HACS, open **⋮ → Custom repositories**.
2. Add `https://github.com/dkwasniak/ha-notione`, category **Integration**.
3. Find **notiOne** in HACS and click **Download**.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/notione/` into your Home Assistant config directory:
   `/config/custom_components/notione/`.
2. Restart Home Assistant.

## Configuration

After installing, add the integration from the UI:

**Settings → Devices & Services → Add Integration → notiOne**, then enter your
notiOne **email** and **password**. Credentials are stored encrypted in the
Home Assistant config entry.

Click **Configure** on the integration at any time to adjust:

| Option | Default | Description |
| --- | --- | --- |
| Tracker name | notiOne name | Overrides the device name; the tracker and its sensors inherit it as their name prefix. Leave blank to keep the name from notiOne. |
| Idle polling interval | 30 s | How often to poll while no device is moving. |
| Moving polling interval | 10 s | How often to poll while a device reports motion. |
| Connection entity | — | Optional `binary_sensor`/`input_boolean`/presence entity that is `on`/`home` when the device is connected (e.g. an ESPHome BLE presence sensor). Turning on forces the fast interval immediately and refreshes — no waiting for API motion. |
| Keep fast polling after disconnect | 300 s | Grace window keeping the fast interval after the connection entity goes off, bridging the device's LTE warm-up until the API reports motion. `0` disables it. |

### Fast-polling logic

Fast polling is active when **API motion OR connection entity on OR within the
grace window**. So when you power on the bike at home its BLE connection triggers
fast polling instantly; when you ride out of BLE range the grace window keeps it
fast until the device's LTE comes online and the API reports motion — a seamless
handover. It returns to the idle interval once there's no motion, no connection,
and the grace window has elapsed. The connection entity only affects the polling
cadence — the **Moving** sensor stays pure API motion.

## How it works

- `POST auth.notinote.me/public/user/authorize/login` → access token (valid ~1 h).
- `GET api.notinote.me/secured/internal/devicelist` (Bearer) → device positions.
- The token is cached and refreshed by re-logging in on expiry or HTTP 401.
- Motion is read from notiOne's accelerometer status, falling back to GPS speed.

## Development

Check the API responds for your account without Home Assistant:

```bash
./custom_components/notione/tools/test_login.sh you@example.com 'your-password'
```

It prints whether login and the device list succeed, with each device's
coordinates.

## Disclaimer

This project is not affiliated with or endorsed by notiOne. It relies on a
private API that may change or break at any time. Use at your own risk.

## License

[MIT](LICENSE)
