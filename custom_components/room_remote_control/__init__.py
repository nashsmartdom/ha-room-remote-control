from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ACTIONS,
    CONF_BRIGHTNESS_CYCLE,
    CONF_EFFECTS,
    CONF_ENTITIES,
    CONF_EXTRA_OFF,
    CONF_LAMPS,
    CONF_REMOTES,
    CONF_TOPICS,
    DEFAULT_BRIGHTNESS_CYCLE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_REMOTES): {
                    cv.string: {
                        vol.Required(CONF_TOPICS): vol.All(cv.ensure_list, [cv.string]),
                        vol.Optional(CONF_LAMPS, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
                        vol.Optional(CONF_EXTRA_OFF, default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
                        vol.Optional(CONF_BRIGHTNESS_CYCLE, default=DEFAULT_BRIGHTNESS_CYCLE): vol.All(
                            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=1, max=100))]
                        ),
                        vol.Optional(CONF_EFFECTS, default=[]): vol.All(cv.ensure_list, [dict]),
                        vol.Optional(CONF_ACTIONS, default={}): {cv.string: dict},
                    }
                }
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config.get(DOMAIN, {})
    remotes: dict[str, dict[str, Any]] = conf.get(CONF_REMOTES, {})
    data = hass.data.setdefault(
        DOMAIN,
        {"remotes": {}, "unsub": [], "effect_index": {}, "brightness_index": {}},
    )

    for remote_name, remote_conf in remotes.items():
        data["remotes"][remote_name] = {
            "conf": remote_conf,
            "active_lamps": list(remote_conf.get(CONF_LAMPS, [])),
        }
        data["effect_index"][remote_name] = 0
        data["brightness_index"].setdefault(remote_name, {})

        for topic in remote_conf.get(CONF_TOPICS, []):
            unsub = await mqtt.async_subscribe(
                hass,
                topic,
                _make_message_handler(hass, remote_name),
                0,
            )
            data["unsub"].append(unsub)
            _LOGGER.info("Room Remote Control: subscribed %s for %s", topic, remote_name)

    async def service_all_on(call: ServiceCall) -> None:
        await _run_builtin(hass, call.data.get("remote"), "all_on")

    async def service_all_off(call: ServiceCall) -> None:
        await _run_builtin(hass, call.data.get("remote"), "all_off")

    async def service_next_effect(call: ServiceCall) -> None:
        await _run_builtin(hass, call.data.get("remote"), "next_effect")

    async def service_reload(call: ServiceCall) -> None:
        _LOGGER.warning("Room Remote Control: YAML reload requires Home Assistant restart")

    hass.services.async_register(DOMAIN, "all_on", service_all_on)
    hass.services.async_register(DOMAIN, "all_off", service_all_off)
    hass.services.async_register(DOMAIN, "next_effect", service_next_effect)
    hass.services.async_register(DOMAIN, "reload", service_reload)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: Any) -> bool:
    return True

def _make_message_handler(hass: HomeAssistant, remote_name: str):
    @callback
    async def _message_received(msg) -> None:
        action = _extract_action(msg.payload)
        if not action:
            return
        await _handle_action(hass, remote_name, action)

    return _message_received

def _extract_action(payload: Any) -> str | None:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "ignore")
    text = str(payload).strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            value = obj.get("action")
            return str(value).strip() if value else None
    except ValueError:
        pass
    return text

async def _handle_action(hass: HomeAssistant, remote_name: str, action: str) -> None:
    remote = hass.data[DOMAIN]["remotes"].get(remote_name)
    if not remote:
        return
    conf = remote["conf"]
    action_conf = conf.get(CONF_ACTIONS, {}).get(action)
    if not action_conf:
        _LOGGER.debug("Room Remote Control: unmapped action %s for %s", action, remote_name)
        return
    await _execute_action(hass, remote_name, action, action_conf)

async def _run_builtin(hass: HomeAssistant, remote_name: str | None, action_type: str) -> None:
    names = [remote_name] if remote_name else list(hass.data[DOMAIN]["remotes"].keys())
    for name in names:
        await _execute_action(hass, name, action_type, {"type": action_type})

async def _execute_action(hass: HomeAssistant, remote_name: str, action_key: str, action_conf: dict[str, Any]) -> None:
    remote = hass.data[DOMAIN]["remotes"].get(remote_name)
    if not remote:
        return
    conf = remote["conf"]
    action_type = action_conf.get("type")

    if action_type == "cycle_brightness":
        entities = list(action_conf.get(CONF_ENTITIES, []))
        pct = _next_brightness(hass, remote_name, action_key, conf)
        await _turn_on(hass, entities, brightness_pct=pct, color_temp=action_conf.get("color_temp"))
        if action_conf.get("remember", True):
            remote["active_lamps"] = list(entities)
        return

    if action_type == "all_on":
        entities = list(conf.get(CONF_LAMPS, []))
        await _turn_on(hass, entities, brightness_pct=action_conf.get("brightness_pct", 80), color_temp=action_conf.get("color_temp"))
        if action_conf.get("remember", True):
            remote["active_lamps"] = list(entities)
        return

    if action_type == "all_off":
        entities = list(conf.get(CONF_LAMPS, [])) + list(conf.get(CONF_EXTRA_OFF, []))
        await _turn_off(hass, entities)
        return

    if action_type == "turn_on":
        entities = list(action_conf.get(CONF_ENTITIES, []))
        await _turn_on(hass, entities, brightness_pct=action_conf.get("brightness_pct"), color_temp=action_conf.get("color_temp"))
        if action_conf.get("remember", True):
            remote["active_lamps"] = list(entities)
        return

    if action_type == "turn_off":
        entities = list(action_conf.get(CONF_ENTITIES, []))
        if action_conf.get("include_extra_off"):
            entities += list(conf.get(CONF_EXTRA_OFF, []))
        await _turn_off(hass, entities)
        return

    if action_type == "next_effect":
        await _next_effect(hass, remote_name, action_conf)
        return

    _LOGGER.warning("Room Remote Control: unknown action type %s", action_type)

def _next_brightness(hass: HomeAssistant, remote_name: str, action_key: str, conf: dict[str, Any]) -> int:
    cycle = list(conf.get(CONF_BRIGHTNESS_CYCLE, DEFAULT_BRIGHTNESS_CYCLE))
    if not cycle:
        cycle = DEFAULT_BRIGHTNESS_CYCLE
    indexes = hass.data[DOMAIN]["brightness_index"].setdefault(remote_name, {})
    index = indexes.get(action_key, 0)
    pct = cycle[index % len(cycle)]
    indexes[action_key] = index + 1
    return pct

async def _turn_on(hass: HomeAssistant, entities: list[str], **kwargs: Any) -> None:
    if not entities:
        return
    data = {CONF_ENTITY_ID: entities}
    data.update({k: v for k, v in kwargs.items() if v is not None})
    await hass.services.async_call("light", "turn_on", data, blocking=False)

async def _turn_off(hass: HomeAssistant, entities: list[str]) -> None:
    if not entities:
        return
    await hass.services.async_call("light", "turn_off", {CONF_ENTITY_ID: entities}, blocking=False)

async def _next_effect(hass: HomeAssistant, remote_name: str, action_conf: dict[str, Any]) -> None:
    remote = hass.data[DOMAIN]["remotes"].get(remote_name)
    conf = remote["conf"]
    effects = list(conf.get(CONF_EFFECTS, []))
    if not effects:
        return
    target = action_conf.get("target", "remembered")
    entities = list(remote.get("active_lamps", [])) if target == "remembered" else list(action_conf.get(CONF_ENTITIES, []))
    if not entities:
        entities = list(conf.get(CONF_LAMPS, []))
    index = hass.data[DOMAIN]["effect_index"].get(remote_name, 0)
    effect_conf = effects[index % len(effects)]
    hass.data[DOMAIN]["effect_index"][remote_name] = index + 1
    data = {CONF_ENTITY_ID: entities}
    data.update(effect_conf)
    await hass.services.async_call("light", "turn_on", data, blocking=False)
