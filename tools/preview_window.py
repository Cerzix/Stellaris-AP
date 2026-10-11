"""Opens the client window with a few sample lines and saves a picture of it, to look at the layout.

    python tools/preview_window.py <picture.png>
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import ImageGrab  # noqa: E402

from stellaris_ap import app  # noqa: E402
from stellaris_ap.profiles import Profiles  # noqa: E402

with tempfile.TemporaryDirectory() as folder:
    user_dir = Path(folder)
    (user_dir / "logs").mkdir()
    store = Profiles(user_dir / "profiles.json")
    store.server("SEED", 1, "archipelago.gg:38281", "Cerzix")
    window = app.App(store, user_dir, log_file=None, delivery="manual")
    window.log("server", "Connecting to archipelago.gg:38281 as Cerzix...")
    window.log("server", "Connected. 4 player(s) in the multiworld.")
    window.log("game", "Stellaris: game loaded")
    window.log("check", [("Checked ", "text"), ("Research: Blue Lasers", "location")])
    window.log("item", [("Cerzix", "me"), (" sent ", "text"), ("Ender Dragon Shard", "progression"), (" to ", "text"),
                        ("Steve", "player"), (" (", "text"), ("Research: Blue Lasers", "location"), (")", "text")])
    window.log("item", [("Received ", "text"), ("Destroyers", "useful"), (" from ", "text"), ("Steve", "player")])
    window.log("hint", [("[Hint]: ", "text"), ("Cerzix", "me"), ("'s ", "text"), ("Progressive Ascension", "progression"),
                        (" is at ", "text"), ("Kill the Ender Dragon", "location"), (" in ", "text"),
                        ("Steve", "player"), ("'s World", "text")])
    window.log("death", "DeathLink: Steve fell into lava")
    window.log("error", "Not connected (the server closed the connection).")
    window.log("chat", [("> ", "text"), ("!hint Battleships", "me")])
    window.window.attributes("-topmost", True)
    deadline = time.monotonic() + 1.2
    while time.monotonic() < deadline:
        window.window.update()
        time.sleep(0.03)
    x, y = window.window.winfo_rootx(), window.window.winfo_rooty()
    ImageGrab.grab((x, y, x + window.window.winfo_width(), y + window.window.winfo_height())).save(sys.argv[1])
    window.close()
