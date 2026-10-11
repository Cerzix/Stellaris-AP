"""The two halves of the game <-> client bridge.

Game -> client: the mod writes "AP_<WORD> [number]" lines to game.log, LogTailer reads them.
Client -> game: the id of the next item is written into the mailbox variable in the memory
of the running game, see mailbox.py. Nothing happens on screen.

As a fallback every received item is also written into a file in the Stellaris user
directory, which is executed in game with the console command "run ap.txt". Each item is
guarded by the ap_item_index variable stored in the save, so running the file again (or
loading an older save) only applies what that save has not received yet. With the delivery
"console" the client runs that file itself, by pressing keys in the game.
"""
import os
import random
import re
import time
from pathlib import Path
from typing import Callable

from . import console
from .data import EMPIRES
from .mailbox import Mailbox, item_value
from .paths import RUN_FILE_NAME

# "AP_<WORD>", "AP_<WORD> <number>" or "AP_<WORD> <number> <text>" at the end of a line
LOG_LINE = re.compile(r"\bAP_([A-Z]+)(?: (\d+)(?: (.*?))?)?\s*$")

# What the mod reports as "AP_DEATH <number> <name>": the kind of death, as in the options that say what
# counts as one. 3 is a fleet that lost a battle, whether it got away or not
DEATHS = {1: "ruler", 2: "leader", 3: "battle", 4: "colony", 5: "colony"}
# What the mod reports as "AP_GOAL <number>": what was achieved in the galaxy, as in the option goal
GOALS = {1: "crisis", 2: "crisis_and_fallen_empires"}

RETRIGGER_SECONDS = 5
MAX_TRIGGER_ATTEMPTS = 5
FOREGROUND_SETTLE_SECONDS = 2


class LogTailer:
    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.partial = b""
        self.restarted = False

    def poll(self) -> list[tuple[str, int | None, str]]:
        """Returns the (word, number, text) of every new AP line. Sets restarted if the game started a fresh log."""
        self.restarted = False
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:
            self.offset = 0
            self.partial = b""
            self.restarted = True
        if size == self.offset:
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            data = f.read()
        self.offset += len(data)
        *lines, self.partial = (self.partial + data).split(b"\n")
        messages = []
        for line in lines:
            match = LOG_LINE.search(line.decode("utf-8", errors="replace"))
            if match:
                messages.append((match.group(1), int(match.group(2)) if match.group(2) else None,
                                 match.group(3) or ""))
        return messages


def render_run_file(effects: list[str], mode: str = "commands") -> str:
    """mode "commands": one console command per line. mode "script": a plain effect script."""
    blocks = []
    for index, effect in enumerate(effects, 1):
        effect = " ".join(effect.split())
        blocks.append(f"if = {{ limit = {{ check_variable = {{ which = ap_item_index value < {index} }} }} "
                      f"{effect} set_variable = {{ which = ap_item_index value = {index} }} }}")
    blocks.append(f'log = "AP_ACK {len(effects)}"')
    blocks.append("ap_report_checks = yes")
    if mode == "commands":
        # No newline at the end, the console would run the empty last line as an unknown command
        return "\n".join(f"effect event_target:ap_player = {{ {block} }}" for block in blocks)
    return "event_target:ap_player = {\n" + "".join(f"\t{block}\n" for block in blocks) + "}\n"


class Bridge:
    def __init__(self, user_dir: Path, on_check: Callable[[int], None], run_mode: str = "commands",
                 delivery: str = "memory", say: Callable[[str], None] = print, mailbox: Mailbox | None = None,
                 deaths_per_doom: int = 0, doom: str = "cracked",
                 on_command: Callable[[int], None] | None = None, run: int = 0,
                 on_death: Callable[[int, str], None] | None = None, death_effect: str = "random",
                 doom_capital: bool = False, pick: Callable[[list], str] = random.choice):
        """delivery: "memory", "console" or "manual" (the player runs the file).
        deaths_per_doom: after this many DeathLink deaths a colony is destroyed, 0 for never.
        doom: what happens to the colony, a key of mailbox.DOOM_CODES.
        doom_capital: whether a doom may strike the capital too.
        death_effect: what a death that is not a doom takes: "none", "leader", "fleet" or "random".
        on_command: called with the number of an option the player picked in the menu in game.
        run: the number of the run that is played. Checks of a save of another run are dropped, see mailbox.py.
        on_death: called with the kind of a death in the player's empire (see DEATHS) and the name of who died."""
        self.on_death = on_death
        # What the save that is loaded has achieved, see GOALS. Like its checks, it only counts once the save
        # has told which run it belongs to
        self.goals: set[str] = set()
        self.pending_goals: set[str] = set()
        self.death_effect = death_effect
        self.doom_capital = doom_capital
        self.pick = pick
        # Checks of a save that has not told yet which run it belongs to
        self.pending_checks: list[int] = []
        self.on_command = on_command
        # What the running game reported: the numbers of its DLCs (see data.dlcs) and the kind of empire
        self.game_dlcs: set[int] = set()
        self.game_empire: str | None = None
        # What is in the log when the client starts happened before, its commands are not carried out again
        self.backlog = True
        self.deaths_per_doom = deaths_per_doom
        self.doom = doom
        self.deaths = 0
        self.tailer = LogTailer(user_dir / "logs" / "game.log")
        self.run_file = user_dir / RUN_FILE_NAME
        self.on_check = on_check
        self.run_mode = run_mode
        self.auto_console = delivery == "console"
        self.mailbox = mailbox or (Mailbox(say=say, run=run) if delivery == "memory" else None)
        self.say = say
        self.items: list[dict] = []
        self.checked: set[int] = set()
        self.in_game = False
        self.acked = 0
        self.attempts = 0
        self.last_trigger = 0.0
        self.foreground_since: float | None = None
        self.write_run_file()

    def set_items(self, items: list[dict]) -> None:
        """Takes all items received so far, in order. An item can have a "sender", the slot of a player."""
        self.items = list(items)
        self.attempts = 0
        self.write_run_file()

    def receive_death(self) -> None:
        """A DeathLink death from the multiworld. It takes something from the player, and counts towards a doom."""
        self.deaths += 1
        if self.deaths_per_doom and self.deaths >= self.deaths_per_doom:
            self.deaths = 0
            self.send_doom()
            return
        effect = self.pick(["leader", "fleet"]) if self.death_effect == "random" else self.death_effect
        if self.deaths_per_doom:
            self.say(f"DeathLink: death {self.deaths} of {self.deaths_per_doom}")
        if self.mailbox:
            self.mailbox.request_death_notice(self.deaths, self.deaths_per_doom, effect)

    def send_doom(self) -> None:
        if self.mailbox is None:
            self.say('DeathLink: doom needs the delivery "memory"')
            return
        self.mailbox.request_doom(self.doom, self.doom_capital)
        self.say("DeathLink: doom is on its way to one of your colonies")

    def write_run_file(self) -> None:
        temp = self.run_file.with_suffix(".tmp")
        temp.write_text(render_run_file([item["effect"] for item in self.items], self.run_mode), encoding="utf-8", newline="\n")
        os.replace(temp, self.run_file)

    def tick(self) -> None:
        messages = self.tailer.poll()
        if self.tailer.restarted:
            self.in_game = False
        for word, number, text in messages:
            if word == "HELLO":
                # A game was started or loaded, it may be behind on items
                self.in_game = True
                self.game_dlcs = set()
                self.game_empire = None
                self.acked = 0
                self.attempts = 0
                self.pending_checks = []
                self.pending_goals = set()
                self.goals = set()
                if self.mailbox:
                    self.mailbox.reset()
                self.say("Stellaris: game loaded")
            elif word == "ACK" and number is not None:
                self.acked = number
                self.attempts = 0
                self.say(f"Stellaris: {number} item(s) applied")
            elif word == "CHECK" and number is not None and number not in self.checked:
                if self.mailbox and getattr(self.mailbox, "run", 0):
                    self.pending_checks.append(number)
                else:
                    self.checked.add(number)
                    self.on_check(number)
            elif word == "GOAL" and number in GOALS:
                if self.mailbox and getattr(self.mailbox, "run", 0):
                    self.pending_goals.add(GOALS[number])
                else:
                    self.goals.add(GOALS[number])
            elif word == "DLC" and number is not None:
                self.game_dlcs.add(number)
            elif word == "EMPIRE" and number in (1, 2, 3):
                self.game_empire = EMPIRES[number - 1]
                self.say(f"Stellaris: {self.game_empire} empire, {len(self.game_dlcs)} of the DLCs that matter")
            elif word == "DEATH" and number in DEATHS and self.on_death and not self.backlog:
                # A name the game could not fill in stays in its brackets
                self.on_death(number, "" if "[" in text else text)
            elif word == "CMD" and number is not None and self.on_command and not self.backlog:
                self.on_command(number)
        self.backlog = False
        if self.mailbox:
            self.mailbox.poll([item_value(item["id"], item.get("sender", 0)) for item in self.items])
            if self.pending_goals and getattr(self.mailbox, "bound", None) is not None:
                if self.mailbox.bound:
                    self.goals |= self.pending_goals
                self.pending_goals = set()
            if self.pending_checks and getattr(self.mailbox, "bound", None) is not None:
                pending, self.pending_checks = self.pending_checks, []
                for number in pending:
                    if self.mailbox.bound and number not in self.checked:
                        self.checked.add(number)
                        self.on_check(number)
        self.trigger_if_pending()

    def trigger_if_pending(self) -> None:
        if not (self.auto_console and self.in_game and self.acked < len(self.items)):
            return
        if self.attempts >= MAX_TRIGGER_ATTEMPTS or time.monotonic() - self.last_trigger < RETRIGGER_SECONDS:
            return
        if not console.stellaris_is_foreground():
            self.foreground_since = None
            return
        # Right after switching to the game it does not take key presses yet
        if self.foreground_since is None:
            self.foreground_since = time.monotonic()
        if time.monotonic() - self.foreground_since < FOREGROUND_SETTLE_SECONDS:
            return
        self.last_trigger = time.monotonic()
        self.attempts += 1
        self.say(f"Pressing keys in Stellaris to deliver items (attempt {self.attempts})")
        console.rerun_last_command()
        if self.attempts == MAX_TRIGGER_ATTEMPTS:
            self.say(f'Items are not arriving, type "run {RUN_FILE_NAME}" in the Stellaris console.')
