"""The connection to an Archipelago server.

It runs in a thread of its own and reports what happens as events, to a function that is called
from that thread:

    ("connected", info)          logged in. info: seed, slot, team, players {slot: name}, slot_data,
                                 checked (location ids the server knows)
    ("refused", [reason, ...])   the server does not let the slot in
    ("disconnected", reason)     the connection is gone, it is made again by itself
    ("items", [item, ...])       every item received so far: {"item", "location", "player", "flags"}
    ("scouted", {location: {"item": name, "player": name, "flags": n}})
    ("print", [(text, kind), ...], type)   a message of the server, in parts. kind: "text", "player",
                                 "me", "location", "progression", "useful", "trap" or "filler"
    ("death", {"source": name, "cause": text})   a DeathLink death
"""
import asyncio
import json
import ssl
import threading
import time
import uuid
from typing import Callable

from .bootstrap import require

websockets = require("websockets")
# The certificates Windows knows can be out of date, which makes a server look like it has an expired one.
# The other Archipelago clients bring their own list too
certifi = require("certifi")

GAME = "Stellaris"
DEFAULT_PORT = 38281
VERSION = {"major": 0, "minor": 6, "build": 7, "class": "Version"}
# Receive the items of every player, of the own world and the ones the player starts with
ITEMS_HANDLING = 0b111
GOAL = 30
RECONNECT_SECONDS = 5

PROGRESSION = 0b001
USEFUL = 0b010
TRAP = 0b100


def item_kind(flags: int) -> str:
    if flags & PROGRESSION:
        return "progression"
    if flags & TRAP:
        return "trap"
    return "useful" if flags & USEFUL else "filler"


def addresses(address: str) -> list[str]:
    """The addresses to try for what the player typed: encrypted first, like the other clients do."""
    address = address.strip()
    if "://" in address:
        return [address]
    if ":" not in address:
        address = f"{address}:{DEFAULT_PORT}"
    return [f"wss://{address}", f"ws://{address}"]


def encryption(address: str) -> ssl.SSLContext | None:
    """How to check the certificate of the server at an address, None if it is not encrypted."""
    if not address.startswith("wss://"):
        return None
    return ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=certifi.where())


class Names:
    """The names of items, locations and players, which the server only sends as numbers."""

    def __init__(self):
        self.items: dict[str, dict[int, str]] = {}
        self.locations: dict[str, dict[int, str]] = {}
        self.players: dict[int, str] = {}
        self.games: dict[int, str] = {}

    def add_game(self, game: str, package: dict) -> None:
        self.items[game] = {number: name for name, number in package.get("item_name_to_id", {}).items()}
        self.locations[game] = {number: name for name, number in package.get("location_name_to_id", {}).items()}

    def player(self, slot: int) -> str:
        return self.players.get(slot, "Archipelago" if slot == 0 else f"Player {slot}")

    def item(self, number: int, slot: int) -> str:
        """The name of an item of the game the player in the slot plays."""
        return self.items.get(self.games.get(slot, ""), {}).get(number, f"Item {number}")

    def location(self, number: int, slot: int) -> str:
        if number < 0:
            return "the server"
        return self.locations.get(self.games.get(slot, ""), {}).get(number, f"Location {number}")

    def render(self, parts: list[dict], me: int) -> list[tuple[str, str]]:
        """A message of the server (PrintJSON) as (text, kind) parts."""
        rendered = []
        for part in parts:
            kind = part.get("type", "text")
            text = str(part.get("text", ""))
            if kind == "player_id":
                rendered.append((self.player(int(text)), "me" if int(text) == me else "player"))
            elif kind == "item_id":
                rendered.append((self.item(int(text), part.get("player", me)), item_kind(part.get("flags", 0))))
            elif kind == "location_id":
                rendered.append((self.location(int(text), part.get("player", me)), "location"))
            elif kind == "player_name":
                rendered.append((text, "player"))
            elif kind == "item_name":
                rendered.append((text, item_kind(part.get("flags", 0))))
            elif kind == "location_name":
                rendered.append((text, "location"))
            else:
                rendered.append((text, "text"))
        return rendered


def merge_items(received: list[dict], index: int, items: list[dict]) -> list[dict] | None:
    """The items received so far after a ReceivedItems message, or None if some are missing in between."""
    if index == 0:
        return list(items)
    if index == len(received):
        return received + list(items)
    if index < len(received):
        # Sent again: what is already there stays
        return received[:index] + list(items) if index + len(items) >= len(received) else received
    return None


class Connection:
    def __init__(self, address: str, slot_name: str, password: str, on_event: Callable[..., None],
                 death_link: bool = False):
        self.address = address
        self.slot_name = slot_name
        self.password = password
        self.on_event = on_event
        self.death_link = death_link
        self.names = Names()
        self.seed = ""
        self.slot = 0
        self.received: list[dict] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self.socket = None
        self.stopped = False
        self.outbox: list[dict] = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    # --- called from the other threads

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopped = True
        if self.loop and self.socket:
            asyncio.run_coroutine_threadsafe(self.socket.close(), self.loop)

    def send(self, message: dict) -> None:
        """Sends a message, or keeps it until there is a connection again."""
        if self.loop and self.socket:
            asyncio.run_coroutine_threadsafe(self.deliver(message), self.loop)
        else:
            self.outbox.append(message)

    def check(self, locations: list[int]) -> None:
        self.send({"cmd": "LocationChecks", "locations": list(locations)})

    def scout(self, locations: list[int]) -> None:
        self.send({"cmd": "LocationScouts", "locations": list(locations), "create_as_hint": 0})

    def say(self, text: str) -> None:
        self.send({"cmd": "Say", "text": text})

    def goal(self) -> None:
        self.send({"cmd": "StatusUpdate", "status": GOAL})

    def die(self, cause: str) -> None:
        """Tells the other players about a death here."""
        self.send({"cmd": "Bounce", "tags": ["DeathLink"],
                   "data": {"time": time.time(), "source": self.slot_name, "cause": cause}})

    # --- the thread of the connection

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        try:
            self.loop.run_until_complete(self.keep_connected())
        finally:
            self.loop.close()

    async def keep_connected(self) -> None:
        while not self.stopped:
            reason = ""
            failures = []
            for address in addresses(self.address):
                try:
                    async with websockets.connect(address, max_size=None, open_timeout=10,
                                                  ssl=encryption(address)) as socket:
                        self.socket = socket
                        reason = await self.listen(socket)
                    break
                except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException) as error:
                    failures.append(f"{address.split('://')[0]}: {str(error) or type(error).__name__}")
                finally:
                    self.socket = None
            # Every way of reaching the server failed: say how, each of them
            reason = reason or "; ".join(failures) or "could not reach the server"
            if self.stopped:
                return
            self.on_event("disconnected", reason)
            if reason == "refused":
                return
            await asyncio.sleep(RECONNECT_SECONDS)

    async def deliver(self, message: dict) -> None:
        try:
            await self.socket.send(json.dumps([message]))
        except (AttributeError, websockets.exceptions.WebSocketException):
            self.outbox.append(message)

    async def listen(self, socket) -> str:
        async for raw in socket:
            for message in json.loads(raw):
                if await self.handle(message) == "refused":
                    return "refused"
        return "the server closed the connection"

    async def handle(self, message: dict) -> str | None:
        command = message.get("cmd")
        if command == "RoomInfo":
            self.seed = message.get("seed_name", "")
            await self.deliver({"cmd": "GetDataPackage", "games": message.get("games", [])})
        elif command == "DataPackage":
            for game, package in message["data"]["games"].items():
                self.names.add_game(game, package)
            await self.deliver({
                "cmd": "Connect", "password": self.password, "game": GAME, "name": self.slot_name,
                "uuid": uuid.getnode().to_bytes(6, "big").hex(), "version": VERSION,
                "items_handling": ITEMS_HANDLING, "tags": ["DeathLink"] if self.death_link else [],
                "slot_data": True})
        elif command == "ConnectionRefused":
            self.on_event("refused", message.get("errors", []))
            return "refused"
        elif command == "Connected":
            self.slot = message["slot"]
            self.names.players = {player["slot"]: player["alias"] for player in message["players"]
                                  if player["team"] == message["team"]}
            self.names.games = {int(slot): info["game"] for slot, info in message.get("slot_info", {}).items()}
            self.on_event("connected", {
                "seed": self.seed, "slot": self.slot, "team": message["team"], "players": dict(self.names.players),
                "slot_data": message.get("slot_data", {}), "checked": list(message.get("checked_locations", []))})
            outbox, self.outbox = self.outbox, []
            for waiting in outbox:
                await self.deliver(waiting)
        elif command == "ReceivedItems":
            merged = merge_items(self.received, message["index"], message["items"])
            if merged is None:
                await self.deliver({"cmd": "Sync"})
            else:
                self.received = merged
                self.on_event("items", list(merged))
        elif command == "LocationInfo":
            self.on_event("scouted", {
                entry["location"]: {"item": self.names.item(entry["item"], entry["player"]),
                                    "player": self.names.player(entry["player"]), "flags": entry.get("flags", 0)}
                for entry in message["locations"]})
        elif command == "PrintJSON":
            self.on_event("print", self.names.render(message.get("data", []), self.slot), message.get("type", ""))
        elif command == "Bounced" and "DeathLink" in message.get("tags", []):
            data = message.get("data", {})
            if data.get("source") != self.slot_name:
                self.on_event("death", {"source": data.get("source", "someone"), "cause": data.get("cause", "")})
        return None
