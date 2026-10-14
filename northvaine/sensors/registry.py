"""Sensor registry (T3.6): look a sensor up by name."""

from __future__ import annotations

from typing import TYPE_CHECKING

from northvaine.core.settings import Settings
from northvaine.sensors.base import Sensor

if TYPE_CHECKING:
    import httpx

SENSOR_NAMES: tuple[str, ...] = (
    "ted",
    "tavily",
    "website",
    "fts",
    "worldbank",
    "usaspending",
    "hmrc",
)


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
    if name == "fts":
        from northvaine.sensors.fts import FtsSensor

        return FtsSensor(client=client, settings=settings)
    if name == "worldbank":
        from northvaine.sensors.worldbank import WorldBankSensor

        return WorldBankSensor(client=client, settings=settings)
    if name == "usaspending":
        from northvaine.sensors.usaspending import UsaspendingSensor

        return UsaspendingSensor(client=client, settings=settings)
    if name == "hmrc":
        from northvaine.sensors.hmrc import HmrcSensor

        return HmrcSensor(client=client, settings=settings)
    raise KeyError(f"unknown sensor {name!r}; known sensors: {', '.join(SENSOR_NAMES)}")
