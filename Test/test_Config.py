import pytest

from config import AppConfig, _pin_value


def test_pin_value_accepts_numbers():
    assert _pin_value(1234) == 1234
    assert _pin_value("5678") == 5678


def test_pin_value_rejects_invalid():
    with pytest.raises(ValueError):
        _pin_value(None)
    with pytest.raises(ValueError):
        _pin_value("abcd")


def test_invalid_thermocouple_model_rejected(tmp_path):
    data = {
        "thermocouple": {"model": "unknown"},
        "security": {"pin": 1234},
    }
    with pytest.raises(ValueError):
        AppConfig.from_toml(data, base_dir=str(tmp_path))


def test_force_simulation_on_missing_pins(tmp_path):
    data = {
        "thermocouple": {"model": "max31855"},
        "hardware": {"gpio_heat": "NOT_A_PIN"},
        "simulation": {"simulate": False},
        "security": {"pin": 1234},
    }
    config = AppConfig.from_toml(data, base_dir=str(tmp_path))
    assert config.simulation.simulate is True
