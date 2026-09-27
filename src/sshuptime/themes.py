"""Dashboard palette; built-in Textual themes are available alongside it."""

from rich.style import Style
from textual.app import App
from textual.color import Color
from textual.theme import Theme

DEFAULT_THEME = "sshuptime"

OBSERVATORY = Theme(
    name=DEFAULT_THEME,
    primary="#5de4c7",
    secondary="#8da5bf",
    accent="#5de4c7",
    foreground="#c5d0e0",
    background="#10151f",
    surface="#192331",
    panel="#192331",
    success="#5de4c7",
    warning="#e7bb75",
    error="#ff6b88",
    variables={
        "border": "#304257",
        "block-cursor-background": "#234a53",
        "block-cursor-foreground": "#e6fff8",
        "footer-key-foreground": "#5de4c7",
    },
)


def text_style(app: App, role: str) -> Style:
    """Resolve contrast-aware theme roles, including native ANSI colors."""
    return Style(color=Color.parse(app.get_css_variables()[role]).rich_color)
