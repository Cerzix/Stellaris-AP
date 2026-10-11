"""Tests the mailbox against a model of the game: fake memory, and the mod's daily poll in Python."""
import struct
import unittest

from stellaris_ap import data
from stellaris_ap.mailbox import (BIND_RUN, DEATH_EFFECTS, DEATH_NOTICE, DOOM_CAPITAL, DOOM_CODES, MAX_RUN,
                                  MAX_SENDERS, SENDER_FACTOR, WRONG_RUN, Mailbox, death_notice, decode, doom_code,
                                  empty_value, is_doom, item_value)
from stellaris_ap.memory import NAME_CAPACITY, SCALE, VALUE_OFFSET, GameMemory, variable_header


class FakeMemory(GameMemory):
    """A block of memory at address 0x1000 holding variables in the layout of the game."""
    BASE = 0x1000

    def __init__(self):
        self.data = bytearray(4096)
        self.used = 0
        self.running = True
        self.writes = []

    def add_variable(self, name: str, value: int) -> int:
        """Returns the address of the value."""
        start = self.used
        header = variable_header(name).ljust(16, b"\xcc") + struct.pack("<QQ", len(name), NAME_CAPACITY)
        self.data[start:start + 40] = header + struct.pack("<q", value * SCALE)
        self.used += 64
        return self.BASE + start + VALUE_OFFSET

    def alive(self) -> bool:
        return self.running

    def close(self) -> None:
        pass

    def read(self, address: int, size: int) -> bytes:
        offset = address - self.BASE
        return bytes(self.data[offset:offset + size]) if 0 <= offset <= len(self.data) - size else b""

    def heap_regions(self):
        yield self.BASE, len(self.data)

    def write_value(self, address: int, value: int) -> bool:
        self.writes.append(address)
        offset = address - self.BASE
        self.data[offset:offset + 8] = struct.pack("<q", value * SCALE)
        return True


class FakeGame:
    """A save: its variables, and ap_poll_mailbox as in the mod."""

    def __init__(self, memory: FakeMemory, items_applied: int = 0, dooms: int = 0, run: int = 0):
        self.memory = memory
        self.items_applied = items_applied
        self.dooms = dooms
        self.run = run
        self.told_wrong_run = 0
        self.doomed = []
        self.notices = []
        self.parity = 0
        self.granted = []
        self.address = memory.add_variable("ap_mailbox", -1)

    def day(self) -> None:
        mailbox = self.memory.read_value(self.address)
        if is_doom(mailbox):
            self.doomed.append(mailbox)
            self.dooms += 1
        elif DEATH_NOTICE <= mailbox < DEATH_NOTICE + 30000:
            effect, rest = divmod(mailbox - DEATH_NOTICE, 10000)
            self.notices.append((*divmod(rest, 100), effect))
            self.dooms += 1
        elif mailbox == WRONG_RUN:
            self.told_wrong_run += 1
            self.dooms += 1
        elif BIND_RUN <= mailbox < BIND_RUN + 10000:
            if self.run == 0:
                self.run = mailbox - BIND_RUN
            self.dooms += 1
        elif mailbox > 0:
            self.granted.append(mailbox)
            self.items_applied += 1
        self.parity = 1 - self.parity
        offset = self.address - FakeMemory.BASE
        self.memory.data[offset:offset + 8] = struct.pack(
            "<q", empty_value(self.items_applied, self.parity, self.dooms, self.run) * SCALE)


class ProtocolTest(unittest.TestCase):
    def test_empty_value_round_trip(self):
        for index in (0, 1, 2, 500):
            for parity in (0, 1):
                for dooms in (0, 1, 7, 999):
                    for run in (0, 1, MAX_RUN):
                        self.assertEqual(decode(empty_value(index, parity, dooms, run)), (index, dooms, run))
        self.assertEqual(len({empty_value(index, parity, dooms)
                              for index in range(50) for parity in (0, 1) for dooms in range(3)}), 300)
        self.assertEqual(decode(empty_value(3, 0, 1002, 5)), (3, 2, 5), "signals are counted modulo 1000")
        # The game stores numbers times 100000 in 64 bits
        self.assertLess(abs(empty_value(499000, 1, 999, MAX_RUN)) * SCALE, 2 ** 63)

    def test_items_and_unknown_values_are_not_empty(self):
        for value in (None, -1, 0, 1, 37, 314159, 20001, -1000000, -1000001):
            self.assertIsNone(decode(value))

    def test_doom_codes_are_not_items(self):
        ids = {item["id"] for item in data.items()}
        self.assertFalse(ids & set(DOOM_CODES.values()))
        self.assertLess(max(ids), min(DOOM_CODES.values()))

    def test_item_value_carries_the_sender(self):
        """The mod splits it with a division and a modulo by 100000."""
        self.assertEqual(SENDER_FACTOR, 100000)
        self.assertLess(max(max(item["id"] for item in data.items()), *DOOM_CODES.values()), SENDER_FACTOR)
        self.assertEqual(item_value(611), 611)
        self.assertEqual(divmod(item_value(611, 37), SENDER_FACTOR), (37, 611))
        self.assertEqual(item_value(611, MAX_SENDERS + 1), 611, "no name for this player in game")


class MemoryLayoutTest(unittest.TestCase):
    def test_finds_variables_by_name(self):
        memory = FakeMemory()
        other = memory.add_variable("ap_mailbox_next", 5)
        mailbox = memory.add_variable("ap_mailbox", -4)
        self.assertEqual(memory.find_variable("ap_mailbox"), [mailbox])
        self.assertEqual(memory.find_variable("ap_mailbox_next"), [other])
        self.assertEqual(memory.read_value(mailbox), -4)

    def test_matches_the_layout_seen_in_the_game(self):
        """Bytes around ap_mailbox = 314159 as found in Stellaris 4.5.2."""
        memory = FakeMemory()
        memory.data[0:40] = bytes.fromhex("61705f6d61696c626f78000008000000" "0a00000000000000" "0f00000000000000"
                                          "6097885007000000")
        address = FakeMemory.BASE + 32
        self.assertEqual(memory.find_variable("ap_mailbox"), [address])
        self.assertEqual(memory.read_value(address), 314159)

    def test_rejects_a_freed_copy(self):
        """A copy whose name was overwritten, as found in the game next to the real one."""
        memory = FakeMemory()
        address = memory.add_variable("ap_mailbox", -4)
        memory.data[0] = 0
        self.assertEqual(memory.find_variable("ap_mailbox"), [])
        self.assertFalse(memory.is_variable(address, "ap_mailbox"))

    def test_fractions_are_not_values(self):
        memory = FakeMemory()
        address = memory.add_variable("ap_mailbox", 3)
        memory.data[32:40] = struct.pack("<q", 3 * SCALE + 1)
        self.assertIsNone(memory.read_value(address))

    def test_long_names_are_refused(self):
        with self.assertRaises(ValueError):
            variable_header("ap_a_name_that_is_too_long")


class MailboxTest(unittest.TestCase):
    def setUp(self):
        self.memory = FakeMemory()
        self.now = 0.0
        self.said = []
        self.mailbox = Mailbox(attach=lambda: self.memory, say=self.said.append, clock=lambda: self.now)

    def play(self, game: FakeGame, item_ids: list[int], days: int) -> None:
        for _ in range(days):
            self.now += 1
            self.mailbox.poll(item_ids)
            game.day()

    def test_delivers_items_in_order_once(self):
        game = FakeGame(self.memory)
        self.play(game, [4, 7, 4], days=10)
        self.assertEqual(game.granted, [4, 7, 4])
        self.assertEqual(game.items_applied, 3)
        self.assertIn("Stellaris: 3 item(s) applied", self.said)

    def test_items_arriving_later(self):
        game = FakeGame(self.memory)
        self.play(game, [], days=5)
        self.play(game, [2], days=3)
        self.play(game, [2, 8], days=3)
        self.assertEqual(game.granted, [2, 8])

    def test_a_save_that_is_ahead_gets_only_the_missing_items(self):
        game = FakeGame(self.memory, items_applied=2)
        self.play(game, [4, 7, 9], days=6)
        self.assertEqual(game.granted, [9])

    def test_nothing_is_written_while_the_game_is_paused(self):
        game = FakeGame(self.memory)
        for _ in range(60):
            self.now += 1
            self.mailbox.poll([4])
        self.assertEqual(self.memory.writes, [])
        self.assertIn("Waiting for the game: items arrive while it is not paused", self.said)
        self.play(game, [4], days=4)
        self.assertEqual(game.granted, [4])

    def test_only_the_copy_in_use_is_written_to(self):
        stale = [self.memory.add_variable("ap_mailbox", value) for value in (314159, -2, -5)]
        game = FakeGame(self.memory)
        self.play(game, [4, 7], days=8)
        self.assertEqual(game.granted, [4, 7])
        self.assertEqual(set(self.memory.writes), {game.address})
        for address, value in zip(stale, (314159, -2, -5)):
            self.assertEqual(self.memory.read_value(address), value)

    def test_loading_another_save_moves_the_mailbox(self):
        first = FakeGame(self.memory)
        self.play(first, [4, 7], days=6)
        # The old save's variable is freed, the loaded save is one item behind
        self.memory.data[first.address - FakeMemory.BASE - VALUE_OFFSET] = 0
        second = FakeGame(self.memory, items_applied=1)
        self.mailbox.reset()
        self.play(second, [4, 7], days=6)
        self.assertEqual(second.granted, [7])
        self.assertNotIn(first.address, self.memory.writes[2:])

    def test_notices_a_moved_mailbox_without_being_told(self):
        first = FakeGame(self.memory)
        self.play(first, [4], days=4)
        self.memory.data[first.address - FakeMemory.BASE - VALUE_OFFSET] = 0
        second = FakeGame(self.memory)
        self.play(second, [4], days=40)
        self.assertEqual(second.granted, [4])

    def test_game_closed_and_started_again(self):
        game = FakeGame(self.memory)
        self.play(game, [4], days=4)
        self.memory.running = False
        self.now += 1
        self.mailbox.poll([4])
        self.assertIsNone(self.mailbox.memory)
        self.memory = FakeMemory()
        game = FakeGame(self.memory)
        self.now += 10
        self.play(game, [4], days=5)
        self.assertEqual(game.granted, [4])

    def test_doom(self):
        game = FakeGame(self.memory)
        self.play(game, [4], days=4)
        self.mailbox.request_doom("tomb")
        self.play(game, [4, 7], days=6)
        self.assertEqual(game.doomed, [DOOM_CODES["tomb"]])
        self.assertEqual(game.granted, [4, 7], "items still arrive, once")
        self.assertIn("Stellaris: doom has struck", self.said)

    def test_death_notices_and_doom_arrive_in_order(self):
        game = FakeGame(self.memory)
        self.mailbox.request_death_notice(1, 3, "leader")
        self.mailbox.request_death_notice(2, 3, "fleet")
        self.mailbox.request_doom("cracked")
        self.play(game, [4], days=12)
        self.assertEqual(game.notices, [(1, 3, DEATH_EFFECTS["leader"]), (2, 3, DEATH_EFFECTS["fleet"])])
        self.assertEqual(game.doomed, [DOOM_CODES["cracked"]])
        self.assertEqual(game.granted, [4])
        self.assertEqual(self.said.count("Stellaris: doom has struck"), 1)

    def test_death_notice_codes(self):
        """The mod takes 50000 to 79999 for a death, and splits it with divisions and modulos."""
        self.assertEqual(DEATH_NOTICE, 50000)
        self.assertEqual(DEATH_EFFECTS, {"none": 0, "leader": 1, "fleet": 2})
        self.assertEqual(death_notice(2, 3), 50203)
        self.assertEqual(death_notice(2, 3, "leader"), 60203)
        self.assertEqual(death_notice(7, 0, "fleet"), 70700)
        self.assertEqual(death_notice(500, 500, "fleet"), 79999)
        self.assertGreater(DEATH_NOTICE, BIND_RUN + MAX_RUN)
        self.assertLess(death_notice(500, 500, "fleet"), SENDER_FACTOR)

    def test_doom_codes(self):
        self.assertEqual((doom_code("cracked"), doom_code("tomb")), (20001, 20002))
        self.assertEqual((doom_code("cracked", True), doom_code("tomb", True)), (20011, 20012))
        self.assertEqual(DOOM_CAPITAL, 10)
        for code in (20001, 20002, 20011, 20012):
            self.assertTrue(is_doom(code))
        for code in (WRONG_RUN, 20013, death_notice(1, 3), 5):
            self.assertFalse(is_doom(code))

    def test_a_doom_on_the_capital(self):
        game = FakeGame(self.memory)
        self.mailbox.request_doom("tomb", capital=True)
        self.play(game, [], days=6)
        self.assertEqual(game.doomed, [20012])
        self.assertIn("Stellaris: doom has struck", self.said)

    def test_two_dooms(self):
        game = FakeGame(self.memory, dooms=5)
        self.mailbox.request_doom("cracked")
        self.mailbox.request_doom("cracked")
        self.play(game, [], days=10)
        self.assertEqual(game.doomed, [DOOM_CODES["cracked"]] * 2)

    def test_doom_is_not_taken_for_done_when_another_save_is_loaded(self):
        first = FakeGame(self.memory, dooms=1)
        self.play(first, [], days=4)
        self.mailbox.request_doom("cracked")
        # Before the doom is written a save with more dooms behind it is loaded
        self.memory.data[first.address - FakeMemory.BASE - VALUE_OFFSET] = 0
        second = FakeGame(self.memory, dooms=9)
        self.mailbox.reset()
        self.play(second, [], days=6)
        self.assertEqual(second.doomed, [DOOM_CODES["cracked"]])

    def test_a_new_game_takes_the_run_of_the_client(self):
        mailbox = Mailbox(attach=lambda: self.memory, say=self.said.append, clock=lambda: self.now, run=42)
        self.mailbox = mailbox
        game = FakeGame(self.memory)
        self.play(game, [4, 7], days=10)
        self.assertEqual(game.run, 42)
        self.assertEqual(game.granted, [4, 7], "items only after the save belongs to the run")
        self.assertTrue(mailbox.bound)
        self.assertIn("Stellaris: a new game, it belongs to this run from now on", self.said)

    def test_a_save_of_the_run_goes_on(self):
        self.mailbox = Mailbox(attach=lambda: self.memory, say=self.said.append, clock=lambda: self.now, run=42)
        game = FakeGame(self.memory, items_applied=1, run=42)
        self.play(game, [4, 7], days=6)
        self.assertEqual(game.granted, [7])
        self.assertEqual(game.dooms, 0, "nothing but the item was sent")

    def test_a_save_of_another_run_is_left_alone(self):
        mailbox = Mailbox(attach=lambda: self.memory, say=self.said.append, clock=lambda: self.now, run=42)
        self.mailbox = mailbox
        game = FakeGame(self.memory, run=7)
        mailbox.request_doom("cracked")
        self.play(game, [4, 7], days=12)
        self.assertEqual((game.granted, game.doomed, game.run), ([], [], 7))
        self.assertEqual(game.told_wrong_run, 1, "the player is told once")
        self.assertIs(mailbox.bound, False)
        # Then a save of the run is loaded
        self.memory.data[game.address - FakeMemory.BASE - VALUE_OFFSET] = 0
        mine = FakeGame(self.memory, run=42)
        mailbox.reset()
        self.assertIsNone(mailbox.bound)
        self.play(mine, [4, 7], days=8)
        self.assertEqual(mine.granted, [4, 7])
        self.assertEqual(mine.told_wrong_run, 0)

    def test_a_client_without_a_run_takes_any_save(self):
        game = FakeGame(self.memory, run=7)
        self.play(game, [4], days=5)
        self.assertEqual((game.granted, game.run), ([4], 7))

    def test_game_not_running(self):
        mailbox = Mailbox(attach=lambda: None, say=self.said.append, clock=lambda: self.now)
        mailbox.poll([4])
        self.assertEqual(self.said, [])


if __name__ == "__main__":
    unittest.main()
