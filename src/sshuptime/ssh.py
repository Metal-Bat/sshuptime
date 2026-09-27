"""Key-authenticated SSH terminal gateway (POSIX).

Every session owns a separate Textual subprocess and pseudo-terminal. No shell,
exec commands, or forwarding are exposed by this server.
"""

import asyncio
import contextlib
import fcntl
import os
import pty
import struct
import sys
import termios
from functools import partial

import asyncssh

from .config import SourceSettings


async def terminal_session(
    process: asyncssh.SSHServerProcess[bytes],
    *,
    theme: str = "sshuptime",
    interval: float = 2,
    mode: str = "live",
    podman_socket: str | None = None,
    kubeconfig: str | None = None,
    kube_context: str | None = None,
    source_settings: SourceSettings | None = None,
) -> None:
    if process.command or not process.term_type:
        process.stderr.write(
            b"Use ssh -t to open the dashboard; commands are not supported.\n"
        )
        process.exit(1)
        return
    master, slave = pty.openpty()
    child = None
    input_task = None
    loop = asyncio.get_running_loop()

    def resize(width: int, height: int) -> None:
        fcntl.ioctl(
            master,
            termios.TIOCSWINSZ,
            struct.pack(
                "HHHH", max(1, min(height, 65535)), max(1, min(width, 65535)), 0, 0
            ),
        )

    def output_ready() -> None:
        try:
            data = os.read(master, 65536)
        except OSError:
            data = b""
        if data:
            process.stdout.write(data)
        else:
            loop.remove_reader(master)

    async def forward_input() -> None:
        while True:
            try:
                data = await process.stdin.read(4096)
            except asyncssh.TerminalSizeChanged as change:
                resize(change.width, change.height)
                continue
            if not data:
                return
            # Short writes are possible for non-blocking PTYs.
            while data:
                try:
                    written = os.write(master, data)
                    data = data[written:]
                except BlockingIOError:
                    await asyncio.sleep(0.01)

    try:
        resize(*process.term_size[:2])
        source_env = {
            f"SSHUPTIME_SOURCES__{key.upper()}": str(value)
            for key, value in (source_settings or SourceSettings()).model_dump().items()
            if value is not None
        }
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "sshuptime",
            mode,
            "--no-config",
            "--theme",
            theme,
            "--interval",
            str(interval),
            *(
                ["--podman-socket", podman_socket]
                if mode == "live" and podman_socket
                else []
            ),
            *(["--kubeconfig", kubeconfig] if mode == "live" and kubeconfig else []),
            *(
                ["--kube-context", kube_context]
                if mode == "live" and kube_context
                else []
            ),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env={
                **os.environ,
                **source_env,
                "TERM": process.term_type,
                "COLORTERM": "truecolor",
            },
            start_new_session=True,
        )
        os.close(slave)
        slave = -1
        os.set_blocking(master, False)
        loop.add_reader(master, output_ready)
        input_task = asyncio.create_task(forward_input())
        wait_task = asyncio.create_task(child.wait())
        try:
            await asyncio.wait(
                [input_task, wait_task], return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            if child.returncode is None:
                child.terminate()
                try:
                    await asyncio.wait_for(child.wait(), 3)
                except TimeoutError:
                    child.kill()
                    await child.wait()
            await wait_task
        process.exit(child.returncode or 0)
    finally:
        loop.remove_reader(master)
        if input_task:
            input_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, OSError, asyncssh.Error):
                await input_task
        os.close(master)
        if slave >= 0:
            os.close(slave)


async def serve(
    host: str,
    port: int,
    host_key: str,
    authorized_keys: str,
    username: str,
    *,
    theme: str = "sshuptime",
    interval: float = 2,
    mode: str = "live",
    podman_socket: str | None = None,
    kubeconfig: str | None = None,
    kube_context: str | None = None,
    source_settings: SourceSettings | None = None,
) -> None:
    keys = asyncssh.read_authorized_keys(authorized_keys)
    expected_username = username

    class DashboardServer(asyncssh.SSHServer):
        def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
            self.conn = conn

        def begin_auth(self, username: str) -> bool:
            self.conn.set_authorized_keys(
                keys if username == expected_username else asyncssh.SSHAuthorizedKeys()
            )
            return True

    async with await asyncssh.create_server(
        DashboardServer,
        host,
        port,
        server_host_keys=[host_key],
        process_factory=partial(
            terminal_session,
            theme=theme,
            interval=interval,
            mode=mode,
            podman_socket=podman_socket,
            kubeconfig=kubeconfig,
            kube_context=kube_context,
            source_settings=source_settings,
        ),
        encoding=None,
        line_editor=False,
    ):
        print(
            f"sshuptime {mode.upper()} listening on {host}:{port} · user {username}",
            flush=True,
        )
        await asyncio.Future()
