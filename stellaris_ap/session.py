"""A run that is being played: the bridge to the game, and where its items come from.

A session has no window. It reports what happens through a function log(kind, parts), where parts
is a text or a list of (text, kind) and kind names what it is about ("item", "check", "hint",
"death", "game", "server", "chat", "error", "info", and for the parts of a message also "player",
"me", "location", "progression", "useful", "trap", "filler", "text").

tick() has to be called a few times a second, from one thread. It is the only thing that touches
the game.
"""
import queue
import time
from typing import Callable

from . import build_mod, data
from .archipelago import GAME, Connection, item_kind
from .bridge import DEATHS, GOALS, Bridge
from .mailbox import MAX_SENDERS
from .profiles import Profile, Profiles
from .tracker import TrackerState

Log = Callable[[str, object], None]

# The options of the menu in game (event ap.100), which it writes to the log as "AP_CMD <number>"
MENU_DEATH = 1
MENU_DOOM = 2
# The player's slot in a run without a server
OFFLINE_SLOT = 1

# The least time between two deaths sent to the multiworld. A lost war is one death, not twenty
DEATH_COOLDOWN_SECONDS = 60
DEATH_TEXT = {1: "{who} ruler {name} has died.", 2: "{who} leader {name} has died.",
              3: "{who} fleet {name} lost a battle.", 4: "{who} colony {name} was invaded.",
              5: "{who} colony {name} was destroyed."}


def death_text(who: str, number: int, name: str) -> str:
    return " ".join(DEATH_TEXT[number].format(who=who, name=name).split())


HELP = """/help            this list
/status          what was checked and received so far
/offline         play without a server: every technology and tradition of your own game, shuffled
/offline new     the same, with a new shuffle"""
SERVER_HELP = """!hint <item>     ask the multiworld where one of your items is. The server answers, and
                 only if you have the hint points for it: /status says how many you have
!hint_location <location>   ask what is at one of your locations
!help            what else the server understands
Anything else you type is said to the other players."""


class Session:
    def __init__(self, user_dir, log: Log, delivery: str = "memory"):
        self.user_dir = user_dir
        self.log = log
        self.delivery = delivery
        self.bridge: Bridge | None = None
        self.profile: Profile | None = None
        self.items = {item["id"]: item for item in data.items()}
        # The icon of every item that is a technology of Stellaris, by its name
        self.icons = {item["name"]: item["icon"] for item in data.items() if item["kind"] == "technology"}
        self.locations = {location["id"]: location["name"] for location in data.locations()}
        # Whether the traditions are shuffled. If not, the player has the trees of the game
        self.shuffled_traditions = True
        # Whether the names of the run are written, which the game needs at its start
        self.ready = False

    def item_id(self, name: str) -> int:
        return next(item["id"] for item in self.items.values() if item["name"] == name)

    def start_bridge(self, deaths_per_doom: int = 3, doom: str = "cracked", death_effect: str = "random",
                     doom_capital: bool = False) -> None:
        self.bridge = Bridge(self.user_dir, self.on_check, delivery=self.delivery, deaths_per_doom=deaths_per_doom,
                             doom=doom, death_effect=death_effect, doom_capital=doom_capital,
                             on_command=self.on_menu, run=self.profile.run, on_death=self.on_game_death,
                             say=lambda text: self.log("game", text))

    def tick(self) -> None:
        if self.bridge:
            self.bridge.tick()

    def stop(self) -> None:
        # No client, no run: a game that is started now belongs to none
        build_mod.write_session()

    def start_items(self) -> list[dict]:
        """Every item received so far, in order."""
        return []

    def write_start(self) -> None:
        """Writes what a new game of the run starts with: the run, its unlocks so far, and the checks done."""
        if self.profile:
            build_mod.write_session(self.profile.run, self.start_items(), self.profile.checked,
                                    vanilla_traditions=not self.shuffled_traditions)

    def on_check(self, location: int) -> None:
        raise NotImplementedError

    def on_game_death(self, number: int, name: str) -> None:
        """Someone or something died in the player's empire."""
        self.log("death", death_text("Your", number, name))

    def on_menu(self, number: int) -> None:
        if number == MENU_DEATH:
            self.bridge.receive_death()
        elif number == MENU_DOOM:
            self.bridge.send_doom()

    def status(self) -> str:
        return ""

    def tracker_state(self) -> TrackerState:
        """What the tracker shows of the run."""
        return TrackerState(checked=set(self.profile.checked) if self.profile else set(),
                            traditions=self.shuffled_traditions)

    def resync(self) -> None:
        """Reads everything again, for the player who thinks something is missing."""

    def command(self, text: str) -> None:
        """Something the player typed."""
        verb = text.split()[0].lower() if text.split() else ""
        if verb == "/help":
            self.log("info", HELP)
        elif verb == "/status":
            self.log("info", self.status())
        elif verb:
            self.log("error", f"{verb} is not a command here, see /help")


class OfflineSession(Session):
    """A randomizer of the client's own: every technology and tradition on the location of another one."""

    def __init__(self, user_dir, log: Log, profile: Profile, shuffle, delivery: str = "memory",
                 deaths_per_doom: int = 3, doom: str = "cracked"):
        super().__init__(user_dir, log, delivery)
        self.profile = profile
        self.placement = shuffle(profile.seed)
        build_mod.write_check_names(
            {location: (self.items[item]["name"], "you") for location, item in self.placement.items()},
            players={OFFLINE_SLOT: "you"})
        self.write_start()
        self.ready = True
        profile.played()
        self.log("info", f"{profile.name}: {len(profile.checked)} of {len(self.locations)} locations checked.")
        self.log("info", "Start Stellaris now. If it is already running, restart it to see the right names.")
        self.start_bridge(deaths_per_doom, doom)
        self.bridge.set_items(self.sent_items())

    def sent_items(self) -> list[dict]:
        return [{**self.items[item], "sender": sender} for item, sender in self.profile.sent]

    start_items = sent_items

    def on_check(self, location: int) -> None:
        item = self.profile.check(location, self.placement, OFFLINE_SLOT)
        if item is not None:
            self.log("check", [("Checked ", "text"), (self.locations[location], "location"), (": found ", "text"),
                               (self.items[item]["name"], "useful")])
            self.bridge.set_items(self.sent_items())
            self.write_start()

    def status(self) -> str:
        return f"{len(self.profile.checked)} of {len(self.locations)} locations, {len(self.profile.sent)} items"

    def tracker_state(self) -> TrackerState:
        return TrackerState(
            checked=set(self.profile.checked), traditions=self.shuffled_traditions,
            holds={location: (self.items[item]["name"], "you", "filler", self.items[item].get("icon"))
                   for location, item in self.placement.items()},
            received={item for item, _ in self.profile.sent},
            perk_slots=sum(self.items[item]["name"] == data.PROGRESSIVE_ASCENSION for item, _ in self.profile.sent))



class ServerSession(Session):
    """A slot of an Archipelago multiworld."""

    def __init__(self, user_dir, log: Log, store: Profiles, address: str, slot_name: str, password: str = "",
                 delivery: str = "memory", connect=Connection):
        super().__init__(user_dir, log, delivery)
        self.store = store
        self.address = address
        self.slot_name = slot_name
        self.events: queue.Queue = queue.Queue()
        self.slot_data: dict = {}
        self.received: list[dict] = []
        self.scouted: dict = {}
        self.announced = 0
        self.won = False
        self.warned = False
        self.connected = False
        # The hint points of the slot and what a hint costs, as the server tells them. None until it has
        self.hints: tuple[int, int] | None = None
        self.last_death_sent = float("-inf")
        self.clock = time.monotonic
        self.connection = connect(address, slot_name, password, lambda *event: self.events.put(event))
        self.log("server", f"Connecting to {address} as {slot_name}...")
        self.connection.start()

    def stop(self) -> None:
        self.connection.stop()
        super().stop()

    def start_items(self) -> list[dict]:
        return [self.items[entry["item"]] for entry in self.received if entry["item"] in self.items]

    def tick(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            getattr(self, "on_" + event[0])(*event[1:])
        super().tick()
        self.compare_with_game()
        if self.bridge and self.bridge.goals:
            self.check_goal()

    # --- what the server reports

    def on_connected(self, info: dict) -> None:
        profile = self.store.server(info["seed"], info["slot"], self.address, self.slot_name)
        if self.profile is not None and profile.run != self.profile.run:
            # The address now hosts another multiworld. The bridge belongs to the run it was made for: going on
            # would feed the checks of that run's saves into this one
            self.connected = False
            self.connection.stop()
            self.log("error", "The server now hosts another multiworld. Press Connect to play that one.")
            return
        self.connected = True
        self.slot = info["slot"]
        self.players = info["players"]
        self.slot_data = info["slot_data"]
        self.profile = profile
        # A multiworld made before this was an option has them shuffled
        self.shuffled_traditions = bool(self.slot_data.get("randomize_traditions", True))
        if not self.shuffled_traditions:
            self.locations = {location["id"]: location["name"] for location in data.locations()
                              if location["kind"] != "tradition"}
        self.log("server", f"Connected. {len(self.players)} player(s) in the multiworld.")
        if self.slot_data.get("death_link") and not self.connection.death_link:
            self.connection.death_link = True
            self.connection.send({"cmd": "ConnectUpdate", "tags": ["DeathLink"]})
        # What was checked while there was no connection
        known = set(info["checked"])
        missing = [location for location in self.profile.checked if location not in known]
        if missing:
            self.connection.check(missing)
        self.profile.state["checked"] = sorted(known | set(self.profile.checked))
        self.store.save()
        if self.bridge is None:
            # Also without DeathLink: the menu in game has a test for a death
            self.start_bridge(self.slot_data.get("deaths_per_doom", 3), self.slot_data.get("doom", "cracked"),
                              self.slot_data.get("death_effect", "random"), bool(self.slot_data.get("doom_capital")))
            self.bridge.checked |= set(self.profile.checked)
        self.connection.scout(list(self.locations))

    def on_hints(self, points: int, cost: int) -> None:
        self.hints = (points, cost)

    def resync(self) -> None:
        if self.connected:
            self.connection.sync()
            self.connection.scout(list(self.locations))
            self.log("server", "Asked the server for everything again.")

    def on_refused(self, errors: list[str]) -> None:
        reasons = {"InvalidSlot": "there is no slot with that name", "InvalidGame": "that slot is not a Stellaris slot",
                   "InvalidPassword": "the password is wrong", "IncompatibleVersion": "the server is too old or too new",
                   "InvalidItemsHandling": "the server does not accept this client"}
        self.log("error", "The server refused: " + ", ".join(reasons.get(error, error) for error in errors))

    def on_disconnected(self, reason: str) -> None:
        if self.connected or reason != "refused":
            self.log("error" if reason != "refused" else "server", f"Not connected ({reason}).")
        self.connected = False

    def on_scouted(self, found: dict) -> None:
        self.scouted = found
        build_mod.write_check_names({location: (entry["item"], entry["player"]) for location, entry in found.items()},
                                    players={slot: name for slot, name in self.players.items() if slot <= MAX_SENDERS})
        self.write_start()
        if not self.ready:
            self.ready = True
            self.log("info", "The technologies and traditions are named after what they send. "
                             "Start Stellaris now. If it is already running, restart it to see the names.")

    def on_items(self, received: list[dict]) -> None:
        self.received = received
        usable = [entry for entry in received if entry["item"] in self.items]
        if self.bridge:
            self.bridge.set_items([{**self.items[entry["item"]], "sender": max(entry["player"], 0)}
                                   for entry in usable])
        if self.announced == 0 and len(received) > 1:
            self.log("item", f"{len(received)} items received so far.")
        else:
            for entry in received[self.announced:]:
                name = self.items.get(entry["item"], {}).get("name", f"Item {entry['item']}")
                self.log("item", [("Received ", "text"), (name, item_kind(entry.get("flags", 0))),
                                  (" from ", "text"), (self.connection.names.player(entry["player"]), "player")])
        self.announced = len(received)
        self.write_start()
        self.check_goal()

    def on_print(self, parts: list[tuple[str, str]], kind: str) -> None:
        self.log({"Hint": "hint", "ItemSend": "item", "ItemCheat": "item", "Chat": "chat", "ServerChat": "chat",
                  "Goal": "info", "Countdown": "info"}.get(kind, "server"), parts)

    def on_death(self, death: dict) -> None:
        cause = death["cause"] or f"{death['source']} died"
        self.log("death", f"DeathLink: {cause}")
        if self.bridge:
            self.bridge.receive_death()

    # --- what the game reports

    def on_check(self, location: int) -> None:
        if location not in self.profile.checked:
            self.profile.checked.append(location)
            self.store.save()
        self.connection.check([location])
        self.write_start()
        self.log("check", [("Checked ", "text"), (self.locations.get(location, f"Location {location}"), "location")])
        self.check_goal()

    def on_game_death(self, number: int, name: str) -> None:
        """A death in the player's empire is a death for everyone with DeathLink, if its kind is one that counts."""
        super().on_game_death(number, name)
        # A multiworld made before battles counted calls them "fleet"
        causes = ["battle" if cause == "fleet" else cause for cause in self.slot_data.get("death_causes", [])]
        if not self.slot_data.get("death_link") or DEATHS[number] not in causes:
            return
        # Not later, if there is no connection right now: see Connection.die
        if not self.connected or self.clock() - self.last_death_sent < DEATH_COOLDOWN_SECONDS:
            return
        self.last_death_sent = self.clock()
        self.connection.die(death_text(f"{self.slot_name}'s", number, name))
        self.log("death", "DeathLink: sent to the multiworld.")

    def count_received(self, name: str) -> int:
        """How many of an item of the own game were received."""
        number = self.item_id(name)
        return sum(entry["item"] == number for entry in self.received)

    def check_goal(self) -> None:
        if self.won or not self.slot_data or self.profile is None:
            return
        goal = self.slot_data.get("goal")
        if goal == "locations":
            done = len(self.profile.checked) >= self.slot_data.get("locations_required", 1)
        elif goal in GOALS.values():
            # Something in the galaxy, which the game reports
            done = bool(self.bridge) and goal in self.bridge.goals
        else:
            done = self.count_received(data.tables.FRAGMENT) >= self.slot_data.get("fragments_required", 1)
        if done:
            self.won = True
            self.connection.goal()
            self.log("info", "Goal reached! You have won your part of the multiworld.")

    def compare_with_game(self) -> None:
        """Warns once if the game that is running is not the one the multiworld was made for."""
        if self.warned or not self.bridge or self.bridge.game_empire is None or not self.slot_data:
            return
        self.warned = True
        empire = self.slot_data.get("empire_type")
        if empire and empire != self.bridge.game_empire:
            self.log("error", f"The multiworld was made for a {empire} empire, but you play a "
                              f"{self.bridge.game_empire} one. Some of your items will do nothing.")
        active = {dlc for number, dlc in enumerate(data.dlcs(), 1) if number in self.bridge.game_dlcs}
        missing = sorted(set(self.slot_data.get("owned_dlc", [])) - active)
        if missing:
            self.log("error", "The multiworld was made with DLC that is not active in your game: "
                              + ", ".join(missing) + ". Items of it will do nothing.")

    def tracker_state(self) -> TrackerState:
        state = super().tracker_state()
        state.holds = {location: (entry["item"], entry["player"], item_kind(entry["flags"]),
                                  self.icons.get(entry["item"]) if entry.get("game") == GAME else None)
                       for location, entry in self.scouted.items()}
        state.received = {entry["item"] for entry in self.received}
        state.perk_slots = self.count_received(data.PROGRESSIVE_ASCENSION)
        goal = self.slot_data.get("goal")
        if goal == "fragments":
            found = self.count_received(data.tables.FRAGMENT)
            state.goal = f"Goal: {found} of {self.slot_data.get('fragments_required', 0)} Precursor Fragments"
        elif goal == "locations":
            state.goal = f"Goal: {len(state.checked)} of {self.slot_data.get('locations_required', 0)} locations"
        elif goal == "crisis":
            state.goal = "Goal: defeat the endgame crisis"
        elif goal == "crisis_and_fallen_empires":
            state.goal = "Goal: defeat the endgame crisis, with no awakened fallen empire left"
        if self.won:
            state.goal += " (reached)"
        return state

    def status(self) -> str:
        if self.profile is None:
            return "Not connected yet."
        text = (f"{len(self.profile.checked)} of {len(self.locations)} locations checked, "
                f"{len(self.received)} items received")
        if self.hints:
            points, cost = self.hints
            text += f", {points} hint points" + (f" (a hint costs {cost})" if cost else " (hints are free)")
        return text

    def command(self, text: str) -> None:
        if text.startswith("/"):
            if text.split()[0].lower() == "/help":
                self.log("info", HELP + "\n" + SERVER_HELP)
            else:
                super().command(text)
        elif text.strip():
            self.connection.say(text.strip())
