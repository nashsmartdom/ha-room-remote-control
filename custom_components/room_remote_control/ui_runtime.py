from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .config_flow import CONF_BUTTONS_TEXT, CONF_EFFECTS_TEXT, CONF_EXTRA_OFF, CONF_LIGHTS, CONF_TOPICS_TEXT

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
        elif spec in {"all_on", "all_off", "next_effect"}:
            result[button] = {"type": spec}
    return result


def parse_effects(text: str) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for line in parse_lines(text):
        parts = [p.strip() for p in line.split("|")]
        if not parts or not parts[0]:
            continue
        item: dict[str, Any] = {"effect": parts[0]}
        if len(parts) > 1 and parts[1]:
            item["brightness_pct"] = int(parts[1])
        if len(parts) > 2 and parts[2]:
            item["color_temp"] = int(parts[2])
        effects.append(item)
    return effects


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
        "effect_index": 0,
        "buttons": parse_buttons(data.get(CONF_BUTTONS_TEXT, "")),
        "effects": parse_effects(data.get(CONF_EFFECTS_TEXT, "")),
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

    if typ == "next_effect":
        effects = store["effects"]
        if not effects:
            return
        idx = store["effect_index"]
        effect = effects[idx % len(effects)]
        store["effect_index"] = idx + 1
        entities = list(store["active_lamps"] or store["lights"])
        await call_light(hass, "turn_on", entities, **effect)


async def call_light(hass: HomeAssistant, service: str, entities: list[str], **kwargs: Any) -> None:
    if not entities:
        return
    data = {CONF_ENTITY_ID: entities}
    data.update({k: v for k, v in kwargs.items() if v is not None})
    await hass.services.async_call("light", service, data, blocking=False)
