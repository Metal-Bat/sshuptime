"""Animated examples using the same validated contract as live collectors."""

import asyncio
import math
from datetime import UTC, datetime

from .models import HostInfo, Resource, Snapshot
from .presentation import runtime_views


class DemoCollector:
    """Deterministic, animated sample data. Never presented as real telemetry."""

    def __init__(self) -> None:
        self.tick = 0

    async def snapshot(self) -> Snapshot:
        """Return one animated frame with runtime views and sample resources."""
        await asyncio.sleep(0.03)
        self.tick += 1
        wave = (math.sin(self.tick / 4) + 1) * 12
        now = datetime.now(UTC).strftime("%H:%M:%S")

        def item(name: str, state: str = "running", cpu: float = 0) -> Resource:
            return Resource(
                id=name,
                name=name,
                state=state,
                cpu=cpu,
                memory=f"{int(64 + cpu * 18)} MiB",
                info="production / eu-west-1",
                manifest={
                    "name": name,
                    "status": state,
                    "labels": {"env": "production"},
                    "resources": {"cpu_percent": round(cpu, 1)},
                    "restartPolicy": "unless-stopped",
                },
                logs=[
                    f"{now} INFO  {name}: heartbeat received",
                    f"{now} {'ERROR backoff: retrying in 30s' if state == 'crashed' else 'INFO  health probe completed'}",
                ],
            )

        containers = [
            item("gateway", cpu=wave),
            item("api-01", cpu=wave + 8),
            item("postgres", cpu=4.2),
            item("worker-03", "crashed"),
            item("nightly-backup", "stopped"),
        ]
        inventory = {
            "Docker": {
                "Containers": containers,
                "Networks": [item("frontend", "active"), item("backend", "active")],
                "Volumes": [item("postgres-data", "mounted")],
            },
            "Kubernetes": {
                "Pods": [
                    item("payments-7db8", cpu=wave),
                    item("ingress-f92a", cpu=2),
                    item("queue-0", "crashed"),
                ],
                "Nodes": [item("node-a", "ready", 24), item("node-b", "ready", 31)],
                "Services": [item("payments", "active"), item("ingress", "active")],
            },
            "Podman": {
                "Containers": [item("metrics-agent", cpu=1.2)],
                "Networks": [item("podman", "active")],
                "Volumes": [],
            },
            "System": self.system_inventory(item, wave),
        }
        return Snapshot(
            host="atlas-prod-01 · DEMO",
            uptime=f"12d 06h {self.tick // 60:02}m",
            cpu=wave + 14,
            memory=61 + wave / 8,
            disk=42,
            inventory=inventory,
            views={
                name: runtime_views(*categories)
                for name, categories in inventory.items()
            },
            host_info=HostInfo(
                hostname="atlas-prod-01",
                ip="10.42.1.17",
                linux="Debian GNU/Linux 13",
                kernel="6.12.0",
            ),
            events=[
                f"{now} ● worker-03 crashed · exit 137",
                f"{now} ● queue-0 waiting · restart backoff",
                f"{now} ○ collector heartbeat #{self.tick}",
            ],
        )

    @staticmethod
    def system_inventory(item, wave: float) -> dict[str, list[Resource]]:
        """Keep the host sample separate from runtime sample construction."""
        return {
            "Processes": [
                Resource(
                    id=str(pid),
                    name=name,
                    state=state,
                    cpu=cpu,
                    memory=mem,
                    info=f"PID {pid} · user {user}",
                    manifest={
                        "pid": pid,
                        "user": user,
                        "command": name,
                        "state": state,
                    },
                )
                for pid, name, state, cpu, mem, user in [
                    (1042, "postgres", "sleeping", 4.2, "412 MiB", "postgres"),
                    (
                        2198,
                        "python worker.py",
                        "running",
                        wave + 8,
                        "186 MiB",
                        "app",
                    ),
                    (845, "containerd", "sleeping", 1.1, "92 MiB", "root"),
                    (
                        3012,
                        "nginx: worker",
                        "running",
                        2.8,
                        "24 MiB",
                        "www-data",
                    ),
                ]
            ],
            "Services": [
                item("sshd.service", "active"),
                item("docker.service", "active"),
                item("backup.service", "failed"),
            ],
            "Errors": [
                Resource(
                    id="journal-demo-1",
                    name="kernel",
                    state="error",
                    info="2026-09-27 12:41:04 UTC · disk I/O retry on nvme0n1",
                    manifest={
                        "PRIORITY": "3",
                        "MESSAGE": "disk I/O retry on nvme0n1",
                        "_TRANSPORT": "kernel",
                    },
                    logs=["2026-09-27 12:41:04 UTC  kernel: disk I/O retry on nvme0n1"],
                ),
                item("backup.service", "failed"),
            ],
            "Cron": [
                Resource(
                    id="demo-cron-backup",
                    name="/usr/local/bin/backup --incremental",
                    state="registered",
                    info="0 2 * * * · root · /etc/crontab",
                    manifest={
                        "schedule": "0 2 * * *",
                        "user": "root",
                        "command": "/usr/local/bin/backup --incremental",
                        "source": "/etc/crontab",
                        "line": 8,
                        "last_run": "2026-09-27 02:00:01 UTC",
                    },
                    logs=[
                        "2026-09-26 02:00:01 UTC  launched by cron (completion status unknown)",
                        "2026-09-27 02:00:01 UTC  launched by cron (completion status unknown)",
                    ],
                ),
                Resource(
                    id="demo-cron-cleanup",
                    name="/usr/local/bin/cleanup --tmp",
                    state="registered",
                    info="@daily · app · user crontab: app",
                    manifest={
                        "schedule": "@daily",
                        "user": "app",
                        "command": "/usr/local/bin/cleanup --tmp",
                        "source": "user crontab: app",
                        "line": 3,
                        "last_run": "—",
                    },
                    logs=[
                        "No matching launch recorded in the readable journal for this boot."
                    ],
                ),
            ],
        }
