"""Constants for the TCL TV LAN media_player integration."""

from homeassistant.const import Platform

DOMAIN = "tcl_tv"
PLATFORMS = [Platform.MEDIA_PLAYER, Platform.REMOTE]

CONF_CLIENT_ID = "client_id"
CONF_MAC = "mac"
CONF_ACTIVE_MAC = "active_mac"
CONF_MODEL = "model"
CONF_SOFTWARE_VERSION = "software_version"

# Name the TV shows for this controller (159 handshake field 1).
CLIENT_NAME = "HomeAssistant"

RECONNECT_INTERVAL = 5.0
VOLUME_POLL_INTERVAL = 10.0
