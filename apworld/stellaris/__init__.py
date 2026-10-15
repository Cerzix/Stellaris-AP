from typing import Any

from BaseClasses import Item, ItemClassification, Location, LocationProgressType, Region
from worlds.AutoWorld import WebWorld, World

from . import content, tables
from .options import OPTION_GROUPS, Goal, StellarisOptions


class StellarisWeb(WebWorld):
    option_groups = OPTION_GROUPS

# Technologies of these tiers, tradition trees from this number and ascension perks from this number are
# the late game, see the option Early Progression
LATE_TIER = 4
LATE_TREE = 4
LATE_PERK = 5


class StellarisItem(Item):
    game = "Stellaris"


class StellarisLocation(Location):
    game = "Stellaris"


def is_late(location: dict) -> bool:
    if location["kind"] == "technology":
        return location["technology"]["tier"] >= LATE_TIER
    if location["kind"] == "tradition":
        return location["slot"] >= LATE_TREE
    return location["number"] >= LATE_PERK


class StellarisWorld(World):
    """Stellaris is a grand strategy game in space. Every technology, the traditions and the ascension perk
    slots are shuffled into the multiworld, and found by researching and adopting what took their place."""
    game = "Stellaris"
    topology_present = False
    web = StellarisWeb()

    options_dataclass = StellarisOptions
    options: StellarisOptions

    item_name_to_id = content.ITEM_NAME_TO_ID
    location_name_to_id = content.LOCATION_NAME_TO_ID

    def locations(self) -> list[dict]:
        """The locations of this player: without the traditions if they are not shuffled."""
        return [location for location in content.LOCATIONS
                if self.options.randomize_traditions or location["kind"] != "tradition"]

    def generate_early(self) -> None:
        self.fragments = 0
        self.fragments_required = 0
        if self.options.goal == Goal.option_fragments:
            self.fragments = self.options.fragment_count.value
            self.fragments_required = min(self.options.fragments_required.value, self.fragments)
        self.locations_required = max(1, len(self.locations()) * self.options.locations_required.value // 100)

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)
        for entry in self.locations():
            location = StellarisLocation(self.player, entry["name"], entry["id"], menu)
            if self.options.early_progression and is_late(entry):
                location.progress_type = LocationProgressType.EXCLUDED
            menu.locations.append(location)

    def create_item(self, name: str) -> StellarisItem:
        item = content.ITEMS_BY_NAME[name]
        if name in (tables.PROGRESSIVE_ASCENSION, tables.FRAGMENT):
            classification = ItemClassification.progression
        elif item["kind"] == "technology" and item["tier"] <= 2:
            classification = ItemClassification.useful
        else:
            classification = ItemClassification.filler
        return StellarisItem(name, classification, item["id"], self.player)

    def create_items(self) -> None:
        """One item for every location: everything the player can use, as far as there is room."""
        room = len(self.locations())
        dlcs = self.options.owned_dlc.value
        empire = self.options.empire_type.current_key
        usable = [item for item in content.ITEMS if tables.usable(item, dlcs, empire)]

        # What has to be there comes first: the slots, the goal, every tradition (the trees of the game are
        # gone, so one that is left out can not be had at all) and every technology that is researched
        names = [tables.PROGRESSIVE_ASCENSION] * tables.ASCENSION_PERK_SLOTS + [tables.FRAGMENT] * self.fragments
        if self.options.randomize_traditions:
            names += [item["name"] for item in usable if item["kind"] == "tradition"]
        # For the tracker, which lists the traditions that can be found
        self.tradition_items = sorted(item["id"] for item in usable if item["kind"] == "tradition"
                                      and self.options.randomize_traditions)
        technologies = [item["name"] for item in usable if item["kind"] == "technology"]
        names += [name for name in technologies if content.ITEMS_BY_NAME[name]["weight"] != 0]
        # Then the Random Events, and the technologies the game only hands out through events, which it
        # still does: as far as there is room
        names += [tables.RANDOM_EVENT] * self.options.random_events.value
        rare = [name for name in technologies if content.ITEMS_BY_NAME[name]["weight"] == 0]
        self.random.shuffle(rare)
        names = (names + rare)[:room]
        while len(names) < room:
            names.append(self.get_filler_item_name())

        items = [self.create_item(name) for name in names]
        # A location that is kept free of progression takes a filler item, of which there have to be enough
        excluded = sum(location.progress_type == LocationProgressType.EXCLUDED
                       for location in self.multiworld.get_locations(self.player))
        filler = sum(item.classification == ItemClassification.filler for item in items)
        for item in items:
            if filler >= excluded:
                break
            if item.classification == ItemClassification.useful:
                item.classification = ItemClassification.filler
                filler += 1
        self.multiworld.itempool += items

    def set_rules(self) -> None:
        player = self.player
        for entry in self.locations():
            if entry["kind"] == "perk":
                # An ascension perk needs a slot
                self.multiworld.get_location(entry["name"], player).access_rule = \
                    lambda state, number=entry["number"]: state.has(tables.PROGRESSIVE_ASCENSION, player, number)
        if self.options.goal == Goal.option_fragments:
            self.multiworld.completion_condition[player] = \
                lambda state: state.has(tables.FRAGMENT, player, self.fragments_required)
        else:
            self.multiworld.completion_condition[player] = lambda state: True

    def get_filler_item_name(self) -> str:
        return self.random.choice(content.FILLER)

    def fill_slot_data(self) -> dict[str, Any]:
        return {
            "goal": self.options.goal.current_key,
            "fragments_required": self.fragments_required,
            "locations_required": self.locations_required,
            "owned_dlc": sorted(self.options.owned_dlc.value),
            "empire_type": self.options.empire_type.current_key,
            "randomize_traditions": bool(self.options.randomize_traditions),
            "tradition_items": self.tradition_items,
            "death_link": bool(self.options.death_link),
            "death_causes": [cause for cause, option in (
                ("ruler", self.options.death_on_ruler), ("leader", self.options.death_on_leader),
                ("colony", self.options.death_on_colony), ("battle", self.options.death_on_battle)) if option],
            "death_effect": {"leader_or_fleet": "random"}.get(self.options.death_effect.current_key,
                                                              self.options.death_effect.current_key),
            "deaths_per_doom": self.options.deaths_per_doom.value,
            "doom": self.options.doom.current_key,
            "doom_capital": bool(self.options.doom_capital),
        }
