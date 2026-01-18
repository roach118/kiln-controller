import logging
import os
from dataclasses import dataclass
from typing import Optional

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


@dataclass
class LoggingConfig:
    level: int
    format: str


@dataclass
class ServerConfig:
    listening_port: int


@dataclass
class CostConfig:
    kwh_rate: float
    kw_elements: float
    currency_type: str


@dataclass
class HardwareConfig:
    spi_sclk: Optional[object]
    spi_miso: Optional[object]
    spi_cs: Optional[object]
    spi_mosi: Optional[object]
    gpio_heat: Optional[object]
    gpio_heat_invert: bool


@dataclass
class ThermocoupleConfig:
    max31855: bool
    max31856: bool
    type: Optional[object]
    ac_freq_50hz: bool
    ignore_tc_lost_connection: bool
    ignore_tc_cold_junction_range_error: bool
    ignore_tc_range_error: bool
    ignore_tc_cold_junction_temp_high: bool
    ignore_tc_cold_junction_temp_low: bool
    ignore_tc_temp_high: bool
    ignore_tc_temp_low: bool
    ignore_tc_voltage_error: bool
    ignore_tc_short_errors: bool
    ignore_tc_unknown_error: bool
    ignore_tc_too_many_errors: bool


@dataclass
class RunConfig:
    seek_start: bool
    sensor_time_wait: float
    kiln_must_catch_up: bool
    pid_control_window: float
    thermocouple_offset: float
    temperature_average_samples: int
    temp_scale: str
    time_scale_slope: str
    time_scale_profile: str
    emergency_shutoff_temp: float
    ignore_temp_too_high: bool
    throttle_below_temp: float
    throttle_percent: float
    stop_integral_windup: bool


@dataclass
class PidConfig:
    kp: float
    ki: float
    kd: float


@dataclass
class SimulationConfig:
    simulate: bool
    t_env: float
    c_heat: float
    c_oven: float
    p_heat: float
    R_o_nocool: float
    R_o_cool: float
    R_ho_noair: float
    R_ho_air: float
    speedup_factor: float


@dataclass
class RestartConfig:
    automatic_restarts: bool
    automatic_restart_window: float
    automatic_restart_state_file: str


@dataclass
class ProfilesConfig:
    kiln_profiles_directory: str


@dataclass
class SecurityConfig:
    pin: int


@dataclass
class AppConfig:
    logging: LoggingConfig
    server: ServerConfig
    cost: CostConfig
    hardware: HardwareConfig
    thermocouple: ThermocoupleConfig
    run: RunConfig
    pid: PidConfig
    simulation: SimulationConfig
    restart: RestartConfig
    profiles: ProfilesConfig
    security: SecurityConfig

    def __post_init__(self):
        missing = []
        if not self.simulation.simulate:
            if self.thermocouple.max31855 is False and self.thermocouple.max31856 is False:
                missing.append("thermocouple.model")
            if self.hardware.gpio_heat is None:
                missing.append("hardware.gpio_heat")
            if self.hardware.spi_cs is None and (
                self.hardware.spi_sclk or self.hardware.spi_miso or self.hardware.spi_mosi
            ):
                missing.append("hardware.spi_cs")
        if self.thermocouple.max31856 and self.thermocouple.type is None:
            missing.append("thermocouple.type")
        if self.run.temperature_average_samples < 1:
            raise ValueError("run.temperature_average_samples must be >= 1")
        if self.run.pid_control_window <= 0:
            raise ValueError("run.pid_control_window must be > 0")
        if self.run.throttle_percent < 0 or self.run.throttle_percent > 100:
            raise ValueError("run.throttle_percent must be between 0 and 100")
        if missing:
            raise ValueError("Missing required config values: " + ", ".join(missing))

    @classmethod
    def from_toml(cls, data, base_dir):
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

        model = thermocouple_cfg.get("model", "max31855").lower()
        max31855 = model == "max31855"
        max31856 = model == "max31856"
        if not (max31855 or max31856):
            raise ValueError(f"Unknown thermocouple model '{model}'")

        thermocouple_type = (
            _thermocouple_type(thermocouple_cfg.get("type", "K"))
            if max31856
            else None
        )

        return cls(
            logging=LoggingConfig(
                level=_log_level(logging_cfg.get("level", "INFO")),
                format=logging_cfg.get(
                    "format",
                    "%(asctime)s %(levelname)s %(name)s: %(message)s",
                ),
            ),
            server=ServerConfig(
                listening_port=int(server_cfg.get("listening_port", 8081)),
            ),
            cost=CostConfig(
                kwh_rate=float(cost_cfg.get("kwh_rate", 0.0)),
                kw_elements=float(cost_cfg.get("kw_elements", 0.0)),
                currency_type=cost_cfg.get("currency_type", "$"),
            ),
            hardware=HardwareConfig(
                spi_sclk=_board_pin(hardware_cfg.get("spi_sclk")),
                spi_miso=_board_pin(hardware_cfg.get("spi_miso")),
                spi_cs=_board_pin(hardware_cfg.get("spi_cs")),
                spi_mosi=_board_pin(hardware_cfg.get("spi_mosi")),
                gpio_heat=_board_pin(hardware_cfg.get("gpio_heat")),
                gpio_heat_invert=bool(hardware_cfg.get("gpio_heat_invert", False)),
            ),
            thermocouple=ThermocoupleConfig(
                max31855=max31855,
                max31856=max31856,
                type=thermocouple_type,
                ac_freq_50hz=bool(thermocouple_cfg.get("ac_freq_50hz", False)),
                ignore_tc_lost_connection=bool(thermocouple_cfg.get("ignore_tc_lost_connection", False)),
                ignore_tc_cold_junction_range_error=bool(thermocouple_cfg.get("ignore_tc_cold_junction_range_error", False)),
                ignore_tc_range_error=bool(thermocouple_cfg.get("ignore_tc_range_error", False)),
                ignore_tc_cold_junction_temp_high=bool(thermocouple_cfg.get("ignore_tc_cold_junction_temp_high", False)),
                ignore_tc_cold_junction_temp_low=bool(thermocouple_cfg.get("ignore_tc_cold_junction_temp_low", False)),
                ignore_tc_temp_high=bool(thermocouple_cfg.get("ignore_tc_temp_high", False)),
                ignore_tc_temp_low=bool(thermocouple_cfg.get("ignore_tc_temp_low", False)),
                ignore_tc_voltage_error=bool(thermocouple_cfg.get("ignore_tc_voltage_error", False)),
                ignore_tc_short_errors=bool(thermocouple_cfg.get("ignore_tc_short_errors", False)),
                ignore_tc_unknown_error=bool(thermocouple_cfg.get("ignore_tc_unknown_error", False)),
                ignore_tc_too_many_errors=bool(thermocouple_cfg.get("ignore_tc_too_many_errors", False)),
            ),
            run=RunConfig(
                seek_start=bool(run_cfg.get("seek_start", False)),
                sensor_time_wait=float(run_cfg.get("sensor_time_wait", 2)),
                kiln_must_catch_up=bool(run_cfg.get("kiln_must_catch_up", True)),
                pid_control_window=float(run_cfg.get("pid_control_window", 5)),
                thermocouple_offset=float(run_cfg.get("thermocouple_offset", 0)),
                temperature_average_samples=int(run_cfg.get("temperature_average_samples", 10)),
                temp_scale=run_cfg.get("temp_scale", "f"),
                time_scale_slope=run_cfg.get("time_scale_slope", "h"),
                time_scale_profile=run_cfg.get("time_scale_profile", "m"),
                emergency_shutoff_temp=float(run_cfg.get("emergency_shutoff_temp", 0)),
                ignore_temp_too_high=bool(run_cfg.get("ignore_temp_too_high", False)),
                throttle_below_temp=float(run_cfg.get("throttle_below_temp", 0)),
                throttle_percent=float(run_cfg.get("throttle_percent", 0)),
                stop_integral_windup=bool(run_cfg.get("stop_integral_windup", True)),
            ),
            pid=PidConfig(
                kp=float(pid_cfg.get("pid_kp", 1)),
                ki=float(pid_cfg.get("pid_ki", 1)),
                kd=float(pid_cfg.get("pid_kd", 1)),
            ),
            simulation=SimulationConfig(
                simulate=bool(simulation_cfg.get("simulate", False)),
                t_env=float(simulation_cfg.get("sim_t_env", 0)),
                c_heat=float(simulation_cfg.get("sim_c_heat", 0)),
                c_oven=float(simulation_cfg.get("sim_c_oven", 0)),
                p_heat=float(simulation_cfg.get("sim_p_heat", 0)),
                R_o_nocool=float(simulation_cfg.get("sim_R_o_nocool", 0)),
                R_o_cool=float(simulation_cfg.get("sim_R_o_cool", 0)),
                R_ho_noair=float(simulation_cfg.get("sim_R_ho_noair", 0)),
                R_ho_air=float(simulation_cfg.get("sim_R_ho_air", 0)),
                speedup_factor=float(simulation_cfg.get("sim_speedup_factor", 1)),
            ),
            restart=RestartConfig(
                automatic_restarts=bool(restart_cfg.get("automatic_restarts", True)),
                automatic_restart_window=float(restart_cfg.get("automatic_restart_window", 15)),
                automatic_restart_state_file=_resolve_path(
                    base_dir,
                    restart_cfg.get("automatic_restart_state_file", "state.json"),
                ),
            ),
            profiles=ProfilesConfig(
                kiln_profiles_directory=_resolve_path(
                    base_dir,
                    profiles_cfg.get("kiln_profiles_directory", "storage/profiles"),
                ),
            ),
            security=SecurityConfig(
                pin=_pin_value(security_cfg.get("pin")),
            ),
        )


def _load_config():
    data = _load_toml(CONFIG_PATH)
    base_dir = os.path.dirname(CONFIG_PATH)
    return AppConfig.from_toml(data, base_dir)


CONFIG = _load_config()

__all__ = ["CONFIG", "CONFIG_PATH", "AppConfig"]
