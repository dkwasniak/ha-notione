# notiOne API reverse engineering

Status: findings verified against notiOne Android 2.2.3 (`versionCode` 20186),
published May 25, 2026. Live API connectivity was tested on June 15, 2026.

This document describes an unofficial private API. It may change without
notice. Do not commit credentials, access tokens, full IMEIs, HAR files, or raw
account responses to the repository.

## Sources and verification

- The public web panel JavaScript was inspected for REST endpoints.
- Android package `me.notinote` 2.2.3 was downloaded as a split XAPK and
  statically analyzed.
- The APK signature was valid and identified the signer as Notinote. It also
  contained a Google Play source stamp.
- The LIVE WebSocket handshake and offline-device timeout were verified using
  a real account and an owned GPS device.

APK SHA-256 used for analysis:

```text
e029e2d6c6c767dbdd9a604e8a131fc38df5e348b0245059d8d54cb3e3346f50
```

## Authentication

Login:

```http
POST https://auth.notinote.me/public/user/authorize/login
Authorization: Basic <public mobile/web client credential>
Content-Type: application/json

{
  "email": "...",
  "password": "...",
  "scope": "NOTI"
}
```

The response contains `accessToken`, `refreshToken`, `tokenType` and token
expiry information. Authenticated requests use:

```http
Authorization: Bearer <accessToken>
Accept: application/notinote.me-5+json
```

The official clients also provide a generated `User-Agent` header.

## REST endpoints

Endpoints relevant to the Home Assistant integration:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/secured/internal/devicelist` | Devices and current/last position |
| `GET` | `/secured/internal/device` | Details for one device; query includes `deviceId` and `version` |
| `GET` | `/secured/internal/devicesamples` | Daily GPS history |
| `GET` | `/secured/internal/devicesamples/timeline` | Compressed timeline data |
| `GET` | `/secured/internal/devicesamples/grouped` | Grouped history data |
| `GET` | `/secured/internal/deviceconfig` | Read configurable GPS settings |
| `POST` | `/secured/internal/deviceconfig` | Update configurable GPS settings |

The base URL is:

```text
https://api.notinote.me
```

### Device configuration

Read configuration:

```http
GET /secured/internal/deviceconfig?deviceId=<deviceId>
```

Update configuration:

```http
POST /secured/internal/deviceconfig?deviceId=<deviceId>
Content-Type: application/json
```

The update model found in the Android application contains:

```json
{
  "movePositionInterval": 0,
  "stationaryPositionInterval": 0,
  "theftAlarmStatus": false,
  "etollEnabled": false,
  "allowCollectGpsData": true,
  "theftAlarmMode": "...",
  "theftAlarmWholeDayNotification": false,
  "theftAlarmBeginTime": "...",
  "theftAlarmEndTime": "...",
  "allowDisableDevice": false,
  "theftAlarmSoundEnabled": false,
  "speedExceedAlarmEnabled": false,
  "speedExceedAlarmThreshold": 0,
  "batterySavingAlarmEnabled": false,
  "batterySavingAlarmThreshold": 0,
  "batterySavingAlarmMoveInterval": 0
}
```

The configuration response additionally contains `allowedMoveIntervals`.
Clients should read this array instead of assuming arbitrary intervals are
accepted. Updating the full configuration is state-changing and should preserve
all unrelated values returned by `GET`.

## `gpsFeatures.allowLiveMode`

`devicelist` or the single-device response may contain:

```json
{
  "gpsDetails": {
    "gpsFeatures": {
      "allowLiveMode": true,
      "allowTimeline": true
    }
  }
}
```

`allowLiveMode` is a server-provided capability/entitlement flag. The Android
application reads it to decide whether the LIVE feature is available in the UI.
It is not sent to the server to activate LIVE and should not be modified by the
client.

The application starts LIVE by sending the device IMEI over the separate
WebSocket protocol described below. A false or missing `allowLiveMode` controls
visibility in the official client. This integration exposes its explicit manual
switch for every GPS device with an IMEI and lets the server accept or reject the
request.

## LIVE WebSocket

LIVE mode does not use repeated REST polling. It uses a binary WebSocket:

```text
wss://api.notinote.me:444/ws/secured/internal/live
```

Handshake headers include:

```http
Authorization: Bearer <accessToken>
User-Agent: <official-compatible user agent>
```

Messages are Protocol Buffers carried in binary WebSocket frames.

### Envelope

```proto
message WSMessage {
  WSMessageType type = 1;
  bytes body = 2;
}

enum WSMessageType {
  LIVE_MODE_ENABLE_REQUEST = 0;
  LIVE_MODE_SAMPLE = 1;
  LIVE_MODE_CONFIG = 2;
}
```

Because `LIVE_MODE_ENABLE_REQUEST` has numeric value zero, proto3 normally
omits field `type` from the serialized enable request.

### Enable request

```proto
message LiveGpsEnableRequest {
  uint64 imei = 1;
}
```

The start request contains only the IMEI. It does not contain `deviceId`, an
interval, or `allowLiveMode`.

### Configuration response

```proto
message LiveModeConfig {
  uint64 imei = 1;
  uint32 maxSessionTime = 2;
}
```

`maxSessionTime` is supplied by the server. Product behavior indicates a
typical maximum of 30 minutes, but clients must use the received value rather
than hard-coding 1800 seconds.

### Position sample

```proto
message LiveGpsSample {
  uint64 imei = 1;
  uint64 gpsTime = 2;
  double longitude = 3;
  double latitude = 4;
  uint32 speed = 5;
  uint32 altitude = 6;
  uint32 azimuth = 7;
}
```

The APK includes sample LIVE data at one-second intervals. A real online-device
test is still required to verify whether every device model consistently
delivers one-second samples or sometimes uses two-second intervals.

### Session close codes

Server close codes found in the Android application:

| Code | Meaning |
| --- | --- |
| `4000` | General error |
| `4001` | Device already registered in another LIVE session |
| `4002` | Session idle timeout |
| `4003` | Maximum session duration exceeded |
| `4004` | Device information was not registered / no-device timeout |
| `4005` | Device did not respond before the response timeout |

Known client close codes begin at `3000`. The official application uses `3000`
when the user presses the stop button.

## Verified offline test

The test device was offline in a garage. The following behavior was observed:

1. REST login succeeded.
2. Device selection and IMEI lookup succeeded.
3. TLS and WebSocket upgrade to the LIVE endpoint succeeded.
4. The binary `LIVE_MODE_ENABLE_REQUEST` was accepted and sent.
5. No LIVE configuration or position sample was received while the device was
   offline.
6. The server closed the session after approximately one minute with:

```json
{
  "code": 4005,
  "reason": "Exceed session device response timeout"
}
```

This proves that the client protocol and authentication are correct. Code
`4005` is expected when the device cannot wake or reach the server.

The Android UI also contains the instruction to press the physical button on
the device to activate LIVE. Whether this is required depends on the GPS model
and its current power state.

## Integration implications

- Polling `devicelist` faster cannot reproduce LIVE behavior. The REST position
  may still update in batches around every 60 seconds.
- Home Assistant LIVE support should maintain a WebSocket only while explicitly
  requested, then expose incoming samples through the coordinator/entities.
- LIVE activation consumes more device power and must be opt-in.
- The integration intentionally does not gate its manual action on
  `gpsFeatures.allowLiveMode`; it requires a numeric IMEI and treats a server
  rejection as a terminal session result.
- Only one active LIVE client appears to be allowed per device.
- The integration must handle server close codes and reconnect conservatively;
  it should not automatically restart an expired 30-minute session forever.
- Regular configurable intervals are separate from LIVE and should use
  `deviceconfig` plus the server-provided `allowedMoveIntervals` list.

## Research tools

Read-only REST observation while LIVE is toggled in the official app:

```bash
./custom_components/notione/tools/probe_live_mode.sh EMAIL
```

Direct LIVE WebSocket test:

```bash
./custom_components/notione/tools/probe_live_websocket.py \
  EMAIL \
  --duration 120 \
  --start-live
```

Both tools request the password interactively. Do not pass a password as a
command-line argument or commit their outputs when those outputs contain device
identifiers.
