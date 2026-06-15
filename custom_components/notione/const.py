"""Constants for the notiOne integration."""

from __future__ import annotations

DOMAIN = "notione"

# Endpoints (unofficial notiOne API, confirmed from captured traffic).
AUTH_BASE = "https://auth.notinote.me"
API_BASE = "https://api.notinote.me"
LOGIN_URL = f"{AUTH_BASE}/public/user/authorize/login"
DEVICELIST_URL = f"{API_BASE}/secured/internal/devicelist"
DEVICECONFIG_URL = f"{API_BASE}/secured/internal/deviceconfig"
LIVE_WS_URL = "wss://api.notinote.me:444/ws/secured/internal/live"
API_ACCEPT = "application/notinote.me-5+json"
USER_AGENT = "notiOne/2.2.3 (Android; Home Assistant)"

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
CONF_MOVING_TRIGGER = "moving_trigger_entity"
CONF_MOVING_GRACE = "moving_grace"
CONF_DEVICE_AUTOMATIONS = "device_automations"
CONF_ZONE_ENTITY = "zone_entity"
CONF_GARAGE_ENTITY = "garage_entity"

STATIONARY_INTERVALS = {
    "1 h": 3600,
    "6 h": 21600,
    "24 h": 86400,
}

# Poll slowly while the device is parked, fast while it reports motion.
DEFAULT_IDLE_INTERVAL = 30  # seconds, used when no device is moving
DEFAULT_MOVING_INTERVAL = 10  # seconds, used while a device reports motion
MIN_INTERVAL = 5
MAX_INTERVAL = 3600

# Keep fast polling this long after the connection-trigger entity goes off, to
# bridge the device's LTE warm-up until the API starts reporting motion.
DEFAULT_MOVING_GRACE = 300  # seconds (5 min); 0 disables the bridge
MIN_GRACE = 0
