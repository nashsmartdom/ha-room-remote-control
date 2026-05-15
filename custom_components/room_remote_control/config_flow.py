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

class RoomRemoteControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_NAME])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Room remote"): str,
                vol.Required(CONF_MQTT_BASE_TOPIC, default="zigbee2mqtt"): str,
                vol.Required(CONF_REMOTE_FRIENDLY_NAME, default="remote_name"): str,
                vol.Optional(CONF_TOPICS_TEXT, default=""): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required(CONF_LIGHTS, default=[]): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Optional(CONF_EXTRA_OFF, default=[]): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Required(CONF_BUTTONS_TEXT, default=DEFAULT_BUTTONS): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return RoomRemoteControlOptionsFlow(config_entry)

class RoomRemoteControlOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        data = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_MQTT_BASE_TOPIC, default=data.get(CONF_MQTT_BASE_TOPIC, "zigbee2mqtt")): str,
                vol.Required(CONF_REMOTE_FRIENDLY_NAME, default=data.get(CONF_REMOTE_FRIENDLY_NAME, "")): str,
                vol.Optional(CONF_TOPICS_TEXT, default=data.get(CONF_TOPICS_TEXT, "")): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required(CONF_LIGHTS, default=data.get(CONF_LIGHTS, [])): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Optional(CONF_EXTRA_OFF, default=data.get(CONF_EXTRA_OFF, [])): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Required(CONF_BUTTONS_TEXT, default=data.get(CONF_BUTTONS_TEXT, DEFAULT_BUTTONS)): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
