"""An async infrastructure observatory for your terminal."""

import argparse
import asyncio

from .config import load_settings, validate_server_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live infrastructure dashboard (demo collectors included)"
    )
    commands = parser.add_subparsers(dest="command")
    demo = commands.add_parser("demo", help="Open the animated demo dashboard")
    live = commands.add_parser("live", help="Open the live local dashboard")
    serve = commands.add_parser(
        "serve", help="Serve the live dashboard over SSH (POSIX)"
    )
    for command in (demo, live, serve):
        config_group = command.add_mutually_exclusive_group()
        config_group.add_argument(
            "--no-config",
            action="store_true",
            help="Ignore automatic YAML and .env discovery",
        )
        config_group.add_argument(
            "--config", help="YAML configuration (default: ./sshuptime.yaml if present)"
        )
        command.add_argument("--theme", help="Textual theme name (press t to browse)")
        command.add_argument(
            "--interval", type=float, help="Refresh interval in seconds (0.2–3600)"
        )
    for command in (live, serve):
        command.add_argument("--podman-socket")
        command.add_argument("--kubeconfig")
        command.add_argument("--kube-context")
    serve.add_argument("--mode", choices=("live", "demo"))
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--host-key")
    serve.add_argument("--authorized-keys")
    serve.add_argument("--username")
    args = parser.parse_args()
    overrides = {
        key: value
        for key, value in vars(args).items()
        if key not in {"command", "config", "no_config"}
    }
    try:
        settings = load_settings(
            getattr(args, "config", None),
            discover=not getattr(args, "no_config", False),
            **overrides,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.command == "serve":
        import asyncssh

        from .ssh import serve as run_server

        try:
            host_key, authorized_keys = validate_server_files(settings)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))

        try:
            asyncio.run(
                run_server(
                    settings.ssh.host,
                    settings.ssh.port,
                    host_key,
                    authorized_keys,
                    settings.ssh.username,
                    theme=settings.dashboard.theme,
                    interval=settings.dashboard.interval,
                    mode=settings.dashboard.mode,
                    podman_socket=settings.sources.podman_socket,
                    kubeconfig=settings.sources.kubeconfig,
                    kube_context=settings.sources.kube_context,
                    source_settings=settings.sources,
                )
            )
        except KeyboardInterrupt:
            pass
        except (OSError, ValueError, asyncssh.Error) as exc:
            parser.error(f"cannot start SSH dashboard: {exc}")
    else:
        from .app import UptimeApp

        if (
            args.command == "demo"
            or settings.dashboard.mode == "demo"
            and args.command is None
        ):
            collector = None
        else:
            from .live import LiveCollector

            collector = LiveCollector(settings=settings.sources)
        UptimeApp(
            collector,
            interval=settings.dashboard.interval,
            theme=settings.dashboard.theme,
        ).run()
