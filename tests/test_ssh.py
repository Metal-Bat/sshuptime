import asyncio
import contextlib

import asyncssh
import pytest

from sshuptime.config import SourceSettings
from sshuptime.ssh import serve


@pytest.mark.asyncio
async def test_ssh_auth_terminal_resize_and_cleanup(tmp_path, monkeypatch):
    host = asyncssh.generate_private_key("ssh-ed25519")
    client = asyncssh.generate_private_key("ssh-ed25519")
    host_path = tmp_path / "host"
    host.write_private_key(host_path)
    authorized = tmp_path / "authorized_keys"
    client.write_public_key(authorized)
    ready = asyncio.Event()
    original = asyncssh.create_server
    servers = []
    children = []
    child_envs = []
    original_subprocess = asyncio.create_subprocess_exec

    async def capture_subprocess(*args, **kwargs):
        children.append(args)
        child_envs.append(kwargs["env"])
        return await original_subprocess(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture_subprocess)

    async def capture(*args, **kwargs):
        server = await original(*args, **kwargs)
        servers.append(server)
        ready.set()
        return server

    monkeypatch.setattr(asyncssh, "create_server", capture)
    task = asyncio.create_task(
        serve(
            "127.0.0.1",
            0,
            str(host_path),
            str(authorized),
            "monitor",
            theme="nord",
            interval=0.5,
            source_settings=SourceSettings(request_timeout=1.5, log_lines=7),
        )
    )
    try:
        await asyncio.wait_for(ready.wait(), 5)
        port = servers[0].get_port()
        known = tmp_path / "known_hosts"
        known.write_text(f"[127.0.0.1]:{port} {host.export_public_key().decode()}")
        options = {"port": port, "known_hosts": str(known), "client_keys": [client]}
        with pytest.raises(asyncssh.PermissionDenied):
            await asyncssh.connect("127.0.0.1", username="wrong-user", **options)
        async with asyncssh.connect("127.0.0.1", username="monitor", **options) as conn:
            rejected = await conn.run("uname -a", check=False)
            assert rejected.exit_status == 1
            async with conn.create_process(
                term_type="xterm-256color", term_size=(120, 40)
            ) as process:
                output = ""
                async with asyncio.timeout(10):
                    while "SSHUPTIME" not in output:
                        output += await process.stdout.read(4096)
                async with asyncio.timeout(15):
                    while "System" not in output:
                        output += await process.stdout.read(4096)
                assert children[0][3] == "live"
                assert children[0][-5:] == (
                    "--no-config",
                    "--theme",
                    "nord",
                    "--interval",
                    "0.5",
                )
                assert child_envs[0]["SSHUPTIME_SOURCES__REQUEST_TIMEOUT"] == "1.5"
                assert child_envs[0]["SSHUPTIME_SOURCES__LOG_LINES"] == "7"
                process.change_terminal_size(80, 24)
                await asyncio.sleep(1)
                process.stdin.write("q")
                result = await asyncio.wait_for(process.wait(), 15)
                assert result.exit_status == 0
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
