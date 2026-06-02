"""Config flow for Impulse Counter integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_SOURCE_ENTITY,
    CONF_METER_TYPE,
    CONF_MULTIPLIER,
    CONF_INITIAL_VALUE,
    CONF_METER_NAME,
    METER_TYPE_WATER,
    METER_TYPE_GAS,
)

_LOGGER = logging.getLogger(__name__)


DOOR_WINDOW_CLASSES = {"door", "window", "opening", "garage_door"}


def _get_binary_sensors(hass):
    result = {}
    fallback = {}

    for state in hass.states.async_all("binary_sensor"):
        eid = state.entity_id
        name = state.attributes.get("friendly_name", eid)
        device_class = state.attributes.get("device_class", "")

        label = f"{name} ({eid})"
        fallback[eid] = label

        if device_class in DOOR_WINDOW_CLASSES:
            result[eid] = label

    # Daca nu gasim niciun senzor de usa/geam, aratam toti senzorii
    if not result:
        return dict(sorted(fallback.items(), key=lambda x: x[1]))

    return dict(sorted(result.items(), key=lambda x: x[1]))


class ImpulseCounterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        sensors = _get_binary_sensors(self.hass)
        if not sensors:
            return self.async_abort(reason="no_binary_sensors")

        if user_input is not None:
            name = user_input.get(CONF_METER_NAME, "").strip()
            if not name:
                errors[CONF_METER_NAME] = "name_required"
            elif not user_input.get(CONF_SOURCE_ENTITY):
                errors[CONF_SOURCE_ENTITY] = "entity_required"
            elif float(user_input.get(CONF_MULTIPLIER, 0)) <= 0:
                errors[CONF_MULTIPLIER] = "invalid_multiplier"
            else:
                await self.async_set_unique_id(f"{DOMAIN}_{user_input[CONF_SOURCE_ENTITY]}_{name}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_METER_NAME, default="Contor Apa"): str,
            vol.Required(CONF_SOURCE_ENTITY): vol.In(sensors),
            vol.Required(CONF_METER_TYPE, default=METER_TYPE_WATER): vol.In({
                METER_TYPE_WATER: "Apa",
                METER_TYPE_GAS: "Gaz",
            }),
            vol.Required(CONF_MULTIPLIER, default=100.0): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
            vol.Required(CONF_INITIAL_VALUE, default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0)),
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ImpulseCounterOptionsFlow()


class ImpulseCounterOptionsFlow(config_entries.OptionsFlow):
    """Options flow — HA 2024+ style: NO __init__, use self.config_entry directly."""

    def _current(self):
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            action = user_input.get("action")
            if action == "edit_config":
                return await self.async_step_edit_config()
            if action == "adjust_index":
                return await self.async_step_adjust_index()
            if action == "reset_counter":
                return await self.async_step_reset_counter()

        schema = vol.Schema({
            vol.Required("action"): vol.In({
                "edit_config":   "Modifica configuratia (senzor, tip, factor)",
                "adjust_index":  "Ajusteaza indexul (desincronizare)",
                "reset_counter": "Reseteaza contorul complet (schimb contor)",
            }),
        })
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_edit_config(self, user_input=None):
        errors = {}
        current = self._current()
        sensors = _get_binary_sensors(self.hass)

        if user_input is not None:
            if not user_input.get(CONF_SOURCE_ENTITY):
                errors[CONF_SOURCE_ENTITY] = "entity_required"
            elif float(user_input.get(CONF_MULTIPLIER, 0)) <= 0:
                errors[CONF_MULTIPLIER] = "invalid_multiplier"
            else:
                return self.async_create_entry(title="", data={**self.config_entry.options, **user_input})

        schema = vol.Schema({
            vol.Required(CONF_SOURCE_ENTITY, default=current.get(CONF_SOURCE_ENTITY)): vol.In(sensors),
            vol.Required(CONF_METER_TYPE, default=current.get(CONF_METER_TYPE, METER_TYPE_WATER)): vol.In({
                METER_TYPE_WATER: "Apa",
                METER_TYPE_GAS: "Gaz",
            }),
            vol.Required(CONF_MULTIPLIER, default=float(current.get(CONF_MULTIPLIER, 100.0))): vol.All(
                vol.Coerce(float), vol.Range(min=0.001)
            ),
        })
        return self.async_show_form(step_id="edit_config", data_schema=schema, errors=errors)

    async def async_step_adjust_index(self, user_input=None):
        errors = {}
        current = self._current()

        total_pulses = self.hass.data.get(DOMAIN, {}).get(f"pulses_{self.config_entry.entry_id}", 0)
        multiplier = float(current.get(CONF_MULTIPLIER, 1))
        old_initial = float(current.get(CONF_INITIAL_VALUE, 0))
        current_reading = round(old_initial + (total_pulses / multiplier), 3)

        if user_input is not None:
            try:
                new_index = float(user_input["new_index"])
                assert new_index >= 0
            except Exception:
                errors["new_index"] = "invalid_value"
            else:
                self.hass.bus.async_fire(
                    f"{DOMAIN}_adjust_index",
                    {"entry_id": self.config_entry.entry_id, "new_index": new_index},
                )
                return self.async_create_entry(title="", data=self.config_entry.options)

        schema = vol.Schema({
            vol.Required("new_index", default=current_reading): vol.All(vol.Coerce(float), vol.Range(min=0)),
        })
        return self.async_show_form(
            step_id="adjust_index",
            data_schema=schema,
            errors=errors,
            description_placeholders={"current_reading": str(current_reading)},
        )

    async def async_step_reset_counter(self, user_input=None):
        errors = {}

        if user_input is not None:
            if not user_input.get("confirm_reset", False):
                errors["confirm_reset"] = "must_confirm"
            else:
                new_initial = float(user_input.get("new_initial_value", 0.0))
                self.hass.bus.async_fire(
                    f"{DOMAIN}_reset",
                    {"entry_id": self.config_entry.entry_id, "new_initial_value": new_initial},
                )
                return self.async_create_entry(title="", data=self.config_entry.options)

        schema = vol.Schema({
            vol.Required("new_initial_value", default=0.0): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Required("confirm_reset", default=False): bool,
        })
        return self.async_show_form(step_id="reset_counter", data_schema=schema, errors=errors)
