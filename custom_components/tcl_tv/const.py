"""Constants for the TCL TV LAN media_player integration."""

from homeassistant.const import Platform

DOMAIN = "tcl_tv"
PLATFORMS = [Platform.MEDIA_PLAYER, Platform.REMOTE]

CONF_CLIENT_ID = "client_id"
CONF_MAC = "mac"
CONF_ACTIVE_MAC = "active_mac"
CONF_MODEL = "model"
CONF_SOFTWARE_VERSION = "software_version"

# Optional IR blaster used when media_player.turn_on / remote.turn_on.
# Calls remote.send_command on the selected remote entity.
CONF_POWER_ON_REMOTE = "power_on_remote"
CONF_POWER_ON_COMMAND = "power_on_command"
CONF_POWER_ON_DEVICE = "power_on_device"

# Name the TV shows for this controller (159 handshake field 1).
CLIENT_NAME = "HomeAssistant"

RECONNECT_INTERVAL = 5.0
VOLUME_POLL_INTERVAL = 10.0
