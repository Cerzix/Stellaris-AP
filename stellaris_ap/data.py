"""The items and locations, for the mod and the client.

data/technologies.json and data/traditions.json are read from the game by stellaris_ap.extract,
data/items.json holds the items that are not read from the game. What is made of them is decided
in apworld/stellaris/tables.py, which the Archipelago world uses too.
"""
import importlib.util
import random
from functools import cache

from .paths import APWORLD_DIR, load_data

_spec = importlib.util.spec_from_file_location("stellaris_tables", APWORLD_DIR / "tables.py")
tables = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tables)

TREE_SLOTS = tables.TREE_SLOTS
TRADITIONS_PER_TREE = tables.TRADITIONS_PER_TREE
PERK_ID_BASE = tables.PERK_ID_BASE
ASCENSION_PERK_SLOTS = tables.ASCENSION_PERK_SLOTS
PROGRESSIVE_ASCENSION = tables.PROGRESSIVE_ASCENSION
tradition_location = tables.tradition_location


@cache
def technologies() -> list[dict]:
    return load_data("technologies")


@cache
def tradition_trees() -> list[dict]:
    return load_data("traditions")


def normal_trees() -> list[dict]:
    return tables.normal_trees(tradition_trees())


@cache
def items() -> list[dict]:
    return tables.build_items(technologies(), tradition_trees(), load_data("items"))


@cache
def locations() -> list[dict]:
    return tables.build_locations(technologies())


def dlcs() -> list[str]:
    """Every DLC a technology or tradition tree needs, in the order of the numbers the mod reports them with."""
    return tables.all_dlcs(technologies(), tradition_trees())


EMPIRES = tables.EMPIRES


def item_pool(generator: random.Random) -> list[int]:
    """The ids of the items of a game without an Archipelago server, one for every location: all technologies
    and ascension perk slots, and as many traditions as there are tradition locations, picked at random."""
    slot = next(item for item in items() if item["name"] == PROGRESSIVE_ASCENSION)
    pool = [item["id"] for item in items() if item["kind"] == "technology"]
    pool += [slot["id"]] * slot["count"]
    traditions = [item["id"] for item in items() if item["kind"] == "tradition"]
    pool += generator.sample(traditions, len(locations()) - len(pool))
    return pool
