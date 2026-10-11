"""The items and locations of the world, loaded from the data files packed with it."""
import json
import pkgutil

from . import tables


def load(name: str) -> list[dict]:
    return json.loads(pkgutil.get_data(__package__, f"data/{name}.json").decode("utf-8"))


TECHNOLOGIES = load("technologies")
TREES = load("traditions")
ITEMS = tables.build_items(TECHNOLOGIES, TREES, load("items"))
LOCATIONS = tables.build_locations(TECHNOLOGIES)
DLCS = tables.all_dlcs(TECHNOLOGIES, TREES)

ITEMS_BY_NAME = {item["name"]: item for item in ITEMS}
ITEM_NAME_TO_ID = {item["name"]: item["id"] for item in ITEMS}
LOCATION_NAME_TO_ID = {location["name"]: location["id"] for location in LOCATIONS}
# What a location that needs an item is filled up with
FILLER = [item["name"] for item in ITEMS if item["kind"] == "other" and item["count"] == 0
          and item["name"] not in (tables.FRAGMENT, tables.RANDOM_EVENT)]
