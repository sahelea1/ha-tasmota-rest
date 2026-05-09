"""Constants for the Tasmota REST integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "tasmota_rest"

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]

# Configuration keys
CONF_DEVICES = "devices"
CONF_VIRTUAL_SWITCH_ENABLED = "virtual_switch_enabled"
CONF_VIRTUAL_SWITCH_THRESHOLD = "virtual_switch_threshold"
CONF_VIRTUAL_SWITCH_PRESS_ENTITY = "virtual_switch_press_entity"
CONF_VERIFY_SSL = "verify_ssl"
CONF_USE_HTTPS = "use_https"

# Defaults
DEFAULT_SCAN_INTERVAL = 5
DEFAULT_TIMEOUT = 5
DEFAULT_VIRTUAL_THRESHOLD = 30
DEFAULT_TIMEZONE_CMD = (
    "Backlog0 Timezone 99; "
    "TimeStd 0,0,10,1,3,60; "
    "TimeDst 0,0,3,1,2,120"
)

# Service names
SERVICE_SET_TIMER = "set_timer"
SERVICE_DISABLE_ALL_TIMERS = "disable_all_timers"
SERVICE_GET_TIMERS = "get_timers"
SERVICE_SET_TIMEZONE = "set_timezone"
SERVICE_SEND_COMMAND = "send_command"
SERVICE_RESTART = "restart"
SERVICE_NORMALIZE_TIME = "normalize_time"
SERVICE_POWER_ON = "power_on"
SERVICE_POWER_OFF = "power_off"
SERVICE_BACKLOG = "backlog"
