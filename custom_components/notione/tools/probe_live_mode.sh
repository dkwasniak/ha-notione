#!/usr/bin/env bash
# Observe all devicelist fields while LIVE mode is toggled in the official app.
# This script is read-only: it never sends a device command.
#
# Usage: ./probe_live_mode.sh <email> [device_id] [duration_s] [interval_s]
# Defaults: first GPS_CONNECT device, 2100 seconds, 1-second polling.
set -euo pipefail

EMAIL="${1:-}"
DEVICE_ID="${2:-}"
DURATION="${3:-2100}"
INTERVAL="${4:-1}"

if [[ -z "$EMAIL" ]]; then
  echo "Usage: $0 <email> [device_id] [duration_s] [interval_s]" >&2
  exit 1
fi
if ! [[ "$DURATION" =~ ^[0-9]+$ ]] || (( DURATION < 1 )); then
  echo "duration_s must be a positive integer" >&2
  exit 1
fi
if ! [[ "$INTERVAL" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "interval_s must be a positive number" >&2
  exit 1
fi
if ! awk -v interval="$INTERVAL" 'BEGIN { exit !(interval > 0) }'; then
  echo "interval_s must be greater than zero" >&2
  exit 1
fi

read -r -s -p "notiOne password: " PASSWORD
echo

CLIENT_BASIC='dGVzdC1vYXV0aC1jbGllbnQtaWQ6JDJ5JDEyJHZYT1V0RWVuVkZDTzFaZ3kyWWllUHVGM1dGL3NEZ05PM1luaFJqbDQ5TklEbEViR2VTZU91'
OUTDIR="${TMPDIR:-/tmp}/notione-live-probe-$(date '+%Y%m%d_%H%M%S')"
mkdir -p "$OUTDIR"
chmod 700 "$OUTDIR"

LOGIN_FILE="$OUTDIR/login.json"
LIST_FILE="$OUTDIR/devicelist.json"
PREV_FILE="$OUTDIR/previous-device.json"
CURR_FILE="$OUTDIR/current-device.json"
LOG_FILE="$OUTDIR/observations.jsonl"
SUMMARY_FILE="$OUTDIR/gpstime.tsv"

cleanup() {
  rm -f "$LOGIN_FILE" "$LIST_FILE" "$PREV_FILE" "$CURR_FILE"
}
trap cleanup EXIT INT TERM

login() {
  curl -fsS -X POST 'https://auth.notinote.me/public/user/authorize/login' \
    -H "Authorization: Basic ${CLIENT_BASIC}" \
    -H 'Content-Type: application/json' \
    --data "$(jq -nc --arg e "$EMAIL" --arg p "$PASSWORD" \
      '{email:$e,password:$p,scope:"NOTI"}')" > "$LOGIN_FILE"

  TOKEN="$(jq -r '.accessToken // empty' "$LOGIN_FILE")"
  EXPIRES_IN="$(jq -r '.expiresIn // 3600' "$LOGIN_FILE")"
  TOKEN_OBTAINED="$(date +%s)"
  if [[ -z "$TOKEN" ]]; then
    echo "Login response did not contain accessToken" >&2
    exit 1
  fi
}

fetch_device_list() {
  local now
  now="$(date +%s)"
  if (( now - TOKEN_OBTAINED + 120 >= EXPIRES_IN )); then
    login
  fi
  curl -fsS 'https://api.notinote.me/secured/internal/devicelist' \
    -H "Authorization: Bearer ${TOKEN}" > "$LIST_FILE"
}

login
fetch_device_list

if [[ -z "$DEVICE_ID" ]]; then
  DEVICE_ID="$(jq -r \
    '.deviceList[] | select(.deviceType == "GPS_CONNECT") | .deviceId' \
    "$LIST_FILE" | head -1)"
fi
if [[ -z "$DEVICE_ID" || "$DEVICE_ID" == "null" ]]; then
  echo "No GPS_CONNECT device found" >&2
  exit 1
fi
if ! [[ "$DEVICE_ID" =~ ^[0-9]+$ ]]; then
  echo "device_id must be an integer" >&2
  exit 1
fi
if ! jq -e --argjson did "$DEVICE_ID" \
  '.deviceList[] | select(.deviceId == $did)' "$LIST_FILE" > "$PREV_FILE"; then
  echo "Device ID $DEVICE_ID not found" >&2
  exit 1
fi

DEVICE_NAME="$(jq -r '.name // "unnamed"' "$PREV_FILE")"
printf 'wall_epoch\twall_utc\tgpstime_ms\tgpstime_utc\tdelta_gps_s\tserver_lag_s\n' \
  > "$SUMMARY_FILE"

echo "Device: $DEVICE_NAME (id=$DEVICE_ID)"
echo "Output: $OUTDIR"
echo
echo "Now enable LIVE mode in the official notiOne app."
echo "Every changed API field and every new GPS timestamp will be printed."
echo "Press Ctrl-C to stop early."
echo

START="$(date +%s)"
END=$((START + DURATION))
PREV_GPSTIME="$(jq -r '.lastPosition.gpstime // 0' "$PREV_FILE")"

while (( $(date +%s) < END )); do
  WALL_EPOCH="$(date +%s)"
  WALL_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  if ! fetch_device_list; then
    echo "$WALL_UTC request failed; retrying" >&2
    sleep "$INTERVAL"
    continue
  fi
  if ! jq -e --argjson did "$DEVICE_ID" \
    '.deviceList[] | select(.deviceId == $did)' "$LIST_FILE" > "$CURR_FILE"; then
    echo "$WALL_UTC device missing from devicelist" >&2
    sleep "$INTERVAL"
    continue
  fi

  jq -cn --argjson wall "$WALL_EPOCH" --arg wallUtc "$WALL_UTC" \
    --slurpfile device "$CURR_FILE" \
    '{wallEpoch:$wall,wallUtc:$wallUtc,device:$device[0]}' >> "$LOG_FILE"

  CHANGES="$(jq -n --slurpfile before "$PREV_FILE" --slurpfile after "$CURR_FILE" '
    def flattened:
      [paths(type != "object" and type != "array") as $p
        | {key: ($p | map(tostring) | join(".")), value: getpath($p)}]
      | from_entries;
    ($before[0] | flattened) as $a
    | ($after[0] | flattened) as $b
    | (($a | keys_unsorted) + ($b | keys_unsorted) | unique)[] as $key
    | select($a[$key] != $b[$key])
    | "  \($key): \($a[$key] | tojson) -> \($b[$key] | tojson)"
  ')"
  if [[ -n "$CHANGES" ]]; then
    echo "[$WALL_UTC] fields changed:"
    echo "$CHANGES"
  fi

  GPSTIME="$(jq -r '.lastPosition.gpstime // 0' "$CURR_FILE")"
  if (( GPSTIME > 0 && GPSTIME != PREV_GPSTIME )); then
    if (( PREV_GPSTIME > 0 )); then
      DELTA_GPS=$(( (GPSTIME - PREV_GPSTIME) / 1000 ))
    else
      DELTA_GPS=0
    fi
    SERVER_LAG=$(( WALL_EPOCH - GPSTIME / 1000 ))
    GPSTIME_UTC="$(date -u -r $((GPSTIME / 1000)) '+%Y-%m-%dT%H:%M:%SZ')"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$WALL_EPOCH" "$WALL_UTC" "$GPSTIME" "$GPSTIME_UTC" \
      "$DELTA_GPS" "$SERVER_LAG" >> "$SUMMARY_FILE"
    echo "[$WALL_UTC] NEW GPS: $GPSTIME_UTC delta=${DELTA_GPS}s lag=${SERVER_LAG}s"
    PREV_GPSTIME="$GPSTIME"
  fi

  cp "$CURR_FILE" "$PREV_FILE"
  sleep "$INTERVAL"
done

echo
echo "Probe complete: $OUTDIR"
echo "GPS timing: $SUMMARY_FILE"
echo "Full snapshots: $LOG_FILE"
