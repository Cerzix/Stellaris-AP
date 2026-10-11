"""Opens the tracker with a made-up run and saves pictures of it, to look at the layout.

    python tools/preview_tracker.py <folder for the pictures>
"""
import random
import sys
import time
import tkinter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import ImageGrab  # noqa: E402

from stellaris_ap import data, tracker  # noqa: E402
from stellaris_ap.settings import Settings  # noqa: E402

generator = random.Random(4)
locations = data.locations()
own = [(item["name"], item.get("icon")) for item in data.items()]
foreign = [("Ender Pearl", None), ("Diamond Sword", None), ("Elytra", None)]
state = tracker.TrackerState(
    checked={location["id"] for location in locations
             if generator.random() < (0.6 if location.get("technology", {}).get("tier", 9) <= 2 else 0.05)},
    holds={location["id"]: (*generator.choice(own + foreign * 60)[:1], generator.choice(["Cerzix", "Steve"]),
                            generator.choice(["progression", "useful", "filler", "filler", "filler"]), None)
           for location in locations},
    received={item["id"] for item in data.items() if generator.random() < 0.2},
    perk_slots=2, goal="Goal: 3 of 10 Precursor Fragments")
icons = dict(own)
state.holds = {location: (item, player, kind, icons.get(item)) for location, (item, player, kind, _) in state.holds.items()}


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)


def grab(name: str) -> None:
    window = view.window
    x, y = window.winfo_rootx(), window.winfo_rooty()
    ImageGrab.grab((x, y, x + window.winfo_width(), y + window.winfo_height())).save(Path(sys.argv[1]) / name)


root = tkinter.Tk()
root.withdraw()
view = tracker.TrackerWindow(root, lambda: state, Settings(None))
view.window.attributes("-topmost", True)
view.zoom_by(1.4)
pump(1.2)
grab("dark.png")
view.search.insert(0, "laser")
view.search_changed()
pump(0.5)
grab("search.png")
view.clear()
view.set_filter("available")
view.collapse("picks")
view.toggle_theme()
pump(0.8)
grab("light_available.png")
view.close()
root.destroy()
