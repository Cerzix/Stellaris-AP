import tempfile
import unittest
from pathlib import Path

from stellaris_ap import bridge as bridge_module
from stellaris_ap.bridge import Bridge, LogTailer, render_run_file


class LogTailerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.log = Path(self.dir.name) / "game.log"

    def append(self, text: str) -> None:
        with open(self.log, "ab") as f:
            f.write(text.encode("utf-8"))

    def test_missing_file(self):
        self.assertEqual(LogTailer(self.log).poll(), [])

    def test_parses_ap_lines_only(self):
        tailer = LogTailer(self.log)
        self.append("[08:43:15][game_application.cpp:248]: Game Version: Pegasus v4.4.3\n"
                    "[08:50:01][effect.cpp:1]: AP_HELLO\r\n"
                    "[08:50:02][effect.cpp:1]: AP_CHECK 7\n"
                    "[08:50:03][effect.cpp:1]: AP_ACK 12\n")
        self.assertEqual(tailer.poll(), [("HELLO", None, ""), ("CHECK", 7, ""), ("ACK", 12, "")])
        self.assertEqual(tailer.poll(), [])

    def test_a_line_can_carry_a_name(self):
        tailer = LogTailer(self.log)
        self.append("[2210.03.01] Log effect, events/ap_events.txt line: 8. AP_DEATH 1 High King Zog the Third\r\n"
                    "AP_DEATH 5 [This.GetName]\nAP_DEATH 3\n")
        self.assertEqual(tailer.poll(), [("DEATH", 1, "High King Zog the Third"), ("DEATH", 5, "[This.GetName]"),
                                         ("DEATH", 3, "")])

    def test_waits_for_complete_lines(self):
        tailer = LogTailer(self.log)
        self.append("[08:50:02][effect.cpp:1]: AP_CHECK 1")
        self.assertEqual(tailer.poll(), [])
        self.append("2\n")
        self.assertEqual(tailer.poll(), [("CHECK", 12, "")])

    def test_game_restart_truncates_log(self):
        tailer = LogTailer(self.log)
        self.append("x" * 200 + "\nAP_CHECK 1\n")
        self.assertEqual(tailer.poll(), [("CHECK", 1, "")])
        self.log.write_bytes(b"AP_CHECK 2\n")
        self.assertEqual(tailer.poll(), [("CHECK", 2, "")])
        self.assertTrue(tailer.restarted)


class RunFileTest(unittest.TestCase):
    def test_commands_mode_is_one_command_per_line(self):
        text = render_run_file(["add_resource = {\n\tminerals = 5\n}", "add_resource = { energy = 5 }"])
        lines = text.split("\n")
        self.assertEqual(len(lines), 4, "an empty last line shows up as an unknown command in the console")
        self.assertTrue(all(line.startswith("effect event_target:ap_player = { ") for line in lines))
        self.assertIn("value < 1 } } add_resource = { minerals = 5 } set_variable = "
                      "{ which = ap_item_index value = 1 }", lines[0])
        self.assertIn("value < 2 }", lines[1])
        self.assertIn('log = "AP_ACK 2"', lines[2])
        self.assertIn("ap_report_checks = yes", lines[3])

    def test_braces_balance(self):
        for mode in ("commands", "script"):
            text = render_run_file(["add_resource = { energy = 5 }"] * 3, mode)
            self.assertEqual(text.count("{"), text.count("}"))

    def test_no_items(self):
        self.assertIn('log = "AP_ACK 0"', render_run_file([], "script"))


ENERGY = {"id": 2, "name": "Energy Cache", "effect": "add_resource = { energy = 5 }"}


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.user_dir = Path(self.dir.name)
        (self.user_dir / "logs").mkdir()
        self.checks = []
        self.triggers = 0
        self.foreground = True
        self.patch(bridge_module.console, "stellaris_is_foreground", lambda: self.foreground)
        self.patch(bridge_module.console, "rerun_last_command", self.count_trigger)
        self.patch(bridge_module, "FOREGROUND_SETTLE_SECONDS", 0)
        self.bridge = Bridge(self.user_dir, self.checks.append, delivery="console", say=lambda text: None)

    def patch(self, target, name, value):
        original = getattr(target, name)
        setattr(target, name, value)
        self.addCleanup(setattr, target, name, original)

    def count_trigger(self):
        self.triggers += 1

    def log(self, text: str) -> None:
        with open(self.user_dir / "logs" / "game.log", "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def test_checks_are_reported_once(self):
        self.log("AP_CHECK 3")
        self.log("AP_CHECK 3")
        self.log("AP_CHECK 4")
        self.bridge.tick()
        self.assertEqual(self.checks, [3, 4])

    def test_items_trigger_the_console_until_acked(self):
        self.bridge.set_items([ENERGY])
        self.bridge.tick()
        self.assertEqual(self.triggers, 0, "no game loaded yet")

        self.log("AP_HELLO")
        self.bridge.tick()
        self.assertEqual(self.triggers, 1)
        self.bridge.tick()
        self.assertEqual(self.triggers, 1, "waits before pressing keys again")

        self.log("AP_ACK 1")
        self.bridge.last_trigger = 0
        self.bridge.tick()
        self.assertEqual(self.triggers, 1)
        self.assertIn("energy", (self.user_dir / "ap.txt").read_text())

    def test_no_keys_while_stellaris_is_in_the_background(self):
        self.foreground = False
        self.bridge.set_items([ENERGY])
        self.log("AP_HELLO")
        self.bridge.tick()
        self.assertEqual(self.triggers, 0)

    def test_waits_after_switching_to_stellaris(self):
        bridge_module.FOREGROUND_SETTLE_SECONDS = 2
        self.bridge.set_items([ENERGY])
        self.log("AP_HELLO")
        self.bridge.tick()
        self.assertEqual(self.triggers, 0)
        self.bridge.foreground_since -= 2
        self.bridge.tick()
        self.assertEqual(self.triggers, 1)

    def death_mailbox(self):
        class FakeMailbox:
            dooms = []
            notices = []

            def request_doom(self, kind, capital=False):
                self.dooms.append((kind, capital))

            def request_death_notice(self, deaths, deaths_per_doom, effect):
                self.notices.append((deaths, deaths_per_doom, effect))

            def reset(self):
                pass

            def poll(self, item_ids):
                pass

        return FakeMailbox()

    def test_deaths_add_up_to_a_doom(self):
        mailbox = self.death_mailbox()
        bridge = Bridge(self.user_dir, self.checks.append, say=lambda text: None, mailbox=mailbox,
                        deaths_per_doom=3, doom="tomb", death_effect="leader", doom_capital=True)
        for _ in range(7):
            bridge.receive_death()
        self.assertEqual(mailbox.dooms, [("tomb", True), ("tomb", True)])
        self.assertEqual(mailbox.notices, [(1, 3, "leader"), (2, 3, "leader"), (1, 3, "leader"), (2, 3, "leader"),
                                           (1, 3, "leader")], "every death that is not a doom takes something")
        bridge.send_doom()
        self.assertEqual(len(mailbox.dooms), 3)

    def test_a_death_takes_a_leader_or_a_fleet(self):
        mailbox = self.death_mailbox()
        picks = iter(["fleet", "leader", "fleet"])
        bridge = Bridge(self.user_dir, self.checks.append, say=lambda text: None, mailbox=mailbox,
                        deaths_per_doom=0, death_effect="random", pick=lambda choices: next(picks))
        for _ in range(3):
            bridge.receive_death()
        self.assertEqual(mailbox.notices, [(1, 0, "fleet"), (2, 0, "leader"), (3, 0, "fleet")])
        self.assertEqual(mailbox.dooms, [], "without a doom the deaths are only counted")
        quiet = self.death_mailbox()
        Bridge(self.user_dir, self.checks.append, say=lambda text: None, mailbox=quiet,
               death_effect="none").receive_death()
        self.assertEqual(quiet.notices, [(1, 0, "none")])

    def test_items_go_to_the_mailbox_with_their_sender(self):
        class FakeMailbox:
            polled = None

            def poll(self, item_ids):
                self.polled = item_ids

        mailbox = FakeMailbox()
        bridge = Bridge(self.user_dir, self.checks.append, say=lambda text: None, mailbox=mailbox)
        bridge.set_items([ENERGY, {**ENERGY, "sender": 3}])
        bridge.tick()
        self.assertEqual(mailbox.polled, [2, 300002])

    def test_menu_commands(self):
        commands = []
        self.log("AP_CMD 2")
        bridge = Bridge(self.user_dir, self.checks.append, delivery="manual", say=lambda text: None,
                        on_command=commands.append)
        bridge.tick()
        self.assertEqual(commands, [], "picked before the client started")
        self.log("AP_CMD 1")
        self.log("AP_CMD 3")
        bridge.tick()
        self.assertEqual(commands, [1, 3])

    def test_game_reports_its_dlcs_and_empire(self):
        said = []
        bridge = Bridge(self.user_dir, self.checks.append, delivery="manual", say=said.append)
        self.log("AP_HELLO")
        self.log("AP_DLC 2")
        self.log("AP_DLC 5")
        self.log("AP_EMPIRE 3")
        bridge.tick()
        self.assertEqual((bridge.game_dlcs, bridge.game_empire), ({2, 5}, "machine"))
        self.assertIn("Stellaris: machine empire, 2 of the DLCs that matter", said)
        self.log("AP_HELLO")
        self.log("AP_EMPIRE 1")
        bridge.tick()
        self.assertEqual((bridge.game_dlcs, bridge.game_empire), (set(), "regular"), "another game was loaded")

    def test_checks_wait_until_the_save_told_its_run(self):
        class FakeMailbox:
            run = 42
            bound = None

            def reset(self):
                self.bound = None

            def poll(self, item_ids):
                pass

        mailbox = FakeMailbox()
        bridge = Bridge(self.user_dir, self.checks.append, say=lambda text: None, mailbox=mailbox)
        self.log("AP_HELLO")
        self.log("AP_CHECK 3")
        bridge.tick()
        self.assertEqual(self.checks, [], "the save may belong to another run")
        mailbox.bound = True
        self.log("AP_CHECK 4")
        bridge.tick()
        self.assertEqual(self.checks, [3, 4])
        # A save of another run is loaded: its checks are dropped
        self.log("AP_HELLO")
        self.log("AP_CHECK 9")
        bridge.tick()
        self.assertIsNone(mailbox.bound)
        mailbox.bound = False
        bridge.tick()
        self.log("AP_CHECK 10")
        bridge.tick()
        self.assertEqual(self.checks, [3, 4])
        # And the save of the run again
        self.log("AP_HELLO")
        self.log("AP_CHECK 3")
        self.log("AP_CHECK 5")
        mailbox.bound = None
        bridge.tick()
        mailbox.bound = True
        bridge.tick()
        self.assertEqual(self.checks, [3, 4, 5])

    def test_goals_wait_until_the_save_told_its_run(self):
        class FakeMailbox:
            run = 42
            bound = None

            def reset(self):
                self.bound = None

            def poll(self, item_ids):
                pass

        mailbox = FakeMailbox()
        bridge = Bridge(self.user_dir, self.checks.append, say=lambda text: None, mailbox=mailbox)
        self.log("AP_HELLO")
        self.log("AP_GOAL 1")
        bridge.tick()
        self.assertEqual(bridge.goals, set())
        mailbox.bound = False
        bridge.tick()
        self.assertEqual(bridge.goals, set(), "the save of another run has won nothing here")
        self.log("AP_HELLO")
        self.log("AP_GOAL 1")
        self.log("AP_GOAL 2")
        bridge.tick()
        mailbox.bound = True
        bridge.tick()
        self.assertEqual(bridge.goals, {"crisis", "crisis_and_fallen_empires"})
        self.log("AP_HELLO")
        bridge.tick()
        self.assertEqual(bridge.goals, set(), "another save was loaded")

    def test_deaths_in_the_game(self):
        deaths = []
        self.log("AP_DEATH 1 Old King")
        bridge = Bridge(self.user_dir, self.checks.append, delivery="manual", say=lambda text: None,
                        on_death=lambda number, name: deaths.append((number, name)))
        bridge.tick()
        self.assertEqual(deaths, [], "died before the client started")
        self.log("AP_DEATH 1 High King Zog")
        self.log("AP_DEATH 4 [This.GetName]")
        self.log("AP_DEATH 9 Nobody")
        bridge.tick()
        self.assertEqual(deaths, [(1, "High King Zog"), (4, "")], "a name the game did not fill in is left out")

    def test_loading_a_save_reapplies_items(self):
        self.bridge.set_items([ENERGY])
        self.log("AP_HELLO")
        self.log("AP_ACK 1")
        self.bridge.tick()
        self.assertEqual(self.triggers, 0)
        self.log("AP_HELLO")
        self.bridge.tick()
        self.assertEqual(self.triggers, 1)


if __name__ == "__main__":
    unittest.main()
