"""The tracker: the technology tree of the game with what every technology holds in this run.

The tree is laid out like the game's: one band for each area of research, from the starting
technologies on the left to the late ones on the right, with a line from a technology to the ones
that follow it. A technology that is a location shows whether it was checked, whether it can come
up as research right now, and what it holds; a dot marks the technologies the player has received.
Above the tree are the locations that are not technologies: the traditions and the ascension perks.

The first half of this file works out what to show and needs no window, the second half is the window.
"""
import tkinter
from dataclasses import dataclass, field, replace
from tkinter import colorchooser

from . import data
from .paths import MOD_DIR, stellaris_game_dir
from .settings import ADJUSTABLE, Settings

AREAS = ("physics", "society", "engineering")
AREA_NAMES = {"physics": "Physics", "society": "Society", "engineering": "Engineering"}
PICKS = "picks"
# The traditions that arrive as items. The game has no place to list them: they work without their tree
TRADITIONS = "traditions"
BAND_NAMES = {PICKS: "Traditions and ascension perks", TRADITIONS: "Archipelago Traditions", **AREA_NAMES}
# The tabs of the window: every part of the tree on its own, and all of them at once
EVERYTHING = "all"
TABS = {PICKS: "Traditions and perks", TRADITIONS: "Archipelago Traditions", **AREA_NAMES, EVERYTHING: "Everything"}
# previously_unlocked in the game's common/technology/tier: so many technologies of a tier have to be
# researched in an area before the next tier comes up there
TIER_NEEDS = 6

# Sizes in the tree, before zooming
NODE_WIDTH = 220
NODE_HEIGHT = 28
COLUMN = 270
ROW = 36
BAND_GAP = 60
BAND_TITLE = 34
MARGIN = 40
LABEL_LENGTH = 27
MIN_ZOOM, MAX_ZOOM = 0.2, 2.0
# Below this zoom the names are too small to read and are left out
TEXT_ZOOM = 0.45

# The legend at the side: how a box looks, and what that means
LEGEND = (
    ("checked", "Checked: you sent what it held"),
    ("available", "Can come up as research now"),
    ("locked", "Locked: its tier is not open yet"),
    ("base", "Base technology, not randomized"),
    ("progression", "Stripe: holds progression"),
    ("useful", "Stripe: holds something useful"),
    ("filler", "Stripe: holds filler"),
    ("received", "Dot: you received this technology or tradition"),
    ("stellaris", "Holds a technology of Stellaris"),
    ("foreign", "Holds something else, or of another game"),
    ("match", "Found by the search"),
    ("pinned", "Clicked, to keep it shown"),
)
LEGEND_ROW = 23
# The technology whose icon stands for all of them in the legend
LEGEND_TECHNOLOGY = "tech_lasers_1"
# What a location is called while it is not known what it holds
UNKNOWN_ITEM = "Archipelago Item"
# The icon of everything that is not a technology of Stellaris
ARCHIPELAGO_ICON = "archipelago"
# The filters at the top: what they are called, and the colour of their mark
FILTERS = {"checked": "checked", "available": "can be researched now", "progression": "holds progression",
           "useful": "holds something useful", "filler": "holds filler", "base": "base technology",
           "received": "received"}
FILTER_COLOUR = {"base": "base_border"}


@dataclass
class Node:
    key: str
    label: str
    # "location": a technology that is a location. "base": one the game keeps as it is. "pick": a tradition
    # or an ascension perk, which is a location too. "tradition": a tradition that arrives as an item
    kind: str
    band: str
    x: float = 0
    y: float = 0
    hidden: bool = False
    # The id of the location that is checked by researching or picking this
    location: int | None = None
    # The id of the item that is this technology or tradition
    item: int | None = None
    # The name of the tree of a tradition
    group: str = ""
    technology: dict | None = None
    # The location of a pick, as data.locations() has it
    pick: dict | None = None
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)


@dataclass
class Band:
    key: str
    title: str
    y: float
    collapsed: bool
    nodes: list[str]


@dataclass
class Tree:
    nodes: dict[str, Node]
    bands: list[Band]
    width: float
    height: float


@dataclass
class TrackerState:
    """What a run has done so far."""
    checked: set = field(default_factory=set)
    # location id -> (name of the item there, name of the player it is for, kind of the item, and the icon of
    # the technology if it is one of Stellaris)
    holds: dict = field(default_factory=dict)
    # The ids of the items received
    received: set = field(default_factory=set)
    # How many ascension perk slots were received
    perk_slots: int = 0
    # How far the goal is, in words
    goal: str = ""
    # Whether what the locations hold was left out until they are checked
    hidden: bool = False
    # Whether the traditions are shuffled. If not, they are neither locations nor items
    traditions: bool = True
    # The ids of the traditions that are items of the multiworld, None if that is not known. The others are
    # not listed: the empire can not use them, so they are nowhere to be found
    pool: frozenset | None = None

    def same(self, other: "TrackerState") -> bool:
        return (self.checked, self.holds, self.received, self.perk_slots, self.goal, self.traditions, self.pool) == (
            other.checked, other.holds, other.received, other.perk_slots, other.goal, other.traditions, other.pool)

    def without_spoilers(self, shown=()) -> "TrackerState":
        """The same run, knowing only what the locations that are checked held, and what the ones in shown
        hold: the game names those itself, see open_locations."""
        return replace(self.copy(), holds={location: entry for location, entry in self.holds.items()
                                           if location in self.checked or location in shown}, hidden=True)

    def copy(self) -> "TrackerState":
        return replace(self, checked=set(self.checked), holds=dict(self.holds), received=set(self.received),
                       hidden=False)


def held(state: TrackerState, location: int | None) -> tuple[str, str, str, str | None]:
    """(item, player, kind, icon) of what a location holds, with empty names if that is not known."""
    entry = tuple(state.holds.get(location, ()))
    entry += ("", "", "filler", None)[len(entry):]
    # A trap is not told apart: it looks like filler
    return entry[0], entry[1], entry[2] if entry[2] in ("progression", "useful") else "filler", entry[3]


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


def build_tree(technologies: list[dict], locations: list[dict], collapsed=(), trees=(), pool=None,
               only: str | None = None) -> Tree:
    """Lays out the tree. collapsed: the keys of the bands that only show their title.
    locations: the locations of the run. trees: the tradition trees whose traditions arrive as items.
    pool: the ids of the traditions that are in the multiworld, None for all of them.
    only: the key of the one band to lay out. The others are still in the tree, but hidden."""
    nodes: dict[str, Node] = {}
    bands = []
    y = MARGIN
    width = MARGIN + (data.ASCENSION_PERK_SLOTS - 1) * COLUMN + NODE_WIDTH

    # The locations that are not technologies. A block for every tradition tree, one next to the other: its
    # adoption at the top, its traditions below that and its finish at the bottom. Under them a row for the
    # ascension perks
    band = Band(PICKS, BAND_NAMES[PICKS], y, PICKS in collapsed, [])
    bands.append(band)
    y += BAND_TITLE
    traditions = sorted((location for location in locations if location["kind"] == "tradition"),
                        key=lambda location: (location["slot"], location["position"]))
    perks = sorted((location for location in locations if location["kind"] == "perk"),
                   key=lambda location: location["number"])
    below = max((location["position"] + 1 for location in traditions), default=0) * ROW
    if traditions and perks:
        below += ROW / 2
    for location in traditions + perks:
        if location["kind"] == "tradition":
            place = MARGIN + location["slot"] * COLUMN, y + location["position"] * ROW
        else:
            place = MARGIN + (location["number"] - 1) * COLUMN, y + below
        key = f"location_{location['id']}"
        # "Tradition Tree 1: Tradition 2" says tradition once too often for a small box
        nodes[key] = Node(key, location["name"].removeprefix("Tradition "), "pick", PICKS, *place,
                          hidden=band.collapsed, location=location["id"], pick=location)
        band.nodes.append(key)
    if not band.collapsed:
        y += below + (ROW if perks else 0)

    # The traditions that arrive as items: a row for every tree they come from
    if trees:
        y += BAND_GAP
        band = Band(TRADITIONS, BAND_NAMES[TRADITIONS], y, TRADITIONS in collapsed, [])
        bands.append(band)
        y += BAND_TITLE
        for tree in trees:
            items = [tradition for tradition in tree["traditions"]
                     if "id" in tradition and (pool is None or tradition["id"] in pool)]
            for index, tradition in enumerate(items):
                key = f"tradition_{tradition['id']}"
                nodes[key] = Node(key, tradition["name"], "tradition", TRADITIONS, MARGIN + index * COLUMN, y,
                                  hidden=band.collapsed, item=tradition["id"], group=tree["name"])
                band.nodes.append(key)
            if items and not band.collapsed:
                y += ROW

    location_of = {location["technology"]["key"]: location["id"] for location in locations
                   if location["kind"] == "technology"}
    column = columns(technologies)
    for technology in technologies:
        key = technology["key"]
        nodes[key] = Node(key, technology["name"], "location" if key in location_of else "base", technology["area"],
                          location=location_of.get(key), item=technology.get("id"), technology=technology,
                          before=[other for other in technology["prerequisites"] if other in column])
    for node in list(nodes.values()):
        for other in node.before:
            nodes[other].after.append(node.key)

    for area in AREAS:
        y += BAND_GAP
        band = Band(area, AREA_NAMES[area], y, area in collapsed, [])
        bands.append(band)
        y += BAND_TITLE
        members = [nodes[technology["key"]] for technology in technologies if technology["area"] == area]
        band.nodes = [node.key for node in members]
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
                node.hidden = band.collapsed
            tallest = max(tallest, len(by_column[number]))
            if not band.collapsed:
                width = max(width, MARGIN + number * COLUMN + NODE_WIDTH)
        if not band.collapsed:
            y += tallest * ROW
    alone = next((band for band in bands if band.key == only), None)
    if alone is None:
        return Tree(nodes, bands, width + MARGIN, y + MARGIN)
    # Only this band, moved up to where the first one was
    up = alone.y - MARGIN
    alone.y = MARGIN
    width, height = MARGIN + NODE_WIDTH, MARGIN + BAND_TITLE
    for node in nodes.values():
        if node.band != only:
            node.hidden = True
        else:
            node.y -= up
            if not node.hidden:
                width, height = max(width, node.x + NODE_WIDTH), max(height, node.y + NODE_HEIGHT)
    return Tree(nodes, [alone], width + MARGIN, height + MARGIN)


def researched(technologies: list[dict], state: TrackerState) -> dict[tuple[str, int], int]:
    """How many technologies of each (area, tier) the player has researched: the locations that are checked,
    and the technologies that arrived as items. Both are technologies to the game."""
    counts: dict[tuple[str, int], int] = {}
    for technology in technologies:
        if "id" in technology:
            done = (technology["id"] in state.checked) + (technology["id"] in state.received)
            counts[technology["area"], technology["tier"]] = counts.get((technology["area"], technology["tier"]), 0) + done
    return counts


def status(node: Node, state: TrackerState, counts: dict) -> str:
    """"base", "checked", "available" (it can be researched or picked now) or "locked"."""
    if node.location is None:
        return "base"
    if node.location in state.checked:
        return "checked"
    if node.technology:
        # The technologies of a tier come up once enough of the tier before are researched
        tier, area = node.technology["tier"], node.technology["area"]
        return "available" if tier <= 1 or counts.get((area, tier - 1), 0) >= TIER_NEEDS else "locked"
    pick = node.pick
    if pick["kind"] == "perk":
        before = pick["number"] == 1 or data.PERK_ID_BASE + pick["number"] - 1 in state.checked
        return "available" if before and state.perk_slots >= pick["number"] else "locked"
    # A tradition: its tree has to be adopted, which takes the tree before it to be adopted. The finish of a
    # tree comes once every tradition between the two is picked
    if pick["position"] == data.TRADITIONS_PER_TREE - 1:
        needed = [data.tradition_location(pick["slot"], position) for position in range(data.TRADITIONS_PER_TREE - 1)]
    elif pick["position"] > 0:
        needed = [data.tradition_location(pick["slot"], 0)]
    else:
        needed = [data.tradition_location(pick["slot"] - 1, 0)] if pick["slot"] else []
    return "available" if all(location in state.checked for location in needed) else "locked"


def open_locations(tree: Tree, technologies: list[dict], state: TrackerState) -> set[int]:
    """The locations that can be researched or picked now. What they hold is no secret: the game names the
    technology after it, and says it in the tooltip of the tradition."""
    counts = researched(technologies, state)
    return {node.location for node in tree.nodes.values()
            if node.location is not None and status(node, state, counts) == "available"}


def fits(node: Node, state: TrackerState, counts: dict, name: str) -> bool:
    """Whether a node belongs to what a filter at the top shows."""
    if name == "base":
        return node.kind == "base"
    if name == "received":
        return node.item is not None and node.item in state.received
    if name in ("checked", "available"):
        return status(node, state, counts) == name
    return node.location is not None and node.location in state.holds and held(state, node.location)[2] == name


def name_of(node: Node, state: TrackerState) -> str:
    """What a node is called in the tree. A location is called after the item it holds, as its technology is
    in the game: "16 Diamonds" where Destroyers would be. Until a run is connected and that is known, it is
    just an item. A technology the game keeps as it is has its own name."""
    if node.location is None:
        return node.label
    return held(state, node.location)[0] or UNKNOWN_ITEM


def short(name: str) -> str:
    return name if len(name) <= LABEL_LENGTH else name[:LABEL_LENGTH - 1] + "\u2026"


def icon_of(node: Node, state: TrackerState) -> str | None:
    """The icon of a node: of the technology itself, of the technology it holds, or the one of Archipelago
    for what comes from somewhere else. None for the name of an icon means there is none to show."""
    if node.kind == "tradition":
        return ARCHIPELAGO_ICON
    if node.location is None:
        return node.technology["icon"]
    return held(state, node.location)[3] or ARCHIPELAGO_ICON


def summary(state: TrackerState, locations: list[dict]) -> dict[str, tuple[int, int]]:
    """(checked, all) for "all" locations and for every kind of them."""
    counts = {"all": [0, 0], "technology": [0, 0], "tradition": [0, 0], "perk": [0, 0]}
    for location in locations:
        for key in ("all", location["kind"]):
            counts[key][1] += 1
            counts[key][0] += location["id"] in state.checked
    return {key: tuple(value) for key, value in counts.items()}


def summary_text(state: TrackerState, locations: list[dict]) -> str:
    """The line at the top. The goal has a line of its own, see TrackerWindow."""
    counts = summary(state, locations)
    done, total = counts["all"]
    traditions = f"Traditions {counts['tradition'][0]}/{counts['tradition'][1]}    " if counts["tradition"][1] else ""
    return (f"{done} of {total} locations checked ({100 * done / max(total, 1):.2f}%)      "
            f"Technologies {counts['technology'][0]}/{counts['technology'][1]}    {traditions}"
            f"Ascension perks {counts['perk'][0]}/{counts['perk'][1]}    "
            f"Items received {len(state.received)}")


def band_text(band: Band, tree: Tree, state: TrackerState) -> str:
    """The heading of a band: whether it is open, its name, and how many of its locations are checked."""
    arrow = "▸" if band.collapsed else "▾"
    if band.key == TRADITIONS:
        got = sum(tree.nodes[key].item in state.received for key in band.nodes)
        return f"{arrow} {band.title}   {got} received"
    places = [tree.nodes[key].location for key in band.nodes if tree.nodes[key].location is not None]
    done = sum(location in state.checked for location in places)
    return f"{arrow} {band.title}   {done}/{len(places)}"


def describe(node: Node, state: TrackerState, counts: dict, names: dict[str, str]) -> list[tuple[str, str]]:
    """What the side of the window says about a node: (text, kind) parts, with line breaks in the text."""
    parts = [(name_of(node, state) + "\n", "title")]
    if node.kind == "tradition":
        got = node.item in state.received
        return parts + [(f"A tradition of {node.group}\n\n", "dim"), ("The tradition itself: ", "dim"),
                        ("received\n" if got else "not received yet\n", "received" if got else "text"),
                        ("\nIt arrives as an item and works from then on, whichever trees you adopt. The game "
                         "has no place to show it, so it is listed here.\n", "dim")]
    technology = node.technology
    if node.location is not None:
        # The box is called after what it holds: say where in the tree that is
        parts.append((f"in the place of {node.label}\n", "dim"))
    if technology:
        parts.append((f"{AREA_NAMES[technology['area']]}, tier {technology['tier']}\n\n", "dim"))
    else:
        parts.append(("\n", "dim"))
    if node.location is None:
        if technology["kind"] == "repeatable":
            parts.append(("A repeatable technology. It is researched as usual.\n", "text"))
        else:
            parts.append(("A base technology. Every empire starts with it or researches it as usual.\n", "text"))
    else:
        now = status(node, state, counts)
        parts.append(("Location: ", "dim"))
        if now == "checked":
            parts.append(("checked\n", "checked"))
        elif now == "available":
            parts.append(("can be researched now\n" if technology else "can be picked now\n", "available"))
        elif technology:
            done = counts.get((technology["area"], technology["tier"] - 1), 0)
            parts.append((f"comes up after {TIER_NEEDS - done} more technologies of tier {technology['tier'] - 1} "
                          f"in {AREA_NAMES[technology['area']]}\n", "text"))
        else:
            parts.append(("not yet\n", "text"))
        if node.location in state.holds:
            item, player, kind, _ = held(state, node.location)
            parts += [("Holds ", "dim"), (item, kind), (" for ", "dim"), (player + "\n", "player")]
        else:
            parts.append(("What it holds is hidden until it can be researched or picked. Spoilers at the top "
                          "shows it.\n" if state.hidden
                          else "What it holds is not known yet.\n", "dim"))
    if node.item is not None:
        got = node.item in state.received
        parts.append(("\nThe technology itself: ", "dim"))
        parts.append(("received\n" if got else "not received yet\n", "received" if got else "text"))
        if technology["dlc"]:
            parts.append(("Needs " + ", ".join(technology["dlc"]) + "\n", "dim"))
    for title, keys in (("Comes after", node.before), ("Leads to", node.after)):
        if keys:
            parts.append((f"\n{title}\n", "dim"))
            parts.append(("".join(f"  {names[key]}\n" for key in keys), "text"))
    return parts


def matches(tree: Tree, state: TrackerState, text: str) -> list[str]:
    """The keys of the nodes whose name, or the name of what they hold, has the text in it. A location whose
    item is hidden is not found by anything: its box says nothing, and lighting it up would give it away."""
    wanted = text.strip().lower()
    if not wanted:
        return []
    found = []
    for key, node in tree.nodes.items():
        if state.hidden and node.location is not None and node.location not in state.holds:
            continue
        if wanted in node.label.lower() or wanted in held(state, node.location)[0].lower():
            found.append(key)
    return found


class Icons:
    """The icons of the technologies, read from the installed game. Without the game, or without the package
    that reads its pictures, there are none."""

    def __init__(self):
        self.folder = None
        self.pictures: dict[str, object] = {}
        self.scaled: dict[tuple, object] = {}
        self.size = 0
        try:
            from .bootstrap import require
            require("PIL", pip_name="Pillow")
            from PIL import Image, ImageTk
            self.image = Image
            self.photo = ImageTk.PhotoImage
        except Exception:
            self.image = None
            return
        game_dir = stellaris_game_dir()
        if game_dir:
            self.folder = game_dir / "gfx" / "interface" / "icons" / "technologies"

    def picture(self, name: str):
        if name not in self.pictures:
            if name == ARCHIPELAGO_ICON:
                path = MOD_DIR / "gfx" / "interface" / "icons" / "technologies" / "ap_check.dds"
            else:
                path = self.folder / f"{name}.dds" if self.folder else None
            try:
                self.pictures[name] = self.image.open(path).convert("RGBA") if path else None
            except Exception:
                # A picture the package cannot read is no reason to stop drawing the tree
                self.pictures[name] = None
        return self.pictures[name]

    def get(self, name: str | None, size: int, background: str, faded: bool):
        """The icon at a size, on the colour it is drawn on. faded: washed out, for what is filtered away."""
        if not self.image or not name or size < 8:
            return None
        if size != self.size:
            # Only the size the tree is drawn at is kept, or every step of zooming would stay in memory
            self.scaled.clear()
            self.size = size
        key = (name, size, background, faded)
        if key not in self.scaled:
            picture = self.picture(name)
            if picture is None:
                self.scaled[key] = None
            else:
                under = self.image.new("RGBA", (size, size), background)
                icon = self.image.alpha_composite(under, picture.resize((size, size), self.image.LANCZOS))
                if faded:
                    icon = self.image.blend(icon, under, 0.75)
                self.scaled[key] = self.photo(icon)
        return self.scaled[key]


class TrackerWindow:
    """The window. state() gives the TrackerState of the run that is played."""

    def __init__(self, parent, state, settings: Settings | None = None,
                 title: str = "Stellaris Archipelago - Tracker", resync=None):
        """resync: called when the player asks for everything to be read again."""
        self.state_of_run = state
        self.resync = resync
        self.state = TrackerState()
        self.settings = settings or Settings()
        self.technologies = data.technologies()
        self.build_tree()
        self.counts = researched(self.technologies, self.state)
        self.icons = Icons()
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.settings.zoom))
        self.pinned: str | None = None
        self.shown: str | None = None
        self.filter: str | None = None
        self.found: list[str] = []
        self.pressed: tuple[int, int] | None = None
        self.drawn: dict[str, dict[str, int]] = {}
        self.band_titles: dict[str, int] = {}
        self.closed = False
        self.timer = None

        self.window = tkinter.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("1320x780")
        self.window.minsize(820, 440)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda event: self.clear())
        self.window.bind("<Control-f>", lambda event: self.search.focus_set())

        self.bar = tkinter.Frame(self.window, padx=10, pady=7)
        self.bar.pack(fill="x")
        self.summary = tkinter.Label(self.bar, anchor="w")
        self.summary.pack(side="left")
        self.buttons = []
        for text, command in (("☀", self.toggle_theme), ("Colours", self.pick_colours),
                              ("", self.toggle_spoilers), ("Refresh", self.rebuild),
                              ("+", lambda: self.zoom_by(1.25)), ("−", lambda: self.zoom_by(0.8)),
                              ("Fit", self.fit)):
            button = tkinter.Button(self.bar, text=text, command=command, relief="flat", padx=8, pady=1,
                                    borderwidth=0, cursor="hand2")
            button.pack(side="right", padx=2)
            self.buttons.append(button)
        self.spoiler_button = self.buttons[2]
        self.label_spoilers()

        # How far the goal is: a line of its own, which is only there if the run has something to count
        self.goal = tkinter.Label(self.window, anchor="w", padx=10, pady=3, font=("Segoe UI", 10, "bold"))

        # One part of the tree at a time: all of it at once is slow to move around
        self.tabs = tkinter.Frame(self.window, padx=10, pady=2)
        self.tabs.pack(fill="x")
        self.tab: dict[str, tkinter.Label] = {}
        for key, text in TABS.items():
            label = tkinter.Label(self.tabs, text=text, cursor="hand2", padx=10, pady=4)
            label.bind("<Button-1>", lambda event, key=key: self.set_tab(key))
            self.tab[key] = label
        self.place_tabs()

        self.chips = tkinter.Frame(self.window, padx=10, pady=4)
        self.chips.pack(fill="x")
        self.found_label = tkinter.Label(self.chips, width=10, anchor="w")
        self.found_label.pack(side="right")
        self.search = tkinter.Entry(self.chips, width=26, relief="flat", highlightthickness=1)
        self.search.pack(side="right", padx=(0, 6), ipady=2)
        self.search.bind("<KeyRelease>", self.search_changed)
        self.search.bind("<Return>", lambda event: self.search_next())
        self.find_label = tkinter.Label(self.chips, text="Find")
        self.find_label.pack(side="right", padx=(0, 5))
        self.chip: dict[str, tuple[tkinter.Label, tkinter.Label]] = {}
        for name, text in FILTERS.items():
            mark = tkinter.Label(self.chips, text="■", cursor="hand2")
            label = tkinter.Label(self.chips, text=text, cursor="hand2", padx=2)
            mark.pack(side="left")
            label.pack(side="left", padx=(0, 12))
            for widget in (mark, label):
                widget.bind("<Button-1>", lambda event, name=name: self.set_filter(name))
            self.chip[name] = (mark, label)

        self.body = tkinter.Frame(self.window)
        self.body.pack(fill="both", expand=True)
        self.side = tkinter.Frame(self.body)
        self.side.pack(side="right", fill="y")
        # What the borders, stripes, dots and icons mean: always in view, below what is shown of a node
        self.legend = tkinter.Canvas(self.side, highlightthickness=0, height=LEGEND_ROW * (len(LEGEND) + 1) + 26)
        self.legend.pack(side="bottom", fill="x")
        self.info = tkinter.Text(self.side, width=38, wrap="word", font=("Segoe UI", 10), borderwidth=0,
                                 padx=14, pady=12, state="disabled", cursor="arrow")
        self.info.pack(side="top", fill="both", expand=True)
        self.canvas = tkinter.Canvas(self.body, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Double-Button-1>", self.double_click)
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<MouseWheel>", lambda event: self.zoom_by(1.15 if event.delta > 0 else 1 / 1.15, event))

        self.apply_theme()
        self.refresh()

    # --- how it looks

    def colour(self, name: str) -> str:
        return self.settings.colour(name)

    def apply_theme(self) -> None:
        """Colours the window after the theme and the colours the player picked, and draws the tree again."""
        bar, text, dim = self.colour("bar"), self.colour("text"), self.colour("dim")
        for frame in (self.bar, self.chips, self.tabs):
            frame.configure(background=bar)
        self.colour_tabs()
        for label in (self.summary, self.find_label, self.found_label):
            label.configure(background=bar, foreground=text)
        self.goal.configure(background=bar, foreground=self.colour("available"))
        for button in self.buttons:
            button.configure(background=self.colour("node"), foreground=text, activebackground=self.colour("panel"),
                             activeforeground=text)
        self.search.configure(background=self.colour("panel"), foreground=text, insertbackground=text,
                              highlightbackground=self.colour("locked"), highlightcolor=self.colour("available"))
        self.body.configure(background=self.colour("background"))
        self.info.configure(background=self.colour("panel"), foreground=text)
        self.info.tag_configure("title", font=("Segoe UI", 12, "bold"))
        self.info.tag_configure("dim", foreground=dim)
        for name in ("checked", "available", "received", "progression", "useful", "filler"):
            self.info.tag_configure(name, foreground=self.colour(name))
        self.info.tag_configure("player", foreground=self.colour("received"))
        self.canvas.configure(background=self.colour("background"))
        self.colour_chips()
        self.draw_legend()
        self.draw()
        self.show(self.shown)

    def draw_legend(self) -> None:
        """Draws a small box for everything a box of the tree can look like, with what it means."""
        legend = self.legend
        legend.delete("all")
        self.legend_pictures = []
        legend.configure(background=self.colour("panel"))
        self.side.configure(background=self.colour("panel"))
        legend.create_line(14, 6, 600, 6, fill=self.colour("locked"))
        legend.create_text(14, 22, text="Legend", anchor="w", fill=self.colour("text"), font=("Segoe UI", 10, "bold"))
        width, height = 46, 18
        for row, (look, text) in enumerate(LEGEND):
            x, y = 14, 38 + row * LEGEND_ROW
            fill, border, thick = self.colour("node"), self.colour("locked"), 1
            if look in ("checked", "available", "match"):
                border, thick = self.colour(look), 2
                fill = self.colour("checked_fill") if look == "checked" else fill
            elif look == "pinned":
                border, thick = self.colour("text"), 2
            elif look == "base":
                fill, border = self.colour("base_fill"), self.colour("base_border")
            legend.create_rectangle(x, y, x + width, y + height, fill=fill, outline=border, width=thick)
            if look in ("progression", "useful", "filler"):
                legend.create_rectangle(x, y, x + 5, y + height, fill=self.colour(look), width=0)
            elif look == "received":
                legend.create_oval(x + width - 13, y + 5, x + width - 5, y + 13, fill=self.colour("received"), outline="")
            elif look in ("stellaris", "foreign"):
                name = LEGEND_TECHNOLOGY if look == "stellaris" else ARCHIPELAGO_ICON
                picture = self.icons.get(name, height - 2, fill, False)
                if picture:
                    # Kept here: the icons of another size than the tree's are not kept anywhere else
                    self.legend_pictures.append(picture)
                    legend.create_image(x + 5, y + height / 2, anchor="w", image=picture)
            legend.create_text(x + width + 10, y + height / 2, text=text, anchor="w", fill=self.colour("text"),
                               font=("Segoe UI", 9))

    def colour_chips(self) -> None:
        bar = self.colour("bar")
        for name, (mark, label) in self.chip.items():
            active = self.filter == name
            mark.configure(background=bar, foreground=self.colour(FILTER_COLOUR.get(name, name)))
            label.configure(background=bar, foreground=self.colour("text" if active or not self.filter else "dim"),
                            font=("Segoe UI", 9, "bold underline" if active else "normal"))

    def shown_tab(self) -> str:
        """The tab that is shown: the one that was picked, if the run has it."""
        tab = self.settings.tab
        return tab if tab in TABS and (tab != TRADITIONS or self.state.traditions) else PICKS

    def place_tabs(self) -> None:
        """Puts the tabs in their row, without the one of the traditions if they are not shuffled."""
        for key, label in self.tab.items():
            label.pack_forget()
            if key != TRADITIONS or self.state.traditions:
                label.pack(side="left", padx=(0, 2))

    def colour_tabs(self) -> None:
        for key, label in self.tab.items():
            active = key == self.shown_tab()
            label.configure(background=self.colour("node" if active else "bar"),
                            foreground=self.colour("text" if active else "dim"),
                            font=("Segoe UI", 10, "bold" if active else "normal"))

    def set_tab(self, tab: str) -> None:
        """Shows another part of the tree, from its top left."""
        if tab == self.shown_tab():
            return
        self.settings.tab = tab
        self.settings.save()
        self.build_tree()
        if self.pinned and self.tree.nodes[self.pinned].hidden:
            self.pinned = self.shown = None
        self.colour_tabs()
        self.draw()
        self.show(self.shown)
        left, top, right, bottom = (float(value) for value in str(self.canvas.cget("scrollregion")).split())
        self.canvas.xview_moveto(-left / (right - left))
        self.canvas.yview_moveto(-top / (bottom - top))

    def label_spoilers(self) -> None:
        self.spoiler_button.configure(text="Spoilers: on" if self.settings.spoilers else "Spoilers: off")

    def toggle_spoilers(self) -> None:
        """Shows what every location holds, or only what the checked ones held."""
        self.settings.spoilers = not self.settings.spoilers
        self.settings.save()
        self.label_spoilers()
        if self.timer:
            self.window.after_cancel(self.timer)
        self.refresh()

    def toggle_theme(self) -> None:
        self.settings.toggle_theme()
        self.apply_theme()

    def pick_colours(self) -> None:
        """A small window to change the colours of the theme that is on."""
        dialog = tkinter.Toplevel(self.window)
        dialog.title("Colours")
        dialog.transient(self.window)
        dialog.resizable(False, False)
        # The theme cannot be changed under it: its colours are the ones of the theme it was opened for
        dialog.grab_set()
        tkinter.Label(dialog, text=f"Colours of the {self.settings.theme} theme", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, padx=14, pady=(12, 6), sticky="w")
        swatches = {}

        def choose(name: str) -> None:
            picked = colorchooser.askcolor(self.colour(name), parent=dialog, title=ADJUSTABLE[name])[1]
            if picked:
                self.settings.set_colour(name, picked)
                swatches[name].configure(background=picked, activebackground=picked)
                self.apply_theme()

        def reset() -> None:
            self.settings.reset_colours()
            for name, swatch in swatches.items():
                swatch.configure(background=self.colour(name), activebackground=self.colour(name))
            self.apply_theme()

        for row, (name, text) in enumerate(ADJUSTABLE.items(), 1):
            tkinter.Label(dialog, text=text).grid(row=row, column=0, padx=(14, 20), pady=3, sticky="w")
            swatches[name] = tkinter.Button(dialog, width=6, background=self.colour(name), relief="flat",
                                            activebackground=self.colour(name), cursor="hand2",
                                            command=lambda name=name: choose(name))
            swatches[name].grid(row=row, column=1, padx=(0, 14), pady=3)
        tkinter.Button(dialog, text="Back to the defaults", command=reset).grid(
            row=len(ADJUSTABLE) + 1, column=0, padx=14, pady=(8, 12), sticky="w")
        tkinter.Button(dialog, text="Close", command=dialog.destroy).grid(
            row=len(ADJUSTABLE) + 1, column=1, padx=14, pady=(8, 12), sticky="e")

    # --- drawing

    def build_tree(self) -> None:
        """Lays the tree out for the run as it is: without the traditions if they are not shuffled."""
        shuffled = self.state.traditions
        self.locations = [location for location in data.locations() if shuffled or location["kind"] != "tradition"]
        tab = self.shown_tab()
        self.tree = build_tree(self.technologies, self.locations, self.settings.collapsed,
                               data.normal_trees() if shuffled else (), self.state.pool,
                               None if tab == EVERYTHING else tab)
        self.names = {key: node.label for key, node in self.tree.nodes.items()}

    def rebuild(self) -> None:
        """Reads everything again and draws the tree anew, for when something looks wrong."""
        if self.resync:
            self.resync()
        self.icons = Icons()
        self.state = TrackerState(traditions=self.state.traditions)
        self.build_tree()
        if self.pinned not in self.tree.nodes or self.shown not in self.tree.nodes:
            self.pinned = self.shown = None
        self.draw()
        if self.timer:
            self.window.after_cancel(self.timer)
        self.refresh()

    def draw(self) -> None:
        """Draws the whole tree at the current zoom."""
        canvas, zoom = self.canvas, self.zoom
        canvas.delete("all")
        self.drawn = {}
        self.band_titles = {}
        canvas.configure(scrollregion=(-300, -300, self.tree.width * zoom + 300, self.tree.height * zoom + 300))
        for band in self.tree.bands:
            self.band_titles[band.key] = canvas.create_text(
                MARGIN * zoom, band.y * zoom, anchor="w", font=("Segoe UI", max(8, int(15 * zoom)), "bold"),
                tags=("band", "band_" + band.key))
        for node in self.tree.nodes.values():
            for key in node.after:
                other = self.tree.nodes[key]
                if node.hidden or other.hidden:
                    continue
                # Lines between the areas would run across everything: only for the technology that is shown
                across = other.band != node.band
                x1, y1 = (node.x + NODE_WIDTH) * zoom, (node.y + NODE_HEIGHT / 2) * zoom
                x2, y2 = other.x * zoom, (other.y + NODE_HEIGHT / 2) * zoom
                bend = 24 * zoom
                canvas.create_line(x1, y1, x1 + bend, y1, x2 - bend, y2, x2, y2, smooth=True,
                                   state="hidden" if across else "normal",
                                   tags=("edge", "from_" + node.key, "to_" + other.key) + (("across",) if across else ()))
        size = max(1, int(9 * zoom))
        for node in self.tree.nodes.values():
            if node.hidden:
                continue
            x, y = node.x * zoom, node.y * zoom
            tags = ("node", "node_" + node.key)
            height = NODE_HEIGHT * zoom
            box = canvas.create_rectangle(x, y, x + NODE_WIDTH * zoom, y + height, tags=tags)
            # What kind of item it holds, as a stripe down its left side
            stripe = canvas.create_rectangle(x, y, x + 5 * zoom, y + height, width=0, tags=tags)
            icon = canvas.create_image(x + 9 * zoom, y + height / 2, anchor="w", tags=tags)
            text = canvas.create_text(x + (NODE_HEIGHT + 9) * zoom, y + height / 2, anchor="w",
                                      font=("Segoe UI", size), tags=tags,
                                      state="normal" if zoom >= TEXT_ZOOM else "hidden")
            radius = 4 * zoom
            dot = canvas.create_oval(x + (NODE_WIDTH - 11) * zoom - radius, y + height / 2 - radius,
                                     x + (NODE_WIDTH - 11) * zoom + radius, y + height / 2 + radius,
                                     outline="", tags=tags)
            self.drawn[node.key] = {"box": box, "stripe": stripe, "icon": icon, "text": text, "dot": dot}
        self.paint()

    def faded(self, node: Node, searching: bool, found: set[str]) -> bool:
        """Whether a node is not what the player is looking at: outside the filter, or not found by the search."""
        if self.filter and not fits(node, self.state, self.counts, self.filter):
            return True
        return searching and node.key not in found

    def paint(self) -> None:
        """Colours the nodes by what the run has done, the filter and the search."""
        canvas, zoom = self.canvas, self.zoom
        background = self.colour("background")
        found = set(self.found)
        searching = bool(self.search.get().strip())
        for band in self.tree.bands:
            canvas.itemconfigure(self.band_titles[band.key], text=band_text(band, self.tree, self.state),
                                 fill=self.colour("text"))
        for key, items in self.drawn.items():
            node = self.tree.nodes[key]
            now = status(node, self.state, self.counts)
            faded = self.faded(node, searching, found)
            if node.kind == "tradition" and node.item in self.state.received:
                fill, border, width, ink = self.colour("node"), self.colour("received"), 2, self.colour("text")
            elif now == "base":
                fill, border, width, ink = self.colour("base_fill"), self.colour("base_border"), 1, self.colour("dim")
            elif now == "checked":
                fill, border, width, ink = self.colour("checked_fill"), self.colour("checked"), 2, self.colour("text")
            elif now == "available":
                fill, border, width, ink = self.colour("node"), self.colour("available"), 2.5, self.colour("text")
            else:
                fill, border, width, ink = self.colour("node"), self.colour("locked"), 1, self.colour("dim")
            stripe = self.colour(held(self.state, node.location)[2]) if node.location in self.state.holds else ""
            if faded:
                fill, border, width, ink, stripe = background, self.colour("edge"), 1, self.colour("edge"), ""
            elif key in found:
                border, width = self.colour("match"), 3
            if key == self.pinned:
                border, width = self.colour("text"), 3
            canvas.itemconfigure(items["box"], fill=fill, outline=border, width=max(1, width * max(zoom, 0.6)))
            canvas.itemconfigure(items["stripe"], fill=stripe, state="normal" if stripe else "hidden")
            canvas.itemconfigure(items["text"], fill=ink, text=short(name_of(node, self.state)))
            picture = self.icons.get(icon_of(node, self.state), int((NODE_HEIGHT - 6) * zoom), fill, faded)
            canvas.itemconfigure(items["icon"], image=picture or "")
            received = node.item is not None and node.item in self.state.received and not faded
            canvas.itemconfigure(items["dot"], fill=self.colour("received"), state="normal" if received else "hidden")
        self.light(self.shown)

    def light(self, key: str | None) -> None:
        """Lights the lines of the technology that is shown."""
        self.canvas.itemconfigure("edge", fill=self.colour("edge"), width=1)
        self.canvas.itemconfigure("across", state="hidden")
        if key:
            for tag in ("from_" + key, "to_" + key):
                # Raising above "edge" fails if there is no line at all, as with every area folded away
                if self.canvas.find_withtag(tag):
                    self.canvas.itemconfigure(tag, fill=self.colour("edge_lit"), width=2, state="normal")
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
                                    "holds, and the technology itself arrives as an item. A box is called "
                                    "after what it holds once it can be researched or picked, as it is in the "
                                    "game. Spoilers at the top shows what every box holds before that.\n\nType in Find to light up what matches, and press Enter to go from one to "
                                    "the next. The tabs at the top show one part of the tree at a time, which is faster "
                                    "than Everything. Click a heading to fold its part of the tree away, and one "
                                    "of the kinds at the top to show only those.\n\nDrag to move, use the wheel to "
                                    "zoom, double click to zoom in on a technology, and press Esc to clear "
                                    "everything.", "dim")
        else:
            for text, kind in describe(self.tree.nodes[key], self.state, self.counts, self.names):
                self.info.insert("end", text, kind)
        self.info.configure(state="disabled")
        self.light(key)

    def refresh(self) -> None:
        """Takes over what the run has done since the last time."""
        if self.closed:
            return
        try:
            state = self.state_of_run()
            if not self.settings.spoilers:
                state = state.without_spoilers(open_locations(self.tree, self.technologies, state))
            if not state.same(self.state) or state.hidden != self.state.hidden:
                hidden = state.hidden
                relaid = (state.traditions, state.pool) != (self.state.traditions, self.state.pool)
                self.state = state.copy()
                self.state.hidden = hidden
                self.counts = researched(self.technologies, self.state)
                if relaid:
                    self.build_tree()
                    self.place_tabs()
                    self.colour_tabs()
                    if self.pinned not in self.tree.nodes or self.shown not in self.tree.nodes:
                        self.pinned = self.shown = None
                self.found = matches(self.tree, self.state, self.search.get())
                if relaid:
                    self.draw()
                else:
                    self.paint()
                self.show(self.shown)
            self.summary.configure(text=summary_text(self.state, self.locations))
            if self.state.goal:
                self.goal.configure(text=self.state.goal)
                self.goal.pack(fill="x", before=self.chips)
            else:
                self.goal.pack_forget()
        finally:
            # Whatever went wrong this time, the tracker keeps following the run
            self.timer = self.window.after(1000, self.refresh)

    # --- what the player does

    def tags_at(self, event) -> tuple:
        return self.canvas.gettags("current")

    def node_at(self, event) -> str | None:
        return next((tag[5:] for tag in self.tags_at(event) if tag.startswith("node_")), None)

    def press(self, event) -> None:
        self.pressed = (event.x, event.y)
        self.canvas.scan_mark(event.x, event.y)

    def drag(self, event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def release(self, event) -> None:
        """A click, if the mouse did not move: folds a band, or keeps the technology under it shown."""
        if self.pressed and abs(event.x - self.pressed[0]) + abs(event.y - self.pressed[1]) < 5:
            band = next((tag[5:] for tag in self.tags_at(event) if tag.startswith("band_")), None)
            if band:
                self.collapse(band)
            else:
                self.pin(self.node_at(event))
        self.pressed = None

    def double_click(self, event) -> None:
        key = self.node_at(event)
        if key:
            node = self.tree.nodes[key]
            self.centre((node.x + NODE_WIDTH / 2, node.y + NODE_HEIGHT / 2), max(self.zoom, 1.0))

    def hover(self, event) -> None:
        tags = self.tags_at(event)
        self.canvas.configure(cursor="hand2" if any(tag.startswith(("band_", "node_")) for tag in tags) else "")
        if self.pinned is None:
            key = self.node_at(event)
            if key != self.shown:
                self.show(key)

    def pin(self, key: str | None) -> None:
        self.pinned = key
        self.paint()
        self.show(key)

    def clear(self) -> None:
        """Esc: nothing is kept shown, searched for or filtered any more."""
        self.search.delete(0, "end")
        self.found = []
        self.found_label.configure(text="")
        self.filter = None
        self.colour_chips()
        self.pin(None)

    def set_filter(self, name: str) -> None:
        """Shows only what fits a filter. Clicking it again shows everything."""
        self.filter = None if self.filter == name else name
        self.colour_chips()
        self.paint()

    def collapse(self, band: str) -> None:
        """Folds a band away, or opens it again."""
        if band in self.settings.collapsed:
            self.settings.collapsed.remove(band)
        else:
            self.settings.collapsed.append(band)
        self.settings.save()
        self.build_tree()
        if self.pinned and self.tree.nodes[self.pinned].hidden:
            self.pinned = self.shown = None
        self.draw()
        self.show(self.shown)

    def search_changed(self, event=None) -> None:
        """Lights up what matches while the player types."""
        if event is not None and event.keysym in ("Return", "Escape"):
            return
        self.found = matches(self.tree, self.state, self.search.get())
        text = self.search.get().strip()
        self.found_label.configure(text=f"{len(self.found)} found" if text else "")
        self.paint()

    def search_next(self) -> None:
        """Enter: goes to the next match, in the tab it is in. Not to one in a part that is folded away."""
        tab = self.shown_tab()
        visible = [key for key in self.found if self.tree.nodes[key].band not in self.settings.collapsed]
        # The ones of the tab that is shown first
        visible.sort(key=lambda key: tab != EVERYTHING and self.tree.nodes[key].band != tab)
        if visible:
            key = visible[(visible.index(self.pinned) + 1) % len(visible)] if self.pinned in visible else visible[0]
            if self.tree.nodes[key].hidden:
                self.set_tab(self.tree.nodes[key].band)
            node = self.tree.nodes[key]
            self.centre((node.x + NODE_WIDTH / 2, node.y + NODE_HEIGHT / 2), max(self.zoom, 0.8))
            self.pin(key)

    def zoom_by(self, factor: float, event=None) -> None:
        """Zooms in or out, around the mouse or the middle of the window."""
        zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom * factor))
        if zoom == self.zoom:
            return
        x = event.x if event else self.canvas.winfo_width() / 2
        y = event.y if event else self.canvas.winfo_height() / 2
        self.centre((self.canvas.canvasx(x) / self.zoom, self.canvas.canvasy(y) / self.zoom), zoom, (x, y))

    def fit(self) -> None:
        """Shows the whole tree."""
        width, height = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        zoom = min(MAX_ZOOM, max(MIN_ZOOM, min(width / self.tree.width, height / self.tree.height)))
        self.centre((self.tree.width / 2, self.tree.height / 2), zoom)

    def centre(self, point: tuple[float, float], zoom: float | None = None, at: tuple[float, float] | None = None) -> None:
        """Puts a point of the tree at a place in the window (its middle if none is given)."""
        if zoom is not None and zoom != self.zoom:
            # Kept when the window closes: the wheel changes it many times a second
            self.zoom = self.settings.zoom = zoom
            self.draw()
        at = at or (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
        left, top, right, bottom = (float(value) for value in str(self.canvas.cget("scrollregion")).split())
        self.canvas.xview_moveto((point[0] * self.zoom - at[0] - left) / (right - left))
        self.canvas.yview_moveto((point[1] * self.zoom - at[1] - top) / (bottom - top))

    def close(self) -> None:
        self.closed = True
        if self.timer:
            self.window.after_cancel(self.timer)
        self.settings.save()
        self.window.destroy()
