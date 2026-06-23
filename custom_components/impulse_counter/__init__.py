"""Impulse Counter - Water & Gas meter using magnetic contact sensors."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, Event, callback
from homeassistant.const import Platform
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, EVENT_INDEX_ADJUSTED

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

    # Listen for index adjustments and auto-calibrate any utility_meter
    # helpers that use our sensor as their source. This prevents
    # utility_meter from recording negative consumption for the period
    # in which the index was corrected (e.g. after a dead/disconnected
    # sensor was re-synced to a lower physical reading).
    if not hass.data[DOMAIN].get("_calibrate_listener_registered"):
        hass.data[DOMAIN]["_calibrate_listener_registered"] = True

        @callback
        def _handle_index_adjusted(event: Event) -> None:
            hass.async_create_task(_calibrate_utility_meters(hass, event))

        hass.bus.async_listen(EVENT_INDEX_ADJUSTED, _handle_index_adjusted)

    return True


async def _calibrate_utility_meters(hass: HomeAssistant, event: Event) -> None:
    """Find utility_meter entities sourced from our sensor and calibrate them."""
    source_entity_id = event.data.get("entity_id")
    new_value = event.data.get("new_value")
    if not source_entity_id or new_value is None:
        return

    found_any = False

    for um_entry in hass.config_entries.async_entries("utility_meter"):
        um_config = {**um_entry.data, **um_entry.options}
        if um_config.get("source") != source_entity_id:
            continue

        # The utility_meter helper creates one sensor per tariff/cycle.
        # We need to find its actual entity_id(s) via the entity registry.
        from homeassistant.helpers import entity_registry as er
        ent_reg = er.async_get(hass)
        entries = er.async_entries_for_config_entry(ent_reg, um_entry.entry_id)

        for reg_entry in entries:
            found_any = True
            _LOGGER.info(
                "Auto-calibrating utility_meter %s to %.3f (source %s was index-adjusted)",
                reg_entry.entity_id, new_value, source_entity_id,
            )
            try:
                await hass.services.async_call(
                    "utility_meter",
                    "calibrate",
                    {
                        "entity_id": reg_entry.entity_id,
                        "value": new_value,
                    },
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Could not auto-calibrate utility_meter %s: %s",
                    reg_entry.entity_id, err,
                )

    if found_any:
        await hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "✅ Contor recalibrat",
                "message": (
                    f"Senzorul `{source_entity_id}` a fost ajustat la {new_value} m³.\n\n"
                    f"Toate utility meter-ele asociate au fost recalibrate automat — "
                    f"nu va apărea consum negativ în Energy Dashboard."
                ),
                "notification_id": f"impulse_counter_calibrated_{source_entity_id.replace('.', '_')}",
            },
        )


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options.

    Skip the reload when this update was triggered internally by
    _persist_initial_value() (adjust_index/reset). Reloading the
    integration at that moment destroys and recreates the entity
    BEFORE the just-updated state (with the new last_reset) has been
    written/processed by the recorder, causing last_reset to be lost
    on restore and the adjustment to be recorded as a large false
    delta in statistics. Reload is still needed for real config
    changes made via the "edit_config"/"edit_params" options steps,
    so we only skip it when the sensor itself flagged this specific
    update as internal (via hass.data, never via entry.options, to
    avoid recursively triggering this same listener again).
    """
    skip_key = f"_skip_reload_{entry.entry_id}"
    if hass.data.get(DOMAIN, {}).pop(skip_key, False):
        _LOGGER.debug("Skipping reload for internal initial_value persistence on %s", entry.entry_id)
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"pulses_{entry.entry_id}", None)
    return unload_ok
