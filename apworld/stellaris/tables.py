"""The items and locations, made from the data that is read from the game.

Shared by the Archipelago world and by the mod and client (stellaris_ap), so that both agree on every
id. It only needs the standard library.

- Every technology of the kind "item" is an item, and gives one location: a technology to research
  in its place.
- An empire adopts up to 7 tradition trees, with 7 traditions each. Those 49 picks are locations,
  told apart by the order in which the trees were adopted and the place of the tradition in its
  tree. They do not depend on which trees the player chooses, so all of them can be reached.
- The traditions of the normal trees are items, apart from the adoption and finish bonus.
- Ascension perk slots are the item "Progressive Ascension". Picking a perk is a location.
- The other items are listed in items.json.

Location ids: technologies below 1000, traditions 1001 to 1049, ascension perks from 2001.
Item ids: a technology has the id of its location, traditions from 1101, other items from 10001.
"""

TRADITION_LOCATION_BASE = 1000
# TRADITION_CATEGORIES_MAX in the game's defines
TREE_SLOTS = 7
TRADITIONS_PER_TREE = 7
PERK_ID_BASE = 2000
# ASCENSION_PERKS_SLOTS in the game's defines
ASCENSION_PERK_SLOTS = 8
PROGRESSIVE_ASCENSION = "Progressive Ascension"
# Collected to win, when that is the goal
FRAGMENT = "Precursor Fragment"
# Something good or bad happens when it arrives
RANDOM_EVENT = "Random Event"
EMPIRES = ("regular", "hive", "machine")


def normal_trees(trees: list[dict]) -> list[dict]:
    return [tree for tree in trees if tree["kind"] == "normal"]


def tradition_location(slot: int, position: int) -> int:
    """The id of the location for the tradition at a position (0 to 6) of the tree adopted as number slot (0 to 6)."""
    return TRADITION_LOCATION_BASE + slot * TRADITIONS_PER_TREE + position + 1


def build_items(technologies: list[dict], trees: list[dict], other: list[dict]) -> list[dict]:
    """{"id", "name", "kind", "effect", "count", "dlc", "empires", "tier"} for every item.

    effect: the script that grants the item, in the scope of the player's country.
    count: how many of the item a game has. 0 for an item only some goals use.
    dlc, empires: the DLCs the item needs, and the kinds of empire that can use it.
    """
    items = [{"id": technology["id"], "name": technology["name"], "kind": "technology", "count": 1,
              "effect": f"give_technology = {{ tech = {technology['key']} message = yes }}",
              "dlc": technology["dlc"], "empires": technology["empires"], "tier": technology["tier"],
              "weight": technology["weight"], "icon": technology["icon"]}
             for technology in technologies if technology["kind"] == "item"]
    for tree in normal_trees(trees):
        for tradition in tree["traditions"]:
            if "id" in tradition:
                items.append({"id": tradition["id"], "name": tradition["name"], "kind": "tradition", "count": 1,
                              "effect": f"ap_add_tradition = {{ KEY = {tradition['key']} }}",
                              "dlc": tree["dlc"], "empires": tree["empires"], "tier": None, "weight": 1})
    for item in other:
        items.append({"kind": "other", "count": 1, "dlc": [], "empires": list(EMPIRES), "tier": None, "weight": 1,
                      **item})
    return items


def build_locations(technologies: list[dict]) -> list[dict]:
    """{"id", "name", "kind"} for every location. A technology location has the "technology" it takes the place of."""
    locations = [{"id": technology["id"], "name": f"Research: {technology['name']}", "kind": "technology",
                  "technology": technology}
                 for technology in technologies if technology["kind"] == "item"]
    for slot in range(TREE_SLOTS):
        for position in range(TRADITIONS_PER_TREE):
            what = ("Adopted" if position == 0 else "Finished" if position == TRADITIONS_PER_TREE - 1
                    else f"Tradition {position}")
            locations.append({"id": tradition_location(slot, position), "name": f"Tradition Tree {slot + 1}: {what}",
                              "kind": "tradition", "slot": slot, "position": position})
    for number in range(1, ASCENSION_PERK_SLOTS + 1):
        locations.append({"id": PERK_ID_BASE + number, "name": f"Ascension Perk {number}", "kind": "perk",
                          "number": number})
    return locations


def all_dlcs(technologies: list[dict], trees: list[dict]) -> list[str]:
    return sorted({dlc for entry in technologies + trees for dlc in entry["dlc"]})


def usable(item: dict, dlcs, empire: str) -> bool:
    """Whether an item does anything for a player with these DLCs and this kind of empire."""
    return empire in item["empires"] and all(dlc in dlcs for dlc in item["dlc"])
