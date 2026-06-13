"""Constants for the notiOne integration."""

from __future__ import annotations

DOMAIN = "notione"

# Endpoints (unofficial notiOne API, confirmed from captured traffic).
AUTH_BASE = "https://auth.notinote.me"
API_BASE = "https://api.notinote.me"
LOGIN_URL = f"{AUTH_BASE}/public/user/authorize/login"
DEVICELIST_URL = f"{API_BASE}/secured/internal/devicelist"

# Static public OAuth client used by the official panel/app. Not a user secret —
# it is the same value shipped in the web panel and the legacy n4ts/ha-notione.
CLIENT_BASIC_AUTH = (
    "Basic dGVzdC1vYXV0aC1jbGllbnQtaWQ6JDJ5JDEyJHZYT1V0RWVuVkZDTzFaZ3ky"
    "WWllUHVGM1dGL3NEZ05PM1luaFJqbDQ5TklEbEViR2VTZU91"
)
SCOPE = "NOTI"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_IDLE_INTERVAL = "idle_interval"
CONF_MOVING_INTERVAL = "moving_interval"

# Poll slowly while the device is parked, fast while it reports motion.
DEFAULT_IDLE_INTERVAL = 30  # seconds, used when no device is moving
DEFAULT_MOVING_INTERVAL = 10  # seconds, used while a device reports motion
MIN_INTERVAL = 5
MAX_INTERVAL = 3600
