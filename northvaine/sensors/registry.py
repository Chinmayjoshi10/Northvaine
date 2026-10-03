"""Sensor registry (T3.6): look a sensor up by name."""

from __future__ import annotations

from typing import TYPE_CHECKING

from northvaine.core.settings import Settings
from northvaine.sensors.base import Sensor

if TYPE_CHECKING:
    import httpx

SENSOR_NAMES: tuple[str, ...] = ("ted", "tavily", "website")


def get_sensor(
    name: str, *, client: httpx.AsyncClient | None = None, settings: Settings | None = None
) -> Sensor:
    """The sensor called `name`; ValueError for an unknown name. T3.6."""
    raise NotImplementedError("T3.6")
