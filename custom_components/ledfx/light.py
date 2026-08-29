"""Light component."""


from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGBW_COLOR,
    ENTITY_ID_FORMAT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_LIGHT_BRIGHTNESS,
    ATTR_LIGHT_COLOR,
    ATTR_LIGHT_CONFIG,
    ATTR_LIGHT_CUSTOM_PRESETS,
    ATTR_LIGHT_DEFAULT_PRESETS,
    ATTR_LIGHT_EFFECT,
    ATTR_LIGHT_EFFECT_CONFIG,
    ATTR_LIGHT_EFFECTS,
    ATTR_LIGHT_PRESET,
    ATTR_LIGHT_STATE,
    ATTR_STATE,
    SIGNAL_NEW_DEVICE,
)
from .entity import LedFxEntity
from .enum import ActionType, EffectCategory, Version
from .helper import build_effects, find_effect, hex_to_rgbw, rgbw_to_hex
from .updater import (
    LedFxEntityDescription,
    LedFxUpdater,
    async_get_updater,
    convert_brightness,
)

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LedFx light entry.

    :param hass: HomeAssistant: Home Assistant object
    :param config_entry: ConfigEntry: ConfigEntry object
    :param async_add_entities: AddEntitiesCallback: AddEntitiesCallback callback object
    """

    updater: LedFxUpdater = async_get_updater(hass, config_entry.entry_id)

    @callback
    def add_device(entity: LedFxEntityDescription) -> None:
        """Add device.

        :param entity: LedFxEntityDescription: Sensor object
        """

        async_add_entities(
            [
                LedFxLight(
                    f"{config_entry.entry_id}-{entity.description.key}",
                    entity,
                    updater,
                )
            ]
        )

    for device in updater.devices.values():
        add_device(device)

    updater.new_device_callback = async_dispatcher_connect(
        hass, SIGNAL_NEW_DEVICE, add_device
    )


# pylint: disable=too-many-ancestors
class LedFxLight(LedFxEntity, LightEntity):
    """LedFx light entry."""

    _type: ActionType

    def __init__(
        self,
        unique_id: str,
        entity: LedFxEntityDescription,
        updater: LedFxUpdater,
    ) -> None:
        """Initialize button.

        :param unique_id: str: Unique ID
        :param entity: LedFxEntityDescription object
        :param updater: LedFxUpdater: Luci updater object
        """

        LedFxEntity.__init__(
            self, unique_id, entity.description, updater, ENTITY_ID_FORMAT
        )

        self._type = entity.type
        self._attr_device_code = entity.description.key

        self._attr_device_info = entity.device_info

        self._attr_supported_features = LightEntityFeature.EFFECT

        # Brightness and color are declared through color modes; ColorMode.RGBW
        # already implies brightness support.
        if updater.version == Version.V2:
            self._attr_supported_color_modes = {ColorMode.RGBW}
            self._attr_color_mode = ColorMode.RGBW
        else:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS

        self._attr_is_on = updater.data.get(
            f"{self._attr_device_code}_{ATTR_LIGHT_STATE}", False
        )
        self._attr_brightness = min(
            updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_BRIGHTNESS}", 0),
            255,
        )

        self._attr_rgbw_color = hex_to_rgbw(
            updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_COLOR}", None)
        )

        self._attr_effect_list = build_effects(
            updater.data.get(ATTR_LIGHT_EFFECTS, []),
            updater.data.get(ATTR_LIGHT_DEFAULT_PRESETS, {}),
            updater.data.get(ATTR_LIGHT_CUSTOM_PRESETS, {}),
        )
        self._attr_effect = self._effect_name(
            updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_EFFECT}"),
            updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_PRESET}"),
        )
        self._attr_extra_state_attributes = updater.data.get(
            f"{self._attr_device_code}_{ATTR_LIGHT_EFFECT_CONFIG}", {}
        ) | updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_CONFIG}", {})

    @staticmethod
    def _effect_name(effect: str | None, preset: str | None) -> str | None:
        """Effect name as shown in effect_list.

        build_effects lists a preset as "<effect> - <preset>", so the selected
        option only stays selected in the UI if the reported effect uses the
        same form.

        :param effect: str | None: Effect type
        :param preset: str | None: Active preset id, if any
        :return str | None
        """

        if effect and preset:
            return f"{effect} - {preset}"

        return effect

    def _handle_coordinator_update(self) -> None:
        """Update state."""

        is_available: bool = self._updater.data.get(ATTR_STATE, False)

        is_on: bool = self._updater.data.get(
            f"{self._attr_device_code}_{ATTR_LIGHT_STATE}", False
        )
        brightness: int = min(
            self._updater.data.get(
                f"{self._attr_device_code}_{ATTR_LIGHT_BRIGHTNESS}", 0
            ),
            255,
        )
        color: tuple | None = hex_to_rgbw(
            self._updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_COLOR}", None)
        )

        effect_list = build_effects(
            self._updater.data.get(ATTR_LIGHT_EFFECTS, []),
            self._updater.data.get(ATTR_LIGHT_DEFAULT_PRESETS, {}),
            self._updater.data.get(ATTR_LIGHT_CUSTOM_PRESETS, {}),
        )
        effect: str | None = self._effect_name(
            self._updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_EFFECT}"),
            self._updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_PRESET}"),
        )
        attributes: dict = {
            code: value
            for code, value in self._updater.data.get(
                f"{self._attr_device_code}_{ATTR_LIGHT_EFFECT_CONFIG}", {}
            ).items()
            if code != ATTR_BRIGHTNESS
        } | self._updater.data.get(f"{self._attr_device_code}_{ATTR_LIGHT_CONFIG}", {})

        if (  # pylint: disable=too-many-boolean-expressions
            self._attr_is_on == is_on
            and self._attr_available == is_available
            and self._attr_brightness == brightness
            and self._attr_rgbw_color == color
            and self._attr_effect == effect
            and self._attr_effect_list == effect_list
            and self._attr_extra_state_attributes == attributes
        ):
            return

        self._attr_available = is_available
        self._attr_is_on = is_on
        self._attr_brightness = brightness
        self._attr_rgbw_color = color  # type: ignore
        self._attr_effect_list = effect_list
        self._attr_effect = effect
        self._attr_extra_state_attributes = attributes

        self.async_write_ha_state()

    async def _device_on(self, **kwargs: Any) -> None:
        """Device on action

        :param kwargs: Any: Any arguments
        """

        code: str = self._attr_device_code  # type: ignore
        old_effect: str | None = self._attr_effect

        # _attr_effect holds the name shown in effect_list, which for a preset
        # is "<effect> - <preset>". The API only ever accepts the bare effect
        # type, so the two are tracked separately.
        requested: str | None = kwargs.get(ATTR_EFFECT)
        effect: str | None = self._updater.data.get(f"{code}_{ATTR_LIGHT_EFFECT}")
        preset: str | None = self._updater.data.get(f"{code}_{ATTR_LIGHT_PRESET}")
        category: EffectCategory = EffectCategory.NONE

        if requested is not None:
            effect, preset, category = find_effect(
                requested,
                self._updater.data.get(ATTR_LIGHT_DEFAULT_PRESETS, {}),
                self._updater.data.get(ATTR_LIGHT_CUSTOM_PRESETS, {}),
            )

        # Re-select of the same preset still re-applies it, matching the
        # previous behaviour of resending whenever a preset was picked.
        effect_changed: bool = requested is not None and requested != old_effect
        preset_requested: bool = requested is not None and preset is not None

        if effect_changed or preset_requested or not self._attr_is_on:
            response: dict = dict(
                await self._updater.client.preset(
                    code,
                    category.value,
                    effect,  # type: ignore
                    preset,  # type: ignore
                )
                if category != EffectCategory.NONE and preset is not None
                else await self._updater.client.device_on(code, effect)  # type: ignore
            )

            effect_config: dict = {}
            if "effect" in response:
                effect_config = {
                    key: value
                    for key, value in response["effect"].get("config", {}).items()
                    if not isinstance(value, dict) and not isinstance(value, list)
                }

            self._updater.data[f"{code}_{ATTR_LIGHT_EFFECT}"] = effect
            self._updater.data[f"{code}_{ATTR_LIGHT_PRESET}"] = preset

            # Report the option the user picked rather than the bare effect
            # type, otherwise the selection does not stick in the UI.
            self._attr_effect = self._effect_name(effect, preset)

            self._updater.data[f"{code}_{ATTR_LIGHT_EFFECT_CONFIG}"] = {
                key: value
                for key, value in effect_config.items()
                if key != ATTR_BRIGHTNESS
            }

        if ATTR_BRIGHTNESS in kwargs:
            await self.async_update_effect(
                ATTR_BRIGHTNESS, convert_brightness(float(kwargs[ATTR_BRIGHTNESS]))
            )

        if ATTR_RGBW_COLOR in kwargs:
            await self.async_update_effect(
                "background_color", rgbw_to_hex(kwargs[ATTR_RGBW_COLOR])
            )

    async def _device_off(self, **kwargs: Any) -> None:
        """Device off action

        :param kwargs: Any: Any arguments
        """

        await self._updater.client.device_off(
            self._attr_device_code  # type: ignore
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on action

        :param kwargs: Any: Any arguments
        """

        await self._async_call(f"_{self._type.value}_{STATE_ON}", STATE_ON, **kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off action

        :param kwargs: Any: Any arguments
        """

        await self._async_call(f"_{self._type.value}_{STATE_OFF}", STATE_OFF, **kwargs)

    async def _async_call(self, method: str, state: str, **kwargs: Any) -> None:
        """Async turn action

        :param method: str: Call method
        :param state: str: Call state
        :param kwargs: Any: Any arguments
        """

        if action := getattr(self, method):
            await action(**kwargs)

            self._updater.data[f"{self._attr_device_code}_{ATTR_LIGHT_STATE}"] = (
                state == STATE_ON
            )
            self._attr_is_on = state == STATE_ON

            if ATTR_BRIGHTNESS in kwargs:
                self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
                self._updater.data[
                    f"{self._attr_device_code}_{ATTR_LIGHT_BRIGHTNESS}"
                ] = self._attr_brightness

            if ATTR_RGBW_COLOR in kwargs:
                self._attr_rgbw_color = kwargs[ATTR_RGBW_COLOR]
                self._updater.data[
                    f"{self._attr_device_code}_{ATTR_LIGHT_COLOR}"
                ] = rgbw_to_hex(
                    self._attr_rgbw_color
                )  # type: ignore

            self._attr_extra_state_attributes = {
                code: value
                for code, value in self._updater.data.get(
                    f"{self._attr_device_code}_{ATTR_LIGHT_EFFECT_CONFIG}", {}
                ).items()
                if code != ATTR_BRIGHTNESS
            } | self._updater.data.get(
                f"{self._attr_device_code}_{ATTR_LIGHT_CONFIG}", {}
            )

            if ATTR_BRIGHTNESS not in kwargs and ATTR_RGBW_COLOR not in kwargs:
                self._updater.async_update_listeners()

            self.async_write_ha_state()
