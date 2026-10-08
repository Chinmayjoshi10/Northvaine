"""Sensor registry: names, protocol conformance, pass-through, unknown name (T3.6)."""

from __future__ import annotations

import httpx
import pytest

from northvaine.core.settings import Settings
from northvaine.sensors.base import Sensor
from northvaine.sensors.registry import SENSOR_NAMES, get_sensor
from northvaine.sensors.tavily import TavilySensor
from northvaine.sensors.ted import TedSensor
from northvaine.sensors.website import WebsiteSensor

SETTINGS = Settings(_env_file=None)


def test_sensor_names_are_fixed() -> None:
    assert SENSOR_NAMES == ("ted", "tavily", "website", "fts", "worldbank", "usaspending")


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_every_name_gives_a_sensor_of_that_name(name: str) -> None:
    sensor = get_sensor(name)
    assert isinstance(sensor, Sensor)
    assert sensor.name == name


def test_classes_match_names() -> None:
    assert isinstance(get_sensor("ted"), TedSensor)
    assert isinstance(get_sensor("tavily"), TavilySensor)
    assert isinstance(get_sensor("website"), WebsiteSensor)


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_client_and_settings_are_passed_through(name: str) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    sensor = get_sensor(name, client=http, settings=SETTINGS)
    assert sensor._client is http  # type: ignore[attr-defined]
    assert sensor._settings is SETTINGS  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", ["", "TED", "bing", "ted "])
def test_unknown_name_raises_keyerror_listing_known_names(name: str) -> None:
    with pytest.raises(KeyError) as info:
        get_sensor(name)
    message = str(info.value)
    for known in SENSOR_NAMES:
        assert known in message
