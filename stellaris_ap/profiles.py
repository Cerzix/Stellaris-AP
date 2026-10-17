"""The runs the player has: what the launcher lists, and what a save belongs to.

A run is one randomized game: so far a shuffle of the client's own, later also a slot of an
Archipelago multiworld. It has a number, which the mod stores in the saves started under it.
"""
import json
import random
import time
from pathlib import Path

from .mailbox import MAX_RUN
from .paths import REPO

PROFILES_FILE = REPO / "profiles.json"


class Profile:
    def __init__(self, store: "Profiles", state: dict):
        self.store = store
        self.state = state

    @property
    def run(self) -> int:
        """The number saves of this run carry."""
        return self.state["run"]

    @property
    def name(self) -> str:
        return self.state["name"]

    @property
    def seed(self) -> int:
        return self.state["seed"]

    @property
    def sent(self) -> list[list[int]]:
        """[item id, slot of the sender] of every item sent to the game so far, in order."""
        return self.state["sent"]

    @property
    def checked(self) -> list[int]:
        return self.state["checked"]

    @property
    def picks(self) -> dict:
        """What the saves of the run picked, which a new save picks again: {"trees": {number: tree key},
        "perks": [ascension perk keys]}. The first save to pick a tree as a number, or a perk, decides."""
        return self.state.setdefault("picks", {"trees": {}, "perks": []})

    def pick_tree(self, number: int, key: str) -> bool:
        """Whether that is new."""
        if str(number) in self.picks["trees"]:
            return False
        self.picks["trees"][str(number)] = key
        self.store.save()
        return True

    def pick_perk(self, key: str) -> bool:
        """Whether that is new."""
        if key in self.picks["perks"]:
            return False
        self.picks["perks"].append(key)
        self.store.save()
        return True

    def check(self, location: int, placement: dict[int, int], slot: int) -> int | None:
        """The id of the item found at the location, the first time it is checked."""
        if location in self.checked or location not in placement:
            return None
        self.checked.append(location)
        self.sent.append([placement[location], slot])
        self.store.save()
        return placement[location]

    def send(self, item: int) -> None:
        self.sent.append([item, 0])
        self.store.save()

    def played(self) -> None:
        self.state["played"] = time.time()
        self.store.save()


class Profiles:
    def __init__(self, path: Path = PROFILES_FILE):
        self.path = path
        self.states: list[dict] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def save(self) -> None:
        self.path.write_text(json.dumps(self.states, indent="\t"), encoding="utf-8")

    def all(self) -> list[Profile]:
        """Every run, the one played last first."""
        return [Profile(self, state) for state in sorted(self.states, key=lambda state: -state["played"])]

    def get(self, run: int) -> Profile | None:
        return next((profile for profile in self.all() if profile.run == run), None)

    def free_run(self) -> int:
        taken = {state["run"] for state in self.states}
        return random.choice([number for number in range(1, MAX_RUN + 1) if number not in taken])

    def new_offline(self) -> Profile:
        number = 1 + sum(state["kind"] == "offline" for state in self.states)
        state = {"run": self.free_run(), "kind": "offline", "name": f"Offline shuffle {number}",
                 "seed": random.randrange(2 ** 31), "sent": [], "checked": [], "played": time.time()}
        self.states.append(state)
        self.save()
        return Profile(self, state)

    def server(self, seed_name: str, slot: int, address: str, slot_name: str) -> Profile:
        """The run of a slot of an Archipelago multiworld. The same multiworld and slot is always the same run,
        whatever address it is reached at."""
        state = next((state for state in self.states if state["kind"] == "server"
                      and (state["seed_name"], state["slot"]) == (seed_name, slot)), None)
        if state is None:
            state = {"run": self.free_run(), "kind": "server", "seed_name": seed_name, "slot": slot,
                     "sent": [], "checked": []}
            self.states.append(state)
        state.update(name=f"{slot_name} at {address}", address=address, slot_name=slot_name, played=time.time())
        self.save()
        return Profile(self, state)

    def recent_servers(self) -> list[tuple[str, str]]:
        """(address, slot name) of the multiworlds played, the last one first."""
        return [(profile.state["address"], profile.state["slot_name"]) for profile in self.all()
                if profile.state["kind"] == "server"]

    def delete(self, run: int) -> None:
        self.states = [state for state in self.states if state["run"] != run]
        self.save()
