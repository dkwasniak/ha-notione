#!/usr/bin/env bash
# Quick check that the notiOne API still accepts your credentials and returns
# device positions — independent of Home Assistant.
#
# Usage: ./test_login.sh <email> <password>
set -euo pipefail

EMAIL="${1:-}"
PASSWORD="${2:-}"
if [[ -z "$EMAIL" || -z "$PASSWORD" ]]; then
  echo "Usage: $0 <email> <password>" >&2
  exit 1
fi

CLIENT_BASIC='dGVzdC1vYXV0aC1jbGllbnQtaWQ6JDJ5JDEyJHZYT1V0RWVuVkZDTzFaZ3kyWWllUHVGM1dGL3NEZ05PM1luaFJqbDQ5TklEbEViR2VTZU91'

echo "== Logging in =="
LOGIN_RESP="$(curl -fsS -X POST 'https://auth.notinote.me/public/user/authorize/login' \
  -H "Authorization: Basic ${CLIENT_BASIC}" \
  -H 'Content-Type: application/json' \
  --data "$(jq -nc --arg e "$EMAIL" --arg p "$PASSWORD" '{email:$e,password:$p,scope:"NOTI"}')")"

TOKEN="$(jq -r '.accessToken' <<<"$LOGIN_RESP")"
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "Login failed:" >&2
  echo "$LOGIN_RESP" >&2
  exit 1
fi
echo "Login OK (token expires in $(jq -r '.expiresIn' <<<"$LOGIN_RESP")s)"

echo "== Fetching device list =="
curl -fsS 'https://api.notinote.me/secured/internal/devicelist' \
  -H "Authorization: Bearer ${TOKEN}" \
| jq -r '.deviceList[]
    | "\(.deviceId)\t\(.name)\t\(.deviceType)\t" +
      (if .lastPosition then "\(.lastPosition.latitude),\(.lastPosition.longitude) speed=\(.lastPosition.speed)" else "no position" end)'
