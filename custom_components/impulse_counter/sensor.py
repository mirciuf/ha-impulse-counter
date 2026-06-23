"""Sensor platform for Impulse Counter."""
from __future__ import annotations

import logging
import math
from collections import deque
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import STATE_ON, STATE_OPEN

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData

from .const import (
    DOMAIN,
    CONF_SOURCE_ENTITY,
    CONF_METER_TYPE,
    CONF_MULTIPLIER,
    CONF_INITIAL_VALUE,
    CONF_METER_NAME,
    METER_TYPES,
    METER_TYPE_WATER,
    METER_TYPE_GAS,
    ATTR_TOTAL_PULSES,
    ATTR_MULTIPLIER,
    ATTR_INITIAL_VALUE,
    ATTR_SOURCE_ENTITY,
    ATTR_METER_TYPE,
    ATTR_LAST_RESET,
    EVENT_INDEX_ADJUSTED,
)

_LOGGER = logging.getLogger(__name__)

# Fereastra de timp pentru calculul debitului (secunde)
FLOW_WINDOW_SECONDS = 60


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Impulse Counter sensor from a config entry."""
    config = {**entry.data, **entry.options}

    meter_sensor = ImpulseCounterSensor(
        hass=hass,
        entry_id=entry.entry_id,
        name=config.get(CONF_METER_NAME, "Impulse Counter"),
        source_entity=config[CONF_SOURCE_ENTITY],
        meter_type=config[CONF_METER_TYPE],
        multiplier=float(config[CONF_MULTIPLIER]),
        initial_value=float(config[CONF_INITIAL_VALUE]),
    )

    flow_sensor = ImpulseCounterFlowSensor(
        hass=hass,
        entry_id=entry.entry_id,
        name=config.get(CONF_METER_NAME, "Impulse Counter"),
        meter_type=config[CONF_METER_TYPE],
        multiplier=float(config[CONF_MULTIPLIER]),
        meter_sensor=meter_sensor,
    )

    # Legatem senzorul de debit la cel principal
    meter_sensor.set_flow_sensor(flow_sensor)

    async_add_entities([meter_sensor, flow_sensor], True)


# ═══════════════════════════════════════════════════════════════════
#  Senzorul principal — index m³
# ═══════════════════════════════════════════════════════════════════

class ImpulseCounterSensor(RestoreEntity, SensorEntity):
    """Representation of an Impulse Counter sensor."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL
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
        self._flow_sensor: ImpulseCounterFlowSensor | None = None

        # Internal state
        self._total_pulses: int = 0
        self._last_source_state: str | None = None
        self._last_pulse_time: datetime | None = None
        self._attr_last_reset: datetime | None = None

        meter_info = METER_TYPES.get(meter_type, METER_TYPES["water"])
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry_id}"
        self._attr_icon = meter_info["icon"]
        self._attr_native_unit_of_measurement = meter_info["unit"]

        if meter_type == METER_TYPE_WATER:
            self._attr_device_class = SensorDeviceClass.WATER
        elif meter_type == METER_TYPE_GAS:
            self._attr_device_class = SensorDeviceClass.GAS

        # Numarul de zecimale din factorul de multiplicare
        if multiplier >= 1:
            self._decimals = max(1, int(math.log10(multiplier)))
        else:
            self._decimals = 1
        self._attr_suggested_display_precision = self._decimals

    def set_flow_sensor(self, flow_sensor: "ImpulseCounterFlowSensor") -> None:
        """Link the flow sensor so we can notify it on each pulse."""
        self._flow_sensor = flow_sensor

    @property
    def native_value(self) -> float:
        """Return the current meter reading in m³."""
        return round(
            self._initial_value + (self._total_pulses / self._multiplier),
            self._decimals,
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
            # NOTE: "last_reset" itself is the native HA property
            # (self._attr_last_reset), automatically merged into the
            # entity's attributes by the base SensorEntity class. We
            # expose the last pulse timestamp separately to avoid
            # colliding with / shadowing that native attribute.
            "last_pulse_time": (
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
                last_pulse_str = attrs.get("last_pulse_time")
                if last_pulse_str:
                    self._last_pulse_time = datetime.fromisoformat(last_pulse_str)
                # Restore the native last_reset property too, so HA's
                # statistics engine doesn't see a fresh reset on every
                # restart (which would otherwise zero out the running sum).
                last_reset_native = last_state.attributes.get("last_reset")
                if last_reset_native:
                    try:
                        self._attr_last_reset = datetime.fromisoformat(last_reset_native)
                    except (ValueError, TypeError):
                        pass
                _LOGGER.debug(
                    "Restored %s: %s pulses → %.3f m³",
                    self._name, self._total_pulses, self.native_value,
                )
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Could not restore state for %s: %s", self._name, err)

        self._publish_pulses()

        self.async_on_remove(
            self.hass.bus.async_listen("state_changed", self._handle_state_change)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_reset", self._handle_reset_event)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_adjust_index", self._handle_adjust_index_event)
        )

        current = self.hass.states.get(self._source_entity)
        if current:
            self._last_source_state = current.state

    # ------------------------------------------------------------------ #
    #  Pulse counting
    # ------------------------------------------------------------------ #

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Count a pulse on every OFF→ON transition."""
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
            now = datetime.now(timezone.utc)
            self._total_pulses += 1
            self._last_pulse_time = now
            self._publish_pulses()

            # Notifica senzorul de debit
            if self._flow_sensor is not None:
                self._flow_sensor.register_pulse(now)

            _LOGGER.debug(
                "%s: pulse #%s → %.3f m³", self._name, self._total_pulses, self.native_value
            )

        self._last_source_state = new_s
        self.async_write_ha_state()

    def _persist_initial_value(self) -> None:
        """Save the current _initial_value into the ConfigEntry's options.

        CRITICAL: async_setup_entry reads initial_value from entry.data/
        entry.options every time the integration is loaded (startup,
        reload, restart). Without persisting here, adjust_index/reset
        only change self._initial_value in memory — the next restart
        reloads the OLD value from the entry, silently undoing the
        correction and causing a large false delta (positive or
        negative) in the Energy dashboard / utility_meter statistics.

        We flag this update as internal via hass.data so __init__.py's
        async_update_options skips the automatic reload it would
        otherwise trigger — reloading right now, before this entity's
        freshly-set last_reset has been written out, would destroy and
        recreate the entity and restore the OLD last_reset, defeating
        the whole point of marking this moment as a reset point.
        """
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            _LOGGER.warning(
                "%s: Could not find config entry %s to persist initial_value",
                self._name, self._entry_id,
            )
            return
        self.hass.data.setdefault(DOMAIN, {})[f"_skip_reload_{self._entry_id}"] = True
        new_options = {**entry.options, CONF_INITIAL_VALUE: self._initial_value}
        self.hass.config_entries.async_update_entry(entry, options=new_options)

    # ------------------------------------------------------------------ #
    #  Reset
    # ------------------------------------------------------------------ #

    @callback
    def _handle_reset_event(self, event: Event) -> None:
        if event.data.get("entry_id") != self._entry_id:
            return
        self._do_reset(float(event.data.get("new_initial_value", 0.0)))

    def _do_reset(self, new_initial_value: float) -> None:
        old_reading = self.native_value
        self._total_pulses = 0
        self._initial_value = new_initial_value
        now = datetime.now(timezone.utc)
        self._last_pulse_time = now
        self._publish_pulses()
        if self._flow_sensor is not None:
            self._flow_sensor.clear_pulses()
        self.async_write_ha_state()
        self._persist_initial_value()

        # A full meter reset/replacement should never count as
        # consumption, regardless of direction — write the statistics
        # sum unchanged (delta = 0) directly via the recorder API.
        self.hass.async_create_task(self._async_correct_statistics(0.0))

        _LOGGER.info(
            "%s: RESET — old reading %.3f m³ → new initial %.3f m³ (persisted, statistics unaffected)",
            self._name, old_reading, new_initial_value,
        )

    # ------------------------------------------------------------------ #
    #  Adjust index
    # ------------------------------------------------------------------ #

    @callback
    def _handle_adjust_index_event(self, event: Event) -> None:
        if event.data.get("entry_id") != self._entry_id:
            return
        self._do_adjust_index(float(event.data.get("new_index", 0.0)))

    def _do_adjust_index(self, new_index: float) -> None:
        old_reading = self.native_value
        delta = round(new_index - old_reading, 3)
        self._initial_value = round(new_index - (self._total_pulses / self._multiplier), 3)

        # Publish the new state immediately so the UI/automations see the
        # corrected reading right away.
        self.async_write_ha_state()

        # Persist the new initial_value to the config entry. Without
        # this, the adjustment only lives in memory and is silently
        # lost on the next restart/reload, causing a large false delta
        # (the sensor "snaps back" toward the old value).
        self._persist_initial_value()

        # CRITICAL FIX: correct the long-term statistics DIRECTLY via
        # the recorder's official statistics API, instead of relying on
        # last_reset. In practice, last_reset did not reliably suppress
        # the jump when this entity's state_changed event was processed
        # (observed: the recorder still added the full new value as
        # consumption for that hour, regardless of last_reset). Writing
        # the correct sum directly removes that ambiguity entirely:
        #   - new_index < old_reading (downward correction): write sum
        #     unchanged (delta = 0) for this point — no false negative
        #     consumption.
        #   - new_index > old_reading (sensor was frozen, real usage
        #     happened in the background): write sum + delta — the real
        #     consumption is recorded on the day of the adjustment.
        self.hass.async_create_task(self._async_correct_statistics(delta))

        _LOGGER.info(
            "%s: INDEX ADJUSTED — %.3f m³ → %.3f m³ (delta %.3f, statistics corrected directly)",
            self._name, old_reading, self.native_value, delta,
        )

        # Fire event so __init__.py can calibrate any utility_meter
        # helpers that use this sensor as their source (if configured
        # as separate utility_meter helpers rather than added directly
        # to the Energy dashboard).
        self.hass.bus.async_fire(
            EVENT_INDEX_ADJUSTED,
            {
                "entity_id": self.entity_id,
                "new_value": self.native_value,
            },
        )

    async def _async_correct_statistics(self, delta: float) -> None:
        """Write a corrected statistics point directly to the recorder.

        This bypasses last_reset entirely (which was found to not
        reliably suppress the jump when the entity's state_changed
        event is processed by the recorder). Instead we read the last
        known sum for this entity and write a new hourly statistics
        point with sum = last_sum + effective_delta, where
        effective_delta is 0 for a downward index correction (no false
        negative consumption) or the real difference for an upward
        correction (real consumption recorded on the day of the
        adjustment).
        """
        statistic_id = self.entity_id
        if not statistic_id:
            _LOGGER.warning("%s: entity_id not yet assigned, cannot correct statistics", self._name)
            return

        recorder_instance = get_instance(self.hass)

        try:
            last_stats = await recorder_instance.async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True, {"sum", "state"}
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: could not read last statistics: %s", self._name, err)
            return

        last_sum = 0.0
        if statistic_id in last_stats and last_stats[statistic_id]:
            last_sum = last_stats[statistic_id][0].get("sum") or 0.0

        # Effective delta to apply: 0 if the index was lowered (avoid
        # negative consumption), otherwise the real positive difference.
        effective_delta = max(delta, 0.0)
        new_sum = round(last_sum + effective_delta, 3)

        now_hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=self._attr_name,
            source="recorder",
            statistic_id=statistic_id,
            unit_of_measurement=self._attr_native_unit_of_measurement,
        )

        stat_point: StatisticData = {
            "start": now_hour_start,
            "state": self.native_value,
            "sum": new_sum,
        }

        try:
            async_import_statistics(self.hass, metadata, [stat_point])
            _LOGGER.info(
                "%s: statistics corrected — sum %.3f → %.3f (delta applied: %.3f)",
                self._name, last_sum, new_sum, effective_delta,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: could not write corrected statistics: %s", self._name, err)

    async def async_reset_counter(self, new_initial_value: float = 0.0) -> None:
        self._do_reset(new_initial_value)

    async def async_adjust_index(self, new_index: float) -> None:
        self._do_adjust_index(new_index)


# ═══════════════════════════════════════════════════════════════════
#  Senzorul de debit — L/min (apă) sau m³/h (gaz)
# ═══════════════════════════════════════════════════════════════════

class ImpulseCounterFlowSensor(SensorEntity):
    """Flow rate sensor derived from pulse timestamps."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        name: str,
        meter_type: str,
        multiplier: float,
        meter_sensor: ImpulseCounterSensor,
    ) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._meter_type = meter_type
        self._multiplier = multiplier
        self._meter_sensor = meter_sensor

        # Coada cu timestamp-urile impulsurilor din ultimele 60 secunde
        self._pulse_times: deque = deque()

        self._attr_unique_id = f"{DOMAIN}_{entry_id}_flow"

        if meter_type == METER_TYPE_WATER:
            # Apa: L/min
            self._attr_name = f"{name} Debit"
            self._attr_icon = "mdi:water-pump"
            self._attr_native_unit_of_measurement = "L/min"
            self._attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
            self._attr_suggested_display_precision = 1
        else:
            # Gaz: m³/h
            self._attr_name = f"{name} Debit"
            self._attr_icon = "mdi:fire"
            self._attr_native_unit_of_measurement = "m³/h"
            self._attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
            self._attr_suggested_display_precision = 3

    @callback
    def register_pulse(self, pulse_time: datetime) -> None:
        """Called by main sensor on every pulse."""
        self._pulse_times.append(pulse_time)
        self._cleanup_old_pulses(pulse_time)
        self.async_write_ha_state()

    @callback
    def clear_pulses(self) -> None:
        """Clear pulse history on reset."""
        self._pulse_times.clear()
        self.async_write_ha_state()

    def _cleanup_old_pulses(self, now: datetime) -> None:
        """Remove pulses older than FLOW_WINDOW_SECONDS."""
        cutoff = now.timestamp() - FLOW_WINDOW_SECONDS
        while self._pulse_times and self._pulse_times[0].timestamp() < cutoff:
            self._pulse_times.popleft()

    @property
    def native_value(self) -> float:
        """Calculate flow rate from pulses in the last 60 seconds."""
        now = datetime.now(timezone.utc)
        self._cleanup_old_pulses(now)

        pulses_in_window = len(self._pulse_times)

        if pulses_in_window == 0:
            return 0.0

        # m³ consumati in fereastra de 60 secunde
        m3_in_window = pulses_in_window / self._multiplier

        if self._meter_type == METER_TYPE_WATER:
            # Convertim in L/min: m³ = 1000L, fereastra = 60s = 1 min
            flow = m3_in_window * 1000.0
            return round(flow, 1)
        else:
            # Gaz: m³/h — extrapolam fereastra de 60s la 1 ora
            flow = m3_in_window * 60.0
            return round(flow, 3)

    async def async_added_to_hass(self) -> None:
        """Start periodic timer to reset flow to 0 when no pulses arrive."""
        await super().async_added_to_hass()

        async def _check_flow(_now=None):
            """Curata impulsurile vechi si forteaza update la 0 daca e cazul."""
            old_count = len(self._pulse_times)
            self._cleanup_old_pulses(datetime.now(timezone.utc))
            new_count = len(self._pulse_times)
            if new_count != old_count or new_count == 0:
                self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                _check_flow,
                timedelta(seconds=15),
            )
        )
