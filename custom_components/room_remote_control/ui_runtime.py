from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.const import CONF_ENTITY_ID, STATE_ON
from homeassistant.core import HomeAssistant, callback

from .config_flow import (
    CONF_BUTTONS_TEXT,
    CONF_EXTRA_OFF,
    CONF_LIGHTS,
    CONF_MQTT_BASE_TOPIC,
    CONF_REMOTE_FRIENDLY_NAME,
    CONF_TOPICS_TEXT,
    MAP_PREFIX,
)
from .const import DOMAIN
from .z2m import actions_from_bridge_devices

_LOGGER = logging.getLogger(__name__)


def lines(text: str) -> list[str]:
    return [x.strip() for x in str(text or "").splitlines() if x.strip() and not x.strip().startswith("#")]


def csv(text: str) -> list[str]:
    return [x.strip() for x in str(text or "").split(",") if x.strip()]


def ints(text: str) -> list[int]:
    return [int(x.strip()) for x in str(text or "").split(",") if x.strip()]


def base_topic(data: dict[str, Any]) -> str:
    return str(data.get(CONF_MQTT_BASE_TOPIC, "zigbee2mqtt")).strip().strip("/")


def remote_name(data: dict[str, Any]) -> str:
    return str(data.get(CONF_REMOTE_FRIENDLY_NAME, "")).strip().strip("/")


def action_topics(data: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    base = base_topic(data)
    remote = remote_name(data)
    if base and remote:
        topics.append(f"{base}/{remote}/action")
    topics.extend(lines(data.get(CONF_TOPICS_TEXT, "")))
    return list(dict.fromkeys(topics))


def bridge_devices_topics(data: dict[str, Any]) -> list[str]:
    base = base_topic(data)
    if not base:
        return []
    return [f"{base}/bridge/devices", f"{base}/bridge/response/devices"]


def bridge_request_devices_topic(data: dict[str, Any]) -> str | None:
    base = base_topic(data)
    return f"{base}/bridge/request/devices" if base else None


def command_to_button(command: str) -> dict[str, Any] | None:
    command = str(command or "ignore").strip()
    if command == "ignore":
        return None
    if command in {"target", "turn_on", "turn_off", "toggle", "all_on", "all_off", "next_effect"}:
        return {"type": command}
    if command.startswith("brightness:"):
        return {"type": "brightness", "step": int(command.split(":", 1)[1])}
    if command.startswith("kelvin:"):
        return {"type": "kelvin", "step": int(command.split(":", 1)[1])}
    if command.startswith("effect:"):
        return {"type": "effect", "effect": command.split(":", 1)[1]}
    return None


def parse_buttons(text: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in lines(text):
        if "=" not in row:
            continue
        key, spec = [x.strip() for x in row.split("=", 1)]
        parts = spec.split(":", 2)
        cmd = parts[0].strip()
        if cmd in {"all_on", "all_off", "next_effect"}:
            out[key] = {"type": cmd}
        elif cmd in {"target", "turn_on", "turn_off", "toggle"} and len(parts) > 1:
            out[key] = {"type": cmd, "entities": csv(parts[1])}
        elif cmd == "brightness" and len(parts) > 1:
            out[key] = {"type": "brightness", "step": int(parts[1]), "entities": csv(parts[2]) if len(parts) > 2 else []}
        elif cmd == "kelvin" and len(parts) > 1:
            out[key] = {"type": "kelvin", "step": int(parts[1]), "entities": csv(parts[2]) if len(parts) > 2 else []}
        elif cmd == "cycle_brightness" and len(parts) > 1:
            out[key] = {"type": "cycle_brightness", "values": ints(parts[1]), "entities": csv(parts[2]) if len(parts) > 2 else []}
        elif cmd == "effect" and len(parts) > 1:
            out[key] = {"type": "effect", "effect": parts[1].strip(), "entities": csv(parts[2]) if len(parts) > 2 else []}
    return out


def build_buttons(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    buttons = parse_buttons(data.get(CONF_BUTTONS_TEXT, ""))
    for key, value in data.items():
        if not str(key).startswith(MAP_PREFIX):
            continue
        action = str(key).removeprefix(MAP_PREFIX)
        button = command_to_button(str(value))
        if button is not None:
            buttons[action] = button
        elif action in buttons:
            del buttons[action]
    return buttons


def extract_action(payload: Any) -> str | None:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "ignore")
    text = str(payload).strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return text
    if isinstance(obj, dict) and obj.get("action"):
        return str(obj["action"]).strip()
    return None


async def async_setup_entry_runtime(hass: HomeAssistant, entry) -> bool:
    data = {**entry.data, **entry.options}
    resolved_remote = remote_name(data)
    root = hass.data.setdefault(DOMAIN, {"entries": {}})
    store = {
        "unsub": [],
        "lights": list(data.get(CONF_LIGHTS, [])),
        "extra_off": list(data.get(CONF_EXTRA_OFF, [])),
        "active": list(data.get(CONF_LIGHTS, [])),
        "buttons": build_buttons(data),
        "idx": {},
        "remote": resolved_remote,
        "discovered_actions": [],
    }
    root["entries"][entry.entry_id] = store

    for topic in action_topics(data):
        unsub = await mqtt.async_subscribe(hass, topic, make_action_handler(hass, entry.entry_id), 0)
        store["unsub"].append(unsub)
        _LOGGER.info("Room Remote Control subscribed to %s", topic)

    for topic in bridge_devices_topics(data):
        unsub = await mqtt.async_subscribe(hass, topic, make_bridge_devices_handler(hass, entry.entry_id), 0)
        store["unsub"].append(unsub)
        _LOGGER.info("Room Remote Control subscribed to %s", topic)

    request_topic = bridge_request_devices_topic(data)
    if request_topic:
        await mqtt.async_publish(hass, request_topic, "{}", 0, False)
        _LOGGER.info("Room Remote Control requested Zigbee2MQTT devices via %s", request_topic)

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


def remember_action(hass: HomeAssistant, entry_id: str, action: str) -> None:
    store = hass.data.get(DOMAIN, {}).get("entries", {}).get(entry_id)
    if not store:
        return
    actions = list(store.get("discovered_actions") or [])
    if action not in actions:
        actions.append(action)
        store["discovered_actions"] = sorted(actions)
        _LOGGER.info("Room Remote Control learned action from remote press: %s", action)


def make_action_handler(hass: HomeAssistant, entry_id: str):
    @callback
    async def handler(msg) -> None:
        action = extract_action(msg.payload)
        if action:
            remember_action(hass, entry_id, action)
            await handle_action(hass, entry_id, action)
    return handler


def make_bridge_devices_handler(hass: HomeAssistant, entry_id: str):
    @callback
    async def handler(msg) -> None:
        store = hass.data.get(DOMAIN, {}).get("entries", {}).get(entry_id)
        if not store:
            return
        payload = msg.payload.decode("utf-8", "ignore") if isinstance(msg.payload, bytes) else str(msg.payload)
        actions = actions_from_bridge_devices(payload, store.get("remote", ""))
        if actions:
            store["discovered_actions"] = sorted(set(list(store.get("discovered_actions") or []) + actions))
            _LOGGER.info("Room Remote Control discovered actions for %s: %s", store.get("remote"), ", ".join(store["discovered_actions"]))
    return handler


def targets(store: dict[str, Any], button: dict[str, Any]) -> list[str]:
    return list(button.get("entities") or store.get("active") or store.get("lights") or [])


async def handle_action(hass: HomeAssistant, entry_id: str, action: str) -> None:
    store = hass.data[DOMAIN]["entries"].get(entry_id)
    if not store:
        return
    button = store["buttons"].get(action)
    if not button:
        _LOGGER.debug("Room Remote Control unmapped action: %s", action)
        return

    typ = button["type"]
    ents = targets(store, button)

    if typ == "target":
        store["active"] = ents
    elif typ == "turn_on":
        store["active"] = ents
        await call_light(hass, "turn_on", ents)
    elif typ == "turn_off":
        await call_light(hass, "turn_off", ents)
    elif typ == "toggle":
        store["active"] = ents
        await call_light(hass, "toggle", ents)
    elif typ == "all_on":
        store["active"] = list(store["lights"])
        await call_light(hass, "turn_on", list(store["lights"]))
    elif typ == "all_off":
        await call_light(hass, "turn_off", list(store["lights"]) + list(store["extra_off"]))
    elif typ == "brightness":
        await step_brightness(hass, ents, int(button["step"]))
    elif typ == "kelvin":
        await step_kelvin(hass, ents, int(button["step"]))
    elif typ == "cycle_brightness":
        await cycle_brightness(hass, store, action, ents, list(button.get("values") or []))
    elif typ == "effect":
        await set_effect(hass, ents, button.get("effect"))
    elif typ == "next_effect":
        await next_effect(hass, store, action, ents)


async def step_brightness(hass: HomeAssistant, ents: list[str], step: int) -> None:
    for ent in ents:
        cur = brightness_pct(hass, ent)
        if cur is None:
            continue
        new = max(0, min(100, cur + step))
        if new == 0:
            await call_light(hass, "turn_off", [ent])
        else:
            await call_light(hass, "turn_on", [ent], brightness_pct=new)


async def cycle_brightness(hass: HomeAssistant, store: dict[str, Any], action: str, ents: list[str], values: list[int]) -> None:
    vals = [max(1, min(100, int(v))) for v in values]
    if not vals:
        return
    i = store["idx"].get(action, 0)
    store["idx"][action] = i + 1
    await call_light(hass, "turn_on", ents, brightness_pct=vals[i % len(vals)])


async def step_kelvin(hass: HomeAssistant, ents: list[str], step: int) -> None:
    for ent in ents:
        cur = kelvin(hass, ent)
        bounds = kelvin_bounds(hass, ent)
        if cur is None or bounds is None:
            continue
        lo, hi = bounds
        await call_light(hass, "turn_on", [ent], color_temp_kelvin=max(lo, min(hi, cur + step)))


def brightness_pct(hass: HomeAssistant, ent: str) -> int | None:
    st = hass.states.get(ent)
    if not st:
        return None
    raw = st.attributes.get("brightness")
    if raw is not None:
        return round(int(raw) * 100 / 255)
    return 100 if st.state == STATE_ON else 0


def kelvin(hass: HomeAssistant, ent: str) -> int | None:
    st = hass.states.get(ent)
    if not st:
        return None
    if st.attributes.get("color_temp_kelvin") is not None:
        return int(st.attributes["color_temp_kelvin"])
    if st.attributes.get("color_temp"):
        return round(1_000_000 / int(st.attributes["color_temp"]))
    b = kelvin_bounds(hass, ent)
    return round((b[0] + b[1]) / 2) if b else None


def kelvin_bounds(hass: HomeAssistant, ent: str) -> tuple[int, int] | None:
    st = hass.states.get(ent)
    if not st:
        return None
    mn = st.attributes.get("min_color_temp_kelvin")
    mx = st.attributes.get("max_color_temp_kelvin")
    if mn is not None and mx is not None:
        return int(mn), int(mx)
    min_mired = st.attributes.get("min_mireds")
    max_mired = st.attributes.get("max_mireds")
    if min_mired is not None and max_mired is not None:
        a = round(1_000_000 / int(min_mired))
        b = round(1_000_000 / int(max_mired))
        return min(a, b), max(a, b)
    return None


def effects(hass: HomeAssistant, ent: str) -> list[str]:
    st = hass.states.get(ent)
    if not st:
        return []
    return [str(x) for x in st.attributes.get("effect_list") or []]


async def set_effect(hass: HomeAssistant, ents: list[str], effect: str | None) -> None:
    if not effect:
        return
    supported = [ent for ent in ents if effect in effects(hass, ent)]
    await call_light(hass, "turn_on", supported, effect=effect)


async def next_effect(hass: HomeAssistant, store: dict[str, Any], action: str, ents: list[str]) -> None:
    lists = [effects(hass, ent) for ent in ents]
    lists = [x for x in lists if x]
    if not lists:
        return
    common = set(lists[0])
    for item in lists[1:]:
        common &= set(item)
    ordered = [x for x in lists[0] if x in common]
    if not ordered:
        return
    i = store["idx"].get(action, 0)
    store["idx"][action] = i + 1
    await call_light(hass, "turn_on", ents, effect=ordered[i % len(ordered)])


async def call_light(hass: HomeAssistant, service: str, ents: list[str], **kw: Any) -> None:
    if not ents:
        return
    data = {CONF_ENTITY_ID: ents}
    data.update({k: v for k, v in kw.items() if v is not None})
    await hass.services.async_call("light", service, data, blocking=False)
