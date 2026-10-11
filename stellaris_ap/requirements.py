"""Works out who can use a technology or tradition tree, from the trigger that makes it available.

Two things are read from a trigger:
- the DLCs it needs (host_has_dlc), also through the game's scripted triggers such as has_paragon_dlc;
- the kinds of empire it is not closed to: regular, hive mind or machine intelligence.

A trigger is true, false or unknown. Everything this file does not know about is unknown, and only
what is certainly false closes a technology to a kind of empire.
"""
from . import pdx

EMPIRES = ("regular", "hive", "machine")
AUTHORITY = {"auth_hive_mind": "hive", "auth_machine_intelligence": "machine"}
# A scripted trigger can use others, but not without end
MAX_DEPTH = 8


def scripted_triggers(game_dir) -> dict[str, list]:
    triggers = {}
    for path in sorted((game_dir / "common" / "scripted_triggers").glob("*.txt")):
        triggers.update((key, value) for key, _, value in pdx.parse_file(path) if isinstance(value, list))
    return triggers


def negate(value: bool | None) -> bool | None:
    return None if value is None else not value


def all_of(values: list) -> bool | None:
    if False in values:
        return False
    return None if None in values else True


def any_of(values: list) -> bool | None:
    if True in values:
        return True
    return None if None in values else False


class Requirements:
    def __init__(self, game_dir):
        self.triggers = scripted_triggers(game_dir)

    def holds(self, block: list, empire: str, depth: int = 0) -> bool | None:
        """Whether the trigger is true for a kind of empire."""
        return all_of([self.entry_holds(entry, empire, depth) for entry in block])

    def entry_holds(self, entry, empire: str, depth: int) -> bool | None:
        key, _, value = entry
        if isinstance(value, list):
            if key in ("AND", "hidden_trigger"):
                return self.holds(value, empire, depth)
            if key == "OR":
                return any_of([self.entry_holds(inner, empire, depth) for inner in value])
            if key in ("NOT", "NOR"):
                return negate(any_of([self.entry_holds(inner, empire, depth) for inner in value]))
            if key == "NAND":
                return negate(self.holds(value, empire, depth))
            return None
        value = value.strip('"') if value else value
        if key == "has_authority":
            return AUTHORITY.get(value, "regular") == empire
        if key == "has_ethic" and value == "ethic_gestalt_consciousness":
            return empire != "regular"
        if key in self.triggers and value in ("yes", "no") and depth < MAX_DEPTH:
            result = self.holds(self.triggers[key], empire, depth + 1)
            return result if value == "yes" else negate(result)
        return None

    def empires(self, block: list) -> list[str]:
        """The kinds of empire a trigger is not certainly false for."""
        return [empire for empire in EMPIRES if self.holds(block, empire) is not False]

    def dlcs(self, block: list, depth: int = 0) -> list[str]:
        """The DLCs a trigger certainly needs: the ones it asks for outright, not as one of several ways."""
        found = []
        for key, _, value in block:
            if key == "host_has_dlc":
                found.append(value.strip('"'))
            elif isinstance(value, list):
                if key in ("AND", "hidden_trigger"):
                    found += self.dlcs(value, depth)
                elif key == "OR" and len(value) == 1:
                    found += self.dlcs(value, depth)
            elif key in self.triggers and value == "yes" and depth < MAX_DEPTH:
                found += self.dlcs(self.triggers[key], depth + 1)
        return sorted(set(found))
