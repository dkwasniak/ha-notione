#!/usr/bin/env bash
# Check how often the notiOne server receives GPS updates from the device.
# Calls both endpoints: devicelist (current state) and devicesamples (history).
#
# Usage: ./check_update_freq.sh <email> <password> [device_id]
set -euo pipefail

EMAIL="${1:-}"
PASSWORD="${2:-}"
DEVICE_ID="${3:-}"
if [[ -z "$EMAIL" || -z "$PASSWORD" ]]; then
  echo "Usage: $0 <email> <password> [device_id]" >&2
  exit 1
fi

CLIENT_BASIC='dGVzdC1vYXV0aC1jbGllbnQtaWQ6JDJ5JDEyJHZYT1V0RWVuVkZDTzFaZ3kyWWllUHVGM1dGL3NEZ05PM1luaFJqbDQ5TklEbEViR2VTZU91'

echo "=== 1. Login ==="
LOGIN_RESP="$(curl -fsS -X POST 'https://auth.notinote.me/public/user/authorize/login' \
  -H "Authorization: Basic ${CLIENT_BASIC}" \
  -H 'Content-Type: application/json' \
  --data "$(jq -nc --arg e "$EMAIL" --arg p "$PASSWORD" '{email:$e,password:$p,scope:"NOTI"}')")"

TOKEN="$(jq -r '.accessToken' <<<"$LOGIN_RESP")"
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "Login failed:" >&2; echo "$LOGIN_RESP" >&2; exit 1
fi
echo "OK"

echo ""
echo "=== 2. devicelist – stan bieżący ==="
DEVLIST="$(curl -fsS 'https://api.notinote.me/secured/internal/devicelist' \
  -H "Authorization: Bearer ${TOKEN}")"

# Pick the first GPS_CONNECT device if no device_id given
if [[ -z "$DEVICE_ID" ]]; then
  DEVICE_ID="$(jq -r '.deviceList[] | select(.deviceType == "GPS_CONNECT") | .deviceId' <<<"$DEVLIST" | head -1)"
fi

jq -r --argjson did "$DEVICE_ID" '
  .deviceList[] | select(.deviceId == $did) |
  "Urządzenie : \(.name) (id=\(.deviceId), type=\(.deviceType))",
  "Stan       : \(.deviceState)",
  "Accelero   : \(.lastPosition.accelerometerStatusEnum // "brak")",
  "Prędkość   : \(.lastPosition.speed // 0) km/h",
  "gpstime    : \(.lastPosition.gpstime) → \(.lastPosition.gpstime / 1000 | todate)",
  "refreshInterval (gpsDetails): \(.gpsDetails.refreshIntervalSeconds // "brak") s",
  "Pozycja    : \(.lastPosition.latitude), \(.lastPosition.longitude)"
' <<<"$DEVLIST"

echo ""
echo "=== 3. devicesamples – historia dziś (odstępy między próbkami) ==="
MIDNIGHT_MS="$(python3 -c "
from datetime import datetime, timezone
import time
now = datetime.now(timezone.utc)
ms = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() * 1000)
print(ms)
")"

SAMPLES="$(curl -fsS \
  "https://api.notinote.me/secured/internal/devicesamples?date=${MIDNIGHT_MS}&deviceId=${DEVICE_ID}&version=TUBE" \
  -H "Authorization: Bearer ${TOKEN}")"

# Extract all gpstime values from gpsSamples, sort, compute intervals
python3 - <<<"$SAMPLES" <<'PYEOF'
import sys, json, math
data = json.loads(sys.stdin.read())
tracks = data.get("trackList") or []
times = []
for track in tracks:
    for pt in track.get("gpsSamples") or []:
        t = pt.get("gpstime")
        if isinstance(t, int):
            times.append(t)

if not times:
    print("Brak próbek GPS na dziś.")
    sys.exit(0)

times.sort()
from datetime import datetime, timezone
def fmt(ms):
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc).strftime("%H:%M:%S")

intervals = [times[i+1] - times[i] for i in range(len(times)-1)]
print(f"Liczba próbek dziś: {len(times)}")
print(f"Od: {fmt(times[0])}  Do: {fmt(times[-1])} UTC")
if intervals:
    avg = sum(intervals) / len(intervals)
    print(f"Odstępy między próbkami (s):")
    print(f"  min={min(intervals)/1000:.0f}s  max={max(intervals)/1000:.0f}s  avg={avg/1000:.0f}s")
    # Show last 10 intervals to see recent pattern
    recent = intervals[-10:]
    print(f"Ostatnie {len(recent)} odstępów (s): {[round(x/1000) for x in recent]}")
print(f"Ostatnia próbka: {fmt(times[-1])} UTC")
PYEOF
