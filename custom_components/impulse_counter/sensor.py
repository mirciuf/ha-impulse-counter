"""Sensor platform for Impulse Counter."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import STATE_ON, STATE_OPEN

from .const import (
    DOMAIN,
    CONF_SOURCE_ENTITY,
    CONF_METER_TYPE,
    CONF_MULTIPLIER,
    CONF_INITIAL_VALUE,
    CONF_METER_NAME,
    METER_TYPES,
    ATTR_TOTAL_PULSES,
    ATTR_MULTIPLIER,
    ATTR_INITIAL_VALUE,
    ATTR_SOURCE_ENTITY,
    ATTR_METER_TYPE,
    ATTR_LAST_RESET,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Impulse Counter sensor from a config entry."""
    config = {**entry.data, **entry.options}

    sensor = ImpulseCounterSensor(
        hass=hass,
        entry_id=entry.entry_id,
        name=config.get(CONF_METER_NAME, "Impulse Counter"),
        source_entity=config[CONF_SOURCE_ENTITY],
        meter_type=config[CONF_METER_TYPE],
        multiplier=float(config[CONF_MULTIPLIER]),
        initial_value=float(config[CONF_INITIAL_VALUE]),
    )

    async_add_entities([sensor], True)


class ImpulseCounterSensor(RestoreEntity, SensorEntity):
    """Representation of an Impulse Counter sensor."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        name: str,
        source_entity: str,
        meter_type: str,
        multiplier: float,
        initial_value: float,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._entry_id = entry_id
        self._name = name
        self._source_entity = source_entity
        self._meter_type = meter_type
        self._multiplier = multiplier
        self._initial_value = initial_value

        # Internal state
        self._total_pulses: int = 0
        self._last_source_state: str | None = None
        self._last_pulse_time: datetime | None = None

        meter_info = METER_TYPES.get(meter_type, METER_TYPES["water"])
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry_id}"
        self._attr_icon = meter_info["icon"]
        self._attr_native_unit_of_measurement = meter_info["unit"]

        if meter_type == "water":
            self._attr_device_class = SensorDeviceClass.WATER
        elif meter_type == "gas":
            self._attr_device_class = SensorDeviceClass.GAS

    @property
    def native_value(self) -> float:
        """Return the current meter reading in m³."""
        return round(
            self._initial_value + (self._total_pulses / self._multiplier), 3
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            ATTR_TOTAL_PULSES: self._total_pulses,
            ATTR_MULTIPLIER: self._multiplier,
            ATTR_INITIAL_VALUE: self._initial_value,
            ATTR_SOURCE_ENTITY: self._source_entity,
            ATTR_METER_TYPE: self._meter_type,
            ATTR_LAST_RESET: (
                self._last_pulse_time.isoformat() if self._last_pulse_time else None
            ),
        }

    def _publish_pulses(self) -> None:
        """Publish current pulse count to hass.data so config_flow can read it."""
        self.hass.data.setdefault(DOMAIN, {})
        self.hass.data[DOMAIN][f"pulses_{self._entry_id}"] = self._total_pulses

    async def async_added_to_hass(self) -> None:
        """Restore state and subscribe to events."""
        await super().async_added_to_hass()

        # Restore previous state
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                attrs = last_state.attributes
                self._total_pulses = int(attrs.get(ATTR_TOTAL_PULSES, 0))
                last_pulse_str = attrs.get(ATTR_LAST_RESET)
                if last_pulse_str:
                    self._last_pulse_time = datetime.fromisoformat(last_pulse_str)
                _LOGGER.debug(
                    "Restored %s: %s pulses → %.3f m³",
                    self._name, self._total_pulses, self.native_value,
                )
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Could not restore state for %s: %s", self._name, err)

        self._publish_pulses()

        # Listen to contact sensor state changes
        self.async_on_remove(
            self.hass.bus.async_listen("state_changed", self._handle_state_change)
        )

        # Listen to RESET event fired from options flow
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_reset", self._handle_reset_event
            )
        )

        # Listen to ADJUST INDEX event fired from options flow
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_adjust_index", self._handle_adjust_index_event
            )
        )

        # Snapshot current source entity state
        current = self.hass.states.get(self._source_entity)
        if current:
            self._last_source_state = current.state

    # ------------------------------------------------------------------ #
    #  Pulse counting                                                       #
    # ------------------------------------------------------------------ #

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Count a pulse on every OFF→ON (closed→open) transition."""
        if event.data.get("entity_id") != self._source_entity:
            return

        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        new_s = new_state.state
        old_s = old_state.state if old_state else None

        ACTIVE = {STATE_ON, STATE_OPEN, "on", "open"}

        if new_s in ACTIVE and old_s not in ACTIVE:
            self._total_pulses += 1
            self._last_pulse_time = datetime.now(timezone.utc)
            self._publish_pulses()
            _LOGGER.debug(
                "%s: pulse #%s → %.3f m³", self._name, self._total_pulses, self.native_value
            )

        self._last_source_state = new_s
        self.async_write_ha_state()

    # ------------------------------------------------------------------ #
    #  Reset (full – for meter replacement)                                #
    # ------------------------------------------------------------------ #

    @callback
    def _handle_reset_event(self, event: Event) -> None:
        """Handle reset fired from the options flow."""
        if event.data.get("entry_id") != self._entry_id:
            return
        new_initial = float(event.data.get("new_initial_value", 0.0))
        self._do_reset(new_initial)

    def _do_reset(self, new_initial_value: float) -> None:
        """Reset pulse counter and set a new initial index."""
        old_reading = self.native_value
        self._total_pulses = 0
        self._initial_value = new_initial_value
        self._last_pulse_time = datetime.now(timezone.utc)
        self._publish_pulses()
        self.async_write_ha_state()
        _LOGGER.info(
            "%s: RESET — old reading %.3f m³ → new initial %.3f m³",
            self._name, old_reading, new_initial_value,
        )

    # ------------------------------------------------------------------ #
    #  Adjust index (re-sync without losing pulse history)                 #
    # ------------------------------------------------------------------ #

    @callback
    def _handle_adjust_index_event(self, event: Event) -> None:
        """Handle index adjustment fired from the options flow."""
        if event.data.get("entry_id") != self._entry_id:
            return
        new_index = float(event.data.get("new_index", 0.0))
        self._do_adjust_index(new_index)

    def _do_adjust_index(self, new_index: float) -> None:
        """
        Recalculate initial_value so that:
            new_index = new_initial_value + (total_pulses / multiplier)
        Pulse history is preserved; only the offset shifts.
        """
        old_reading = self.native_value
        # new_initial = new_index - pulses_contribution
        pulses_contribution = self._total_pulses / self._multiplier
        self._initial_value = round(new_index - pulses_contribution, 3)
        self.async_write_ha_state()
        _LOGGER.info(
            "%s: INDEX ADJUSTED — old reading %.3f m³ → new reading %.3f m³ "
            "(initial_value now %.3f, pulses unchanged: %s)",
            self._name, old_reading, self.native_value,
            self._initial_value, self._total_pulses,
        )

    # ------------------------------------------------------------------ #
    #  Public service (callable from automations / scripts)               #
    # ------------------------------------------------------------------ #

    async def async_reset_counter(self, new_initial_value: float = 0.0) -> None:
        """Service call: full reset."""
        self._do_reset(new_initial_value)

    async def async_adjust_index(self, new_index: float) -> None:
        """Service call: adjust index without losing pulse history."""
        self._do_adjust_index(new_index)
