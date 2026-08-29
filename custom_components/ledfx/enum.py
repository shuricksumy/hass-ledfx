"""Enums.

StrEnum rather than (str, Enum): with the latter, Python 3.11 changed
f"{Member}" to render "Class.MEMBER" instead of the value, which silently
broke every handler name built by interpolating one of these.
"""

from __future__ import annotations

from enum import StrEnum


class Method(StrEnum):
    """Method enum"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class ActionType(StrEnum):
    """ActionType enum"""

    DEFAULT = "default"
    SCENE = "scene"
    DEVICE = "device"


class EffectCategory(StrEnum):
    """EffectCategory enum"""

    NONE = "none"
    DEFAULT = "ledfx_presets"
    CUSTOM = "user_presets"
