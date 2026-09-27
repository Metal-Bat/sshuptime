# ◈ sshuptime

A live Textual infrastructure dashboard with a key-authenticated AsyncSSH gateway.
Dark panels, mint highlights, host identity, OS errors, resource meters, and a rolling CPU graph.

## Dashboard preview

![sshuptime dashboard showing containers, health, resource graphs, inspector, and event stream](docs/dashboard.svg)

*The screenshots use simulated data; live mode uses the same interface.*

| Nord theme | Light theme |
| --- | --- |
| ![sshuptime in the Nord theme](docs/theme-nord.svg) | ![sshuptime in the light theme](docs/theme-textual-light.svg) |

[Browse every theme preview](#theme-gallery).

**System health:** the Errors tab groups failed services and recent OS journal errors.

![sshuptime System Errors tab showing recent OS errors and failed services](docs/system-errors.svg)

**Scheduled jobs:** System → Cron lists readable cron entries with their schedule,
owner, command, and latest recorded launch. Click a job to open its History.

![sshuptime System Cron tab showing scheduled jobs and launch history](docs/system-cron.svg)

**Live mode is available now.** Host metrics, processes, systemd services, Docker,
Podman, and Kubernetes are collected from the machine running sshuptime. Optional
runtime tabs appear when their APIs answer. The demo remains available explicitly.

## Install with uv

Clone the repository and run it from the checkout (Python 3.14 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/) are required):

```sh
git clone git@github.com:Metal-Bat/sshuptime.git
cd sshuptime
uv sync
uv run sshuptime demo  # sample data; no SSH setup needed
uv run sshuptime live  # live data from this machine
```

To install the command outside a checkout, use uv's isolated tool environment:

```sh
uv tool install --python 3.14 'git+ssh://git@github.com/Metal-Bat/sshuptime.git'
sshuptime demo
```

The Git commands require GitHub SSH access to this repository and its project
files to be committed and pushed. `uv tool install` installs the `sshuptime`
executable and its dependencies in an isolated environment. uv can download
Python 3.14 if it is not installed. If uv warns that the tool directory is not
on `PATH`, run `uv tool update-shell` and
open a new shell. Use `uv tool upgrade sshuptime` after pushing updates, or
`uv tool uninstall sshuptime` to remove it. See [uv's tool guide](https://docs.astral.sh/uv/guides/tools/)
for details.

For development from an existing checkout:

```sh
uv sync
uv run sshuptime                   # live local dashboard
uv run sshuptime demo --interval 1 # animated demo
```

To build distributable wheel and source archives from the checkout, run
`uv build`. The files are written to `dist/`. Building a package does not embed
`sshuptime.yaml` or SSH keys; supply them where the installed command runs.

## Your implementation roadmap

The [step-by-step collector roadmap](docs/ROADMAP.md) is now a learning guide for
understanding and extending the shipped adapters. Each stage has a completion check.
[The design guide](docs/DESIGN.md) covers themes and future feature handoffs.

## Themes

Press **t** to choose a theme using the searchable picker. The original `sshuptime`
palette, Nord, Dracula, Gruvbox, and light themes are available. Theme changes also
recolor health states and retained events while paused. Selection lasts for the
current session; use the CLI to choose a repeatable startup theme:

```sh
uv run sshuptime demo --theme nord
uv run sshuptime demo --theme textual-light
```

### Theme gallery

These previews use the same demo dashboard. Click an image to open the full SVG.
The ANSI previews resolve colors through Textual's sample dark and light
terminal palettes; their appearance in the app depends on your terminal palette.

| | |
| --- | --- |
| **sshuptime**<br>![sshuptime theme preview](docs/theme-sshuptime.svg) | **ANSI Dark**<br>![ANSI Dark theme preview](docs/theme-ansi-dark.svg) |
| **ANSI Light**<br>![ANSI Light theme preview](docs/theme-ansi-light.svg) | **Atom One Dark**<br>![Atom One Dark theme preview](docs/theme-atom-one-dark.svg) |
| **Atom One Light**<br>![Atom One Light theme preview](docs/theme-atom-one-light.svg) | **Catppuccin Frappé**<br>![Catppuccin Frappé theme preview](docs/theme-catppuccin-frappe.svg) |
| **Catppuccin Latte**<br>![Catppuccin Latte theme preview](docs/theme-catppuccin-latte.svg) | **Catppuccin Macchiato**<br>![Catppuccin Macchiato theme preview](docs/theme-catppuccin-macchiato.svg) |
| **Catppuccin Mocha**<br>![Catppuccin Mocha theme preview](docs/theme-catppuccin-mocha.svg) | **Dracula**<br>![Dracula theme preview](docs/theme-dracula.svg) |
| **Flexoki**<br>![Flexoki theme preview](docs/theme-flexoki.svg) | **Gruvbox**<br>![Gruvbox theme preview](docs/theme-gruvbox.svg) |
| **Monokai**<br>![Monokai theme preview](docs/theme-monokai.svg) | **Nord**<br>![Nord theme preview](docs/theme-nord.svg) |
| **Rosé Pine**<br>![Rosé Pine theme preview](docs/theme-rose-pine.svg) | **Rosé Pine Dawn**<br>![Rosé Pine Dawn theme preview](docs/theme-rose-pine-dawn.svg) |
| **Rosé Pine Moon**<br>![Rosé Pine Moon theme preview](docs/theme-rose-pine-moon.svg) | **Solarized Dark**<br>![Solarized Dark theme preview](docs/theme-solarized-dark.svg) |
| **Solarized Light**<br>![Solarized Light theme preview](docs/theme-solarized-light.svg) | **Textual Dark**<br>![Textual Dark theme preview](docs/theme-textual-dark.svg) |
| **Textual Light**<br>![Textual Light theme preview](docs/theme-textual-light.svg) | **Tokyo Night**<br>![Tokyo Night theme preview](docs/theme-tokyo-night.svg) |

Regenerate the gallery after changing the UI or themes with
`uv run python docs/generate_theme_previews.py`.

## Workspace

- Docker / Podman: containers, networks, volumes.
- Kubernetes: pods, nodes, services.
- Processes: PID, command, CPU, memory, state, and user; CPU sorting.
- System: processes, services, recent OS errors, and registered cron jobs.
- Each inventory has a scrollable table and Details / Logs / JSON inspector;
  Cron uses Details / History / JSON.
- Runtime tabs follow the collector's inventory; omit runtimes that aren't available.
- Collection happens asynchronously, without overlapping requests. A ten-second
  timeout or collector failure retains the previous data and marks it **STALE**.
- Event history is bounded to 300 lines. The inspector shows the selected resource's
  latest log snapshot (up to 1,000 rendered lines), not a separate streaming API.

Click a column header to sort that inventory; ▲ or ▼ appears on the active
header. Click it again to reverse the order.
The chosen sort stays active during live updates. CPU and memory sort numerically.
Click a row or navigate with arrows to inspect it. Scroll each table, log panel,
or inspector independently. At smaller terminal heights the summary compacts.
80×24 is supported; 120×35 or larger gives the inspector more room.

| Key | Action |
| --- | --- |
| `/` | Focus inventory filter (name, state, PID, context) |
| `Esc` | Clear filter and leave input |
| `Space` | Pause / resume collection |
| `r` | Refresh now and resume |
| `e` | Toggle failures only |
| `s` | Toggle CPU descending / errors first (clears header sort) |
| `t` | Open the theme picker |
| `Tab` / `Shift+Tab` | Move focus between controls |
| `q` | Quit |

Shortcuts are typed normally while the filter input is focused; press Esc first.
Textual's command palette is available with Ctrl+P.

## Live collectors

`sshuptime` and `sshuptime live` show this machine. `sshuptime serve` opens the
same live view over SSH; set `dashboard.mode: demo` to serve the animated sample
instead. `sshuptime demo` always opens the sample locally. Host collection and
coordination live in [live.py](src/sshuptime/live.py); Docker/Podman and Kubernetes
strategies live in [engines.py](src/sshuptime/engines.py) and
[kubernetes.py](src/sshuptime/kubernetes.py).

The top strip shows hostname, primary IP, Linux distribution, and kernel version.
The System tab shows processes, systemd services, Cron, and an Errors view. The Errors
view includes failed services and the latest 50 current-boot journal entries at
error priority or higher. Journal messages show time, source, and full JSON details.
When journal access is unavailable, the tab explains that rather than reporting a
clean host. See the [journalctl manual](https://www.freedesktop.org/software/systemd/man/latest/journalctl.html)
for access requirements.

Cron reads the current user's crontab plus readable system crontabs and scripts in
`/etc/cron.{hourly,daily,weekly,monthly}`. Its History view matches launches in
the readable current-boot journal by user and command (up to 500 recent cron
records). Cron launch records do not show whether a command completed or
succeeded. Periodic script entries show when the directory was invoked, not
whether a specific script ran. If journal access is unavailable or no matching
launch is recorded, the inspector says so. SSH users see what the sshuptime server
process can read; restricted crontabs need appropriate server permissions.

Docker and Podman show running and stopped containers, networks, and volumes; container details include inspect
JSON, stats where available, and bounded recent logs. Kubernetes shows pods, nodes,
and services from the configured context, plus inspect JSON and bounded pod logs.
The collector uses local Docker/Podman sockets and kubeconfig or in-cluster access.
Missing runtimes are omitted. A source error retains its last inventory and appears
in the event stream/host status; healthy sources keep updating. Restart to pick up
source path/context changes. Inspect JSON redacts common credential fields and
container environment variables, but review access to this dashboard before
sharing production metadata.

### Kubernetes permissions required

> **The runner must have Kubernetes API access.** The identity used by the
> `sshuptime` process needs permission to **list pods and services in all
> namespaces**, **list nodes**, and **get pod logs in all namespaces**. SSH
> dashboard users do not supply their own Kubernetes credentials. When running
> in a pod, grant these permissions to its ServiceAccount; otherwise grant them
> to the identity in the runner's kubeconfig. A kubeconfig path alone does not
> grant access.

For an in-cluster runner, this is an example of the required read-only RBAC.
Replace `sshuptime` and `monitoring` in the binding with the runner's actual
ServiceAccount name and namespace:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: sshuptime-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "nodes"]
    verbs: ["list"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: sshuptime-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: sshuptime-reader
subjects:
  - kind: ServiceAccount
    name: sshuptime
    namespace: monitoring
```

If access is denied, the corresponding inventory shows an error; denied pod
logs appear empty. This example uses a `ClusterRoleBinding` because the runner
queries all namespaces and lists cluster-scoped nodes.

SDK requests use short timeouts. Logs are limited to 40 lines and 32 KiB per item;
container log collection is limited to the first 12 listed containers per engine.
Kubernetes log collection covers the first 12 pods and failing pods. Large hosts
and clusters may need namespace/resource filters or an on-demand inspector API.

`SourceSettings` is injected into System, Cron, Docker, Podman, and Kubernetes
collectors. Set `sources.request_timeout`, `log_lines`, `log_bytes`,
`max_log_items`, `journal_lines`, and `cron_history_lines` in YAML or `.env` to
adjust bounded collection. SSH sessions receive the server's resolved source
settings. `LiveCollector` accepts a tuple of runtime strategies with `name`,
`views`, and an async `collect()` method. Each strategy owns its SDK calls and
supplies `CategoryView` definitions for the table; the dashboard loops over
those definitions rather than choosing Docker or Kubernetes columns itself.

## Bring your own collectors

See [the Pydantic collector contract](src/sshuptime/models.py),
[presentation definitions](src/sshuptime/presentation.py), and
[animated examples](src/sshuptime/collectors.py). The UI takes a collector:

```python
from sshuptime.app import UptimeApp
from sshuptime.models import Resource, Snapshot


class MyCollector:
    async def snapshot(self) -> Snapshot:
        # Collect here; IDs must remain stable between refreshes.
        return Snapshot(
            host="my-server",
            uptime="3d 2h",
            cpu=18,
            memory=42,
            disk=51,
            inventory={
                "Docker": {
                    "Containers": [
                        Resource(
                            id="abc123",
                            name="api",
                            state="running",
                            cpu=4.2,
                            memory="128 MiB",
                            manifest={"image": "my-api:latest"},
                            logs=["INFO ready"],
                        )
                    ]
                },
                "Processes": {"Processes": []},
            },
            events=["INFO api became healthy"],
        )


UptimeApp(MyCollector()).run()
```

Use `asyncio.to_thread()` around synchronous Docker/Podman SDK operations, with
SDK-level request timeouts: cancelling an await doesn't stop a running thread.
Bound log payloads, return only new events per snapshot, and keep manifests JSON
serializable. Raw collector strings render literally, without Rich markup.
Detect a successful engine/API connection rather than just an installed binary.
Independent collectors can run with `asyncio.gather`; catch per-engine failures
in your coordinator if you want healthy engines to keep updating independently.
Use a shared coordinator/cache if multiple SSH viewers should share collection.

The gateway starts a separate local `sshuptime live` process per SSH session (or
`demo` when configured). The UI runs on the SSH server host.

## Configuration: YAML or .env

Configuration uses Pydantic Settings. The YAML file is **runtime configuration**:
you do not add it to the Python package or pass it to `uv sync`. Run the command
from the directory containing `sshuptime.yaml` for automatic discovery, or pass
`--config /absolute/path/to/sshuptime.yaml` after the `serve`, `live`, or `demo`
subcommand. This works the same way for `uv run sshuptime` and a tool install.

From a checkout, copy [sshuptime.example.yaml](sshuptime.example.yaml) if you do
not already have `sshuptime.yaml`. Create the SSH server's host key and an
allowlist of client **public** keys:

```sh
# Skip this copy if you already have sshuptime.yaml:
cp sshuptime.example.yaml sshuptime.yaml
ssh-keygen -t ed25519 -f ./ssh_host_ed25519_key -N ''
cp ~/.ssh/id_ed25519.pub ./dashboard_authorized_keys
# Edit sshuptime.yaml for this machine, then start the SSH gateway:
uv run sshuptime serve --config ./sshuptime.yaml
# In another terminal on this machine:
ssh -t -p 8022 monitor@127.0.0.1
```

The `cp` command assumes the connecting user already has an Ed25519 SSH key.
If not, create one with `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519`, then copy
its `.pub` file. For another client computer, put that client's public key in
`dashboard_authorized_keys` on the server. Set `ssh.host` to `0.0.0.0` to accept
remote connections, and connect to the server's reachable address. The host key
is the server's **private** key; `authorized_keys` contains allowed client
**public** keys. Do not point it at `~/.ssh/known_hosts`.

The example maps to the program as follows:

| YAML setting | What it controls |
| --- | --- |
| `ssh.host`, `ssh.port`, `ssh.username` | Gateway bind address, port, and login name used by `sshuptime serve`. `ssh.host` is the address of the machine running sshuptime. |
| `ssh.host_key`, `ssh.authorized_keys` | Server identity and client key allowlist, required for `serve`. |
| `dashboard.mode`, `dashboard.theme`, `dashboard.interval` | Live or demo view, startup theme, and refresh seconds. |
| `sources.*` | Optional local Podman socket, Kubernetes context/config, and collection limits. |

Live metrics come from the **machine running sshuptime**, using the processes,
services, container sockets, and Kubernetes credentials that its user can access.
The YAML file does not tell sshuptime to SSH into a second machine. To monitor a
remote machine, run `sshuptime serve` there and connect to its dashboard via SSH.
For a tool install, create the same YAML and key files on that machine; the
repository's example file is not installed with the command.

You can also copy [.env.example](.env.example) to `.env` in the working directory,
or override one value for a run, for example:

```sh
sshuptime serve --config /path/to/sshuptime.yaml --port 9022
```

```yaml
ssh:
  host: "127.0.0.1"  # Use "0.0.0.0" for connections from other computers.
  port: 8022
  username: "monitor"
  host_key: "./ssh_host_ed25519_key"
  authorized_keys: "./dashboard_authorized_keys"
dashboard:
  mode: "live"
  theme: "nord"
  interval: 2
```

For `.env`, the equivalent theme setting is `SSHUPTIME_DASHBOARD__THEME=nord`.
Use double underscores between the section and field; the sample lists all fields.
The default startup theme and refresh rate live in `DashboardSettings` in
[src/sshuptime/config.py](src/sshuptime/config.py).

Precedence: **CLI flags > environment > .env > YAML > model defaults**. Partial
sections merge, so changing a theme doesn't erase SSH settings. Numeric environment
values are parsed and validated by Pydantic. Unknown YAML keys, invalid themes,
invalid ranges, and missing explicitly requested config files fail before startup.

YAML key paths are relative to the YAML file's directory. CLI, environment, and
`.env` key paths are relative to the current working directory. Absolute paths and
`~` work too. `.env` is discovered in the working directory even with `--config`.
`--no-config` disables automatic YAML/.env loading; real environment variables still
apply. YAML and `.env` do not reload while running: restart to apply edits.

Local `sshuptime` / `sshuptime demo` also read the dashboard settings. SSH children
receive the resolved theme and refresh interval from the server. Press `t` for a
session-only change; edit configuration to choose the next startup theme. Starting
with no subcommand opens the local live dashboard; use `serve` for SSH.

## SSH dashboard without YAML (Linux/macOS)

You can also pass the required key paths as CLI flags. From a checkout, use
`uv run sshuptime` in place of `sshuptime` below:

```sh
ssh-keygen -t ed25519 -f ./ssh_host_ed25519_key -N ''
cp ~/.ssh/id_ed25519.pub ./dashboard_authorized_keys
sshuptime serve --host-key ./ssh_host_ed25519_key \
  --authorized-keys ./dashboard_authorized_keys
# In another terminal:
ssh -t -p 8022 monitor@127.0.0.1
```

The default listener binds to loopback. Set `--host 0.0.0.0` to listen externally;
`--port` and `--username` are configurable. Authentication requires an allowlisted
key and the configured username. Password login, shell commands, and forwarding
aren't offered. Each viewer gets its own PTY/subprocess, terminal resizing, and
cleanup on disconnect. The server isn't started automatically by installation.

## Run as a systemd service (Linux)

To keep the SSH dashboard running, use a systemd **user** service under the
account that owns the checkout. First run `uv sync`, create the host key and
client public-key allowlist as shown above, and set `ssh.host_key` and
`ssh.authorized_keys` in `sshuptime.yaml` to those files. In particular,
`authorized_keys` must point to the client **public-key allowlist**, not
`~/.ssh/known_hosts`. Use `pwd` from the checkout to find its absolute path.

Run `mkdir -p ~/.config/systemd/user`, then create
`~/.config/systemd/user/sshuptime.service` with the following contents,
replacing every `/absolute/path/to/sshuptime` with that checkout path:

```ini
[Unit]
Description=sshuptime SSH dashboard

[Service]
Type=simple
WorkingDirectory=/absolute/path/to/sshuptime
ExecStart=/absolute/path/to/sshuptime/.venv/bin/sshuptime serve --config /absolute/path/to/sshuptime/sshuptime.yaml
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

Then start it and inspect its status or logs:

```sh
systemctl --user daemon-reload
systemctl --user enable --now sshuptime.service
systemctl --user status sshuptime.service
journalctl --user -u sshuptime.service -f
```

To have the user service start at boot and continue after logout, enable linger
for that account once with `sudo loginctl enable-linger "$(whoami)"`.
After changing the YAML or unit, run `systemctl --user restart sshuptime.service`
(and `systemctl --user daemon-reload` first if the unit changed).

For access from another computer, set `ssh.host: "0.0.0.0"` in the YAML, allow
inbound TCP traffic to the configured port (default `8022`) on the server, and
connect with a private key whose public key is in `ssh.authorized_keys`:

```sh
ssh -t -i ~/.ssh/id_ed25519 -p 8022 monitor@SERVER_IP_OR_DNS
```

`monitor` is the configured `ssh.username`, not the Linux account running the
service. The dashboard and its Kubernetes collector use that Linux account's
permissions and kubeconfig; see [Kubernetes permissions required](#kubernetes-permissions-required).

## Development

```sh
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
```

Tests exercise filtering, failure retention, runtime changes, concurrent refresh
suppression, narrow terminals, and a real local SSH login/resize/exit with temporary
keys. The SSH test needs permission to bind a loopback socket.

## Useful next additions

- A k9s-style namespace/context switcher and saved filters.
- A resource relationship view: process → container → pod → node.
- A manifest diff against the previous snapshot, highlighting changed fields.
- An incident timeline linking restarts, exit codes, health probes, and logs.
- Per-resource pinned watches, log search, and follow/freeze controls.
- Multi-host switching and a shared collector cache for multiple viewers.

Design references: [Yazi](https://yazi-rs.github.io/),
[witr](https://github.com/pranshuparmar/witr), and
[btop](https://github.com/aristocratos/btop). Built with
[Textual](https://textual.textualize.io/) and [AsyncSSH](https://asyncssh.readthedocs.io/).
