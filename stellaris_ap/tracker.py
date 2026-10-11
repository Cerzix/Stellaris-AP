"""The tracker: the technology tree of the game with what every technology holds in this run.

The tree is laid out like the game's: one band for each area of research, from the starting
technologies on the left to the late ones on the right, with a line from a technology to the ones
that follow it. A technology that is a location shows whether it was checked and what it holds; a
dot marks the technologies the player has received. Above the tree are the locations that are not
technologies: the traditions and the ascension perks.

The first half of this file works out what to show and needs no window, the second half is the window.
"""
import tkinter
from dataclasses import dataclass, field
from tkinter import ttk

from . import data

AREAS = ("physics", "society", "engineering")
AREA_NAMES = {"physics": "Physics", "society": "Society", "engineering": "Engineering"}

# Sizes in the tree, before zooming
NODE_WIDTH = 210
NODE_HEIGHT = 28
COLUMN = 260
ROW = 36
BAND_GAP = 70
MARGIN = 40
LABEL_LENGTH = 30

BACKGROUND = "#14181f"
TEXT = "#d7dde5"
DIM = "#6b7785"
EDGE = "#2a3240"
EDGE_LIT = "#f7d774"
# The border of a location that is not checked yet, by the kind of item it holds
KIND_COLOUR = {"progression": "#c792ea", "useful": "#82aaff", "trap": "#ff5370", "filler": "#56606f"}
CHECKED = ("#1d3a29", "#4caf50")
OPEN = "#1b2230"
BASE = ("#1a1d23", "#343b47")
RECEIVED = "#ffcb6b"


@dataclass
class Node:
    key: str
    label: str
    # "location": a technology that is a location. "base": one the game keeps as it is. "pick": a tradition
    # or an ascension perk, which is a location too
    kind: str
    x: float = 0
    y: float = 0
    # The id of the location that is checked by researching or picking this
    location: int | None = None
    # The id of the item that is this technology
    item: int | None = None
    technology: dict | None = None
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)


@dataclass
class Tree:
    nodes: dict[str, Node]
    # (title, y) of the headings of the bands
    bands: list[tuple[str, float]]
    width: float
    height: float


@dataclass
class TrackerState:
    """What a run has done so far."""
    checked: set = field(default_factory=set)
    # location id -> (name of the item there, name of the player it is for, kind of the item)
    holds: dict = field(default_factory=dict)
    # The ids of the items received
    received: set = field(default_factory=set)
    # How far the goal is, in words
    goal: str = ""


def columns(technologies: list[dict]) -> dict[str, int]:
    """The column of every technology: at least its tier, and to the right of everything that comes before it."""
    by_key = {technology["key"]: technology for technology in technologies}
    column: dict[str, int] = {}

    def place(key: str, seen: tuple = ()) -> int:
        if key not in column:
            technology = by_key[key]
            before = [place(other, seen + (key,)) + 1 for other in technology["prerequisites"]
                      if other in by_key and other not in seen]
            column[key] = max([technology["tier"]] + before)
        return column[key]

    for technology in technologies:
        place(technology["key"])
    return column


def build_tree(technologies: list[dict], locations: list[dict]) -> Tree:
    nodes: dict[str, Node] = {}
    bands = []
    y = MARGIN

    # The locations that are not technologies: a row for every tradition tree, and one for the ascension perks
    bands.append(("Traditions and ascension perks", y))
    y += 30
    rows: dict[int, list[dict]] = {}
    for location in locations:
        if location["kind"] == "tradition":
            rows.setdefault(location["slot"], []).append(location)
        elif location["kind"] == "perk":
            rows.setdefault(data.TREE_SLOTS, []).append(location)
    for row in sorted(rows):
        for index, location in enumerate(rows[row]):
            nodes[f"location_{location['id']}"] = Node(
                f"location_{location['id']}", location["name"], "pick", MARGIN + index * COLUMN, y,
                location=location["id"])
        y += ROW
    width = MARGIN + (data.ASCENSION_PERK_SLOTS - 1) * COLUMN + NODE_WIDTH

    location_of = {location["technology"]["key"]: location["id"] for location in locations
                   if location["kind"] == "technology"}
    column = columns(technologies)
    for technology in technologies:
        key = technology["key"]
        nodes[key] = Node(key, technology["name"], "location" if key in location_of else "base",
                          location=location_of.get(key), item=technology.get("id"), technology=technology,
                          before=[other for other in technology["prerequisites"] if other in column])
    for node in list(nodes.values()):
        for other in node.before:
            nodes[other].after.append(node.key)

    for area in AREAS:
        y += BAND_GAP
        bands.append((AREA_NAMES[area], y))
        y += 30
        members = [nodes[technology["key"]] for technology in technologies if technology["area"] == area]
        by_column: dict[int, list[Node]] = {}
        for node in members:
            by_column.setdefault(column[node.key], []).append(node)
        position: dict[str, float] = {}
        tallest = 0
        for number in sorted(by_column):
            # Next to what it follows, and otherwise by its field of research
            def order(node: Node) -> tuple:
                placed = [position[other] for other in node.before if other in position]
                return (sum(placed) / len(placed) if placed else float("inf"), node.technology["category"],
                        node.label)

            for index, node in enumerate(sorted(by_column[number], key=order)):
                position[node.key] = index
                node.x = MARGIN + number * COLUMN
                node.y = y + index * ROW
            tallest = max(tallest, len(by_column[number]))
            width = max(width, MARGIN + number * COLUMN + NODE_WIDTH)
        y += tallest * ROW
    return Tree(nodes, bands, width + MARGIN, y + MARGIN)


def summary(state: TrackerState, locations: list[dict]) -> dict[str, tuple[int, int]]:
    """(checked, all) for "all" locations and for every kind of them."""
    counts = {"all": [0, 0], "technology": [0, 0], "tradition": [0, 0], "perk": [0, 0]}
    for location in locations:
        for key in ("all", location["kind"]):
            counts[key][1] += 1
            counts[key][0] += location["id"] in state.checked
    return {key: tuple(value) for key, value in counts.items()}


def summary_text(state: TrackerState, locations: list[dict]) -> str:
    counts = summary(state, locations)
    done, total = counts["all"]
    text = (f"{done} of {total} locations checked ({100 * done // max(total, 1)}%)      "
            f"Technologies {counts['technology'][0]}/{counts['technology'][1]}    "
            f"Traditions {counts['tradition'][0]}/{counts['tradition'][1]}    "
            f"Ascension perks {counts['perk'][0]}/{counts['perk'][1]}    "
            f"Items received {len(state.received)}")
    return text + (f"      {state.goal}" if state.goal else "")


def colours(node: Node, state: TrackerState) -> tuple[str, str, str]:
    """(fill, border, text colour) of a node."""
    if node.location is None:
        return BASE[0], BASE[1], DIM
    if node.location in state.checked:
        return CHECKED[0], CHECKED[1], TEXT
    kind = state.holds.get(node.location, ("", "", "filler"))[2]
    return OPEN, KIND_COLOUR.get(kind, KIND_COLOUR["filler"]), TEXT


def describe(node: Node, state: TrackerState) -> list[tuple[str, str]]:
    """What the side of the window says about a node: (text, kind) parts, with line breaks in the text."""
    parts = [(node.label + "\n", "title")]
    technology = node.technology
    if technology:
        parts.append((f"{AREA_NAMES[technology['area']]}, tier {technology['tier']}\n\n", "dim"))
    else:
        parts.append(("\n", "dim"))
    if node.location is None:
        if technology and technology["kind"] == "repeatable":
            parts.append(("A repeatable technology. It is researched as usual.\n", "text"))
        else:
            parts.append(("A base technology. Every empire starts with it or researches it as usual.\n", "text"))
    else:
        done = node.location in state.checked
        parts.append(("Location: ", "dim"))
        parts.append(("checked\n" if done else "not checked yet\n", "checked" if done else "text"))
        if node.location in state.holds:
            item, player, kind = state.holds[node.location]
            parts += [("Holds ", "dim"), (item, kind), (" for ", "dim"), (player + "\n", "player")]
        else:
            parts.append(("What it holds is not known yet.\n", "dim"))
    if node.item is not None:
        got = node.item in state.received
        parts.append(("\nThe technology itself: ", "dim"))
        parts.append(("received\n" if got else "not received yet\n", "received" if got else "text"))
        if technology and technology["dlc"]:
            parts.append(("Needs " + ", ".join(technology["dlc"]) + "\n", "dim"))
    if technology and node.before:
        parts.append(("\nComes after\n", "dim"))
        parts.append(("".join(f"  {name}\n" for name in node.before), "text"))
    return parts


def find(tree: Tree, state: TrackerState, text: str, after: str | None = None) -> str | None:
    """The key of the next node whose name, or the name of what it holds, has the text in it."""
    wanted = text.strip().lower()
    if not wanted:
        return None
    keys = [key for key, node in tree.nodes.items()
            if wanted in node.label.lower() or wanted in state.holds.get(node.location, ("",))[0].lower()]
    if not keys:
        return None
    return keys[(keys.index(after) + 1) % len(keys)] if after in keys else keys[0]


class TrackerWindow:
    """The window. state() gives the TrackerState of the run that is played."""

    def __init__(self, parent, state, title: str = "Stellaris Archipelago - Tracker"):
        self.state_of_run = state
        self.state = TrackerState()
        self.tree = build_tree(data.technologies(), data.locations())
        self.names = {key: node.label for key, node in self.tree.nodes.items()}
        for node in self.tree.nodes.values():
            node.before = [self.names[key] for key in node.before]
        self.zoom = 0.6
        self.pinned: str | None = None
        self.shown: str | None = None
        self.pressed: tuple[int, int] | None = None
        self.drawn: dict[str, tuple[int, int, int]] = {}
        self.closed = False

        self.window = tkinter.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("1280x760")
        self.window.minsize(760, 420)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        bar = ttk.Frame(self.window, padding=(10, 8, 10, 6))
        bar.pack(fill="x")
        self.summary = ttk.Label(bar, text="")
        self.summary.pack(side="left")
        ttk.Button(bar, text="+", width=3, command=lambda: self.zoom_by(1.25)).pack(side="right")
        ttk.Button(bar, text="-", width=3, command=lambda: self.zoom_by(0.8)).pack(side="right", padx=(6, 2))
        self.search = ttk.Entry(bar, width=24)
        self.search.pack(side="right")
        self.search.bind("<Return>", lambda event: self.search_next())
        ttk.Label(bar, text="Find").pack(side="right", padx=(0, 4))

        legend = ttk.Frame(self.window, padding=(10, 0, 10, 6))
        legend.pack(fill="x")
        for text, colour in (("checked", CHECKED[1]), ("holds progression", KIND_COLOUR["progression"]),
                             ("holds something useful", KIND_COLOUR["useful"]), ("holds filler", KIND_COLOUR["filler"]),
                             ("holds a trap", KIND_COLOUR["trap"]), ("base technology", BASE[1]),
                             ("technology received", RECEIVED)):
            tkinter.Label(legend, text="■", foreground=colour).pack(side="left")
            ttk.Label(legend, text=text + "   ").pack(side="left")
        ttk.Label(legend, text="Drag to move, wheel to zoom, click to keep a technology shown",
                  foreground="#777777").pack(side="right")

        body = ttk.Frame(self.window)
        body.pack(fill="both", expand=True)
        self.info = tkinter.Text(body, width=36, background="#1a1f28", foreground=TEXT, wrap="word",
                                 font=("Segoe UI", 10), borderwidth=0, padx=12, pady=10, state="disabled")
        self.info.pack(side="right", fill="y")
        self.info.tag_configure("title", font=("Segoe UI", 12, "bold"))
        self.info.tag_configure("dim", foreground=DIM)
        self.info.tag_configure("checked", foreground=CHECKED[1])
        self.info.tag_configure("received", foreground=RECEIVED)
        self.info.tag_configure("player", foreground="#ffcb6b")
        for kind, colour in KIND_COLOUR.items():
            self.info.tag_configure(kind, foreground=colour if kind != "filler" else "#89ddff")
        self.canvas = tkinter.Canvas(body, background=BACKGROUND, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<MouseWheel>", lambda event: self.zoom_by(1.15 if event.delta > 0 else 1 / 1.15, event))

        self.draw()
        self.show(None)
        self.refresh()

    # --- drawing

    def draw(self) -> None:
        """Draws the whole tree at the current zoom."""
        canvas, zoom = self.canvas, self.zoom
        canvas.delete("all")
        self.drawn = {}
        canvas.configure(scrollregion=(-200, -200, self.tree.width * zoom + 200, self.tree.height * zoom + 200))
        for title, y in self.tree.bands:
            canvas.create_text(MARGIN * zoom, y * zoom, text=title, anchor="w", fill=TEXT,
                               font=("Segoe UI", max(8, int(15 * zoom)), "bold"))
        for node in self.tree.nodes.values():
            for key in node.after:
                other = self.tree.nodes[key]
                # Lines between the areas would run across everything: only for the technology that is shown
                across = other.technology["area"] != node.technology["area"]
                x1, y1 = (node.x + NODE_WIDTH) * zoom, (node.y + NODE_HEIGHT / 2) * zoom
                x2, y2 = other.x * zoom, (other.y + NODE_HEIGHT / 2) * zoom
                bend = 24 * zoom
                canvas.create_line(x1, y1, x1 + bend, y1, x2 - bend, y2, x2, y2, smooth=True, fill=EDGE,
                                   state="hidden" if across else "normal",
                                   tags=("edge", "from_" + node.key, "to_" + other.key) + (("across",) if across else ()))
        size = max(1, int(9 * zoom))
        for node in self.tree.nodes.values():
            x, y = node.x * zoom, node.y * zoom
            tag = "node_" + node.key
            box = canvas.create_rectangle(x, y, x + NODE_WIDTH * zoom, y + NODE_HEIGHT * zoom, width=max(1, 2 * zoom),
                                          tags=("node", tag))
            label = node.label if len(node.label) <= LABEL_LENGTH else node.label[:LABEL_LENGTH - 1] + "…"
            text = canvas.create_text(x + 8 * zoom, y + NODE_HEIGHT * zoom / 2, text=label, anchor="w",
                                      font=("Segoe UI", size), tags=("node", tag),
                                      state="normal" if zoom >= 0.45 else "hidden")
            radius = 4 * zoom
            dot = canvas.create_oval(x + (NODE_WIDTH - 12) * zoom - radius, y + NODE_HEIGHT * zoom / 2 - radius,
                                     x + (NODE_WIDTH - 12) * zoom + radius, y + NODE_HEIGHT * zoom / 2 + radius,
                                     fill=RECEIVED, outline="", tags=("node", tag), state="hidden")
            self.drawn[node.key] = (box, text, dot)
        self.colour()
        self.light(self.shown)

    def colour(self) -> None:
        """Colours the nodes by what the run has done."""
        for key, (box, text, dot) in self.drawn.items():
            node = self.tree.nodes[key]
            fill, border, ink = colours(node, self.state)
            self.canvas.itemconfigure(box, fill=fill, outline="#ffffff" if key == self.pinned else border)
            self.canvas.itemconfigure(text, fill=ink)
            self.canvas.itemconfigure(dot, state="normal" if node.item in self.state.received else "hidden")

    def light(self, key: str | None) -> None:
        """Lights the lines of the technology that is shown."""
        self.canvas.itemconfigure("edge", fill=EDGE, width=1)
        self.canvas.itemconfigure("across", state="hidden")
        if key:
            for tag in ("from_" + key, "to_" + key):
                self.canvas.itemconfigure(tag, fill=EDGE_LIT, width=2, state="normal")
                self.canvas.tag_raise(tag, "edge")

    def show(self, key: str | None) -> None:
        """Shows a node at the side, or what the tracker is if there is none."""
        self.shown = key
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        if key is None:
            self.info.insert("end", "Tracker\n", "title")
            self.info.insert("end", "\nMove the mouse over a technology to see what it holds, and click it to keep "
                                    "it shown.\n\nA line leads from a technology to the ones that follow it in the "
                                    "game. In this run a technology is a location: researching it sends what it "
                                    "holds, and the technology itself arrives as an item.", "dim")
        else:
            for text, kind in describe(self.tree.nodes[key], self.state):
                self.info.insert("end", text, kind)
        self.info.configure(state="disabled")
        self.light(key)

    def refresh(self) -> None:
        """Takes over what the run has done since the last time."""
        if self.closed:
            return
        state = self.state_of_run()
        if (state.checked, state.holds, state.received, state.goal) != (
                self.state.checked, self.state.holds, self.state.received, self.state.goal):
            self.state = TrackerState(set(state.checked), dict(state.holds), set(state.received), state.goal)
            self.colour()
            self.show(self.shown)
        self.summary.configure(text=summary_text(self.state, data.locations()))
        self.window.after(1000, self.refresh)

    # --- the mouse

    def node_at(self, event) -> str | None:
        for tag in self.canvas.gettags("current"):
            if tag.startswith("node_"):
                return tag[5:]
        return None

    def press(self, event) -> None:
        self.pressed = (event.x, event.y)
        self.canvas.scan_mark(event.x, event.y)

    def drag(self, event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def release(self, event) -> None:
        """A click, if the mouse did not move: keeps the technology under it shown."""
        if self.pressed and abs(event.x - self.pressed[0]) + abs(event.y - self.pressed[1]) < 5:
            self.pin(self.node_at(event))
        self.pressed = None

    def hover(self, event) -> None:
        if self.pinned is None:
            key = self.node_at(event)
            if key != self.shown:
                self.show(key)

    def pin(self, key: str | None) -> None:
        self.pinned = key
        self.colour()
        self.show(key)

    def zoom_by(self, factor: float, event=None) -> None:
        """Zooms in or out, around the mouse or the middle of the window."""
        zoom = min(2.0, max(0.2, self.zoom * factor))
        if zoom == self.zoom:
            return
        x = event.x if event else self.canvas.winfo_width() / 2
        y = event.y if event else self.canvas.winfo_height() / 2
        self.centre((self.canvas.canvasx(x) / self.zoom, self.canvas.canvasy(y) / self.zoom), zoom, (x, y))

    def centre(self, point: tuple[float, float], zoom: float | None = None, at: tuple[float, float] | None = None) -> None:
        """Puts a point of the tree at a place in the window (its middle if none is given)."""
        if zoom is not None and zoom != self.zoom:
            self.zoom = zoom
            self.draw()
        at = at or (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
        left, top, right, bottom = (float(value) for value in str(self.canvas.cget("scrollregion")).split())
        self.canvas.xview_moveto((point[0] * self.zoom - at[0] - left) / (right - left))
        self.canvas.yview_moveto((point[1] * self.zoom - at[1] - top) / (bottom - top))

    def search_next(self) -> None:
        key = find(self.tree, self.state, self.search.get(), self.pinned)
        if key:
            node = self.tree.nodes[key]
            self.centre((node.x + NODE_WIDTH / 2, node.y + NODE_HEIGHT / 2), max(self.zoom, 0.8))
            self.pin(key)

    def close(self) -> None:
        self.closed = True
        self.window.destroy()
