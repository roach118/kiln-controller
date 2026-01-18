import logging
import os
from types import SimpleNamespace

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older Python
    import tomli as tomllib


CONFIG_PATH = os.environ.get(
    "KILN_CONFIG",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "config.toml")),
)


def _load_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def _resolve_path(base_dir, value):
    if not value:
        return value
    if os.path.isabs(value):
        return value
    return os.path.abspath(os.path.join(base_dir, value))


def _board_pin(name):
    if not name:
        return None
    try:
        import board
    except Exception:
        return name
    if not hasattr(board, name):
        raise ValueError(f"Unknown board pin '{name}'")
    return getattr(board, name)


def _log_level(value):
    if isinstance(value, int):
        return value
    levels = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }
    level = levels.get(str(value).upper())
    if level is None:
        raise ValueError(f"Unknown log level '{value}'")
    return level


def _pin_value(value):
    if value is None:
        raise ValueError("Missing security.pin in config.toml")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError("security.pin must be a numeric value")


def _thermocouple_type(value):
    if not value:
        return None
    import adafruit_max31856
    try:
        return getattr(adafruit_max31856.ThermocoupleType, value)
    except AttributeError as exc:
        raise ValueError(f"Unknown thermocouple type '{value}'") from exc


CONFIG = SimpleNamespace()

__all__ = ["CONFIG"]


def _set(key, value):
    setattr(CONFIG, key, value)


def _load_config():
    data = _load_toml(CONFIG_PATH)
    base_dir = os.path.dirname(CONFIG_PATH)

    logging_cfg = data.get("logging", {})
    server_cfg = data.get("server", {})
    cost_cfg = data.get("cost", {})
    hardware_cfg = data.get("hardware", {})
    thermocouple_cfg = data.get("thermocouple", {})
    run_cfg = data.get("run", {})
    pid_cfg = data.get("pid", {})
    simulation_cfg = data.get("simulation", {})
    restart_cfg = data.get("restart", {})
    profiles_cfg = data.get("profiles", {})
    security_cfg = data.get("security", {})

    _set("log_level", _log_level(logging_cfg.get("level", "INFO")))
    _set("log_format", logging_cfg.get("format", "%(asctime)s %(levelname)s %(name)s: %(message)s"))

    _set("listening_port", int(server_cfg.get("listening_port", 8081)))

    _set("kwh_rate", float(cost_cfg.get("kwh_rate", 0.0)))
    _set("kw_elements", float(cost_cfg.get("kw_elements", 0.0)))
    _set("currency_type", cost_cfg.get("currency_type", "$"))

    _set("spi_sclk", _board_pin(hardware_cfg.get("spi_sclk")))
    _set("spi_miso", _board_pin(hardware_cfg.get("spi_miso")))
    _set("spi_cs", _board_pin(hardware_cfg.get("spi_cs")))
    _set("spi_mosi", _board_pin(hardware_cfg.get("spi_mosi")))
    _set("gpio_heat", _board_pin(hardware_cfg.get("gpio_heat")))
    _set("gpio_heat_invert", bool(hardware_cfg.get("gpio_heat_invert", False)))

    model = thermocouple_cfg.get("model", "max31855").lower()
    max31855 = model == "max31855"
    max31856 = model == "max31856"
    if not (max31855 or max31856):
        raise ValueError(f"Unknown thermocouple model '{model}'")
    _set("max31855", max31855)
    _set("max31856", max31856)
    _set("thermocouple_type", _thermocouple_type(thermocouple_cfg.get("type", "K")) if max31856 else None)
    _set("ac_freq_50hz", bool(thermocouple_cfg.get("ac_freq_50hz", False)))
    _set("ignore_tc_lost_connection", bool(thermocouple_cfg.get("ignore_tc_lost_connection", False)))
    _set("ignore_tc_cold_junction_range_error", bool(thermocouple_cfg.get("ignore_tc_cold_junction_range_error", False)))
    _set("ignore_tc_range_error", bool(thermocouple_cfg.get("ignore_tc_range_error", False)))
    _set("ignore_tc_cold_junction_temp_high", bool(thermocouple_cfg.get("ignore_tc_cold_junction_temp_high", False)))
    _set("ignore_tc_cold_junction_temp_low", bool(thermocouple_cfg.get("ignore_tc_cold_junction_temp_low", False)))
    _set("ignore_tc_temp_high", bool(thermocouple_cfg.get("ignore_tc_temp_high", False)))
    _set("ignore_tc_temp_low", bool(thermocouple_cfg.get("ignore_tc_temp_low", False)))
    _set("ignore_tc_voltage_error", bool(thermocouple_cfg.get("ignore_tc_voltage_error", False)))
    _set("ignore_tc_short_errors", bool(thermocouple_cfg.get("ignore_tc_short_errors", False)))
    _set("ignore_tc_unknown_error", bool(thermocouple_cfg.get("ignore_tc_unknown_error", False)))
    _set("ignore_tc_too_many_errors", bool(thermocouple_cfg.get("ignore_tc_too_many_errors", False)))

    _set("seek_start", bool(run_cfg.get("seek_start", False)))
    _set("sensor_time_wait", float(run_cfg.get("sensor_time_wait", 2)))
    _set("kiln_must_catch_up", bool(run_cfg.get("kiln_must_catch_up", True)))
    _set("pid_control_window", float(run_cfg.get("pid_control_window", 5)))
    _set("thermocouple_offset", float(run_cfg.get("thermocouple_offset", 0)))
    _set("temperature_average_samples", int(run_cfg.get("temperature_average_samples", 10)))
    _set("temp_scale", run_cfg.get("temp_scale", "f"))
    _set("time_scale_slope", run_cfg.get("time_scale_slope", "h"))
    _set("time_scale_profile", run_cfg.get("time_scale_profile", "m"))
    _set("emergency_shutoff_temp", float(run_cfg.get("emergency_shutoff_temp", 0)))
    _set("ignore_temp_too_high", bool(run_cfg.get("ignore_temp_too_high", False)))
    _set("throttle_below_temp", float(run_cfg.get("throttle_below_temp", 0)))
    _set("throttle_percent", float(run_cfg.get("throttle_percent", 0)))
    _set("stop_integral_windup", bool(run_cfg.get("stop_integral_windup", True)))

    _set("pid_kp", float(pid_cfg.get("pid_kp", 1)))
    _set("pid_ki", float(pid_cfg.get("pid_ki", 1)))
    _set("pid_kd", float(pid_cfg.get("pid_kd", 1)))

    _set("simulate", bool(simulation_cfg.get("simulate", False)))
    _set("sim_t_env", float(simulation_cfg.get("sim_t_env", 0)))
    _set("sim_c_heat", float(simulation_cfg.get("sim_c_heat", 0)))
    _set("sim_c_oven", float(simulation_cfg.get("sim_c_oven", 0)))
    _set("sim_p_heat", float(simulation_cfg.get("sim_p_heat", 0)))
    _set("sim_R_o_nocool", float(simulation_cfg.get("sim_R_o_nocool", 0)))
    _set("sim_R_o_cool", float(simulation_cfg.get("sim_R_o_cool", 0)))
    _set("sim_R_ho_noair", float(simulation_cfg.get("sim_R_ho_noair", 0)))
    _set("sim_R_ho_air", float(simulation_cfg.get("sim_R_ho_air", 0)))
    _set("sim_speedup_factor", float(simulation_cfg.get("sim_speedup_factor", 1)))

    _set("automatic_restarts", bool(restart_cfg.get("automatic_restarts", True)))
    _set("automatic_restart_window", float(restart_cfg.get("automatic_restart_window", 15)))
    _set(
        "automatic_restart_state_file",
        _resolve_path(base_dir, restart_cfg.get("automatic_restart_state_file", "state.json")),
    )

    _set(
        "kiln_profiles_directory",
        _resolve_path(base_dir, profiles_cfg.get("kiln_profiles_directory", "storage/profiles")),
    )

    _set("security_pin", _pin_value(security_cfg.get("pin")))

    _validate_config()


def _validate_config():
    missing = []
    if CONFIG.max31855 is False and CONFIG.max31856 is False:
        missing.append("thermocouple.model")
    if CONFIG.gpio_heat is None:
        missing.append("hardware.gpio_heat")
    if CONFIG.spi_cs is None and (CONFIG.spi_sclk or CONFIG.spi_miso or CONFIG.spi_mosi):
        missing.append("hardware.spi_cs")
    if CONFIG.temperature_average_samples < 1:
        raise ValueError("run.temperature_average_samples must be >= 1")
    if CONFIG.pid_control_window <= 0:
        raise ValueError("run.pid_control_window must be > 0")
    if CONFIG.throttle_percent < 0 or CONFIG.throttle_percent > 100:
        raise ValueError("run.throttle_percent must be between 0 and 100")
    if missing:
        raise ValueError("Missing required config values: " + ", ".join(missing))


_load_config()
