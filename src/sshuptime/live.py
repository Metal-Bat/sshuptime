"""Read-only live collectors for the local host and available runtimes."""

import asyncio
import ipaddress
import json
import os
import platform
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from .config import SourceSettings
from .cron import CronCollector
from .engines import DockerCollector, PodmanCollector
from .kubernetes import KubernetesCollector
from .models import HostInfo, Resource, RuntimeStrategy, Snapshot
from .presentation import default_view, runtime_views
from .source_utils import memory_text, safe_json


def default_route_interfaces() -> list[str]:
    """Prefer interfaces with a gateway in Linux's local routing table."""
    try:
        lines = Path("/proc/net/route").read_text(encoding="ascii").splitlines()[1:]
    except OSError:
        return []
    routes: list[tuple[int, str]] = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "00000000":
            try:
                if int(parts[3], 16) & 1:
                    routes.append((0 if parts[2] != "00000000" else 1, parts[0]))
            except ValueError:
                continue
    return [name for _, name in sorted(routes)]


def primary_ip() -> str:
    """Choose an active default-route IPv4 address, then fall back to others."""
    routes = default_route_interfaces()
    candidates: list[tuple[int, int, str, str]] = []
    interfaces = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        if not interfaces.get(name) or not interfaces[name].isup:
            continue
        for address in addresses:
            if address.family not in (socket.AF_INET, socket.AF_INET6):
                continue
            value = address.address.split("%", 1)[0]
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified:
                continue
            route_rank = routes.index(name) if name in routes else 3
            bridge_penalty = 2 if name.startswith(("docker", "br-", "veth")) else 0
            candidates.append(
                (
                    route_rank + bridge_penalty,
                    0 if parsed.version == 4 else 1,
                    name,
                    value,
                )
            )
    return min(candidates)[-1] if candidates else "—"


def host_info() -> HostInfo:
    try:
        release = platform.freedesktop_os_release()
        linux = release.get("PRETTY_NAME") or release.get("NAME") or platform.system()
    except OSError:
        linux = platform.system()
    return HostInfo(
        hostname=socket.gethostname(),
        ip=primary_ip(),
        linux=linux,
        kernel=platform.release(),
    )


class SystemCollector:
    """Host metrics, processes, services, journal errors, and cron jobs."""

    def __init__(self, settings: SourceSettings | None = None) -> None:
        self.settings = settings or SourceSettings()
        self.views = runtime_views("Processes", "Services", "Errors", "Cron")
        psutil.cpu_percent(interval=None)
        self.processes: dict[tuple[int, float], psutil.Process] = {}
        self.cron = CronCollector(self.settings)

    async def collect(self) -> tuple[dict[str, Any], dict[str, list[Resource]]]:
        """Collect host readings and System categories concurrently."""
        metrics, services, journal, cron = await asyncio.gather(
            asyncio.to_thread(self._read_host),
            self._read_services(),
            self._read_journal(),
            self.cron.collect(),
        )
        inventory = {"Processes": metrics.pop("processes")}
        if services is not None:
            inventory["Services"] = services
        failed = [service for service in services or [] if service.state == "failed"]
        errors = failed + journal
        if not errors:
            errors = [
                Resource(
                    id="no-errors",
                    name="No OS errors found",
                    state="ready",
                    info="No failed services or journal errors in the current boot",
                    manifest={
                        "journal_scope": "current boot",
                        "priority": "error or higher",
                    },
                )
            ]
        inventory["Errors"] = errors
        inventory["Cron"] = cron
        return metrics, inventory

    def _read_host(self) -> dict[str, Any]:
        now = time.time()
        boot = psutil.boot_time()
        elapsed = max(0, int(now - boot))
        disk = psutil.disk_usage("/")
        seen: set[tuple[int, float]] = set()
        rows: list[Resource] = []
        for proc in psutil.process_iter(
            attrs=[
                "pid",
                "name",
                "username",
                "status",
                "memory_info",
                "create_time",
                "cmdline",
            ],
            ad_value=None,
        ):
            try:
                data = proc.info
                pid = data["pid"]
                created = data["create_time"]
                if created is None:
                    continue
                identity = (pid, created)
                seen.add(identity)
                sampled = self.processes.get(identity)
                if sampled is None:
                    sampled = proc
                    sampled.cpu_percent(interval=None)
                    self.processes[identity] = sampled
                    cpu = 0.0
                else:
                    cpu = sampled.cpu_percent(interval=None)
                command = " ".join(data["cmdline"] or []) or data["name"] or str(pid)
                rss = data["memory_info"].rss if data["memory_info"] else None
                state = str(data["status"] or "unknown")
                rows.append(
                    Resource(
                        id=f"{pid}:{created}",
                        name=(data["name"] or command)[:64],
                        state=state,
                        cpu=cpu,
                        memory=memory_text(rss),
                        info=f"PID {pid} · {data['username'] or 'unknown'}",
                        manifest={
                            "pid": pid,
                            "created": datetime.fromtimestamp(created, UTC).isoformat(),
                            "command": command,
                            "user": data["username"],
                            "status": state,
                            "rss_bytes": rss,
                        },
                    )
                )
            except psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess:
                continue
        for identity in self.processes.keys() - seen:
            del self.processes[identity]
        return {
            "host": socket.gethostname(),
            "host_info": host_info(),
            "uptime": f"{elapsed // 86400}d {(elapsed % 86400) // 3600:02}h {(elapsed % 3600) // 60:02}m",
            "cpu": psutil.cpu_percent(interval=None),
            "memory": psutil.virtual_memory().percent,
            "disk": disk.percent,
            "processes": rows,
        }

    async def _read_services(self) -> list[Resource] | None:
        if os.name != "posix" or not Path("/run/systemd/system").exists():
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl",
                "list-units",
                "--type=service",
                "--all",
                "--no-legend",
                "--no-pager",
                "--plain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            output, _ = await asyncio.wait_for(
                proc.communicate(), self.settings.request_timeout
            )
        except OSError, TimeoutError:
            if "proc" in locals() and proc.returncode is None:
                proc.kill()
                await proc.wait()
            return None
        if proc.returncode:
            return None
        rows = []
        for line in output.decode(errors="replace").splitlines():
            fields = line.strip().lstrip("● ").split(maxsplit=4)
            if len(fields) < 4 or not fields[0].endswith(".service"):
                continue
            unit, load, active, sub = fields[:4]
            state = "failed" if active == "failed" else active
            rows.append(
                Resource(
                    id=unit,
                    name=unit,
                    state=state,
                    info=fields[4] if len(fields) > 4 else sub,
                    manifest={"unit": unit, "load": load, "active": active, "sub": sub},
                )
            )
        return rows

    async def _read_journal(self) -> list[Resource]:
        """Show recent current-boot journal entries at error priority or higher."""
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "journalctl",
                "--boot",
                "--priority=err",
                f"--lines={self.settings.journal_lines}",
                "--output=json",
                "--no-pager",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, stderr = await asyncio.wait_for(
                proc.communicate(), self.settings.request_timeout
            )
        except (OSError, TimeoutError) as exc:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            return [
                Resource(
                    id="journal-unavailable",
                    name="Journal unavailable",
                    state="unavailable",
                    info=str(exc) or "Journal request timed out",
                    manifest={"source": "journalctl", "error": str(exc)},
                )
            ]
        if proc.returncode or (not output and b"No journal files" in stderr):
            message = (
                stderr.decode(errors="replace").strip()
                or f"journalctl exited {proc.returncode}"
            )
            return [
                Resource(
                    id="journal-unavailable",
                    name="Journal unavailable",
                    state="unavailable",
                    info=message[:240],
                    manifest={"source": "journalctl", "error": message[:500]},
                )
            ]
        rows = []
        for line in output.splitlines():
            try:
                entry = json.loads(line)
            except ValueError, TypeError:
                continue
            if not isinstance(entry, dict):
                continue
            cursor = str(
                entry.get("__CURSOR") or entry.get("__REALTIME_TIMESTAMP") or len(rows)
            )
            raw_timestamp = entry.get("__REALTIME_TIMESTAMP")
            try:
                timestamp = datetime.fromtimestamp(
                    int(raw_timestamp) / 1_000_000, UTC
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
            except TypeError, ValueError, OverflowError:
                timestamp = "Unknown time"
            unit = str(
                entry.get("_SYSTEMD_UNIT") or entry.get("SYSLOG_IDENTIFIER") or "kernel"
            )
            message = " ".join(str(entry.get("MESSAGE") or "No message").split())
            rows.append(
                Resource(
                    id=cursor,
                    name=unit,
                    state="error",
                    info=f"{timestamp} · {message[:160]}",
                    manifest=safe_json(entry),
                    logs=[f"{timestamp}  {message[: self.settings.log_bytes]}"],
                )
            )
        rows.reverse()
        return rows


class LiveCollector:
    """Combine injected runtime strategies without coupling their failures."""

    def __init__(
        self,
        *,
        settings: SourceSettings | None = None,
        strategies: tuple[RuntimeStrategy, ...] | None = None,
        podman_socket: str | None = None,
        kubeconfig: str | None = None,
        kube_context: str | None = None,
    ) -> None:
        overrides = {
            key: value
            for key, value in (
                ("podman_socket", podman_socket),
                ("kubeconfig", kubeconfig),
                ("kube_context", kube_context),
            )
            if value is not None
        }
        self.settings = SourceSettings(
            **{**(settings or SourceSettings()).model_dump(), **overrides}
        )
        self.system = SystemCollector(self.settings)
        if strategies is None:
            self.docker = DockerCollector(self.settings)
            self.podman = PodmanCollector(settings=self.settings)
            self.kubernetes = KubernetesCollector(settings=self.settings)
            self.strategies: tuple[RuntimeStrategy, ...] = (
                self.docker,
                self.podman,
                self.kubernetes,
            )
        else:
            self.strategies = strategies
        self.last_inventory: dict[str, dict[str, list[Resource]]] = {}
        self.last_error: dict[str, str] = {}
        self.last_states: dict[tuple[str, str, str], str] = {}
        self.lock = asyncio.Lock()

    async def snapshot(self) -> Snapshot:
        """Collect host data and merge independently available runtimes."""
        async with self.lock:
            system_task = asyncio.create_task(self.system.collect())
            runtime_results = await asyncio.gather(
                *(strategy.collect() for strategy in self.strategies),
                return_exceptions=True,
            )
            metrics, system_inventory = await system_task
            inventory: dict[str, dict[str, list[Resource]]] = {
                "System": system_inventory
            }
            views = {
                "System": {
                    category: self.system.views.get(category, default_view(category))
                    for category in system_inventory
                }
            }
            events: list[str] = []
            for strategy, result in zip(self.strategies, runtime_results):
                self._merge_runtime(strategy, result, inventory, events)
                if strategy.name in inventory:
                    views[strategy.name] = {
                        category: strategy.views.get(category, default_view(category))
                        for category in inventory[strategy.name]
                    }
            events.extend(self._state_events(inventory))
            if self.last_error:
                metrics["host"] += " · STALE: " + ", ".join(self.last_error)
            return Snapshot(inventory=inventory, views=views, events=events, **metrics)

    def _merge_runtime(
        self,
        strategy: RuntimeStrategy,
        result: dict[str, list[Resource]] | BaseException | None,
        inventory: dict[str, dict[str, list[Resource]]],
        events: list[str],
    ) -> None:
        """Retain one strategy's last data across an isolated failure."""
        name = strategy.name
        if isinstance(result, BaseException):
            message = f"{type(result).__name__}: {result}"
            if self.last_error.get(name) != message:
                events.append(f"{name} unavailable · {message}")
            self.last_error[name] = message
        elif result is None:
            if name in self.last_inventory:
                if name not in self.last_error:
                    events.append(
                        f"{name} unavailable · endpoint not found; showing last data"
                    )
                self.last_error[name] = "endpoint not found"
        else:
            if name in self.last_error:
                events.append(f"{name} connection restored")
                self.last_error.pop(name, None)
            self.last_inventory[name] = result
            inventory[name] = result
            return
        if name in self.last_inventory:
            inventory[name] = self.last_inventory[name]

    def _state_events(
        self, inventory: dict[str, dict[str, list[Resource]]]
    ) -> list[str]:
        """Report state transitions only for fresh runtime observations."""
        states: dict[tuple[str, str, str], str] = {}
        events = []
        for runtime, categories in inventory.items():
            if runtime in self.last_error:
                continue
            for category, rows in categories.items():
                for row in rows:
                    key = (runtime, category, row.id)
                    states[key] = row.state
                    before = self.last_states.get(key)
                    if before is not None and before != row.state:
                        events.append(
                            f"{runtime}/{category} {row.name}: {before} → {row.state}"
                        )
        self.last_states = states
        return events
