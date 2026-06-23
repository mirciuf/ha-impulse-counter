"""Constants for Impulse Counter integration."""

DOMAIN = "impulse_counter"
NAME = "Impulse Counter"
VERSION = "1.6.0"

# Config keys
CONF_SOURCE_ENTITY = "source_entity"
CONF_METER_TYPE = "meter_type"
CONF_MULTIPLIER = "multiplier"
CONF_INITIAL_VALUE = "initial_value"
CONF_METER_NAME = "meter_name"

# Meter types
METER_TYPE_WATER = "water"
METER_TYPE_GAS = "gas"

METER_TYPES = {
    METER_TYPE_WATER: {
        "name": "Apă",
        "icon": "mdi:water",
        "unit": "m³",
        "device_class": "water",
    },
    METER_TYPE_GAS: {
        "name": "Gaz",
        "icon": "mdi:fire",
        "unit": "m³",
        "device_class": "gas",
    },
}

# Storage
STORAGE_KEY = "impulse_counter_data"
STORAGE_VERSION = 1

# Attributes
ATTR_TOTAL_PULSES = "total_pulses"
ATTR_MULTIPLIER = "multiplier"
ATTR_INITIAL_VALUE = "initial_value"
ATTR_SOURCE_ENTITY = "source_entity"
ATTR_METER_TYPE = "meter_type"
ATTR_LAST_RESET = "last_reset"

# Event fired after adjust_index so __init__.py can calibrate
# any utility_meter helpers that use this sensor as source.
EVENT_INDEX_ADJUSTED = f"{DOMAIN}_index_adjusted"
