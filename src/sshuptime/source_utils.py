"""Shared mapping and bounded-output helpers for runtime adapters."""

from datetime import datetime
from typing import Any


def safe_json(value: Any, key: str = "") -> Any:
    """Make SDK objects JSON-safe and remove common credential fields."""
    if any(
        secret in key.lower()
        for secret in ("password", "secret", "token", "credential", "privatekey")
    ) or key.lower() in {"env", "environment"}:
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): safe_json(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value[:200]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def memory_text(value: float | None) -> str:
    """Format a byte count for compact inventory cells."""
    if value is None:
        return "—"
    return (
        f"{value / 1024**2:.0f} MiB"
        if value < 1024**3
        else f"{value / 1024**3:.1f} GiB"
    )


def log_tail(
    value: bytes | str | None, *, lines: int = 40, max_bytes: int = 32_768
) -> list[str]:
    """Keep a bounded tail of a runtime's log payload."""
    if not value:
        return []
    if isinstance(value, bytes):
        value = value[-max_bytes:].decode("utf-8", errors="replace")
    return value[-max_bytes:].splitlines()[-lines:]


def runtime_state(value: str | None) -> str:
    """Normalize engine-specific lifecycle names for the dashboard."""
    state = (value or "unknown").lower()
    return {
        "exited": "stopped",
        "dead": "crashed",
        "created": "stopped",
        "up": "running",
    }.get(state, state)


def docker_cpu(stats: dict) -> float:
    """Calculate Docker's CPU percentage from its current and prior samples."""
    current = stats.get("cpu_stats") or {}
    previous = stats.get("precpu_stats") or {}
    delta = (current.get("cpu_usage") or {}).get("total_usage", 0) - (
        previous.get("cpu_usage") or {}
    ).get("total_usage", 0)
    system_delta = current.get("system_cpu_usage", 0) - previous.get(
        "system_cpu_usage", 0
    )
    cores = (
        current.get("online_cpus")
        or len((current.get("cpu_usage") or {}).get("percpu_usage") or [])
        or 1
    )
    return max(0.0, delta / system_delta * cores * 100) if system_delta > 0 else 0.0
