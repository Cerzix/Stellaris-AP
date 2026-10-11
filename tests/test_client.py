import tempfile
import threading
import time
import unittest
from pathlib import Path

from stellaris_ap import data
from stellaris_ap import app, client, session
from stellaris_ap.client import GameWatch, shuffle
from stellaris_ap.mailbox import MAX_RUN
from stellaris_ap.paths import MOD_DIR, REPO
from stellaris_ap.profiles import Profiles


class OfflineGameTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "profiles.json"

    def test_shuffle_puts_every_item_on_one_location(self):
        placement = shuffle(1)
        locations = [location["id"] for location in data.locations()]
        self.assertEqual(sorted(placement), sorted(locations))
        self.assertEqual(len(placement), len(set(placement)))
        self.assertEqual(placement, shuffle(1))
        self.assertNotEqual(placement, shuffle(2))

    def test_ascension_slots_are_not_behind_ascension_perks(self):
        slot = next(item["id"] for item in data.items() if item["name"] == data.PROGRESSIVE_ASCENSION)
        perks = [location["id"] for location in data.locations() if location["kind"] == "perk"]
        for seed in range(200):
            placement = shuffle(seed)
            self.assertNotIn(slot, [placement[perk] for perk in perks], seed)
            self.assertEqual(list(placement.values()).count(slot), data.ASCENSION_PERK_SLOTS, seed)

    def test_shuffle_holds_every_technology_and_some_traditions(self):
        found = list(shuffle(5).values())
        items = {item["id"]: item for item in data.items()}
        technologies = [technology["id"] for technology in data.technologies() if technology["kind"] == "item"]
        traditions = [item for item in found if "add_tradition" in items[item]["effect"]]
        self.assertLessEqual(set(technologies), set(found))
        self.assertEqual(len(traditions), data.TREE_SLOTS * data.TRADITIONS_PER_TREE)
        self.assertEqual(len(traditions), len(set(traditions)), "no tradition twice")
        self.assertNotEqual(sorted(traditions), sorted(
            item for item in shuffle(6).values() if "add_tradition" in items[item]["effect"]))

    def test_a_check_sends_its_item_once(self):
        profile = Profiles(self.path).new_offline()
        placement = shuffle(profile.seed)
        location = data.locations()[0]["id"]
        self.assertEqual(profile.check(location, placement, 1), placement[location])
        self.assertIsNone(profile.check(location, placement, 1))
        self.assertIsNone(profile.check(999999, placement, 1))
        self.assertEqual(profile.sent, [[placement[location], 1]])

    def test_runs_are_kept(self):
        store = Profiles(self.path)
        first = store.new_offline()
        second = store.new_offline()
        self.assertNotEqual(first.run, second.run)
        self.assertNotEqual(first.seed, second.seed)
        self.assertTrue(1 <= first.run <= MAX_RUN)
        placement = shuffle(first.seed)
        one, two = (location["id"] for location in data.locations()[:2])
        first.check(two, placement, 1)
        first.send(10001)
        first.check(one, placement, 1)
        again = Profiles(self.path).get(first.run)
        self.assertEqual((again.seed, again.name), (first.seed, "Offline shuffle 1"))
        self.assertEqual(again.sent, [[placement[two], 1], [10001, 0], [placement[one], 1]])
        self.assertEqual(again.checked, [two, one])
        self.assertEqual(Profiles(self.path).get(second.run).checked, [], "a run of its own")

    def test_the_run_played_last_comes_first(self):
        store = Profiles(self.path)
        first = store.new_offline()
        second = store.new_offline()
        first.state["played"] = second.state["played"] + 60
        self.assertEqual([profile.run for profile in store.all()], [first.run, second.run])
        store.delete(first.run)
        self.assertEqual([profile.run for profile in Profiles(self.path).all()], [second.run])
        self.assertIsNone(store.get(first.run))

    def test_a_run_in_the_offline_list(self):
        profile = Profiles(self.path).new_offline()
        profile.check(data.locations()[0]["id"], shuffle(profile.seed), 1)
        self.assertEqual(app.describe(profile), f"Offline shuffle 1  (1 of {len(data.locations())} locations)")

    def test_a_slot_of_a_multiworld_is_one_run(self):
        store = Profiles(self.path)
        first = store.server("SEED1", 2, "archipelago.gg:38281", "Cerzix")
        again = Profiles(self.path).server("SEED1", 2, "localhost:38281", "Cerzix")
        other_slot = store.server("SEED1", 3, "archipelago.gg:38281", "Friend")
        other_seed = Profiles(self.path).server("SEED2", 2, "archipelago.gg:38281", "Cerzix")
        self.assertEqual(again.run, first.run, "the same multiworld at another address")
        self.assertEqual(len({first.run, other_slot.run, other_seed.run}), 3)
        self.assertEqual(Profiles(self.path).recent_servers()[0], ("archipelago.gg:38281", "Cerzix"))


class BackgroundTest(unittest.TestCase):
    def watch(self, pids: list):
        self.now = 0.0
        return GameWatch(find_game=lambda: pids[0], clock=lambda: self.now)

    def test_client_waits_for_the_game_and_leaves_with_it(self):
        pids = [None]
        watch = self.watch(pids)
        self.assertFalse(watch.game_is_over(), "the game is still starting")
        self.now += 60
        pids[0] = 1234
        self.assertFalse(watch.game_is_over())
        self.now += 3600
        self.assertFalse(watch.game_is_over())
        self.now += 60
        pids[0] = None
        self.assertTrue(watch.game_is_over())

    def test_client_gives_up_if_the_game_never_starts(self):
        watch = self.watch([None])
        self.now += client.GAME_START_SECONDS - 1
        self.assertFalse(watch.game_is_over())
        self.now += 60
        self.assertTrue(watch.game_is_over())

    def test_only_one_client(self):
        first = client.only_instance(wait=0)
        if first is None:
            self.skipTest("a client is running")
        self.addCleanup(first.close)
        self.assertFalse(client.asked_to_quit(first))
        self.assertIsNone(client.only_instance(wait=0))

    def test_a_new_client_takes_over(self):
        first = client.only_instance(wait=0)
        if first is None:
            self.skipTest("a client is running")
        result = []
        starting = threading.Thread(target=lambda: result.append(client.only_instance(wait=10)))
        starting.start()
        deadline = time.monotonic() + 5
        while not client.asked_to_quit(first):
            self.assertLess(time.monotonic(), deadline, "the new client did not ask")
            time.sleep(0.05)
        first.close()
        starting.join(10)
        self.assertIsNotNone(result[0])
        result[0].close()

    def test_menu_options_match_the_mod(self):
        events = (MOD_DIR / "events" / "ap_events.txt").read_text(encoding="utf-8")
        menu = events[events.index("id = ap.100"):]
        self.assertNotIn("shuffle", menu, "a new run is made in the launcher")
        for option, number in (("death", session.MENU_DEATH), ("doom", session.MENU_DOOM)):
            self.assertRegex(menu, rf'name = ap\.100\.{option}\s+hidden_effect = \{{ log = "AP_CMD {number}" \}}')

    def test_launcher_starts_the_client_and_the_game(self):
        script = (REPO / "Play Stellaris Archipelago.bat").read_text(encoding="utf-8")
        self.assertIn("pythonw -m stellaris_ap.app", script)
        self.assertEqual(app.STELLARIS, "steam://rungameid/281990")


if __name__ == "__main__":
    unittest.main()
