"""Stellaris Archipelago client.

Stellaris cannot talk to anything outside of itself, so this program has to run next to it. It is
normally the window of stellaris_ap.app ("Play Stellaris Archipelago.bat"). This is the same without
a window and without a server, for testing:

    python -m stellaris_ap.client --offline          the run without a server that was played last
    python -m stellaris_ap.client --offline --new    a new run

A run without an Archipelago server is a randomizer of its own: every technology and tradition is
shuffled onto the location of another one. The client has to start before the game, because the
game reads the names of the technologies when it starts.
"""
import argparse
import queue
import random
import socket
import sys
import threading
import time

from . import build_mod, data
from .bridge import Bridge
from .mailbox import DOOM_CODES
from .memory import stellaris_pid
from .paths import REPO, RUN_FILE_NAME, WRITE_BLOCKED_HINT, stellaris_user_dir
from .profiles import Profile, Profiles
from .session import MENU_DEATH, MENU_DOOM

LOG_FILE = REPO / "client.log"
# The player's slot in a run without a server
OFFLINE_SLOT = 1
OFFLINE_HELP = """Commands:
  item <id or name>   send an extra item to the game
  sent                list the items sent so far
  quit"""

# Only one client at a time may write into the game. A port that is taken means another one is running
INSTANCE_PORT = 48219
# How long a new client waits for the one that is running to quit
TAKEOVER_SECONDS = 15
GAME_CHECK_SECONDS = 5
# How long the game may take to show up after the launcher started it
GAME_START_SECONDS = 600


def shuffle(seed: int) -> dict[int, int]:
    """{location id: id of the item there}: every technology and tradition on the location of another one."""
    generator = random.Random(seed)
    locations = [location["id"] for location in data.locations()]
    items = data.item_pool(generator)
    generator.shuffle(items)
    placement = dict(zip(locations, items))
    # Picking an ascension perk needs a slot, so it must not be where the slots are found
    slot = next(item["id"] for item in data.items() if item["name"] == data.PROGRESSIVE_ASCENSION)
    perks = [location["id"] for location in data.locations() if location["kind"] == "perk"]
    free = [location for location in locations if location not in perks and placement[location] != slot]
    for perk in perks:
        if placement[perk] == slot:
            other = free.pop(generator.randrange(len(free)))
            placement[perk], placement[other] = placement[other], placement[perk]
    return placement


def write_names(profile: Profile) -> None:
    """Names the technologies and traditions in game after the items of the run. The game reads them at its start."""
    items = {item["id"]: item for item in data.items()}
    build_mod.write_check_names(
        {location: (items[item]["name"], "you") for location, item in shuffle(profile.seed).items()},
        players={OFFLINE_SLOT: "you"})
    build_mod.write_session(profile.run, [items[item] for item, _ in profile.sent], profile.checked)


class GameWatch:
    """Tells when the game was closed, for a client that should not outlive it."""

    def __init__(self, find_game=stellaris_pid, clock=time.monotonic):
        self.find_game = find_game
        self.clock = clock
        self.started = clock()
        self.next_check = 0.0
        self.seen = False

    def game_is_over(self) -> bool:
        if self.clock() < self.next_check:
            return False
        self.next_check = self.clock() + GAME_CHECK_SECONDS
        if self.find_game() is not None:
            self.seen = True
            return False
        return self.seen or self.clock() - self.started > GAME_START_SECONDS


def read_stdin(commands: queue.Queue) -> None:
    while True:
        try:
            commands.put(input())
        except EOFError:
            commands.put("quit")
            return


def run_profile(args, user_dir, lock: socket.socket, profile: Profile) -> None:
    items = {item["id"]: item for item in data.items()}
    locations = {location["id"]: location["name"] for location in data.locations()}
    placement = shuffle(profile.seed)
    write_names(profile)
    profile.played()
    print(f"{profile.name} (run {profile.run}): {len(profile.checked)} of {len(locations)} locations checked.")
    print("The technologies were named after their items. If Stellaris is running, restart it to see them.")

    def sent_items() -> list[dict]:
        return [{**items[item], "sender": sender} for item, sender in profile.sent]

    def on_check(location: int) -> None:
        item = profile.check(location, placement, OFFLINE_SLOT)
        if item is not None:
            print(f"CHECK: {locations[location]} -> {items[item]['name']}")
            bridge.set_items(sent_items())

    def on_command(number: int) -> None:
        if number == MENU_DEATH:
            bridge.receive_death()
        elif number == MENU_DOOM:
            bridge.send_doom()

    bridge = make_bridge(args, user_dir, on_check, on_command, profile.run)
    bridge.set_items(sent_items())
    commands: queue.Queue = queue.Queue()
    watch = GameWatch() if args.background else None
    if not args.background:
        threading.Thread(target=read_stdin, args=(commands,), daemon=True).start()
        print(OFFLINE_HELP)
    while True:
        bridge.tick()
        if watch and watch.game_is_over():
            print("Stellaris was closed")
            return
        if asked_to_quit(lock):
            print("Another client was started")
            return
        try:
            command = commands.get(timeout=0.5).strip("﻿ \t\r\n")
        except queue.Empty:
            continue
        verb, _, argument = command.partition(" ")
        argument = argument.strip().lower()
        if verb == "quit":
            return
        elif verb == "sent":
            for index, item in enumerate(sent_items(), 1):
                print(f"  {index}. {item['name']}")
        elif verb == "item":
            item = next((i for i in items.values() if argument in (str(i["id"]), i["name"].lower())), None)
            if item is None:
                print(f'Unknown item "{argument}"')
                continue
            profile.send(item["id"])
            bridge.set_items(sent_items())
            print(f"Sending {item['name']} ({len(profile.sent)} item(s) total)")
        elif command:
            print(OFFLINE_HELP)


def make_bridge(args, user_dir, on_check, on_command, run: int) -> Bridge:
    try:
        bridge = Bridge(user_dir, on_check, run_mode=args.run_mode, delivery=args.delivery,
                        deaths_per_doom=args.deaths_per_doom, doom=args.doom, on_command=on_command, run=run)
    except OSError:
        sys.exit(WRITE_BLOCKED_HINT.format(path=user_dir / RUN_FILE_NAME, python=sys.executable))
    print(f"Watching {bridge.tailer.path}")
    if args.delivery == "console":
        print(f'Type "run {RUN_FILE_NAME}" in the Stellaris console once after loading your game.')
    return bridge


def only_instance(wait: float = TAKEOVER_SECONDS) -> socket.socket | None:
    """A socket to keep for as long as the client runs, or None if another client keeps running.

    A client that is already running is asked to quit, by connecting to its socket. That is how the
    client of the last game makes room when the game is started again right away.
    """
    deadline = time.monotonic() + wait
    while True:
        lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            lock.bind(("127.0.0.1", INSTANCE_PORT))
            lock.listen()
            lock.setblocking(False)
            return lock
        except OSError:
            lock.close()
        if time.monotonic() >= deadline:
            return None
        try:
            socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=1).close()
        except OSError:
            pass
        time.sleep(0.2)


def asked_to_quit(lock: socket.socket) -> bool:
    """Whether another client was started, and wants to take over."""
    try:
        connection, _ = lock.accept()
    except OSError:
        return False
    connection.close()
    return True


def pick_profile(args, store: Profiles) -> Profile:
    if args.run:
        profile = store.get(args.run)
        if profile is None:
            sys.exit(f"There is no run {args.run}")
        return profile
    offline = [profile for profile in store.all() if profile.state["kind"] == "offline"]
    return store.new_offline() if args.new or not offline else offline[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=int, help="the number of the run to play, as the launcher passes it")
    parser.add_argument("--offline", action="store_true", help="play the run without a server that was played last")
    parser.add_argument("--new", action="store_true", help="with --offline: a new run")
    parser.add_argument("--background", action="store_true",
                        help=f"no commands on the console, write to {LOG_FILE.name}, and exit when Stellaris is closed")
    parser.add_argument("--stellaris-dir", help="Stellaris user directory (default: auto detect)")
    parser.add_argument("--run-mode", choices=["commands", "script"], default="commands",
                        help="format of the run file: console commands (default) or a plain effect script")
    parser.add_argument("--delivery", choices=["memory", "console", "manual"], default="memory",
                        help="how items reach the game: written into the game's memory in the background (default), "
                             f'by pressing keys in the game to run {RUN_FILE_NAME} in the console, '
                             "or only when you run that file yourself")
    parser.add_argument("--deaths-per-doom", type=int, default=3, metavar="N",
                        help="DeathLink: every N deaths in the multiworld destroy one of your colonies, "
                             "0 for never (default: 3)")
    parser.add_argument("--doom", choices=sorted(DOOM_CODES), default="cracked",
                        help="DeathLink: the colony is cracked for good (default), or becomes a tomb world "
                             "covered in ruins that can be settled again")
    args = parser.parse_args()
    lock = only_instance()
    if args.background:
        # Started without a window, there is no console to write to. Opened once the client that ran before
        # has quit, which writes to the same file
        sys.stdout = sys.stderr = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
    if lock is None:
        sys.exit("Another client is running and does not quit")
    if not args.offline and not args.run:
        parser.error("connecting to an Archipelago server is not implemented yet, use --offline")

    user_dir = stellaris_user_dir(args.stellaris_dir)
    if not user_dir.is_dir():
        parser.error(f"Stellaris user directory not found: {user_dir}")
    try:
        run_profile(args, user_dir, lock, pick_profile(args, Profiles()))
    except KeyboardInterrupt:
        pass
    finally:
        lock.close()


if __name__ == "__main__":
    main()
