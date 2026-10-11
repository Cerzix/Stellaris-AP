"""Packs the Archipelago world into stellaris.apworld.

    python -m stellaris_ap.build_apworld            pack it
    python -m stellaris_ap.build_apworld --install  also copy it into the custom_worlds folder of Archipelago

The world carries a copy of the data files, so run this after stellaris_ap.extract.
"""
import argparse
import shutil
import sys
import zipfile
from pathlib import Path

from .paths import APWORLD_DIR, DATA_DIR, REPO

APWORLD = REPO / "stellaris.apworld"
DATA_FILES = ("technologies.json", "traditions.json", "items.json")
ARCHIPELAGO_DIR = Path(r"C:\ProgramData\Archipelago")


def build() -> Path:
    (APWORLD_DIR / "data").mkdir(exist_ok=True)
    for name in DATA_FILES:
        shutil.copyfile(DATA_DIR / name, APWORLD_DIR / "data" / name)
    with zipfile.ZipFile(APWORLD, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(APWORLD_DIR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                # The folder in the archive is the name of the world's package
                archive.write(path, Path(APWORLD_DIR.name) / path.relative_to(APWORLD_DIR))
    print(f"Packed {APWORLD}")
    return APWORLD


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--install", action="store_true", help="copy the world into Archipelago's custom_worlds")
    parser.add_argument("--archipelago-dir", default=str(ARCHIPELAGO_DIR), help="where Archipelago is installed")
    args = parser.parse_args()
    apworld = build()
    if args.install:
        target = Path(args.archipelago_dir) / "custom_worlds"
        if not target.is_dir():
            sys.exit(f"Archipelago's custom_worlds folder not found: {target}")
        shutil.copyfile(apworld, target / apworld.name)
        print(f"Installed into {target}")


if __name__ == "__main__":
    main()
