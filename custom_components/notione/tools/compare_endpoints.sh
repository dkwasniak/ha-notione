#!/usr/bin/env bash
# Compare freshness of devicelist vs devicesamples.
#
# Key question: between two devicelist updates (~60s apart), do NEW intermediate
# 10-second GPS points appear in devicesamples, or does devicesamples also only
# update every 60s (batch upload)?
#
# Tracked per poll:
#   - devicelist: gpstime (changes when server gets new data)
#   - devicesamples: count of total gpsSamples today + gpstime of latest sample
#     → if count grows by 1 each 10s: server gets data in real-time
#     → if count jumps by 6 every 60s: device batches and uploads every minute
#
# Usage: ./compare_endpoints.sh <email> <password> [interval_s] [duration_s]
# Defaults: interval=10s, duration=180s
set -euo pipefail

EMAIL="${1:-}"
PASSWORD="${2:-}"
INTERVAL="${3:-10}"
DURATION="${4:-180}"

if [[ -z "$EMAIL" || -z "$PASSWORD" ]]; then
  echo "Usage: $0 <email> <password> [interval_s] [duration_s]" >&2
  exit 1
fi

CLIENT_BASIC='dGVzdC1vYXV0aC1jbGllbnQtaWQ6JDJ5JDEyJHZYT1V0RWVuVkZDTzFaZ3kyWWllUHVGM1dGL3NEZ05PM1luaFJqbDQ5TklEbEViR2VTZU91'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPATH="${SCRIPT_DIR}/compare_endpoints_$(date '+%Y%m%d_%H%M%S').tsv"

TMP_DL="$(mktemp)"
TMP_DS="$(mktemp)"
cleanup() { rm -f "$TMP_DL" "$TMP_DS"; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
echo "=== Login ==="
LOGIN_RESP="$(curl -fsS -X POST 'https://auth.notinote.me/public/user/authorize/login' \
  -H "Authorization: Basic ${CLIENT_BASIC}" \
  -H 'Content-Type: application/json' \
  --data "$(jq -nc --arg e "$EMAIL" --arg p "$PASSWORD" '{email:$e,password:$p,scope:"NOTI"}')")"

TOKEN="$(jq -r '.accessToken' <<<"$LOGIN_RESP")"
EXPIRES_IN="$(jq -r '.expiresIn' <<<"$LOGIN_RESP")"
TOKEN_OBTAINED="$(date +%s)"

if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "Login failed" >&2; exit 1
fi
echo "OK (token valid ${EXPIRES_IN}s)"

DEVICE_ID="$(curl -fsS 'https://api.notinote.me/secured/internal/devicelist' \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq -r '.deviceList[] | select(.deviceType == "GPS_CONNECT") | .deviceId' | head -1)"
echo "Device ID: ${DEVICE_ID}"

MIDNIGHT_MS="$(python3 -c "
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
print(int(datetime(now.year,now.month,now.day,tzinfo=timezone.utc).timestamp()*1000))
")"

echo ""
echo "Polling co ${INTERVAL}s przez ${DURATION}s → ${OUTPATH}"
echo ""
echo "Legenda kolumn:"
echo "  dl_gpstime    = gpstime z devicelist (zmiana = nowe dane z urządzenia)"
echo "  ds_count      = łączna liczba gpsSamples dziś w devicesamples"
echo "  ds_count_diff = przyrost próbek vs poprzedni poll (+1 co 10s = real-time, +6 co 60s = batch)"
echo "  ds_latest     = gpstime ostatniej próbki w devicesamples"
echo "  dl_vs_ds      = dl_gpstime == ds_latest? (powinno być zawsze tak)"
echo ""

printf 'wall_time\twall_epoch\tdl_gpstime_utc\tdl_gpstime_ms\tdl_speed\tdl_accel\tdl_state\tds_count\tds_count_diff\tds_latest_utc\tds_latest_ms\tdl_vs_ds_equal\n' \
  > "$OUTPATH"

printf '%-10s  %-12s  %-6s  %-6s  %-8s  %-8s  %-10s  %-8s\n' \
  "wall" "dl_gpstime" "speed" "accel" "state" "ds_count" "ds_diff" "dl==ds?"
echo "------------------------------------------------------------------------"

PREV_DS_COUNT=0
END_TIME=$(( $(date +%s) + DURATION ))

while [[ $(date +%s) -lt $END_TIME ]]; do
  NOW="$(date +%s)"
  if (( NOW - TOKEN_OBTAINED + 120 >= EXPIRES_IN )); then
    LOGIN_RESP="$(curl -fsS -X POST 'https://auth.notinote.me/public/user/authorize/login' \
      -H "Authorization: Basic ${CLIENT_BASIC}" \
      -H 'Content-Type: application/json' \
      --data "$(jq -nc --arg e "$EMAIL" --arg p "$PASSWORD" '{email:$e,password:$p,scope:"NOTI"}')")"
    TOKEN="$(jq -r '.accessToken' <<<"$LOGIN_RESP")"
    EXPIRES_IN="$(jq -r '.expiresIn' <<<"$LOGIN_RESP")"
    TOKEN_OBTAINED="$NOW"
    echo "[re-login OK]"
  fi

  WALL="$(date '+%H:%M:%S')"
  WALL_EPOCH="$(date +%s)"

  curl -fsS 'https://api.notinote.me/secured/internal/devicelist' \
    -H "Authorization: Bearer ${TOKEN}" > "$TMP_DL" &
  PID_DL=$!

  curl -fsS \
    "https://api.notinote.me/secured/internal/devicesamples?date=${MIDNIGHT_MS}&deviceId=${DEVICE_ID}&version=TUBE" \
    -H "Authorization: Bearer ${TOKEN}" > "$TMP_DS" &
  PID_DS=$!

  wait $PID_DL $PID_DS

  ROW="$(python3 - "$DEVICE_ID" "$WALL" "$WALL_EPOCH" "$TMP_DL" "$TMP_DS" "$PREV_DS_COUNT" <<'PYEOF'
import sys, json
from datetime import datetime, timezone

device_id     = int(sys.argv[1])
wall          = sys.argv[2]
wall_ep       = sys.argv[3]
dl_file       = sys.argv[4]
ds_file       = sys.argv[5]
prev_count    = int(sys.argv[6])

def fmt_ms(ms):
    if ms is None:
        return "null", "null"
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%H:%M:%S"), str(ms)

# devicelist
with open(dl_file) as f:
    dl_data = json.load(f)
device   = next((d for d in dl_data.get("deviceList", []) if d.get("deviceId") == device_id), {})
pos      = device.get("lastPosition") or {}
dl_ms    = pos.get("gpstime")
dl_speed = pos.get("speed", "null")
dl_accel = pos.get("accelerometerStatusEnum") or "-"
dl_state = device.get("deviceState") or "-"
dl_utc, dl_ms_str = fmt_ms(dl_ms)

# devicesamples — count ALL gpsSamples and find latest gpstime
with open(ds_file) as f:
    ds_data = json.load(f)
ds_count   = 0
ds_latest  = None
for track in ds_data.get("trackList") or []:
    for pt in track.get("gpsSamples") or []:
        ds_count += 1
        t = pt.get("gpstime")
        if isinstance(t, int) and (ds_latest is None or t > ds_latest):
            ds_latest = t

ds_utc, ds_ms_str = fmt_ms(ds_latest)
ds_diff   = ds_count - prev_count
dl_vs_ds  = "YES" if dl_ms is not None and dl_ms == ds_latest else "NO"

tsv = "\t".join([
    wall, wall_ep,
    dl_utc, dl_ms_str, str(dl_speed), dl_accel, dl_state,
    str(ds_count), str(ds_diff),
    ds_utc, ds_ms_str,
    dl_vs_ds,
])
# last field for bash: current ds_count (used as PREV_DS_COUNT next iteration)
print(tsv + "\t" + str(ds_count))
PYEOF
)"

  # Split off the trailing ds_count helper field
  PREV_DS_COUNT="$(awk -F'\t' '{print $NF}' <<<"$ROW")"
  ROW_TSV="$(rev <<<"$ROW" | cut -f2- | rev)"

  printf '%s\n' "$ROW_TSV" >> "$OUTPATH"

  DL_UTC="$(cut -f3  <<<"$ROW_TSV")"
  DL_SPEED="$(cut -f5  <<<"$ROW_TSV")"
  DL_ACCEL="$(cut -f6  <<<"$ROW_TSV")"
  DL_STATE="$(cut -f7  <<<"$ROW_TSV")"
  DS_COUNT="$(cut -f8  <<<"$ROW_TSV")"
  DS_DIFF="$(cut -f9  <<<"$ROW_TSV")"
  DL_VS_DS="$(cut -f12 <<<"$ROW_TSV")"

  printf '%-10s  %-12s  %-6s  %-6s  %-8s  %-8s  %-10s  %-8s\n' \
    "$WALL" "$DL_UTC" "$DL_SPEED" "$DL_ACCEL" "$DL_STATE" "$DS_COUNT" "+${DS_DIFF}" "$DL_VS_DS"

  sleep "$INTERVAL"
done

echo ""
echo "=== Gotowe: ${OUTPATH} ==="
echo "Podsumowanie:"
python3 - "$OUTPATH" <<'PYEOF'
import sys, csv
from collections import Counter

diffs = []
with open(sys.argv[1]) as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        try:
            d = int(row['ds_count_diff'])
            if d > 0:   # skip first row (prev_count=0)
                diffs.append(d)
        except (ValueError, KeyError):
            pass

if not diffs:
    print("Brak danych.")
    sys.exit(0)

dist = Counter(diffs)
print(f"  Przyrosty ds_count między pollami: {dict(sorted(dist.items()))}")
print()
if all(d == 1 for d in diffs):
    print("  → devicesamples aktualizuje się CO 10s (real-time, 1 próbka na poll)")
elif len(dist) == 1:
    k = list(dist.keys())[0]
    print(f"  → devicesamples aktualizuje się w paczkach po {k} próbki (batch upload)")
else:
    print(f"  → mieszany wzorzec — sprawdź plik TSV")
PYEOF
