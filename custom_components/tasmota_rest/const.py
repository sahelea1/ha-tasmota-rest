"""Constants for the Tasmota REST integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "tasmota_rest"

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]

# ---- Entry types ----
ENTRY_TYPE = "entry_type"
ENTRY_TYPE_HUB = "hub"
ENTRY_TYPE_DEVICE = "device"
HUB_UNIQUE_ID = "tasmota_rest_hub"

# ---- Per-device configuration keys ----
CONF_DEVICES = "devices"
CONF_VIRTUAL_SWITCH_ENABLED = "virtual_switch_enabled"
CONF_VIRTUAL_SWITCH_THRESHOLD = "virtual_switch_threshold"
CONF_VIRTUAL_SWITCH_PRESS_ENTITY = "virtual_switch_press_entity"
CONF_VERIFY_SSL = "verify_ssl"
CONF_USE_HTTPS = "use_https"

# ---- Hub configuration keys ----
CONF_WIFI_SSID = "wifi_ssid"
CONF_WIFI_PASSWORD = "wifi_password"
CONF_WIFI_SSID2 = "wifi_ssid2"
CONF_WIFI_PASSWORD2 = "wifi_password2"
CONF_DEFAULT_USERNAME = "default_username"
CONF_DEFAULT_PASSWORD = "default_password"
CONF_SCAN_SUBNETS = "scan_subnets"
CONF_SCAN_INTERVAL_MIN = "scan_interval_minutes"
CONF_AP_AUTO_PROVISION = "ap_auto_provision"
CONF_AP_IP = "ap_ip"
CONF_AP_SSID_PATTERN = "ap_ssid_pattern"
CONF_AUTO_ADD_DISCOVERED = "auto_add_discovered"
CONF_HOSTNAME_TEMPLATE = "hostname_template"
CONF_TIMEZONE_CMD = "timezone_command"
CONF_WIFI_SCAN_ENABLED = "wifi_scan_enabled"

# ---- Defaults ----
DEFAULT_SCAN_INTERVAL = 5
DEFAULT_TIMEOUT = 5
DEFAULT_PROBE_TIMEOUT = 2
DEFAULT_VIRTUAL_THRESHOLD = 30
DEFAULT_AP_IP = "192.168.4.1"
DEFAULT_AP_SSID_PATTERN = "tasmota"
DEFAULT_SCAN_MINUTES = 10
DEFAULT_TIMEZONE_CMD = (
    "Backlog0 Timezone 99; "
    "TimeStd 0,0,10,1,3,60; "
    "TimeDst 0,0,3,1,2,120"
)
DEFAULT_HOSTNAME_TEMPLATE = ""

# ---- Service names ----
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
SERVICE_PROVISION_AP = "provision_ap"
SERVICE_PROVISION_DEVICE = "provision_device"
SERVICE_SCAN_NOW = "scan_now"

# ---- Internal hass.data layout ----
DATA_HUB = "hub"
DATA_DEVICES = "devices"
