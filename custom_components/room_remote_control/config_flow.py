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

DEFAULT_BUTTONS = """button_1=target:light.example_1
button_2=toggle:light.example_1
button_3=brightness:+10
button_4=brightness:-10
button_5=kelvin:+300
button_6=kelvin:-300
button_7=next_effect
button_8=all_off"""


def light_selector():
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True))


def text_selector():
    return selector.TextSelector(selector.TextSelectorConfig(multiline=True))


def discovered_actions_for_entry(hass, entry_id: str) -> list[str]:
    return list(hass.data.get(DOMAIN, {}).get("entries", {}).get(entry_id, {}).get("discovered_actions", []))


def rules_template(actions: list[str], current: str) -> str:
    if current and "button_1=" not in current:
        return current
    if not actions:
        return current or DEFAULT_BUTTONS
    return "\n".join(f"{action}=target:light.example_1" for action in actions)


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
            vol.Required(CONF_BUTTONS_TEXT, default=DEFAULT_BUTTONS): text_selector(),
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
        default_rules = rules_template(actions, data.get(CONF_BUTTONS_TEXT, DEFAULT_BUTTONS))
        schema = vol.Schema({
            vol.Required(CONF_MQTT_BASE_TOPIC, default=data.get(CONF_MQTT_BASE_TOPIC, "zigbee2mqtt")): str,
            vol.Required(CONF_REMOTE_FRIENDLY_NAME, default=data.get(CONF_REMOTE_FRIENDLY_NAME, "")): str,
            vol.Optional(CONF_TOPICS_TEXT, default=data.get(CONF_TOPICS_TEXT, "")): text_selector(),
            vol.Required(CONF_LIGHTS, default=data.get(CONF_LIGHTS, [])): light_selector(),
            vol.Optional(CONF_EXTRA_OFF, default=data.get(CONF_EXTRA_OFF, [])): light_selector(),
            vol.Required(CONF_BUTTONS_TEXT, default=default_rules): text_selector(),
        })
        return self.async_show_form(step_id="init", data_schema=schema, errors={})
