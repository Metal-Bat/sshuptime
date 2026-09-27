"""Read-only cron inventory and current-boot launch history."""

import asyncio
import getpass
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from .config import SourceSettings
from .models import Resource

PERIODIC = ("hourly", "daily", "weekly", "monthly")
NICKNAMES = {
    "@reboot",
    "@yearly",
    "@annually",
    "@monthly",
    "@weekly",
    "@daily",
    "@hourly",
}
ENVIRONMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")
LAUNCH = re.compile(r"\((?P<user>[^)]+)\)\s+CMD\s+\((?P<command>.*)\)")


def parse_crontab(
    contents: str, source: str, *, user: str | None = None, system: bool = False
) -> list[Resource]:
    """Parse user/system cron entries while preserving their source and line."""
    jobs = []
    for number, raw in enumerate(contents.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or ENVIRONMENT.match(line):
            continue
        if line.startswith("@"):
            fields = line.split(maxsplit=2 if system else 1)
            if fields[0] not in NICKNAMES:
                continue
            if len(fields) < (3 if system else 2):
                continue
            schedule = fields[0]
            owner = fields[1] if system else user or "unknown"
            command = fields[2] if system else fields[1]
        else:
            fields = line.split(maxsplit=6 if system else 5)
            if len(fields) < (7 if system else 6):
                continue
            schedule = " ".join(fields[:5])
            owner = fields[5] if system else user or "unknown"
            command = fields[6] if system else fields[5]
        jobs.append(
            Resource(
                id=f"{source}:{number}",
                name=command[:64],
                state="registered",
                info=f"{schedule} · {owner} · {source}",
                manifest={
                    "schedule": schedule,
                    "user": owner,
                    "command": command,
                    "source": source,
                    "line": number,
                    "last_run": "—",
                },
            )
        )
    return jobs


def read_system_jobs() -> tuple[list[Resource], set[str]]:
    """Read only cron files visible to this process, without privilege escalation."""
    jobs: list[Resource] = []
    spool_users: set[str] = set()
    paths = [Path("/etc/crontab")]
    cron_d = Path("/etc/cron.d")
    try:
        paths.extend(
            sorted(
                path
                for path in cron_d.iterdir()
                if path.is_file() and not path.name.startswith(".")
            )
        )
    except OSError:
        pass
    for path in paths:
        try:
            jobs.extend(
                parse_crontab(
                    path.read_text(encoding="utf-8", errors="replace"),
                    str(path),
                    system=True,
                )
            )
        except OSError:
            continue
    for directory in (
        Path("/var/spool/cron/crontabs"),
        Path("/var/spool/cron/tabs"),
        Path("/var/spool/cron"),
    ):
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.name in spool_users
            ):
                continue
            try:
                contents = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            spool_users.add(path.name)
            jobs.extend(parse_crontab(contents, str(path), user=path.name))
    for period in PERIODIC:
        directory = Path(f"/etc/cron.{period}")
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            if (
                not path.is_file()
                or not re.fullmatch(r"[A-Za-z0-9_-]+", path.name)
                or not os.access(path, os.X_OK)
            ):
                continue
            jobs.append(
                Resource(
                    id=str(path),
                    name=path.name,
                    state="registered",
                    info=f"@{period} · root · {path}",
                    manifest={
                        "schedule": f"@{period}",
                        "user": "root",
                        "command": str(path),
                        "source": str(path),
                        "source_type": "periodic-script",
                        "last_run": "—",
                    },
                )
            )
    return jobs, spool_users


def attach_history(
    jobs: list[Resource],
    journal: bytes,
    warning: str | None = None,
    *,
    max_entries: int = 40,
) -> None:
    """Attach exact user+command matches; never infer a job's exit status."""
    launches: dict[tuple[str, str], list[str]] = {}
    directory_runs: dict[str, list[str]] = {}
    for line in journal.splitlines():
        try:
            entry = json.loads(line)
        except ValueError, TypeError:
            continue
        if not isinstance(entry, dict):
            continue
        match = LAUNCH.search(str(entry.get("MESSAGE") or ""))
        if match is None:
            continue
        try:
            when = datetime.fromtimestamp(
                int(entry.get("__REALTIME_TIMESTAMP")) / 1_000_000, UTC
            ).strftime("%Y-%m-%d %H:%M:%S UTC")
        except TypeError, ValueError, OverflowError:
            when = "Unknown time"
        owner = match.group("user")
        command = match.group("command")
        launches.setdefault((owner, command), []).append(when)
        if "run-parts" in command:
            for period in PERIODIC:
                if f"/etc/cron.{period}" in command:
                    directory_runs.setdefault(period, []).append(when)
    for job in jobs:
        manifest = job.manifest
        if manifest.get("source_type") == "periodic-script":
            period = str(manifest["schedule"])[1:]
            runs = directory_runs.get(period, [])
            job.logs = [
                f"{when}  cron.{period} directory invoked (script execution unverified)"
                for when in runs[-max_entries:]
            ]
        else:
            runs = launches.get((str(manifest["user"]), str(manifest["command"])), [])
            job.logs = [
                f"{when}  launched by cron (completion status unknown)"
                for when in runs[-max_entries:]
            ]
        if job.logs:
            manifest["last_run"] = runs[-1]
        else:
            job.logs = [
                warning
                or "No matching launch recorded in the readable journal for this boot."
            ]
        if warning and runs:
            job.logs.insert(0, f"History may be incomplete: {warning}")


class CronCollector:
    """Collect jobs from user/system crontabs and launch records from journald."""

    def __init__(self, settings: SourceSettings | None = None) -> None:
        self.settings = settings or SourceSettings()

    async def collect(self) -> list[Resource]:
        system_jobs, current_user = await asyncio.gather(
            asyncio.to_thread(read_system_jobs), self._user_crontab()
        )
        jobs, spool_users = system_jobs
        if current_user is not None and getpass.getuser() not in spool_users:
            jobs.extend(
                parse_crontab(
                    current_user,
                    f"user crontab: {getpass.getuser()}",
                    user=getpass.getuser(),
                )
            )
        if not jobs:
            return []
        output, warning = await self._journal_history()
        attach_history(jobs, output, warning, max_entries=self.settings.log_lines)
        return jobs

    async def _user_crontab(self) -> str | None:
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "crontab",
                "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, _ = await asyncio.wait_for(
                proc.communicate(), self.settings.request_timeout
            )
            return output.decode(errors="replace") if proc.returncode == 0 else None
        except OSError, TimeoutError:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            return None

    async def _journal_history(self) -> tuple[bytes, str | None]:
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "journalctl",
                "--boot",
                "--identifier=CRON",
                "--identifier=crond",
                "--identifier=cron",
                f"--lines={self.settings.cron_history_lines}",
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
            return b"", f"Cron journal unavailable: {exc or 'request timed out'}"
        if proc.returncode or (not output and b"No journal files" in stderr):
            return b"", stderr.decode(
                errors="replace"
            ).strip() or "Cron journal unavailable"
        notice = stderr.decode(errors="replace").strip()
        if "not seeing messages from other users" in notice:
            return output, "Journal access is limited to visible users and groups"
        return output, None
