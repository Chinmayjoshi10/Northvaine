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
    """The sensor called `name`, built with the given client and settings.

    Raises KeyError listing the known names for an unknown name. Sensor modules are imported
    on use, so asking for one sensor never imports the others.
    """
    if name == "ted":
        from northvaine.sensors.ted import TedSensor

        return TedSensor(client=client, settings=settings)
    if name == "tavily":
        from northvaine.sensors.tavily import TavilySensor

        return TavilySensor(client=client, settings=settings)
    if name == "website":
        from northvaine.sensors.website import WebsiteSensor

        return WebsiteSensor(client=client, settings=settings)
    raise KeyError(f"unknown sensor {name!r}; known sensors: {', '.join(SENSOR_NAMES)}")
