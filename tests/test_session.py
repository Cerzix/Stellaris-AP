"""Tests the connection to a multiworld without a server, and the session without a game.

Nothing here may deliver through the game's memory: a game that happens to run would take it for real.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

from stellaris_ap import app, archipelago, bootstrap, build_mod, data, session
from stellaris_ap.archipelago import Names, addresses, item_kind, merge_items
from stellaris_ap.client import shuffle
from stellaris_ap.profiles import Profiles
from stellaris_ap.session import OfflineSession, ServerSession


class ProtocolTest(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(addresses(" archipelago.gg:38281 "), ["wss://archipelago.gg:38281", "ws://archipelago.gg:38281"])
        self.assertEqual(addresses("localhost"), ["wss://localhost:38281", "ws://localhost:38281"])
        self.assertEqual(addresses("ws://localhost:1234"), ["ws://localhost:1234"])

    def test_encrypted_connections_bring_their_certificates(self):
        self.assertIsNone(archipelago.encryption("ws://localhost:38281"))
        context = archipelago.encryption("wss://archipelago.gg:38281")
        self.assertTrue(context.check_hostname)
        self.assertGreater(len(context.get_ca_certs()), 50, "the list of certifi, not the one of Windows")
        source = Path(archipelago.__file__).read_text(encoding="utf-8")
        self.assertIn('certifi = require("certifi")', source)

    def test_item_kinds(self):
        self.assertEqual([item_kind(flags) for flags in (0, 1, 2, 3, 4)],
                         ["filler", "progression", "useful", "progression", "trap"])

    def test_received_items_are_kept_in_order(self):
        a, b, c = ({"item": number} for number in (1, 2, 3))
        self.assertEqual(merge_items([], 0, [a, b]), [a, b])
        self.assertEqual(merge_items([a, b], 2, [c]), [a, b, c])
        self.assertEqual(merge_items([a, b, c], 0, [a]), [a], "the server starts over")
        self.assertEqual(merge_items([a, b], 1, [b, c]), [a, b, c], "sent again")
        self.assertEqual(merge_items([a, b, c], 1, [b]), [a, b, c])
        self.assertIsNone(merge_items([a], 3, [c]), "items are missing in between: ask again")

    def test_messages_get_their_names(self):
        names = Names()
        names.add_game("Stellaris", {"item_name_to_id": {"Destroyers": 7}, "location_name_to_id": {"Research: X": 3}})
        names.add_game("Minecraft", {"item_name_to_id": {"Ender Pearl": 7}, "location_name_to_id": {"Kill Dragon": 3}})
        names.players = {1: "Cerzix", 2: "Steve"}
        names.games = {1: "Stellaris", 2: "Minecraft"}
        parts = names.render([
            {"text": "2", "type": "player_id"}, {"text": " sent "},
            {"text": "7", "type": "item_id", "player": 1, "flags": 1}, {"text": " to "},
            {"text": "1", "type": "player_id"}, {"text": " ("},
            {"text": "3", "type": "location_id", "player": 2}, {"text": ")"}], me=1)
        self.assertEqual(parts, [("Steve", "player"), (" sent ", "text"), ("Destroyers", "progression"),
                                 (" to ", "text"), ("Cerzix", "me"), (" (", "text"), ("Kill Dragon", "location"),
                                 (")", "text")])
        self.assertEqual(names.item(7, 2), "Ender Pearl", "the same number is another item in another game")
        self.assertEqual(names.item(99, 2), "Item 99")
        self.assertEqual(names.player(0), "Archipelago")


def keep_mod_files(test, write_session=lambda run=0, items=(), checked=(): None) -> None:
    """A session writes what a new game starts with into the mod. Not the session of a test."""
    original = build_mod.write_session
    build_mod.write_session = write_session
    test.addCleanup(setattr, build_mod, "write_session", original)


class FakeConnection:
    """What a session does to the server, written down."""

    def __init__(self, address, slot_name, password, on_event):
        self.on_event = on_event
        self.death_link = False
        self.names = Names()
        self.names.players = {1: "Cerzix", 2: "Steve"}
        self.sent = []
        self.checked = []
        self.said = []
        self.scouted = []
        self.died = []
        self.won = False

    def start(self):
        pass

    def stop(self):
        pass

    def send(self, message):
        self.sent.append(message)

    def check(self, locations):
        self.checked += locations

    def scout(self, locations):
        self.scouted = list(locations)

    def say(self, text):
        self.said.append(text)

    def goal(self):
        self.won = True

    def die(self, cause):
        self.died.append(cause)


class ServerSessionTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.user_dir = Path(self.dir.name)
        (self.user_dir / "logs").mkdir()
        self.lines = []
        self.names = []
        original = build_mod.write_check_names
        build_mod.write_check_names = lambda names=None, players=None: self.names.append((names, players))
        self.addCleanup(setattr, build_mod, "write_check_names", original)
        self.starts = []
        keep_mod_files(self, lambda run=0, items=(), checked=(): self.starts.append(
            (run, [item["id"] for item in items], list(checked))))
        self.store = Profiles(self.user_dir / "profiles.json")
        self.session = self.connect()
        self.server = self.session.connection

    def connect(self) -> ServerSession:
        return ServerSession(self.user_dir, lambda kind, parts: self.lines.append((kind, app.plain(parts))),
                             self.store, "localhost:38281", "Cerzix", delivery="manual", connect=FakeConnection)

    def log(self, text: str) -> None:
        with open(self.user_dir / "logs" / "game.log", "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def connected(self, session=None, checked=(), **slot_data) -> None:
        session = session or self.session
        session.connection.on_event("connected", {
            "seed": "SEED", "slot": 1, "team": 0, "players": {1: "Cerzix", 2: "Steve"}, "checked": list(checked),
            "slot_data": {"goal": "fragments", "fragments_required": 2, "locations_required": 3, "death_link": False,
                          "deaths_per_doom": 2, "doom": "tomb", "owned_dlc": [], "empire_type": "regular",
                          "death_effect": "fleet", "doom_capital": True,
                          **slot_data}})
        session.tick()

    def test_connecting_names_the_game_and_binds_the_run(self):
        self.connected()
        self.assertEqual(self.session.profile.state["seed_name"], "SEED")
        self.assertEqual(self.session.bridge.mailbox, None, "no delivery through memory in a test")
        self.assertEqual(sorted(self.server.scouted), sorted(location["id"] for location in data.locations()))
        self.assertFalse(self.session.ready)
        self.server.on_event("scouted", {5: {"item": "Ender Pearl", "player": "Steve", "flags": 1}})
        self.session.tick()
        self.assertEqual(self.names, [({5: ("Ender Pearl", "Steve")}, {1: "Cerzix", 2: "Steve"})])
        self.assertTrue(self.session.ready)
        self.assertEqual(self.store.recent_servers(), [("localhost:38281", "Cerzix")])

    def test_checks_go_to_the_server(self):
        self.connected()
        self.log("AP_HELLO")
        self.log("AP_CHECK 5")
        self.log("AP_CHECK 1001")
        self.session.tick()
        self.assertEqual(self.server.checked, [5, 1001])
        self.assertEqual(self.session.profile.checked, [5, 1001])
        self.assertIn(("check", "Checked Tradition Tree 1: Adopted"), self.lines)

    def test_checks_made_without_a_connection_are_sent_later(self):
        self.connected()
        self.log("AP_CHECK 5")
        self.session.tick()
        again = self.connect()
        self.connected(again, checked=[7])
        self.assertEqual(again.connection.checked, [5], "the server did not know it")
        self.assertEqual(again.profile.checked, [5, 7])
        self.log("AP_CHECK 7")
        again.tick()
        self.assertEqual(again.connection.checked, [5], "already known, not sent again")

    def test_items_reach_the_game_with_their_sender(self):
        self.connected()
        technology = data.items()[0]
        self.server.on_event("items", [{"item": technology["id"], "location": 3, "player": 2, "flags": 2},
                                       {"item": 999999, "location": 3, "player": 2, "flags": 0}])
        self.session.tick()
        self.assertEqual([(item["id"], item["sender"]) for item in self.session.bridge.items], [(technology["id"], 2)])
        self.assertIn(technology["effect"], (self.user_dir / "ap.txt").read_text())

    def test_new_items_are_announced(self):
        self.connected()
        first, second = data.items()[:2]
        self.server.on_event("items", [{"item": first["id"], "location": 3, "player": 2, "flags": 0}])
        self.server.on_event("items", [{"item": first["id"], "location": 3, "player": 2, "flags": 0},
                                       {"item": second["id"], "location": 4, "player": 1, "flags": 0}])
        self.session.tick()
        self.assertIn(("item", f"Received {first['name']} from Steve"), self.lines)
        self.assertIn(("item", f"Received {second['name']} from Cerzix"), self.lines)

    def test_a_new_game_starts_with_what_the_run_has(self):
        self.connected(checked=[5])
        technology, other = data.items()[0], data.items()[1]
        self.server.on_event("scouted", {5: {"item": "Ender Pearl", "player": "Steve", "flags": 1}})
        self.server.on_event("items", [{"item": technology["id"], "location": 3, "player": 2, "flags": 0}])
        self.session.tick()
        run = self.session.profile.run
        self.assertEqual(self.starts[-1], (run, [technology["id"]], [5]))
        self.log("AP_CHECK 9")
        self.server.on_event("items", [{"item": technology["id"], "location": 3, "player": 2, "flags": 0},
                                       {"item": other["id"], "location": 4, "player": 2, "flags": 0}])
        self.session.tick()
        self.assertEqual(self.starts[-1], (run, [technology["id"], other["id"]], [5, 9]))
        self.session.stop()
        self.assertEqual(self.starts[-1], (0, [], []), "without a client a new game belongs to no run")

    def test_checks_made_before_the_client_started_are_sent(self):
        """The game writes its checks to its log, and reports all of them again whenever a save is loaded."""
        self.log("AP_HELLO")
        self.log("AP_CHECK 5")
        self.log("AP_CHECK 1001")
        later = self.connect()
        self.connected(later)
        later.tick()
        self.assertEqual(later.connection.checked, [5, 1001])

    def test_items_received_while_away_reach_the_game(self):
        """The server keeps them, and sends all of them to a client that connects."""
        first, second = data.items()[:2]
        self.connected()
        self.server.on_event("items", [{"item": first["id"], "location": 3, "player": 2, "flags": 0},
                                       {"item": second["id"], "location": 4, "player": 2, "flags": 0}])
        self.session.tick()
        self.assertEqual([item["id"] for item in self.session.bridge.items], [first["id"], second["id"]])
        self.assertIn(("item", "2 items received so far."), self.lines)

    def test_goal_fragments(self):
        self.connected()
        fragment = next(item["id"] for item in data.items() if item["name"] == data.tables.FRAGMENT)
        entry = {"item": fragment, "location": 3, "player": 2, "flags": 1}
        self.server.on_event("items", [entry])
        self.session.tick()
        self.assertFalse(self.server.won)
        self.server.on_event("items", [entry, entry])
        self.session.tick()
        self.assertTrue(self.server.won)

    def test_goal_locations(self):
        self.connected(goal="locations")
        for location in (5, 6):
            self.log(f"AP_CHECK {location}")
        self.session.tick()
        self.assertFalse(self.server.won)
        self.log("AP_CHECK 7")
        self.session.tick()
        self.assertTrue(self.server.won)

    def test_goal_crisis(self):
        self.connected(goal="crisis")
        self.log("AP_HELLO")
        self.session.tick()
        self.assertFalse(self.server.won)
        self.log("AP_GOAL 1")
        self.session.tick()
        self.assertTrue(self.server.won)

    def test_goal_crisis_and_fallen_empires(self):
        self.connected(goal="crisis_and_fallen_empires")
        self.log("AP_GOAL 1")
        self.session.tick()
        self.assertFalse(self.server.won, "an awakened empire is still around")
        self.log("AP_GOAL 2")
        self.session.tick()
        self.assertTrue(self.server.won)

    def test_a_defeated_crisis_is_no_other_goal(self):
        self.connected()
        self.log("AP_GOAL 1")
        self.log("AP_GOAL 2")
        self.session.tick()
        self.assertFalse(self.server.won)

    def test_deathlink(self):
        self.connected(death_link=True)
        self.assertIn({"cmd": "ConnectUpdate", "tags": ["DeathLink"]}, self.server.sent)
        bridge = self.session.bridge
        self.assertEqual((bridge.deaths_per_doom, bridge.doom, bridge.death_effect, bridge.doom_capital),
                         (2, "tomb", "fleet", True))
        self.server.on_event("death", {"source": "Steve", "cause": "Steve fell into lava"})
        self.session.tick()
        self.assertEqual(self.session.bridge.deaths, 1)
        self.assertIn(("death", "DeathLink: Steve fell into lava"), self.lines)

    def test_deathlink_off(self):
        self.connected()
        self.assertEqual(self.server.sent, [], "no DeathLink for this client")
        self.assertEqual(self.session.bridge.deaths_per_doom, 2, "the test in the menu in game still works")
        self.session.tick()
        self.log("AP_DEATH 1 High King Zog")
        self.session.tick()
        self.assertEqual(self.server.died, [])
        self.assertIn(("death", "Your ruler High King Zog has died."), self.lines)

    def test_deaths_in_the_game_are_sent(self):
        self.connected(death_link=True, death_causes=["ruler", "colony"])
        now = [1000.0]
        self.session.clock = lambda: now[0]
        self.session.tick()
        self.log("AP_DEATH 2 Admiral Vex")
        self.log("AP_DEATH 5 New Hope")
        self.log("AP_DEATH 1 High King Zog")
        self.session.tick()
        self.assertEqual(self.server.died, ["Cerzix's colony New Hope was destroyed."],
                         "leaders are not a cause here, and one death in a minute is enough")
        now[0] += session.DEATH_COOLDOWN_SECONDS + 1
        self.log("AP_DEATH 1 [From.GetName]")
        self.session.tick()
        self.assertEqual(self.server.died[-1], "Cerzix's ruler has died.")

    def test_a_lost_battle_is_a_death(self):
        for causes in (["battle"], ["fleet"]):
            again = self.connect()
            self.connected(again, death_link=True, death_causes=causes)
            again.tick()
            self.log("AP_DEATH 3 1st Fleet")
            again.tick()
            self.assertEqual(again.connection.died, ["Cerzix's fleet 1st Fleet lost a battle."], causes)

    def test_death_texts(self):
        self.assertEqual(session.death_text("Your", 3, "1st Fleet"), "Your fleet 1st Fleet lost a battle.")
        self.assertEqual(session.death_text("Steve's", 4, ""), "Steve's colony was invaded.")
        self.assertEqual(set(session.DEATH_TEXT), set(session.DEATHS))

    def test_what_is_typed(self):
        self.connected()
        self.session.command("!hint Destroyers")
        self.session.command("hello there")
        self.session.command("/status")
        self.session.command("/nonsense")
        self.assertEqual(self.server.said, ["!hint Destroyers", "hello there"])
        self.assertIn(("info", f"0 of {len(data.locations())} locations checked, 0 items received"), self.lines)
        self.assertEqual(self.lines[-1][0], "error")

    def test_server_messages_are_shown_by_their_kind(self):
        self.connected()
        self.server.on_event("print", [("Steve", "player"), (" found it", "text")], "Hint")
        self.server.on_event("print", [("Steve: hi", "text")], "Chat")
        self.server.on_event("refused", ["InvalidSlot"])
        self.session.tick()
        self.assertIn(("hint", "Steve found it"), self.lines)
        self.assertIn(("chat", "Steve: hi"), self.lines)
        self.assertIn(("error", "The server refused: there is no slot with that name"), self.lines)

    def test_warns_about_another_empire_and_missing_dlc(self):
        self.connected(empire_type="machine", owned_dlc=[data.dlcs()[0], data.dlcs()[1]])
        self.log("AP_HELLO")
        self.log("AP_DLC 2")
        self.log("AP_EMPIRE 1")
        self.session.tick()
        errors = [text for kind, text in self.lines if kind == "error"]
        self.assertEqual(len(errors), 2)
        self.assertIn("made for a machine empire, but you play a regular one", errors[0])
        self.assertIn(data.dlcs()[0], errors[1])
        self.assertNotIn(data.dlcs()[1], errors[1])


class BootstrapTest(unittest.TestCase):
    def test_what_is_there_is_not_installed(self):
        installed = []
        self.assertIs(bootstrap.require("json", install=installed.append), __import__("json"))
        self.assertEqual(installed, [])

    def test_a_missing_package_is_installed_once(self):
        with tempfile.TemporaryDirectory() as folder:
            def install(package):
                installed.append(package)
                (Path(folder) / f"{package}.py").write_text("VALUE = 5\n")

            installed, shown = [], []
            sys.path.insert(0, folder)
            self.addCleanup(sys.path.remove, folder)
            module = bootstrap.require("ap_test_package_one", install=install, notice=shown.append)
            self.assertEqual((module.VALUE, installed), (5, ["ap_test_package_one"]))
            self.assertIn("installing ap_test_package_one", shown[0])
            bootstrap.require("ap_test_package_one", install=install, notice=shown.append)
            self.assertEqual(len(installed), 1)

    def test_a_failed_install_says_what_to_do(self):
        class Failed:
            stderr = "no network"

        with self.assertRaises(ImportError) as raised:
            bootstrap.require("ap_test_package_two", install=lambda package: Failed(), notice=lambda text: None)
        self.assertIn("pip install ap_test_package_two", str(raised.exception))
        self.assertIn("no network", str(raised.exception))

    def test_the_connection_asks_for_websockets(self):
        source = Path(archipelago.__file__).read_text(encoding="utf-8")
        self.assertIn('websockets = require("websockets")', source)
        self.assertNotIn("\nimport websockets", source)


class OfflineSessionTest(unittest.TestCase):
    def test_a_check_finds_an_item(self):
        with tempfile.TemporaryDirectory() as folder:
            user_dir = Path(folder)
            (user_dir / "logs").mkdir()
            original = build_mod.write_check_names
            build_mod.write_check_names = lambda names=None, players=None: None
            self.addCleanup(setattr, build_mod, "write_check_names", original)
            keep_mod_files(self)
            lines = []
            profile = Profiles(user_dir / "profiles.json").new_offline()
            offline = OfflineSession(user_dir, lambda kind, parts: lines.append((kind, app.plain(parts))), profile,
                                     shuffle, delivery="manual")
            self.assertTrue(offline.ready)
            (user_dir / "logs" / "game.log").write_text("AP_HELLO\nAP_CHECK 5\n", encoding="utf-8")
            offline.tick()
            found = shuffle(profile.seed)[5]
            self.assertEqual(profile.sent, [[found, session.OFFLINE_SLOT]])
            self.assertEqual([item["id"] for item in offline.bridge.items], [found])
            self.assertTrue(any(kind == "check" for kind, _ in lines))
            for test_command in ("/item mineral cache", "/death", "/doom"):
                offline.command(test_command)
                self.assertEqual(lines[-1][0], "error", "the commands for testing are gone")
            self.assertEqual(len(profile.sent), 1)
            self.assertEqual(offline.bridge.deaths, 0)


class AppTest(unittest.TestCase):
    def test_the_window_shows_what_is_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            user_dir = Path(folder)
            (user_dir / "logs").mkdir()
            original = build_mod.write_check_names
            build_mod.write_check_names = lambda names=None, players=None: None
            self.addCleanup(setattr, build_mod, "write_check_names", original)
            keep_mod_files(self)
            window = app.App(Profiles(user_dir / "profiles.json"), user_dir, log_file=None, delivery="manual")
            try:
                window.log("item", [("Received ", "text"), ("Destroyers", "progression"), (" from ", "text"),
                                    ("Steve", "player")])
                window.requests.put(("command", "/offline"))
                window.requests.put(("command", "/status"))
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not (window.session and window.lines.empty()):
                    window.window.update()
                    time.sleep(0.05)
                for _ in range(10):
                    window.window.update()
                    time.sleep(0.05)
                text = window.text.get("1.0", "end")
                self.assertIn("ITEM   Received Destroyers from Steve", text)
                self.assertIn("Offline shuffle 1", text)
                self.assertIn(f"0 of {len(data.locations())} locations, 0 items", text)
                self.assertEqual(str(window.play["state"]), "normal")
                self.assertFalse(hasattr(window, "offline_menu"), "offline is a command, not a button")
                self.assertIn("progression", window.text.tag_names(window.text.search("Destroyers", "1.0")))
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
