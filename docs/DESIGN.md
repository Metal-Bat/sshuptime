# Dashboard design and next-feature handoffs

This document separates the working interface from proposed extensions. It is a
shared design target for your data work and future UI work, not a claim that all
features below already exist.

## Working workspace

```text
◈ SSHUPTIME / infrastructure observatory
HOST atlas-prod-01 │ IP 10.42.1.17 │ LINUX Debian 13 │ KERNEL 6.12
● LIVE / host                         last update / refresh interval
┌ CPU + history ┐ ┌ MEMORY ┐ ┌ DISK ┐ ┌ UPTIME ┐
/filter name, status, PID, context
Docker │ Kubernetes │ Podman │ System
Containers │ Networks │ Volumes (System: Processes │ Services │ Errors │ Cron)
┌ INVENTORY ───────────────────┐ ┌ INSPECTOR ─────────────────┐
│ name    state    cpu    mem  │ │ Details │ Logs │ JSON      │
│ selected resource           │ │ scrollable resource view   │
└─────────────────────────────┘ └────────────────────────────┘
┌ EVENT STREAM / recent observations ────────────────────────┐
└───────────────────────────────────────────────────────────┘
q Quit   Space Pause   / Filter   e Errors   s CPU sort   t Theme
```

Keep focus/selection visible. Give each data block its own scrolling. State text
must accompany color, so color is never the only way to recognize a failure.
Preserve resource selection during refresh and theme changes. Use fewer summary
rows at short terminal heights, with horizontal table scrolling for wide data.

## Themes — implemented

Press **t** to open the searchable Textual theme picker; select with Enter or mouse,
or cancel with Esc. Available themes include the custom `sshuptime` palette plus
Textual's built-ins such as `nord`, `dracula`, `gruvbox`, and `textual-light`.
Picker selections apply to the current session; they are not saved to disk.
Set `dashboard.theme` in YAML or `SSHUPTIME_DASHBOARD__THEME` in `.env` to choose
the startup default. See [configuration](../README.md#configuration-yaml-or-env).

```sh
uv run sshuptime demo --theme nord
uv run sshuptime demo --theme textual-light
```

Use theme roles in TCSS: `$background`, `$surface`, `$foreground`, `$text-muted`,
`$accent`, `$border`, and cursor colors. Rich table cells and stored events must
also update when the palette changes, including when live collection is paused.
Success/error/warning colors have semantic meaning across every palette.

The custom palette is in `src/sshuptime/themes.py`. Register future palettes there
and keep raw hex values out of widget code. Textual's theme system and variables
are described in its [theme guide](https://textual.textualize.io/guide/design/).

### Theme previews

The [README gallery](../README.md#theme-gallery) shows every selectable theme.
Regenerate its SVGs with `uv run python docs/generate_theme_previews.py`.

## Next designs — planned

| Feature | What the viewer sees | Data you prepare | UI work still needed |
| --- | --- | --- | --- |
| Source health | `Docker · STALE 14s`, last success, concise error; host keeps updating | Per-source availability, last-success time, error, cached data | Extend Snapshot; source badges and reconnect state |
| Unknown metrics | `— unavailable`, distinct from measured zero | Nullable readings and reason | Nullable metric rendering and sorting |
| Relationships | A tree beside the resource inspector; Enter follows a link | Stable IDs and typed edges: process → container → pod → node | Tree view, navigation history, unresolved-link handling |
| Manifest diff | `JSON / Changes` tabs with added/removed/changed fields | Previous/current JSON keyed by resource identity and sample time | Diff renderer, field paths, bounded history |
| Incident timeline | Chronological failure/recovery rows; selecting an event opens its resource | Event ID, timestamp, severity, source, resource ID, message | Structured event model, timeline table, cross-resource navigation |
| Log follow | Search, level filter, follow/freeze indicator; scroll up freezes following | Timestamped bounded batches, stream cursor, cancellation | Selection-aware collector API, search controls, streaming worker |
| Context switcher | Host/context/namespace selector above runtime tabs | Available contexts/namespaces and explicit connection status | Picker, reconnect state, scoped filter/selection reset |
| Pinned watches | Small pinned resource list with health and last change | Scoped stable IDs and latest resource data | Pin/unpin, missing-resource state, optional persistence |

### Relationships

```text
RELATIONSHIPS                 INSPECTOR
node-a                       api-7d9 / container api
└─ payments/api-7d9           state: running
   └─ container api          CPU / memory / restart count
      └─ PID 2198            [Details] [Logs] [JSON]
```

Only draw links supported by collected IDs/ownership metadata. Label unresolved
parents rather than inventing relationships. Selecting a tree item should use the
same inspector and logs as inventory selection.

### Manifest changes

```text
JSON │ Changes
Compared with 12:40:02 UTC
+ spec.replicas             3
~ image                    api:v1 → api:v2
- metadata.annotations.old value removed
```

Keep raw JSON available. Identify the comparison timestamp and resource identity;
never compare two different resources after a name gets reused. Bound stored
snapshots and hide/redact secrets before either snapshot reaches the UI.

### Incident timeline

```text
TIME       LEVEL   RESOURCE        OBSERVATION
12:40:02   error   worker-03       exited 137
12:40:32   warn    worker-03       restart attempted
12:40:38   ok      worker-03       health check recovered
```

Click an event to open its resource; show “resource no longer present” if removed.
Show timestamps, severity text, and source. Keep collection errors distinct from
workload failures. A collector outage cannot prove that a workload crashed.

## Design acceptance checklist

- [ ] Selection survives data refresh and theme changes.
- [ ] Dark and light themes retain readable states, JSON, and focus indicators.
- [ ] Keyboard and mouse can reach each view; Esc has a predictable exit.
- [ ] 80×24 remains usable; 140×42 shows the full workspace comfortably.
- [ ] Empty, unavailable, forbidden, loading, stale, and recovered states differ.
- [ ] Large logs and inventories stay bounded; slow sources don't freeze input.

The first four are continuing checks for the existing UI; the final source-state
and scale requirements become release gates as real adapters are added.
