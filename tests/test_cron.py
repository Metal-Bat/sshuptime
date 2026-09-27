import json

import pytest

from sshuptime.cron import CronCollector, attach_history, parse_crontab


def test_parse_user_and_system_crontabs():
    user_jobs = parse_crontab(
        "# comment\nMAILTO=root\n0 2 * * * /bin/backup --fast\n@daily /bin/cleanup\n",
        "user crontab: app",
        user="app",
    )
    system_jobs = parse_crontab(
        "*/5 * * * * root /usr/bin/check --all\n@reboot deploy /bin/start\n",
        "/etc/crontab",
        system=True,
    )
    assert [(j.manifest["schedule"], j.manifest["user"]) for j in user_jobs] == [
        ("0 2 * * *", "app"),
        ("@daily", "app"),
    ]
    assert [j.manifest["command"] for j in system_jobs] == [
        "/usr/bin/check --all",
        "/bin/start",
    ]
    assert system_jobs[0].id == "/etc/crontab:1"


def test_history_matches_exact_user_and_command_and_does_not_claim_success():
    jobs = parse_crontab("* * * * * /bin/job\n", "test", user="alice")
    entries = [
        {"MESSAGE": "(bob) CMD (/bin/job)", "__REALTIME_TIMESTAMP": "1000000"},
        {
            "MESSAGE": "(alice) CMD (/bin/job --other)",
            "__REALTIME_TIMESTAMP": "2000000",
        },
        {"MESSAGE": "(alice) CMD (/bin/job)", "__REALTIME_TIMESTAMP": "3000000"},
    ]
    attach_history(jobs, "\n".join(json.dumps(e) for e in entries).encode())
    assert jobs[0].manifest["last_run"] == "1970-01-01 00:00:03 UTC"
    assert len(jobs[0].logs) == 1
    assert "completion status unknown" in jobs[0].logs[0]
    attach_history(
        jobs,
        json.dumps(entries[-1]).encode(),
        "Journal access is limited to visible users and groups",
    )
    assert jobs[0].logs[0].startswith("History may be incomplete:")


@pytest.mark.asyncio
async def test_collector_reports_unavailable_history(monkeypatch):
    from sshuptime import cron

    monkeypatch.setattr(
        cron,
        "read_system_jobs",
        lambda: (
            parse_crontab("@hourly root /bin/job", "/etc/crontab", system=True),
            set(),
        ),
    )

    async def no_crontab():
        return None

    async def no_journal():
        return b"", "Cron journal unavailable"

    monkeypatch.setattr(CronCollector, "_user_crontab", lambda self: no_crontab())
    monkeypatch.setattr(CronCollector, "_journal_history", lambda self: no_journal())
    jobs = await CronCollector().collect()
    assert len(jobs) == 1
    assert jobs[0].logs == ["Cron journal unavailable"]
    assert jobs[0].manifest["last_run"] == "—"
