"""Validated settings: CLI > environment > .env > YAML > model defaults."""

from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource
from textual.theme import BUILTIN_THEMES

from .themes import DEFAULT_THEME


class SSHSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8022, ge=1, le=65535)
    username: str = Field(default="monitor", min_length=1)
    host_key: str | None = Field(default=None, min_length=1)
    authorized_keys: str | None = Field(default=None, min_length=1)

    @field_validator("port", mode="before")
    @classmethod
    def reject_boolean_port(cls, value):
        if isinstance(value, bool):
            raise ValueError("port must be an integer, not a boolean")  # noqa: TRY004 - Pydantic validators require ValueError
        return value

    @field_validator("host_key", "authorized_keys")
    @classmethod
    def resolve_path(cls, value: str | None) -> str | None:
        return str(Path(value).expanduser().resolve()) if value is not None else None


class DashboardSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # The startup theme and refresh rate are configured here for local and SSH UI.
    theme: str = DEFAULT_THEME
    interval: float = Field(default=2, ge=0.2, le=3600, allow_inf_nan=False)
    mode: str = Field(default="live", pattern="^(live|demo)$")

    @field_validator("theme")
    @classmethod
    def known_theme(cls, value: str) -> str:
        if value not in {DEFAULT_THEME, *BUILTIN_THEMES}:
            raise ValueError(
                f"unknown theme {value!r}; use the dashboard's t picker to browse"
            )
        return value

    @field_validator("interval", mode="before")
    @classmethod
    def reject_boolean_interval(cls, value):
        if isinstance(value, bool):
            raise ValueError("interval must be a number, not a boolean")  # noqa: TRY004 - Pydantic validators require ValueError
        return value


class SourceSettings(BaseModel):
    """Connection and collection limits injected into each runtime strategy."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    podman_socket: str | None = None
    kubeconfig: str | None = None
    kube_context: str | None = None
    request_timeout: float = Field(default=3, gt=0, le=30)
    log_lines: int = Field(default=40, ge=1, le=1000)
    log_bytes: int = Field(default=32_768, ge=256, le=1_048_576)
    max_log_items: int = Field(default=12, ge=0, le=500)
    journal_lines: int = Field(default=50, ge=1, le=1000)
    cron_history_lines: int = Field(default=500, ge=1, le=5000)

    @field_validator("podman_socket", "kubeconfig")
    @classmethod
    def resolve_path(cls, value: str | None) -> str | None:
        return str(Path(value).expanduser().resolve()) if value else None


class RelativeYamlSource(YamlConfigSettingsSource):
    """Keep key paths relative to the YAML file, regardless of launch directory."""

    def _read_file(self, file_path: Path | Traversable) -> dict[str, Any]:
        try:
            with file_path.open(encoding="utf-8") as yaml_file:
                data = yaml.safe_load(yaml_file)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML in {file_path}: {exc}") from exc
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("config must be a YAML mapping")  # noqa: TRY004
        base_directory = (
            file_path.absolute().parent if isinstance(file_path, Path) else None
        )
        ssh = data.get("ssh")
        if isinstance(ssh, dict):
            for key in ("host_key", "authorized_keys"):
                value = ssh.get(key)
                if (
                    base_directory is not None
                    and isinstance(value, str)
                    and value.strip()
                ):
                    ssh[key] = str(
                        (base_directory / Path(value.strip()).expanduser()).resolve()
                    )
        sources = data.get("sources")
        if isinstance(sources, dict):
            for key in ("podman_socket", "kubeconfig"):
                value = sources.get(key)
                if (
                    base_directory is not None
                    and isinstance(value, str)
                    and value.strip()
                ):
                    sources[key] = str(
                        (base_directory / Path(value.strip()).expanduser()).resolve()
                    )
        if data.get("sources") is None:
            data.pop("sources", None)
        return data


class Settings(BaseSettings):
    """Application configuration merged from CLI, environment, dotenv, and YAML."""

    model_config = SettingsConfigDict(
        env_prefix="SSHUPTIME_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )
    _yaml_file: ClassVar[Path | None] = Path("sshuptime.yaml")

    ssh: SSHSettings = Field(default_factory=SSHSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    sources: SourceSettings = Field(default_factory=SourceSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            RelativeYamlSource(settings_cls, yaml_file=cls._yaml_file),
        )


def load_settings(
    path: str | None = None, *, discover: bool = True, **overrides: object
) -> Settings:
    """Load a config without mutating the Settings class or other sessions.

    CLI and environment paths resolve against cwd. YAML paths resolve against its
    directory. discover=False disables automatic YAML and .env loading, not env vars.
    """
    config_path = (
        Path(path).expanduser() if path is not None else Path("sshuptime.yaml")
    )
    if path is not None:
        # Pydantic's file sources skip missing files; explicit paths must fail.
        with config_path.open():
            pass

    class ConfiguredSettings(Settings):
        _yaml_file: ClassVar[Path | None] = (
            config_path if path is not None or discover else None
        )

    values: dict = {}
    for key, value in overrides.items():
        section = (
            "ssh"
            if key in SSHSettings.model_fields
            else "sources"
            if key in SourceSettings.model_fields
            else "dashboard"
        )
        if key not in (
            SSHSettings.model_fields
            | DashboardSettings.model_fields
            | SourceSettings.model_fields
        ):
            raise ValueError(f"unknown setting: {key}")
        if value is not None:
            values.setdefault(section, {})[key] = value
    return ConfiguredSettings(_env_file=".env" if discover else None, **values)


def validate_server_files(settings: Settings) -> tuple[str, str]:
    """Require existing key files and return their validated paths."""
    host_key = settings.ssh.host_key
    if host_key is None:
        raise ValueError("set ssh.host_key in YAML or pass --host-key")
    if not Path(host_key).is_file():
        raise ValueError(f"host_key file does not exist: {host_key}")
    authorized_keys = settings.ssh.authorized_keys
    if authorized_keys is None:
        raise ValueError("set ssh.authorized_keys in YAML or pass --authorized-keys")
    if not Path(authorized_keys).is_file():
        raise ValueError(f"authorized_keys file does not exist: {authorized_keys}")
    return host_key, authorized_keys
