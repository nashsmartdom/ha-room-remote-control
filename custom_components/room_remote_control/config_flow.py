from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import DOMAIN

CONF_MQTT_BASE_TOPIC = "mqtt_base_topic"
CONF_REMOTE_FRIENDLY_NAME = "remote_friendly_name"
CONF_TOPICS_TEXT = "topics_text"
CONF_LIGHTS = "lights"
CONF_EXTRA_OFF = "extra_off"
CONF_BUTTONS_TEXT = "buttons_text"
MAP_PREFIX = "map__"

DEFAULT_BUTTONS = "# fallback rules, optional"

BASE_COMMANDS = {
    "ignore": "Ignore",
    "target": "Set active lights",
    "turn_on": "Turn on",
    "turn_off": "Turn off",
    "toggle": "Toggle",
    "all_on": "All on",
    "all_off": "All off",
    "brightness:+10": "Brightness +10%",
    "brightness:-10": "Brightness -10%",
    "kelvin:-300": "Warmer",
    "kelvin:+300": "Cooler",
    "next_effect": "Next effect",
}


def light_selector():
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True))


def text_selector():
    return selector.TextSelector(selector.TextSelectorConfig(multiline=True))


def discovered_actions_for_entry(hass, entry_id: str) -> list[str]:
    return list(hass.data.get(DOMAIN, {}).get("entries", {}).get(entry_id, {}).get("discovered_actions", []))


def map_field(action: str) -> str:
    return f"{MAP_PREFIX}{action}"


def effect_options(hass, lights: list[str]) -> dict[str, str]:
    out = dict(BASE_COMMANDS)
    seen: set[str] = set()
    for entity in lights:
        state = hass.states.get(entity)
        if not state:
            continue
        for effect in state.attributes.get("effect_list") or []:
            effect = str(effect)
            if effect not in seen:
                seen.add(effect)
                out[f"effect:{effect}"] = f"Effect: {effect}"
    return out


class RoomRemoteControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_NAME])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_NAME, default="Room remote"): str,
            vol.Required(CONF_MQTT_BASE_TOPIC, default="zigbee2mqtt"): str,
            vol.Required(CONF_REMOTE_FRIENDLY_NAME, default="remote_name"): str,
            vol.Optional(CONF_TOPICS_TEXT, default=""): text_selector(),
            vol.Required(CONF_LIGHTS, default=[]): light_selector(),
            vol.Optional(CONF_EXTRA_OFF, default=[]): light_selector(),
            vol.Optional(CONF_BUTTONS_TEXT, default=DEFAULT_BUTTONS): text_selector(),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors={})

    @staticmethod
    def async_get_options_flow(config_entry):
        return RoomRemoteControlOptionsFlow(config_entry)


class RoomRemoteControlOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        data = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        actions = discovered_actions_for_entry(self.hass, self._entry.entry_id)
        lights = list(data.get(CONF_LIGHTS, []))
        commands = effect_options(self.hass, lights)

        fields: dict[Any, Any] = {
            vol.Required(CONF_MQTT_BASE_TOPIC, default=data.get(CONF_MQTT_BASE_TOPIC, "zigbee2mqtt")): str,
            vol.Required(CONF_REMOTE_FRIENDLY_NAME, default=data.get(CONF_REMOTE_FRIENDLY_NAME, "")): str,
            vol.Optional(CONF_TOPICS_TEXT, default=data.get(CONF_TOPICS_TEXT, "")): text_selector(),
            vol.Required(CONF_LIGHTS, default=lights): light_selector(),
            vol.Optional(CONF_EXTRA_OFF, default=data.get(CONF_EXTRA_OFF, [])): light_selector(),
        }
        for action in actions:
            current = str(data.get(map_field(action), "ignore"))
            if current not in commands:
                current = "ignore"
            fields[vol.Optional(map_field(action), default=current)] = vol.In(commands)
        fields[vol.Optional(CONF_BUTTONS_TEXT, default=data.get(CONF_BUTTONS_TEXT, DEFAULT_BUTTONS))] = text_selector()
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields), errors={})
