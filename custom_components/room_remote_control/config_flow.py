from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import DOMAIN

CONF_TOPICS_TEXT = "topics_text"
CONF_LIGHTS = "lights"
CONF_EXTRA_OFF = "extra_off"
CONF_BUTTONS_TEXT = "buttons_text"
CONF_EFFECTS_TEXT = "effects_text"

DEFAULT_BUTTONS = """on=cycle:light.wiz_3
arrow_left_click=cycle:light.wiz_7
arrow_right_click=cycle:light.wiz_al_1,light.wiz_4
arrow_up_click=all_on
brightness_move_up=all_on
brightness_step_up=all_on
up=all_on
arrow_down_click=all_off
brightness_move_down=all_off
brightness_step_down=all_off
down=all_off
off_hold=all_off
off=all_off
arrow_right_hold=next_effect"""

DEFAULT_EFFECTS = """Warm white|80|435
Daylight|100|
Candlelight|25|"""

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
                vol.Required(CONF_NAME, default="alisa_spinne"): str,
                vol.Required(CONF_TOPICS_TEXT, default="zigbee2mqtt/licht_alisa\nzigbee2mqtt/licht_alisa/action"): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required(CONF_LIGHTS, default=["light.wiz_3", "light.wiz_7", "light.wiz_al_1", "light.wiz_4"]): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Optional(CONF_EXTRA_OFF, default=["light.hochbett"]): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Required(CONF_BUTTONS_TEXT, default=DEFAULT_BUTTONS): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional(CONF_EFFECTS_TEXT, default=DEFAULT_EFFECTS): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
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
                vol.Required(CONF_TOPICS_TEXT, default=data.get(CONF_TOPICS_TEXT, "")): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Required(CONF_LIGHTS, default=data.get(CONF_LIGHTS, [])): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Optional(CONF_EXTRA_OFF, default=data.get(CONF_EXTRA_OFF, [])): selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True)),
                vol.Required(CONF_BUTTONS_TEXT, default=data.get(CONF_BUTTONS_TEXT, DEFAULT_BUTTONS)): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional(CONF_EFFECTS_TEXT, default=data.get(CONF_EFFECTS_TEXT, DEFAULT_EFFECTS)): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
