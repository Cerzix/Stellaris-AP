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

generator = random.Random(4)
locations = data.locations()
names = [item["name"] for item in data.items()] + ["Ender Pearl", "Diamond Sword", "Elytra"]
state = tracker.TrackerState(
    checked={location["id"] for location in locations if generator.random() < 0.25},
    holds={location["id"]: (generator.choice(names), generator.choice(["Cerzix", "Steve"]),
                            generator.choice(["progression", "useful", "filler", "filler", "filler", "trap"]))
           for location in locations},
    received={item["id"] for item in data.items() if generator.random() < 0.2},
    goal="Goal: 3 of 10 Precursor Fragments")


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
view = tracker.TrackerWindow(root, lambda: state)
view.window.attributes("-topmost", True)
pump(1.0)
grab("overview.png")
view.search.insert(0, "destroyers")
view.search_next()
pump(0.6)
grab("found.png")
view.zoom_by(0.4)
view.zoom_by(0.6)
pump(0.6)
grab("far.png")
view.close()
root.destroy()
