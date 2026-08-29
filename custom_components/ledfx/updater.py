"""LedFx data updater."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import timedelta
from functools import cached_property
from typing import Any, Final

from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.light import LightEntityDescription
from homeassistant.components.sensor import SensorEntityDescription, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import event
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import utcnow
from httpx import USE_CLIENT_DEFAULT, codes

from .client import LedFxClient
from .const import (
    ATTR_DEVICE_SW_VERSION,
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
    ATTR_SELECT_AUDIO_INPUT,
    ATTR_SELECT_GRADIENT,
    ATTR_SELECT_AUDIO_INPUT_OPTIONS,
    ATTR_STATE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MAINTAINER,
    NAME,
    PRESET_COMPARE_IGNORED_KEYS,
    SIGNAL_NEW_BUTTON,
    SIGNAL_NEW_DEVICE,
    SIGNAL_NEW_SENSOR,
    UPDATER,
)
from .enum import ActionType
from .exceptions import LedFxConnectionError, LedFxError, LedFxRequestError

PREPARE_METHODS: Final = (
    "config",
    "info",
    "colors",
    "schema",
    "devices",
    "scenes",
)

_LOGGER = logging.getLogger(__name__)


# pylint: disable=too-many-branches,too-many-lines,too-many-arguments
class LedFxUpdater(DataUpdateCoordinator):
    """LedFx data updater for interaction with LedFX API."""

    client: LedFxClient
    code: codes = codes.BAD_GATEWAY
    ip: str
    port: str

    new_button_callback: CALLBACK_TYPE | None = None
    new_device_callback: CALLBACK_TYPE | None = None
    new_select_callback: CALLBACK_TYPE | None = None
    new_sensor_callback: CALLBACK_TYPE | None = None

    _scan_interval: int
    _is_only_check: bool = False

    def __init__(
        self,
        hass: HomeAssistant,
        ip: str,
        port: str,
        auth: Any = USE_CLIENT_DEFAULT,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        timeout: int = DEFAULT_TIMEOUT,
        is_only_check: bool = False,
    ) -> None:
        """Initialize updater.

        :rtype: object
        :param hass: HomeAssistant: Home Assistant object
        :param ip: str: ip address
        :param port: str: port
        :param auth: Any: Basic auth
        :param scan_interval: int: Update interval
        :param timeout: int: Query execution timeout
        :param is_only_check: bool: Only config flow
        """

        self.client = LedFxClient(
            get_async_client(hass, False),
            ip,
            port,
            auth,
            timeout,
        )

        self.ip = ip  # pylint: disable=invalid-name
        self.port = port

        self._scan_interval = scan_interval
        self._is_only_check = is_only_check

        if hass is not None:
            super().__init__(
                hass,
                _LOGGER,
                name=f"{NAME} updater",
                update_interval=self._update_interval,
                update_method=self.update,
            )

        self.data: dict[str, Any] = {}

        self.buttons: dict[str, LedFxEntityDescription] = {}
        self.devices: dict[str, LedFxEntityDescription] = {}
        self.sensors: dict[str, LedFxEntityDescription] = {}

        self.color_properties: set = set()
        self.gradient_effects: set = set()
        self.presets: dict = {}
        self.colors: dict = {}
        self.gradients: dict = {}
        self.color_names: dict = {}

        self._is_first_update: bool = True

    async def async_stop(self) -> None:
        """Stop updater"""

        callbacks: list = [
            self.new_button_callback,
            self.new_device_callback,
            self.new_select_callback,
            self.new_sensor_callback,
        ]

        for _callback in callbacks:
            if _callback is not None:
                _callback()  # pylint: disable=not-callable

        # Clear them so a later EVENT_HOMEASSISTANT_STOP does not disconnect
        # the same dispatchers twice.
        self.new_button_callback = None
        self.new_device_callback = None
        self.new_select_callback = None
        self.new_sensor_callback = None

    @cached_property
    def _update_interval(self) -> timedelta:
        """Update interval

        :return timedelta: update_interval
        """

        return timedelta(seconds=self._scan_interval)

    async def update(self) -> dict:
        """Update LedFx information.

        :return dict: dict with LedFx data.
        """

        self.code = codes.OK

        _err: LedFxError | None = None

        try:
            for method in PREPARE_METHODS:
                if not self._is_only_check or method == "config":
                    await self._async_prepare(method, self.data)
        except LedFxConnectionError as _e:
            _err = _e

            self.code = codes.NOT_FOUND
        except LedFxRequestError as _e:
            _err = _e

            self.code = codes.FORBIDDEN
        else:
            if self._is_first_update:
                self._is_first_update = False

        self.data[ATTR_STATE] = codes.is_success(self.code)

        return self.data

    @cached_property
    def address(self) -> str:
        """Full address

        :return str
        """

        return f"{self.ip}:{self.port}"

    @property
    def device_info(self) -> DeviceInfo:
        """Device info.

        :return DeviceInfo: Service DeviceInfo.
        """

        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self.address)},
            name=NAME,
            manufacturer=MAINTAINER,
            sw_version=self.data.get(ATTR_DEVICE_SW_VERSION, None),
            configuration_url=f"http://{self.address}/",
        )

    def schedule_refresh(self, offset: timedelta) -> None:
        """Schedule refresh.

        :param offset: timedelta
        """

        if self._unsub_refresh:  # type: ignore
            self._unsub_refresh()  # type: ignore
            self._unsub_refresh = None

        self._unsub_refresh = event.async_track_point_in_utc_time(
            self.hass,
            self._job,
            utcnow().replace(microsecond=0) + offset,
        )

    async def _async_prepare(self, method: str, data: dict) -> None:
        """Prepare data.

        :param method: str
        :param data: dict
        """

        action = getattr(self, f"_async_prepare_{method}")

        if action is not None:
            await action(data)

    async def _async_prepare_info(self, data: dict) -> None:
        """Prepare info.

        :param data: dict
        """

        response: dict = await self.client.info()

        if "version" in response:
            data[ATTR_DEVICE_SW_VERSION] = response["version"]

    async def _async_prepare_colors(self, data: dict) -> None:
        """Prepare colors.

        :param data: dict
        """

        response: dict = await self.client.colors()

        colors: dict = {}
        gradients: dict = {}
        if "colors" in response:
            if "builtin" in response["colors"]:
                colors |= response["colors"]["builtin"]
            if "user" in response["colors"]:
                colors |= response["colors"]["user"]

        if "gradients" in response:
            if "builtin" in response["gradients"]:
                gradients |= response["gradients"]["builtin"]
            if "user" in response["gradients"]:
                gradients |= response["gradients"]["user"]

        self.colors = colors
        self.gradients = gradients

        # Reverse lookup for showing a stored color value by its name. Colors
        # win over gradients on the rare value that appears in both.
        self.color_names = {
            value: name
            for name, value in list(gradients.items()) + list(colors.items())
        }

    async def _async_prepare_schema(self, data: dict) -> None:
        """Prepare schema.

        :param data: dict
        """

        response: dict = await self.client.schema()

        if "effects" in response and response["effects"]:
            data[ATTR_LIGHT_EFFECTS] = sorted(list(response["effects"].keys()))

            # Only the color-typed keys are needed, to show colors by name in
            # the light attributes and translate them back when writing.
            for effect, fields in response["effects"].items():
                for code, parameter in fields["schema"]["properties"].items():
                    if parameter.get("type") != "color":
                        continue

                    self.color_properties.add(code)

                    # 42 of 63 effects expose a "gradient" key; the rest of the
                    # color keys appear in a handful of effects each and get no
                    # entity of their own.
                    if code == ATTR_SELECT_GRADIENT:
                        self.gradient_effects.add(effect)

        if (
            "audio" in response
            and "schema" in response["audio"]
            and "properties" in response["audio"]["schema"]
            and "audio_device" in response["audio"]["schema"]["properties"]
            and "enum" in response["audio"]["schema"]["properties"]["audio_device"]
        ):
            data[ATTR_SELECT_AUDIO_INPUT_OPTIONS] = dict(
                response["audio"]["schema"]["properties"]["audio_device"]["enum"]
            )

            if (
                isinstance(data[ATTR_SELECT_AUDIO_INPUT], int)
                and str(data[ATTR_SELECT_AUDIO_INPUT])
                in data[ATTR_SELECT_AUDIO_INPUT_OPTIONS]
            ):
                data[ATTR_SELECT_AUDIO_INPUT] = data[ATTR_SELECT_AUDIO_INPUT_OPTIONS][
                    str(data[ATTR_SELECT_AUDIO_INPUT])
                ]

    async def _async_prepare_config(self, data: dict) -> None:
        """Prepare config.

        :param data: dict
        """

        response: dict = await self.client.config()

        if "audio" in response:
            for code, value in response["audio"].items():
                if code == "audio_device":
                    data[ATTR_SELECT_AUDIO_INPUT] = int(
                        response["audio"]["audio_device"]
                    )
                elif code != "device_index":
                    data[code] = value

                    if code in self.sensors:
                        continue

                    self.sensors[code] = LedFxEntityDescription(
                        description=SensorEntityDescription(
                            key=code,
                            name=code.replace("_", " ").title(),
                            state_class=SensorStateClass.TOTAL,
                            entity_category=EntityCategory.DIAGNOSTIC,
                            entity_registry_enabled_default=False,
                        ),
                        device_info=self.device_info,
                    )

                    if self.new_sensor_callback:
                        async_dispatcher_send(
                            self.hass, SIGNAL_NEW_SENSOR, self.sensors[code]
                        )

        if "ledfx_presets" in response and response["ledfx_presets"]:
            data[ATTR_LIGHT_DEFAULT_PRESETS] = {
                effect: sorted(list(presets.keys()))
                for effect, presets in response["ledfx_presets"].items()
            }
            self.presets[ATTR_LIGHT_DEFAULT_PRESETS] = response["ledfx_presets"]

        if "user_presets" in response and response["user_presets"]:
            data[ATTR_LIGHT_CUSTOM_PRESETS] = {
                effect: sorted(list(presets.keys()))
                for effect, presets in response["user_presets"].items()
            }
            self.presets[ATTR_LIGHT_CUSTOM_PRESETS] = response["user_presets"]

    async def _async_prepare_devices(self, data: dict) -> None:
        """Prepare devices.

        :param data: dict
        """

        response: dict = await self.client.devices()

        if "devices" not in response or not response["devices"]:  # pragma: no cover
            return

        v_response: dict = await self.client.virtuals()

        if "virtuals" in v_response and v_response["virtuals"]:
            devices: dict = {}
            for key, virtual in v_response["virtuals"].items():
                devices[key] = virtual

                if (
                    virtual.get("is_device")
                    and virtual.get("is_device", "") in response["devices"]
                ):
                    devices[key]["config"] |= {
                        code: value
                        for code, value in response["devices"][
                            virtual.get("is_device")
                        ]["config"].items()
                        if code == "ip_address"
                    }
                    devices[key]["type"] = response["devices"][
                        virtual.get("is_device")
                    ]["type"]

            self._build_device(data, devices)

    def _build_device(self, data: dict, devices: dict) -> None:
        """Build device

        :param data: dict
        :param devices: dict
        """

        for code, device in devices.items():
            data[f"{code}_{ATTR_LIGHT_STATE}"] = bool(
                "effect" in device and device["effect"]
            )

            if data[f"{code}_{ATTR_LIGHT_STATE}"]:
                # LedFx does not say which preset is active, so infer it by
                # comparing configs. Must happen before _convert_effect_config,
                # which rewrites colors to names in place.
                preset, _ = find_matching_preset(
                    self.presets,
                    device["effect"].get("type", ""),
                    device["effect"].get("config", {}),
                )

                # The light's color needs the raw hex; _convert_effect_config
                # rewrites it to a color name in place.
                background: str | None = device["effect"]["config"].get(
                    "background_color"
                )

                data |= {
                    f"{code}_{ATTR_LIGHT_BRIGHTNESS}": convert_brightness(
                        float(device["effect"]["config"]["brightness"]), True
                    ),
                    f"{code}_{ATTR_LIGHT_EFFECT}": device["effect"].get("type"),
                    f"{code}_{ATTR_LIGHT_PRESET}": preset,
                    f"{code}_{ATTR_LIGHT_EFFECT_CONFIG}": self._convert_effect_config(
                        device["effect"]["config"]
                    ),
                    f"{code}_{ATTR_LIGHT_COLOR}": background,
                }
            else:
                data |= {
                    f"{code}_{ATTR_LIGHT_BRIGHTNESS}": 0,
                    f"{code}_{ATTR_LIGHT_EFFECT}": data.get(ATTR_LIGHT_EFFECTS, ["-"])[
                        0
                    ],
                    f"{code}_{ATTR_LIGHT_PRESET}": None,
                    f"{code}_{ATTR_LIGHT_EFFECT_CONFIG}": {},
                    f"{code}_{ATTR_LIGHT_COLOR}": None,
                }

            data[f"{code}_{ATTR_LIGHT_CONFIG}"] = {
                config: value
                for config, value in device.get("config", {}).items()
                if config not in ["icon_name", "name"]
            }

            device_config: dict = device.get("config", {})
            device_info: DeviceInfo = DeviceInfo(
                identifiers={
                    (DOMAIN, device_config.get("ip_address", f"{self.address}-{code}"))
                },
                name=device_config.get("name", code),
                model=device_config.get("type"),
                # LedFx 2.x frontend is a hash-routed SPA:
                # http://<host>:<port>/#/device/<virtual_id>
                configuration_url=f"http://{self.address}/#/device/{code}",
            )

            if code in self.devices:
                continue

            icon: str = device_config.get("icon_name", "")

            self.devices[code] = LedFxEntityDescription(
                description=LightEntityDescription(
                    key=code,
                    name=device_config.get("name", code),
                    icon=icon if icon.startswith("mdi:") else "mdi:led-strip-variant",
                    entity_registry_enabled_default=True,
                ),
                type=ActionType.DEVICE,
                device_info=device_info,
            )

            if self.new_device_callback:
                async_dispatcher_send(self.hass, SIGNAL_NEW_DEVICE, self.devices[code])

    def _convert_effect_config(self, config: dict) -> dict:
        """Convert effect config

        :param config: dict
        :return dict
        """

        for code, value in config.items():
            if code in self.color_properties and value in self.color_names:
                config[code] = self.color_names[value]

        return config

    async def _async_prepare_scenes(self, data: dict) -> None:
        """Prepare scenes.

        :param data: dict
        """

        response: dict = await self.client.scenes()

        if "scenes" in response and response["scenes"]:
            for code, scene in response["scenes"].items():
                if code in self.buttons:
                    continue

                self.buttons[code] = LedFxEntityDescription(
                    description=ButtonEntityDescription(
                        key=code,
                        name=scene["name"].title() if "name" in scene else code,
                        icon="mdi:image",
                        entity_registry_enabled_default=True,
                    ),
                    type=ActionType.SCENE,
                    device_info=self.device_info,
                )

                if self.new_button_callback:
                    async_dispatcher_send(
                        self.hass, SIGNAL_NEW_BUTTON, self.buttons[code]
                    )


@dataclass
class LedFxEntityDescription:
    """LedFx entity description."""

    description: EntityDescription
    device_info: DeviceInfo
    device_code: str | None = None
    type: ActionType = ActionType.DEFAULT
    extra: dict | None = None


def find_matching_preset(
    presets: dict, effect: str, config: dict
) -> tuple[str | None, str | None]:
    """Find the preset whose config matches an effect's active config.

    Mirrors ledfx.config.find_matching_preset: LedFx does not report which
    preset is active, so it is inferred by comparing configs, ignoring the
    UI-only keys LedFx itself ignores.

    :param presets: dict: {category: {effect: {preset_id: {"config": {...}}}}}
    :param effect: str: Active effect type
    :param config: dict: Active effect config
    :return tuple[str | None, str | None]: (preset_id, category)
    """

    if not isinstance(config, dict):
        return None, None

    target: dict = {
        code: value
        for code, value in config.items()
        if code not in PRESET_COMPARE_IGNORED_KEYS
    }

    for category in (ATTR_LIGHT_DEFAULT_PRESETS, ATTR_LIGHT_CUSTOM_PRESETS):
        for preset, data in presets.get(category, {}).get(effect, {}).items():
            candidate: dict = {
                code: value
                for code, value in data.get("config", {}).items()
                if code not in PRESET_COMPARE_IGNORED_KEYS
            }

            if candidate == target:
                return preset, category

    return None, None


def convert_brightness(brightness: float, is_reverse: bool = False) -> float:
    """Convert brightness

    :param brightness: float
    :param is_reverse: bool
    :return: float
    """

    if is_reverse:
        return min(float(math.ceil(brightness * 100 * 2.55)), 255)

    # pylint: disable=consider-using-f-string
    return float("{:.1f}".format(min(float(brightness / 100 / 2.55), 1.0)))


@callback
def async_get_updater(hass: HomeAssistant, identifier: str) -> LedFxUpdater:
    """Return LedFxUpdater for ip address or entry id.

    :param hass: HomeAssistant
    :param identifier: str
    :return LedFxUpdater
    """

    if (
        DOMAIN not in hass.data
        or identifier not in hass.data[DOMAIN]
        or UPDATER not in hass.data[DOMAIN][identifier]
    ):
        raise ValueError(f"Integration with identifier: {identifier} not found.")

    return hass.data[DOMAIN][identifier][UPDATER]
