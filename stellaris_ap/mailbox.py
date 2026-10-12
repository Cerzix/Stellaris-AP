"""Delivers items to the game through the script variable ap_mailbox, see ap_poll_mailbox in the mod.

The mod looks into the mailbox once a day:
- a positive value is an item, which it grants, or a signal, which it carries out: a doom, the
  message about a death in the multiworld, or the run the save belongs to from now on.
  An item is its id + 100000 * the slot of the player who sent it, for the message in game;
- afterwards it stores -(2 * (items applied + 1) + parity + 1000000 * (signals carried out modulo
  1000) + 1000000000 * run) in it, with a parity that flips every day.

A save belongs to one run: an Archipelago multiworld, or a shuffle of the client. A new game takes
the run of the client that is running, and keeps it. Nothing is sent to or taken from a save of
another run.

The game's memory holds several copies of the variable (script constants, old saves). The one
in use is the one whose value keeps changing, so nothing is written before a change was seen.
"""
import time
from typing import Callable

from .memory import GameMemory

VARIABLE = "ap_mailbox"

ATTACH_SECONDS = 5
SCAN_SECONDS = 30
PAUSED_HINT_SECONDS = 15

# What a DeathLink doom does to a random colony. Above every item id.
DOOM_CODES = {"cracked": 20001, "tomb": 20002}
# Added to the code of a doom that may also strike the capital
DOOM_CAPITAL = 10
# The message that the save belongs to another run
WRONG_RUN = 20003
# A death that is not a doom: this + 10000 * what it takes from the player (DEATH_EFFECTS) + 100 * deaths so
# far + deaths for a doom (0 if there is none)
DEATH_NOTICE = 50000
DEATH_EFFECTS = {"none": 0, "leader": 1, "fleet": 2}
# The run a new save belongs to: this + the number of the run
BIND_RUN = 40000
MAX_RUN = 9999
# Above every item id and signal
SENDER_FACTOR = 100000
SIGNAL_FACTOR = 1000000
SIGNAL_MODULO = 1000
RUN_FACTOR = 1000000000
# Players of a multiworld whose names can be shown in game
MAX_SENDERS = 250


def death_notice(deaths: int, deaths_per_doom: int, effect: str = "none") -> int:
    return DEATH_NOTICE + 10000 * DEATH_EFFECTS[effect] + 100 * min(deaths, 99) + min(deaths_per_doom, 99)


def doom_code(kind: str, capital: bool = False) -> int:
    return DOOM_CODES[kind] + (DOOM_CAPITAL if capital else 0)


def is_doom(signal: int) -> bool:
    return signal in DOOM_CODES.values() or signal - DOOM_CAPITAL in DOOM_CODES.values()


def item_value(item: int, sender: int = 0) -> int:
    """What is written into the mailbox for an item. sender: the slot of the player who sent it, 0 for nobody."""
    return item + SENDER_FACTOR * (sender if 0 <= sender <= MAX_SENDERS else 0)


def empty_value(item_index: int, parity: int, signals: int = 0, run: int = 0) -> int:
    return -(2 * (item_index + 1) + parity + SIGNAL_FACTOR * (signals % SIGNAL_MODULO) + RUN_FACTOR * run)


def decode(value: int | None) -> tuple[int, int, int] | None:
    """(items applied, signals carried out modulo 1000, run) of the save, if the mailbox is empty."""
    if value is None or value > -2:
        return None
    run, rest = divmod(-value, RUN_FACTOR)
    signals, rest = divmod(rest, SIGNAL_FACTOR)
    return (rest // 2 - 1, signals, run) if rest >= 2 else None


class Mailbox:
    def __init__(self, attach: Callable[[], GameMemory | None] = GameMemory.attach,
                 say: Callable[[str], None] = print, clock: Callable[[], float] = time.monotonic, run: int = 0):
        """run: the number of the run the client plays (1 to 9999), 0 to take any save."""
        self.attach = attach
        self.say = say
        self.clock = clock
        self.run = run
        self.memory: GameMemory | None = None
        self.next_attach = 0.0
        # Signals the game that is running has not carried out yet
        self.signals: list[int] = []
        self.reset()

    def request_doom(self, kind: str, capital: bool = False) -> None:
        """One more doom for the game that is running. capital: whether it may strike the capital too."""
        self.signals.append(doom_code(kind, capital))

    def request_death_notice(self, deaths: int, deaths_per_doom: int, effect: str = "none") -> None:
        """A death that was counted: tells the player in game, and takes a leader or a fleet if that is the effect."""
        self.signals.append(death_notice(deaths, deaths_per_doom, effect))

    def reset(self) -> None:
        """Forgets where the mailbox is. Called when a game is loaded, which moves it."""
        self.candidates: dict[int, int | None] = {}
        self.live: int | None = None
        self.item_index: int | None = None
        # Whether the save belongs to the run of the client. None until the game told
        self.bound: bool | None = None
        # Another save has another number of signals behind it
        self.signals_seen: int | None = None
        self.next_scan = 0.0
        self.waiting_since: float | None = None
        # A signal about the save that was loaded before means nothing to this one
        # (WRONG_RUN and the run it was given). Dooms and deaths are still owed to the game
        self.signals = [signal for signal in self.signals
                        if signal != WRONG_RUN and not BIND_RUN <= signal < DEATH_NOTICE]

    def poll(self, item_ids: list[int]) -> None:
        """Takes all items received so far, as item_value(), and writes the next one the save needs."""
        if self.memory is not None and not self.memory.alive():
            self.memory.close()
            self.memory = None
            self.reset()
        if self.memory is None:
            if self.clock() < self.next_attach:
                return
            self.next_attach = self.clock() + ATTACH_SECONDS
            self.memory = self.attach()
            if self.memory is None:
                return
        if self.live is not None and not self.memory.is_variable(self.live, VARIABLE):
            self.reset()
        if self.live is None:
            self.find_live()
        if self.live is None:
            return
        state = decode(self.memory.read_value(self.live))
        if state is None:
            # Holds something the game has not taken yet
            return
        index, signals, run = state
        if self.signals_seen is not None:
            for _ in range(min((signals - self.signals_seen) % SIGNAL_MODULO, len(self.signals))):
                if is_doom(self.signals.pop(0)):
                    self.say("Stellaris: doom has struck")
        self.signals_seen = signals
        self.check_run(run)
        if self.bound and index != self.item_index:
            self.item_index = index
            self.say(f"Stellaris: {index} item(s) applied")
        if self.bound is False:
            # Only tells the player, once
            value = WRONG_RUN if WRONG_RUN in self.signals else None
        elif self.signals:
            value = self.signals[0]
        elif self.bound and index < len(item_ids):
            value = item_ids[index]
        else:
            value = None
        # Checked again right before writing: nothing may be written anywhere else
        if value is not None and self.memory.is_variable(self.live, VARIABLE):
            self.memory.write_value(self.live, value)

    def check_run(self, run: int) -> None:
        """Compares the run of the save with the one of the client. A save without a run gets the client's."""
        if not self.run or run == self.run:
            if self.bound is None:
                self.say("Stellaris: this save belongs to this run" if self.run else "Stellaris: save found")
            self.bound = True
        elif run == 0:
            if BIND_RUN + self.run not in self.signals:
                self.signals.insert(0, BIND_RUN + self.run)
                self.say("Stellaris: a new game, it belongs to this run from now on")
        elif self.bound is None:
            self.bound = False
            self.signals = [WRONG_RUN]
            self.say(f"Stellaris: this save belongs to another run ({run}). Nothing is sent or received.")

    def find_live(self) -> None:
        now = self.clock()
        if now >= self.next_scan:
            self.candidates = {address: self.candidates.get(address, self.memory.read_value(address))
                               for address in self.memory.find_variable(VARIABLE)}
            # A scan takes several seconds. With copies found, most likely the game is just paused
            self.next_scan = now + (SCAN_SECONDS * 4 if self.candidates else SCAN_SECONDS)
        for address, last in list(self.candidates.items()):
            if not self.memory.is_variable(address, VARIABLE):
                del self.candidates[address]
                continue
            value = self.memory.read_value(address)
            self.candidates[address] = value
            if value != last and decode(value) is not None:
                self.live = address
                self.say("Connected to the game")
                return
        if self.candidates:
            if self.waiting_since is None:
                self.waiting_since = now
            elif now - self.waiting_since > PAUSED_HINT_SECONDS:
                self.waiting_since = float("inf")
                self.say("Waiting for the game: items arrive while it is not paused")
