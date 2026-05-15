# Room Remote Control

Home Assistant custom integration for controlling room lights with Zigbee2MQTT remotes over MQTT.

The integration is hardware agnostic. It does not contain fixed lamp names, fixed effects, fixed color temperatures or fixed brightness values.

## Main idea

Create one room remote in the Home Assistant UI:

- choose MQTT action topics
- choose room light entities
- choose optional extra_off light entities
- map Zigbee2MQTT button actions to generic light commands

The integration reads capabilities directly from Home Assistant light entities:

- current brightness from `brightness`
- color temperature from `color_temp_kelvin` or `color_temp`
- color temperature limits from `min_color_temp_kelvin` / `max_color_temp_kelvin` or mired attributes
- effects from `effect_list`

## Installation with HACS

Add this repository as a custom HACS repository:

```text
https://github.com/nashsmartdom/ha-room-remote-control
```

Category:

```text
Integration
```

Install and restart Home Assistant.

## Setup

Open:

```text
Settings -> Devices & services -> Add integration -> Room Remote Control
```

Fields:

- Name
- MQTT action topics
- Room lights
- Additional lights for all_off only
- Button rules

## Button rule format

One rule per line:

```text
mqtt_action=command
```

Examples:

```text
on=target:light.bed
arrow_left_click=target:light.desk
arrow_right_click=target:light.cabinet,light.chair
single=toggle:light.bed
up=brightness:+10
down=brightness:-10
left=kelvin:-300
right=kelvin:+300
hold=next_effect
off=all_off
```

## Supported commands

### target

Select active lights without changing them.

```text
button=target:light.one,light.two
```

### turn_on / turn_off / toggle

Control explicit lights.

```text
button=turn_on:light.one,light.two
button=turn_off:light.one
button=toggle:light.one
```

### all_on / all_off

Control all selected room lights. `all_off` also includes extra_off entities.

```text
button=all_on
button=all_off
```

### brightness

Change brightness relative to current entity state.

```text
button=brightness:+10
button=brightness:-10
button=brightness:+20:light.one,light.two
```

If no entities are specified, the command uses the current active lights.

### kelvin

Change color temperature relative to current entity state.

```text
button=kelvin:+300
button=kelvin:-300
button=kelvin:+500:light.one
```

The integration uses each light's own min/max color temperature limits.

### cycle_brightness

Cycle through user-defined brightness values.

```text
button=cycle_brightness:20,50,100
button=cycle_brightness:10,30,80:light.one
```

### effect

Set a named effect if the selected lights support it.

```text
button=effect:Candlelight
button=effect:Rainbow:light.one
```

### next_effect

Cycle through effects from the selected lights' `effect_list`.

```text
button=next_effect
```

When several lights are active, only effects supported by all active lights are used.

## MQTT payloads

Both forms are supported:

```json
{"action":"on"}
```

and:

```text
on
```
