"""Constants for the TCL TV LAN media_player integration."""

from homeassistant.const import Platform

DOMAIN = "tcl_tv"
PLATFORMS = [Platform.MEDIA_PLAYER, Platform.REMOTE]

CONF_CLIENT_ID = "client_id"
CONF_MAC = "mac"
CONF_ACTIVE_MAC = "active_mac"
CONF_MODEL = "model"
CONF_SOFTWARE_VERSION = "software_version"

# Optional HA button entity pressed when media_player.turn_on / remote.turn_on.
CONF_POWER_ON_BUTTON = "power_on_button"

# Name the TV shows for this controller (159 handshake field 1).
CLIENT_NAME = "HomeAssistant"

RECONNECT_INTERVAL = 5.0
VOLUME_POLL_INTERVAL = 10.0
