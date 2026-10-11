import ctypes
import json
import os
import re
import winreg
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
# The Archipelago world, packed into stellaris.apworld by stellaris_ap.build_apworld
APWORLD_DIR = REPO / "apworld" / "stellaris"
MOD_DIR = REPO / "mod" / "archipelago"
# Optional second mod, moves the console off screen so that delivering items is invisible
HIDDEN_CONSOLE_MOD_DIR = REPO / "mod" / "archipelago_hidden_console"

# Name of the file the client writes into the Stellaris user directory,
# executed in game with the console command "run ap.txt"
RUN_FILE_NAME = "ap.txt"


WRITE_BLOCKED_HINT = """Could not write to {path}
If Windows "Controlled folder access" is on, it blocks Python from writing to Documents:
Windows Security > Virus & threat protection > Ransomware protection >
Allow an app through Controlled folder access > add {python}"""


def stellaris_user_dir(override: str | None = None) -> Path:
    """Documents/Paradox Interactive/Stellaris (the Documents folder may be redirected, e.g. to OneDrive)."""
    if override:
        return Path(override)
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # 5 = CSIDL_PERSONAL
    return Path(buf.value) / "Paradox Interactive" / "Stellaris"


def stellaris_game_dir(override: str | None = None) -> Path | None:
    """The Stellaris install directory, found through the Steam libraries. None if not installed."""
    override = override or os.environ.get("STELLARIS_GAME_DIR")
    if override:
        return Path(override)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
        libraries = re.findall(r'"path"\s+"([^"]+)"',
                               (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8"))
    except OSError:
        return None
    for library in libraries:
        game = Path(library.replace("\\\\", "\\")) / "steamapps" / "common" / "Stellaris"
        if (game / "common").is_dir():
            return game
    return None


def load_data(name: str) -> list[dict]:
    with open(DATA_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)
