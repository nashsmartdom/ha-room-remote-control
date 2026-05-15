from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .config_flow import CONF_BUTTONS_TEXT, CONF_EXTRA_OFF, CONF_LIGHTS, CONF_TOPICS_TEXT

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_CYCLE = [30, 10, 100, 80]


def parse_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def parse_buttons(text: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line in parse_lines(text):
        if "=" not in line:
            continue
        button, spec = line.split("=", 1)
        button = button.strip()
        spec = spec.strip()
        if spec.startswith("cycle:"):
            entities = [x.strip() for x in spec.removeprefix("cycle:").split(",") if x.strip()]
            result[button] = {"type": "cycle", "entities": entities}
        elif spec.startswith("effect:"):
            effect = spec.removeprefix("effect:").strip()
            result[button] = {"type": "effect", "effect": effect}
        elif spec in {"all_on", "all_off", "next_effect"}:
            result[button] = {"type": spec}
    return result


def extract_action(payload: Any) -> str | None:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "ignore")
    text = str(payload).strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and obj.get("action"):
            return str(obj["action"]).strip()
    except ValueError:
        pass
    return text


async def async_setup_entry_runtime(hass: HomeAssistant, entry) -> bool:
    data = {**entry.data, **entry.options}
    store = hass.data.setdefault(DOMAIN, {"entries": {}})
    entry_store = {
        "unsub": [],
        "active_lamps": list(data.get(CONF_LIGHTS, [])),
        "brightness_index": {},
        "effect_index": {},
        "buttons": parse_buttons(data.get(CONF_BUTTONS_TEXT, "")),
        "lights": list(data.get(CONF_LIGHTS, [])),
        "extra_off": list(data.get(CONF_EXTRA_OFF, [])),
    }
    store["entries"][entry.entry_id] = entry_store

    for topic in parse_lines(data.get(CONF_TOPICS_TEXT, "")):
        unsub = await mqtt.async_subscribe(hass, topic, make_handler(hass, entry.entry_id), 0)
        entry_store["unsub"].append(unsub)
        _LOGGER.info("Room Remote Control subscribed to %s", topic)

    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_unload_entry_runtime(hass: HomeAssistant, entry) -> bool:
    store = hass.data.get(DOMAIN, {}).get("entries", {}).pop(entry.entry_id, None)
    if not store:
        return True
    for unsub in store.get("unsub", []):
        unsub()
    return True


async def async_update_listener(hass: HomeAssistant, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def make_handler(hass: HomeAssistant, entry_id: str):
    @callback
    async def handler(msg) -> None:
        action = extract_action(msg.payload)
        if action:
            await handle_action(hass, entry_id, action)

    return handler


async def handle_action(hass: HomeAssistant, entry_id: str, action: str) -> None:
    store = hass.data[DOMAIN]["entries"].get(entry_id)
    if not store:
        return
    button = store["buttons"].get(action)
    if not button:
        _LOGGER.debug("Room Remote Control unmapped action: %s", action)
        return

    typ = button["type"]
    if typ == "cycle":
        entities = list(button.get("entities", []))
        idx = store["brightness_index"].get(action, 0)
        pct = BRIGHTNESS_CYCLE[idx % len(BRIGHTNESS_CYCLE)]
        store["brightness_index"][action] = idx + 1
        store["active_lamps"] = entities
        await call_light(hass, "turn_on", entities, brightness_pct=pct)
        return

    if typ == "all_on":
        entities = list(store["lights"])
        store["active_lamps"] = entities
        await call_light(hass, "turn_on", entities, brightness_pct=80, color_temp=435)
        return

    if typ == "all_off":
        await call_light(hass, "turn_off", list(store["lights"]) + list(store["extra_off"]))
        return

    if typ == "effect":
        entities = list(store["active_lamps"] or store["lights"])
        await apply_named_effect(hass, entities, button.get("effect"))
        return

    if typ == "next_effect":
        entities = list(store["active_lamps"] or store["lights"])
        await apply_next_entity_effect(hass, store, action, entities)
        return


async def apply_named_effect(hass: HomeAssistant, entities: list[str], effect: str | None) -> None:
    if not effect:
        return
    supported = [entity for entity in entities if effect in get_effect_list(hass, entity)]
    await call_light(hass, "turn_on", supported, effect=effect)


async def apply_next_entity_effect(hass: HomeAssistant, store: dict[str, Any], action: str, entities: list[str]) -> None:
    common = common_effects(hass, entities)
    if not common:
        return
    idx = store["effect_index"].get(action, 0)
    effect = common[idx % len(common)]
    store["effect_index"][action] = idx + 1
    await call_light(hass, "turn_on", entities, effect=effect)


def get_effect_list(hass: HomeAssistant, entity: str) -> list[str]:
    state = hass.states.get(entity)
    if not state:
        return []
    effects = state.attributes.get("effect_list") or []
    return [str(item) for item in effects]


def common_effects(hass: HomeAssistant, entities: list[str]) -> list[str]:
    lists = [get_effect_list(hass, entity) for entity in entities]
    lists = [items for items in lists if items]
    if not lists:
        return []
    common = set(lists[0])
    for items in lists[1:]:
        common &= set(items)
    return [effect for effect in lists[0] if effect in common]


async def call_light(hass: HomeAssistant, service: str, entities: list[str], **kwargs: Any) -> None:
    if not entities:
        return
    data = {CONF_ENTITY_ID: entities}
    data.update({k: v for k, v in kwargs.items() if v is not None})
    await hass.services.async_call("light", service, data, blocking=False)
