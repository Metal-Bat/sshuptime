"""Export one demo dashboard SVG for every selectable theme.

Run from the repository root with ``uv run python docs/generate_theme_previews.py``.
"""

import asyncio
from pathlib import Path

from sshuptime.app import UptimeApp


async def main() -> None:
    output_dir = Path(__file__).resolve().parent
    app = UptimeApp(interval=3600)
    # Native ANSI colors have no terminal palette in an exported SVG. Resolve
    # them through Textual's dark/light terminal palettes before capture.
    app.ansi_color = False
    async with app.run_test(size=(140, 42)) as pilot:
        for _ in range(100):
            await pilot.pause(0.02)
            if app.views and not app.busy:
                break
        else:
            raise RuntimeError("demo dashboard did not load")

        for theme in sorted(app.available_themes):
            app.theme = theme
            await pilot.pause(0.03)
            (output_dir / f"theme-{theme}.svg").write_text(
                app.export_screenshot(), encoding="utf-8"
            )
            print(f"theme-{theme}.svg")


if __name__ == "__main__":
    asyncio.run(main())
