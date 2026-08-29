# LedFx for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

Home Assistant integration for [LedFx](https://github.com/LedFx/LedFx), the
real-time LED effect controller.

Every LedFx **virtual** becomes a light entity with its effects and presets as
the effect list, plus entities for the audio input, scenes and LedFx's audio
configuration.

## Requirements

* LedFx **2.x** — developed and verified against
  [v2.1.9](https://github.com/LedFx/LedFx/releases/tag/v2.1.9)
* Home Assistant 2023.6 or newer (verified on 2026.8)

LedFx 2.x moved effects and presets onto virtuals and dropped them from
devices, so this release targets the `virtuals` API only. LedFx 0.10.x is no
longer supported.

## Install

**HACS** (recommended) — add this repository as a custom repository, then
download it and restart Home Assistant.

**Manually** — copy `custom_components/ledfx` into your `config/custom_components`
directory and restart. You won't get update notifications this way.

## Config

`Settings` > `Devices & Services` > `Add Integration` > `LedFx`

Enter the IP address and port of your LedFx instance. Tick **basic auth** if
LedFx sits behind a reverse proxy that requires it, then supply the username
and password.

❗ YAML configuration is not supported.

## Entities

For a LedFx at `192.168.1.50`, entity IDs look like this:

| Entity | Example | What it does |
| --- | --- | --- |
| Light (one per virtual) | `light.ledfx_192_168_1_50_matrix` | On/off, brightness, colour, effect and preset selection |
| | `light.ledfx_192_168_1_50_wled_144_l` | Entity IDs use the LedFx **virtual id**, not its display name |
| Audio input | `select.ledfx_192_168_1_50_audio_input` | Switches LedFx's audio source |
| Scene | `button.ledfx_192_168_1_50_party` | Activates a LedFx scene |
| Connection state | `binary_sensor.ledfx_192_168_1_50_state` | Whether LedFx is reachable |
| Audio settings | `sensor.ledfx_192_168_1_50_min_volume` | LedFx audio config values (disabled by default) |

The light's `effect_list` contains both bare effects (`rain`) and presets
(`rain - ripples`, plus any of your own user presets). Selecting a preset
applies it and keeps it selected; changing any effect setting afterwards drops
back to the bare effect name, because the config no longer matches the preset.

## Examples

### Toggle a virtual, turning it on with a specific effect

`light.toggle` accepts every `turn_on` parameter and ignores them when turning
off, so no templating is needed.

```yaml
type: button
entity: light.ledfx_192_168_1_50_matrix
name: Matrix
icon: mdi:equalizer
tap_action:
  action: perform-action
  perform_action: light.toggle
  target:
    entity_id: light.ledfx_192_168_1_50_matrix
  data:
    effect: rain
hold_action:
  action: more-info
```

### A row of preset buttons

Each button applies one preset. Re-tapping a button that is already active
re-applies the preset, which is a handy way to reset an effect after fiddling
with its settings.

```yaml
type: horizontal-stack
cards:
  - type: button
    name: Ripples
    icon: mdi:water
    tap_action:
      action: perform-action
      perform_action: light.turn_on
      target:
        entity_id: light.ledfx_192_168_1_50_matrix
      data:
        effect: rain - ripples
  - type: button
    name: Equalizer
    icon: mdi:equalizer
    tap_action:
      action: perform-action
      perform_action: light.turn_on
      target:
        entity_id: light.ledfx_192_168_1_50_matrix
      data:
        effect: equalizer2d - cold
  - type: button
    name: Off
    icon: mdi:power
    tap_action:
      action: perform-action
      perform_action: light.turn_off
      target:
        entity_id: light.ledfx_192_168_1_50_matrix
```

### Full control panel

The stock light card gives brightness, colour and the whole effect/preset list
in its more-info dialog.

```yaml
type: entities
title: LedFx
entities:
  - entity: light.ledfx_192_168_1_50_matrix
  - entity: light.ledfx_192_168_1_50_wled_144_l
  - entity: light.ledfx_192_168_1_50_wled_144_r
  - type: divider
  - entity: select.ledfx_192_168_1_50_audio_input
  - entity: binary_sensor.ledfx_192_168_1_50_state
```

### Custom button-card with state feedback

Requires [button-card](https://github.com/custom-cards/button-card) from HACS.

```yaml
type: custom:button-card
entity: light.ledfx_192_168_1_50_matrix
icon: mdi:equalizer
show_name: false
show_label: true
label: Matrix
tap_action:
  action: perform-action
  perform_action: light.toggle
  target:
    entity_id: light.ledfx_192_168_1_50_matrix
  data:
    effect: rain
hold_action:
  action: more-info
layout: vertical
size: 50%
state:
  - value: "on"
    styles:
      icon:
        - color: var(--state-light-active-color)
  - value: "off"
    styles:
      icon:
        - color: var(--state-icon-color)
        - opacity: 0.5
styles:
  card:
    - height: 55px
  label:
    - font-size: 10px
    - color: var(--secondary-text-color)
    - margin-top: 2px
```

### Automation: sunset scene

```yaml
automation:
  - alias: LedFx at sunset
    triggers:
      - trigger: sun
        event: sunset
    actions:
      - action: light.turn_on
        target:
          entity_id: light.ledfx_192_168_1_50_matrix
        data:
          effect: equalizer2d - cold
          brightness_pct: 60
```

### Selecting the audio input

```yaml
- action: select.select_option
  target:
    entity_id: select.ledfx_192_168_1_50_audio_input
  data:
    option: "ALSA: pulse"
```

## Verifying against your LedFx

`scripts/ledfx_api_check.py` runs the integration's own REST client against a
LedFx instance, so you can confirm the API contract without Home Assistant. It
needs nothing but `httpx`.

```bash
# read-only: every request the coordinator depends on
python3 scripts/ledfx_api_check.py --host 192.168.1.50 --port 8888

# also exercise turn-on / brightness / preset / turn-off (changes your lights,
# then restores the previous effect)
python3 scripts/ledfx_api_check.py --host 192.168.1.50 --port 8888 --write my-virtual
```

To check offline, run the bundled mock of the LedFx 2.x API instead:

```bash
python3 scripts/mock_ledfx.py 8899 &
python3 scripts/ledfx_api_check.py --host 127.0.0.1 --port 8899 --write my-strip
```

## Tests

Request-shape tests need only `httpx`:

```bash
python3 -m pytest tests/test_client_ledfx2.py -q
```

The rest need the Home Assistant test harness (`requirements_test.txt`) and run
against the bundled mock:

```bash
python3 -m pytest tests/ -q -o asyncio_mode=auto
```

`tests/test_live_ha.py` additionally boots Home Assistant against a real LedFx,
and is skipped unless `LEDFX_HOST` is set:

```bash
LEDFX_HOST=192.168.1.50 python3 -m pytest tests/test_live_ha.py -q -o asyncio_mode=auto
```

## Credits

Originally written by [@dmamontov](https://github.com/dmamontov); this fork
updates it for the LedFx 2.x API and current Home Assistant.
