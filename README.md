# LedFx for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

Home Assistant integration for [LedFx](https://github.com/LedFx/LedFx), the
real-time LED effect controller.

> Continuation of [dmamontov/hass-ledfx](https://github.com/dmamontov/hass-ledfx),
> which last saw a release in July 2023 and targets the LedFx 0.10.x API. This
> version targets LedFx 2.x. See [Credits](#credits).

Every LedFx **virtual** becomes a light entity with its effects and presets as
the effect list, plus entities for the audio input, scenes and LedFx's audio
configuration.

## Requirements

* LedFx **2.x** — developed and verified against
  [v2.1.9](https://github.com/LedFx/LedFx/releases/tag/v2.1.9)
* Home Assistant **2026.8** or newer, on Python 3.14 (developed and verified
  against 2026.8.3)

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
| Colour pattern (one per virtual) | `select.ledfx_192_168_1_50_matrix_color_pattern` | Gradient or solid colour for the active effect |
| Audio input | `select.ledfx_192_168_1_50_audio_input` | Switches LedFx's audio source |
| Scene | `button.ledfx_192_168_1_50_party` | Activates a LedFx scene |
| Connection state | `binary_sensor.ledfx_192_168_1_50_state` | Whether LedFx is reachable |
| Audio settings | `sensor.ledfx_192_168_1_50_min_volume` | LedFx audio config values (disabled by default) |

### Colour patterns

Most effects (42 of the 63 in LedFx 2.1.9) colour themselves from a *gradient*.
Each virtual gets one **Colour pattern** select listing every LedFx gradient
and solid colour — LedFx accepts either. It is unavailable while the light is
off, or when the active effect has no gradient of its own.

Everything else in an effect's config is left to the LedFx UI. Earlier releases
made an entity for every setting of every effect, which came to thousands of
unused, disabled entities per instance.

### Effects and presets

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

### Brightness and colour pattern

Tile cards expose both inline, with no custom cards and no more-info dialog.
`light-brightness` gives a slider, `select-options` a dropdown of every
gradient and colour LedFx offers.

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: light.ledfx_192_168_1_50_matrix
    name: Matrix
    features_position: bottom
    features:
      - type: light-brightness
  - type: tile
    entity: select.ledfx_192_168_1_50_matrix_color_pattern
    name: Colour pattern
    features_position: bottom
    features:
      - type: select-options
```

The colour pattern select is unavailable while the light is off, or when the
active effect has no gradient.

### One card with everything

The stock light card gives a brightness dial, an RGBW colour picker and the
full effect and preset list in one place.

```yaml
type: vertical-stack
cards:
  - type: light
    entity: light.ledfx_192_168_1_50_matrix
    name: Matrix
  - type: tile
    entity: select.ledfx_192_168_1_50_matrix_color_pattern
    name: Colour pattern
    features:
      - type: select-options
```

### Effect, brightness and colour pattern in one tap

Effect and brightness go in a single `light.turn_on`; the colour pattern is a
separate entity, so this needs a script rather than a button's `tap_action`.

```yaml
script:
  ledfx_matrix_party:
    alias: Matrix party
    sequence:
      - action: light.turn_on
        target:
          entity_id: light.ledfx_192_168_1_50_matrix
        data:
          effect: equalizer2d - cold
          brightness_pct: 80
      - action: select.select_option
        target:
          entity_id: select.ledfx_192_168_1_50_matrix_color_pattern
        data:
          option: Ocean
```

```yaml
type: button
name: Party
icon: mdi:party-popper
tap_action:
  action: perform-action
  perform_action: script.ledfx_matrix_party
```

Setting a preset and a brightness together applies both, but the light then
reports the bare effect (`equalizer2d`) rather than `equalizer2d - cold`: the
brightness has moved the config away from the preset, so it is no longer that
preset. LedFx decides this the same way. Drop `brightness_pct` if you want the
preset name to stick.

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
      - action: select.select_option
        target:
          entity_id: select.ledfx_192_168_1_50_matrix_color_pattern
        data:
          option: Ocean
```

### Setting brightness on its own

`brightness_pct` takes 0-100, `brightness` takes 0-255. Either turns the light
on if it is off, keeping whatever effect it had.

```yaml
- action: light.turn_on
  target:
    entity_id: light.ledfx_192_168_1_50_matrix
  data:
    brightness_pct: 40
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

## Development

Linting and formatting use [ruff](https://docs.astral.sh/ruff/); CI also runs
Home Assistant's `hassfest` and the HACS validator.

```bash
pip install -r requirements_test.txt
ruff check .
ruff format --check .
```

## Tests

Request-shape tests need only `httpx`:

```bash
python3 -m pytest tests/test_client_ledfx2.py -q
```

The rest need the Home Assistant test harness (`requirements_test.txt`) and run
against the bundled mock:

```bash
pytest tests/ -q
```

`tests/test_live_ha.py` additionally boots Home Assistant against a real LedFx,
and is skipped unless `LEDFX_HOST` is set:

```bash
LEDFX_HOST=192.168.1.50 pytest tests/test_live_ha.py -q
```

## Credits

Originally written by **[Dmitry Mamontov](https://github.com/dmamontov)** and
published as **[dmamontov/hass-ledfx](https://github.com/dmamontov/hass-ledfx)**.
The config flow, coordinator and entity structure are all his work, and this
repository would not exist without it.

Licensed under the Apache License 2.0, as the original is. See
[LICENSE](LICENSE).

### Changes from the original

The upstream project targets LedFx `>= 0.10.7` and was last released in July
2023. Against LedFx 2.x it fails to control anything, and on current Home
Assistant it fails to load. This version:

* **Rewrote the REST client for the LedFx 2.x API.** Effects and presets moved
  onto virtuals and were dropped from devices; `POST /virtuals/{id}/effects`
  no longer accepts `{"config": {"active": true}}`; preset categories were
  renamed to `ledfx_presets` / `user_presets`; the audio device endpoint reads
  a different key. Support for LedFx 0.10.x was removed.
* **Fixed loading on modern Home Assistant.** `DeviceEntryType` moved out of
  `homeassistant.helpers.entity`, the deprecated `SUPPORT_*` light constants
  were replaced with colour modes, and platforms are now forwarded inside
  `async_setup_entry` rather than from a deferred task, which had left config
  entries stuck in `failed_unload`.
* **Fixed entity actions on Python 3.11+.** Handler names were built by
  interpolating a `str`-mixin enum, which changed rendering in 3.11 and broke
  turn on/off, button press, number set and select in seven places.
* **Replaced the per-effect entities.** Every effect setting used to become a
  number, switch or select on every virtual — 4832 disabled entities on a
  20-virtual instance. Removed in favour of one colour pattern select per
  virtual, and preset selection that stays selected.
* **Replaced the test suite** with request-shape, config-flow, service-call
  and live-instance tests, plus a standalone API checker and a LedFx 2.x mock.

Full detail is in the commit history.
