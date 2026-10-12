"""What the player set up: the theme of the tracker, its colours, and how it was left."""
import json
import re
from pathlib import Path

from .paths import REPO

SETTINGS_FILE = REPO / "settings.json"

THEMES = {
    "dark": {
        "background": "#14181f", "bar": "#1c222c", "panel": "#1a1f28", "text": "#d7dde5", "dim": "#6b7785",
        "edge": "#2a3240", "edge_lit": "#f7d774", "node": "#1b2230", "base_fill": "#171a20",
        "base_border": "#343b47", "locked": "#3d4654", "checked_fill": "#1d3a29",
        "checked": "#4caf50", "available": "#4dd0e1", "progression": "#c792ea", "useful": "#82aaff",
        "filler": "#6b7785", "received": "#ffcb6b", "match": "#ff9f43",
    },
    "light": {
        "background": "#f3f4f7", "bar": "#e4e7ec", "panel": "#ffffff", "text": "#1f2630", "dim": "#7a8494",
        "edge": "#c9ced8", "edge_lit": "#c77700", "node": "#ffffff", "base_fill": "#e9ebf0",
        "base_border": "#bcc3cf", "locked": "#b4bcc9", "checked_fill": "#dcf3df",
        "checked": "#2e9a3c", "available": "#0097a7", "progression": "#8e44c9", "useful": "#2f6fe0",
        "filler": "#8a94a3", "received": "#d98e00", "match": "#e8590c",
    },
}
# The colours the player can change, and what they stand for
ADJUSTABLE = {
    "checked": "Checked", "available": "Can be researched now", "progression": "Holds progression",
    "useful": "Holds something useful", "filler": "Holds filler", "received": "Technology received",
    "match": "Found by the search",
}
# A colour as the colour chooser gives it
COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


class Settings:
    def __init__(self, path: Path | None = SETTINGS_FILE):
        """path: where the settings are kept, None to keep them nowhere."""
        self.path = path
        saved = {}
        if path and path.is_file():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
        # A file that was changed by hand may hold anything: what does not fit is left out
        if not isinstance(saved, dict):
            saved = {}
        self.theme: str = saved.get("theme") if saved.get("theme") in THEMES else "dark"
        # {theme: {name: colour}}: what the player changed
        colours = saved.get("colours") if isinstance(saved.get("colours"), dict) else {}
        self.colours: dict[str, dict[str, str]] = {
            theme: {name: colour for name, colour in colours[theme].items()
                    if name in THEMES[theme] and isinstance(colour, str) and COLOUR.fullmatch(colour)}
            if isinstance(colours.get(theme), dict) else {} for theme in THEMES}
        zoom = saved.get("zoom")
        self.zoom: float = float(zoom) if isinstance(zoom, (int, float)) and not isinstance(zoom, bool) else 0.6
        collapsed = saved.get("collapsed")
        self.collapsed: list[str] = ([band for band in collapsed if isinstance(band, str)]
                                     if isinstance(collapsed, list) else [])
        # Whether the tracker shows what a location holds before it is checked. Not unless the player asks
        self.spoilers: bool = saved.get("spoilers") is True
        # The part of the tree the tracker shows, see tracker.TABS. One part at a time is the default: the
        # whole tree is some thousand shapes, which is slow to move around
        self.tab: str = saved.get("tab") if isinstance(saved.get("tab"), str) else "physics"

    def save(self) -> None:
        """Keeps the settings. They are only a convenience: if they cannot be written, they are not kept."""
        if self.path:
            try:
                self.path.write_text(json.dumps({"theme": self.theme, "colours": self.colours, "zoom": self.zoom,
                                                 "collapsed": self.collapsed, "spoilers": self.spoilers,
                                                 "tab": self.tab},
                                                indent="	"), encoding="utf-8")
            except OSError:
                pass

    def colour(self, name: str) -> str:
        return self.colours[self.theme].get(name, THEMES[self.theme][name])

    def set_colour(self, name: str, colour: str) -> None:
        self.colours[self.theme][name] = colour
        self.save()

    def reset_colours(self) -> None:
        self.colours[self.theme] = {}
        self.save()

    def toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        self.save()
