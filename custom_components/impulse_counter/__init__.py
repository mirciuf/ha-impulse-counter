"""Impulse Counter - Water & Gas meter using magnetic contact sensors."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import Platform
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Impulse Counter component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Impulse Counter from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Register services once (guard against multiple entries)
    if not hass.services.has_service(DOMAIN, "reset_counter"):
        async def handle_reset(call: ServiceCall) -> None:
            """Handle reset_counter service call."""
            entity_id = call.data.get("entity_id")
            new_initial = float(call.data.get("new_initial_value", 0.0))
            # Find the entry_id that owns this entity
            for eid, _data in hass.data[DOMAIN].items():
                if not isinstance(_data, dict):
                    continue
                sensor_entity_id = f"sensor.{_data.get('meter_name', '').lower().replace(' ', '_')}"
                # Fire by entry_id — sensor listens to the event
                hass.bus.async_fire(
                    f"{DOMAIN}_reset",
                    {"entry_id": eid, "new_initial_value": new_initial},
                )

        async def handle_adjust_index(call: ServiceCall) -> None:
            """Handle adjust_index service call."""
            new_index = float(call.data.get("new_index", 0.0))
            for eid in list(hass.data[DOMAIN].keys()):
                if not eid.startswith("pulse"):
                    hass.bus.async_fire(
                        f"{DOMAIN}_adjust_index",
                        {"entry_id": eid, "new_index": new_index},
                    )

        hass.services.async_register(
            DOMAIN,
            "reset_counter",
            handle_reset,
            schema=vol.Schema({
                vol.Optional("entity_id"): cv.entity_id,
                vol.Optional("new_initial_value", default=0.0): vol.Coerce(float),
            }),
        )

        hass.services.async_register(
            DOMAIN,
            "adjust_index",
            handle_adjust_index,
            schema=vol.Schema({
                vol.Optional("entity_id"): cv.entity_id,
                vol.Required("new_index"): vol.Coerce(float),
            }),
        )

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"pulses_{entry.entry_id}", None)
    return unload_ok
