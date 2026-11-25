"""Constants for the TCL TV LAN media_player integration."""

from homeassistant.const import Platform

DOMAIN = "tcl_tv"
PLATFORMS = [Platform.MEDIA_PLAYER, Platform.REMOTE, Platform.CAMERA]

CONF_CLIENT_ID = "client_id"
CONF_MAC = "mac"
CONF_ACTIVE_MAC = "active_mac"
CONF_MODEL = "model"
CONF_SOFTWARE_VERSION = "software_version"

# Optional IR power-on (Configure): remote + learned device/command.
# Calls remote.send_command; codes listed like ir_television (Broadlink /
# Harmony / Xiaomi Home storage files). Empty options → Wake-on-LAN.
CONF_POWER_ON_REMOTE = "power_on_remote"
CONF_POWER_ON_COMMAND = "power_on_command"
CONF_POWER_ON_DEVICE = "power_on_device"

# Manual input sources: [{name, hidden, buttons: [button.*…], interval}].
# T-Cast has no HDMI inventory; each source is a button-press sequence.
CONF_SOURCES = "sources"
CONF_SOURCE_NAME = "name"
CONF_SOURCE_ORDER = "source_order"

# Name the TV shows for this controller (159 handshake field 1).
CLIENT_NAME = "HomeAssistant"

RECONNECT_INTERVAL = 5.0
VOLUME_POLL_INTERVAL = 10.0
