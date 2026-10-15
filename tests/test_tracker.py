import tempfile
import tkinter
import unittest
from pathlib import Path

from stellaris_ap import data, tracker
from stellaris_ap.settings import ADJUSTABLE, THEMES, Settings
from stellaris_ap.tracker import TrackerState, build_tree


def counts_of(state: TrackerState) -> dict:
    return tracker.researched(data.technologies(), state)


class TreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = build_tree(data.technologies(), data.locations())

    def test_every_technology_and_location_is_in_the_tree(self):
        for technology in data.technologies():
            self.assertIn(technology["key"], self.tree.nodes)
        locations = {node.location for node in self.tree.nodes.values() if node.location is not None}
        self.assertEqual(locations, {location["id"] for location in data.locations()})
        self.assertEqual(self.tree.nodes["tech_destroyers"].kind, "location")
        self.assertEqual(self.tree.nodes["tech_corvettes"].kind, "base")
        self.assertIsNone(self.tree.nodes["tech_corvettes"].location)
        self.assertEqual(self.tree.nodes["location_1001"].label, "Tree 1: Adopted")

    def test_a_technology_is_right_of_what_comes_before_it(self):
        column = tracker.columns(data.technologies())
        for technology in data.technologies():
            self.assertGreaterEqual(column[technology["key"]], technology["tier"])
            node = self.tree.nodes[technology["key"]]
            for before in node.before:
                self.assertLess(self.tree.nodes[before].x, node.x, technology["key"])
                self.assertIn(technology["key"], self.tree.nodes[before].after)

    def test_nothing_overlaps(self):
        places = [(node.x, node.y) for node in self.tree.nodes.values()]
        self.assertEqual(len(places), len(set(places)))
        for node in self.tree.nodes.values():
            self.assertLessEqual(node.x + tracker.NODE_WIDTH, self.tree.width)
            self.assertLessEqual(node.y + tracker.NODE_HEIGHT, self.tree.height)
        self.assertLess(tracker.NODE_HEIGHT, tracker.ROW)
        self.assertLess(tracker.NODE_WIDTH, tracker.COLUMN)

    def test_the_areas_are_bands_below_each_other(self):
        self.assertEqual([band.key for band in self.tree.bands], ["picks", "physics", "society", "engineering"])
        bands = {band.key: band for band in self.tree.bands}
        for technology in data.technologies():
            band = bands[technology["area"]]
            later = [other.y for other in self.tree.bands if other.y > band.y]
            node = self.tree.nodes[technology["key"]]
            self.assertIn(node.key, band.nodes)
            self.assertGreater(node.y, band.y)
            if later:
                self.assertLess(node.y, min(later))

    def test_a_folded_band_takes_no_room(self):
        folded = build_tree(data.technologies(), data.locations(), ["society", "picks"])
        bands = {band.key: band for band in folded.bands}
        self.assertTrue(bands["society"].collapsed)
        self.assertFalse(bands["physics"].collapsed)
        self.assertTrue(all(folded.nodes[key].hidden for key in bands["society"].nodes + bands["picks"].nodes))
        self.assertFalse(any(folded.nodes[key].hidden for key in bands["physics"].nodes))
        self.assertLess(folded.height, self.tree.height)
        self.assertEqual(bands["engineering"].y - bands["society"].y, tracker.BAND_GAP + tracker.BAND_TITLE)

    def test_a_cycle_in_the_data_does_not_hang(self):
        technologies = [{"key": "a", "tier": 1, "prerequisites": ["b"]}, {"key": "b", "tier": 1, "prerequisites": ["a"]}]
        self.assertEqual(set(tracker.columns(technologies)), {"a", "b"})


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tree = build_tree(data.technologies(), data.locations())
        self.names = {key: node.label for key, node in self.tree.nodes.items()}
        self.destroyers = self.tree.nodes["tech_destroyers"]
        self.cruisers = self.tree.nodes["tech_cruisers"]
        self.state = TrackerState(
            checked={self.destroyers.location, 1001, 2001},
            holds={self.destroyers.location: ("Ender Pearl", "Steve", "progression", None),
                   self.cruisers.location: ("Blue Lasers", "Cerzix", "trap", "tech_lasers_2")},
            received={self.cruisers.item}, perk_slots=2)

    def test_counts(self):
        counts = tracker.summary(self.state, data.locations())
        self.assertEqual(counts["all"], (3, len(data.locations())))
        self.assertEqual((counts["technology"][0], counts["tradition"], counts["perk"]), (1, (1, 49), (1, 8)))
        text = tracker.summary_text(self.state, data.locations())
        self.assertIn(f"3 of {len(data.locations())} locations checked (0.47%)", text)
        self.assertIn("Items received 1", text)
        everything = TrackerState(checked={location["id"] for location in data.locations()}, goal="Goal: done")
        text = tracker.summary_text(everything, data.locations())
        self.assertIn("(100.00%)", text)
        self.assertNotIn("Goal", text, "the goal has a line of its own")
        without = [location for location in data.locations() if location["kind"] != "tradition"]
        self.assertNotIn("Traditions", tracker.summary_text(self.state, without))
        band = next(band for band in self.tree.bands if band.key == "picks")
        self.assertEqual(tracker.band_text(band, self.tree, self.state), "▾ Traditions and ascension perks   2/57")

    def test_what_is_held(self):
        self.assertEqual(tracker.held(self.state, self.destroyers.location), ("Ender Pearl", "Steve", "progression", None))
        self.assertEqual(tracker.held(self.state, self.cruisers.location)[2], "filler", "a trap is not told apart")
        self.assertEqual(tracker.held(self.state, 9999), ("", "", "filler", None))
        self.state.holds[5] = ("Old", "Steve", "useful")
        self.assertEqual(tracker.held(self.state, 5), ("Old", "Steve", "useful", None), "without an icon")

    def test_a_location_is_called_after_what_it_holds(self):
        """As in the game, where the technology in the place of Destroyers is called after its item."""
        self.assertEqual(tracker.name_of(self.destroyers, self.state), "Ender Pearl")
        self.assertEqual(tracker.name_of(self.cruisers, self.state), "Blue Lasers")
        self.assertEqual(tracker.name_of(self.tree.nodes["tech_battleships"], self.state), "Archipelago Item",
                         "not known yet")
        self.assertEqual(tracker.name_of(self.tree.nodes["location_1002"], self.state), "Archipelago Item")
        self.assertEqual(tracker.name_of(self.tree.nodes["tech_corvettes"], self.state), "Corvettes")
        self.assertEqual(tracker.short("x" * 40), "x" * (tracker.LABEL_LENGTH - 1) + "\u2026")
        self.assertEqual(tracker.short("16 Diamonds"), "16 Diamonds")

    def test_icons(self):
        self.assertEqual(tracker.icon_of(self.tree.nodes["tech_corvettes"], self.state), "tech_corvettes")
        self.assertEqual(tracker.icon_of(self.destroyers, self.state), tracker.ARCHIPELAGO_ICON, "from another game")
        self.assertEqual(tracker.icon_of(self.cruisers, self.state), "tech_lasers_2", "a technology of Stellaris")
        self.assertEqual(tracker.icon_of(self.tree.nodes["tech_battleships"], self.state), tracker.ARCHIPELAGO_ICON)

    def test_what_can_be_researched_now(self):
        """The technologies of a tier come up once six of the tier before are researched in that area."""
        counts = counts_of(self.state)
        self.assertEqual(tracker.status(self.tree.nodes["tech_corvettes"], self.state, counts), "base")
        self.assertEqual(tracker.status(self.destroyers, self.state, counts), "checked")
        self.assertEqual(self.cruisers.technology["tier"], 3)
        self.assertEqual(tracker.status(self.cruisers, self.state, counts), "locked")
        first = [node for node in self.tree.nodes.values() if node.technology
                 and node.technology["area"] == "engineering" and node.technology["tier"] == 1 and node.location]
        second = [node for node in self.tree.nodes.values() if node.technology
                  and node.technology["area"] == "engineering" and node.technology["tier"] == 2 and node.location]
        self.assertEqual(tracker.status(first[0], self.state, counts), "available", "the first tier always is")
        self.assertEqual(tracker.status(second[-1], self.state, counts), "locked")
        # Checked locations and received technologies both are technologies to the game
        self.state.checked |= {node.location for node in first[:4]}
        self.state.received |= {node.item for node in first[4:6]}
        counts = counts_of(self.state)
        self.assertEqual(counts["engineering", 1], tracker.TIER_NEEDS)
        self.assertEqual(tracker.status(second[-1], self.state, counts), "available")
        self.assertEqual(tracker.status(self.cruisers, self.state, counts), "locked", "tier 3 needs tier 2")

    def test_which_traditions_and_perks_can_be_picked(self):
        counts = counts_of(self.state)

        def now(location: int) -> str:
            return tracker.status(self.tree.nodes[f"location_{location}"], self.state, counts)

        self.assertEqual(now(1001), "checked")
        self.assertEqual(now(1002), "available", "its tree is adopted")
        self.assertEqual(now(1008), "available", "the next tree can be adopted")
        self.assertEqual(now(1009), "locked", "its tree is not adopted")
        self.assertEqual(now(1015), "locked", "the tree before it is not adopted")
        self.assertEqual(now(1007), "locked", "a tree is finished by picking all of it")
        self.state.checked |= set(range(1002, 1007))
        self.assertEqual(now(1007), "available")
        self.assertEqual(now(2002), "available", "a second slot was received")
        self.assertEqual(now(2003), "locked")
        self.state.perk_slots = 1
        self.assertEqual(now(2002), "locked", "no slot for it")

    def test_filters(self):
        counts = counts_of(self.state)
        fits = {name: {key for key, node in self.tree.nodes.items() if tracker.fits(node, self.state, counts, name)}
                for name in tracker.FILTERS}
        self.assertIn("tech_destroyers", fits["checked"])
        self.assertIn("tech_destroyers", fits["progression"])
        self.assertEqual(fits["progression"], {"tech_destroyers"})
        self.assertEqual(fits["filler"], {"tech_cruisers"}, "only what is known to hold filler")
        self.assertEqual(fits["received"], {"tech_cruisers"})
        self.assertIn("tech_corvettes", fits["base"])
        self.assertNotIn("tech_destroyers", fits["available"])
        self.assertIn("location_1002", fits["available"])
        self.assertNotIn("trap", tracker.FILTERS)

    def text(self, key: str) -> str:
        return "".join(text for text, _ in tracker.describe(self.tree.nodes[key], self.state, counts_of(self.state),
                                                           self.names))

    def test_what_is_said_about_a_node(self):
        text = self.text("tech_destroyers")
        self.assertTrue(text.startswith("Ender Pearl\nin the place of Destroyers\nEngineering, tier 2"), text[:80])
        self.assertIn("Location: checked", text)
        self.assertIn("Holds Ender Pearl for Steve", text)
        self.assertIn("The technology itself: not received yet", text)
        self.assertIn("Comes after\n  Corvettes", text)
        self.assertIn("Leads to\n", text)
        self.assertIn("  Cruisers\n", text)
        text = self.text("tech_cruisers")
        # Destroyers is of tier 2 and checked: one of the six
        self.assertIn("Location: comes up after 5 more technologies of tier 2 in Engineering", text)
        self.assertIn("The technology itself: received", text)
        self.assertIn("What it holds is not known yet", self.text("tech_battleships"))
        self.assertTrue(self.text("tech_battleships").startswith("Archipelago Item\nin the place of Battleships\n"))
        self.assertIn("A base technology", self.text("tech_corvettes"))
        self.assertIn("A repeatable technology", self.text("tech_repeatable_weapon_type_energy_damage"))
        self.assertIn("Needs Apocalypse", self.text("tech_titans"))
        self.assertIn("in the place of Tree 1: Adopted", self.text("location_1001"))
        self.assertIn("Location: can be picked now", self.text("location_1002"))

    def test_received_traditions_are_listed(self):
        tree = tracker.build_tree(data.technologies(), data.locations(), trees=data.normal_trees())
        self.assertEqual([band.key for band in tree.bands], ["picks", "traditions", "physics", "society", "engineering"])
        band = tree.bands[1]
        traditions = [item for item in data.items() if item["kind"] == "tradition"]
        self.assertEqual(len(band.nodes), len(traditions))
        first = traditions[0]
        node = tree.nodes[f"tradition_{first['id']}"]
        self.assertEqual((node.label, node.kind, node.item, node.location), (first["name"], "tradition", first["id"], None))
        self.assertTrue(node.group)
        state = TrackerState(received={first["id"]})
        self.assertEqual(tracker.band_text(band, tree, state), "▾ Archipelago Traditions   1 received")
        self.assertTrue(tracker.fits(node, state, {}, "received"))
        said = "".join(text for text, _ in tracker.describe(node, state, {}, {}))
        self.assertIn(f"A tradition of {node.group}", said)
        self.assertIn("The tradition itself: received", said)
        self.assertIn(node.key, tracker.matches(tree, state, first["name"]))
        places = [(other.x, other.y) for other in tree.nodes.values()]
        self.assertEqual(len(places), len(set(places)), "nothing overlaps")
        # Not shuffled: neither the locations nor the list
        plain = tracker.build_tree(data.technologies(), [location for location in data.locations()
                                                         if location["kind"] != "tradition"])
        self.assertEqual([band.key for band in plain.bands], ["picks", "physics", "society", "engineering"])
        self.assertEqual(len(plain.bands[0].nodes), data.ASCENSION_PERK_SLOTS)

    def test_a_hidden_location_is_not_found_by_the_name_of_its_place(self):
        hidden = self.state.without_spoilers()
        self.assertIn("tech_destroyers", tracker.matches(self.tree, hidden, "Destroyer"), "checked, so it is shown")
        self.assertNotIn("tech_cruisers", tracker.matches(self.tree, hidden, "Cruisers"))
        self.assertIn("tech_cruisers", tracker.matches(self.tree, self.state, "Cruisers"))
        self.assertIn("tech_corvettes", tracker.matches(self.tree, hidden, "Corvettes"), "a base technology is no secret")

    def test_what_can_be_researched_or_picked_now_is_named_without_spoilers(self):
        # Tree 1 is adopted: its first tradition can be picked, the one of tree 2 can not
        self.state.holds[1002] = ("Hookshot", "Link", "progression", None)
        self.state.holds[1009] = ("Bombs", "Link", "useful", None)
        shown = tracker.open_locations(self.tree, data.technologies(), self.state)
        self.assertIn(1002, shown)
        self.assertNotIn(1009, shown)
        self.assertNotIn(self.cruisers.location, shown, "its tier is not open")
        self.assertNotIn(1001, shown, "checked, which is shown anyway")
        hidden = self.state.without_spoilers(shown)
        self.assertEqual(set(hidden.holds), {self.destroyers.location, 1002})
        self.assertEqual(tracker.name_of(self.tree.nodes["location_1002"], hidden), "Hookshot")
        self.assertEqual(tracker.name_of(self.tree.nodes["location_1009"], hidden), tracker.UNKNOWN_ITEM)

    def test_a_tradition_tree_is_a_block_from_its_adoption_down_to_its_finish(self):
        for slot in range(data.TREE_SLOTS):
            block = [self.tree.nodes[f"location_{data.tradition_location(slot, position)}"]
                     for position in range(data.TRADITIONS_PER_TREE)]
            self.assertEqual(len({node.x for node in block}), 1, "one below the other")
            self.assertEqual([node.y for node in block], sorted(node.y for node in block))
            self.assertTrue(block[0].label.endswith("Adopted") and block[-1].label.endswith("Finished"))
            if slot:
                self.assertGreater(block[0].x, self.tree.nodes[f"location_{data.tradition_location(slot - 1, 0)}"].x)
        perks = [self.tree.nodes[f"location_{data.PERK_ID_BASE + number}"]
                 for number in range(1, data.ASCENSION_PERK_SLOTS + 1)]
        self.assertEqual(len({node.y for node in perks}), 1)
        self.assertGreater(perks[0].y, self.tree.nodes[f"location_{data.tradition_location(0, 6)}"].y)

    def test_search(self):
        self.assertEqual(tracker.matches(self.tree, self.state, "ender pearl"), ["tech_destroyers"], "by what it holds")
        found = tracker.matches(self.tree, self.state, "Destroyer")
        self.assertGreater(len(found), 1)
        self.assertTrue(all("destroyer" in self.names[key].lower() for key in found))
        self.assertEqual(tracker.matches(self.tree, self.state, "no such thing"), [])
        self.assertEqual(tracker.matches(self.tree, self.state, "  "), [])


class SettingsTest(unittest.TestCase):
    def test_themes_have_the_same_colours(self):
        self.assertEqual(set(THEMES["dark"]), set(THEMES["light"]))
        self.assertLessEqual(set(ADJUSTABLE), set(THEMES["dark"]))
        for name in tracker.FILTERS:
            self.assertIn(tracker.FILTER_COLOUR.get(name, name), THEMES["dark"])
        self.assertNotIn("trap", THEMES["dark"])

    def test_settings_are_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = Settings(path)
            self.assertEqual((settings.theme, settings.colour("checked")), ("dark", THEMES["dark"]["checked"]))
            settings.set_colour("checked", "#123456")
            settings.toggle_theme()
            self.assertEqual(settings.colour("checked"), THEMES["light"]["checked"], "a colour belongs to a theme")
            settings.collapsed.append("society")
            settings.zoom = 1.5
            settings.save()
            self.assertFalse(settings.spoilers, "hidden unless the player asks")
            settings.spoilers = True
            settings.save()
            again = Settings(path)
            self.assertEqual((again.theme, again.zoom, again.collapsed, again.spoilers),
                             ("light", 1.5, ["society"], True))
            again.toggle_theme()
            self.assertEqual(again.colour("checked"), "#123456")
            again.reset_colours()
            self.assertEqual(Settings(path).colour("checked"), THEMES["dark"]["checked"])

    def test_a_broken_settings_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text("{ not json", encoding="utf-8")
            self.assertEqual(Settings(path).theme, "dark")
            path.write_text('{"theme": "neon"}', encoding="utf-8")
            self.assertEqual(Settings(path).theme, "dark")
            path.write_text('[1, 2]', encoding="utf-8")
            self.assertEqual(Settings(path).zoom, 0.6)
            path.write_text('{"zoom": "big", "collapsed": 3, "colours": {"dark": {"checked": "nothing", '
                            '"useful": "#010203"}, "light": 7}}', encoding="utf-8")
            settings = Settings(path)
            self.assertEqual((settings.zoom, settings.collapsed), (0.6, []))
            self.assertEqual(settings.colours, {"dark": {"useful": "#010203"}, "light": {}})

    def test_settings_that_cannot_be_written_are_not_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(Path(folder) / "missing" / "settings.json")
            settings.toggle_theme()
            self.assertEqual(settings.theme, "light")


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.root = tkinter.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.state = TrackerState()
        self.settings = Settings(None)
        self.settings.tab = tracker.EVERYTHING
        self.view = tracker.TrackerWindow(self.root, lambda: self.state, self.settings)
        self.addCleanup(lambda: self.view.closed or self.view.close())
        self.root.update()

    def item(self, key: str, part: str, option: str) -> str:
        return self.view.canvas.itemcget(self.view.drawn[key][part], option)

    def test_the_window_follows_the_run(self):
        view = self.view
        self.assertEqual(len(view.drawn), len(view.tree.nodes))
        self.assertEqual(self.item("tech_destroyers", "dot", "state"), "hidden")
        self.assertEqual(self.item("tech_destroyers", "box", "outline"), self.settings.colour("locked"))
        node = view.tree.nodes["tech_destroyers"]
        self.state.checked.add(node.location)
        self.state.received.add(node.item)
        self.state.holds[node.location] = ("Ender Pearl", "Steve", "progression", None)
        view.refresh()
        self.root.update()
        self.assertEqual(self.item("tech_destroyers", "box", "fill"), self.settings.colour("checked_fill"))
        self.assertEqual(self.item("tech_destroyers", "box", "outline"), self.settings.colour("checked"))
        self.assertEqual(self.item("tech_destroyers", "stripe", "fill"), self.settings.colour("progression"))
        self.assertEqual(self.item("tech_destroyers", "dot", "state"), "normal")
        self.assertEqual(self.item("tech_destroyers", "text", "text"), "Ender Pearl", "called after what it holds")
        self.assertEqual(self.item("tech_corvettes", "text", "text"), "Corvettes")
        self.assertIn("1 of", view.summary.cget("text"))
        self.assertIn("1/", view.canvas.itemcget(view.band_titles["engineering"], "text"))

    def test_what_can_be_researched_has_its_own_border(self):
        first = next(key for key, node in self.view.tree.nodes.items()
                     if node.technology and node.technology["tier"] == 1 and node.location)
        self.assertEqual(self.item(first, "box", "outline"), self.settings.colour("available"))

    def test_the_search_is_live(self):
        view = self.view
        view.search.insert(0, "destroyer")
        view.search_changed()
        self.assertEqual(view.found, [], "hidden locations are not found by the name of their place")
        view.toggle_spoilers()
        view.search_changed()
        self.assertGreater(len(view.found), 1)
        self.assertIn("found", view.found_label.cget("text"))
        self.assertEqual(self.item("tech_destroyers", "box", "outline"), self.settings.colour("match"))
        self.assertEqual(self.item("tech_cruisers", "box", "fill"), self.settings.colour("background"), "faded")
        view.search_next()
        self.root.update()
        first = view.pinned
        self.assertIn(first, view.found)
        self.assertEqual(self.item(first, "box", "outline"), self.settings.colour("text"), "kept shown")
        lit = view.canvas.find_withtag("from_tech_destroyers")
        view.pin("tech_destroyers")
        self.assertEqual(view.canvas.itemcget(lit[0] if lit else view.canvas.find_withtag("from_tech_destroyers")[0],
                                              "fill"), self.settings.colour("edge_lit"))
        view.search_next()
        self.assertNotEqual(view.pinned, "tech_destroyers", "Enter goes on to the next one")
        view.clear()
        self.assertEqual((view.found, view.pinned, view.search.get()), ([], None, ""))
        self.assertNotEqual(self.item("tech_cruisers", "box", "fill"), self.settings.colour("background"))

    def test_filters_fade_the_rest(self):
        view = self.view
        view.set_filter("base")
        self.assertEqual(self.item("tech_destroyers", "box", "fill"), self.settings.colour("background"))
        self.assertEqual(self.item("tech_corvettes", "box", "fill"), self.settings.colour("base_fill"))
        self.assertIn("underline", str(view.chip["base"][1].cget("font")))
        view.set_filter("base")
        self.assertIsNone(view.filter)
        self.assertEqual(self.item("tech_destroyers", "box", "fill"), self.settings.colour("node"))

    def test_a_tab_shows_one_part_of_the_tree(self):
        view = self.view
        everything = len(view.drawn)
        view.pin("tech_destroyers")
        view.set_tab("physics")
        self.assertEqual(self.settings.tab, "physics")
        self.assertIn("tech_lasers_2", view.drawn)
        self.assertNotIn("tech_destroyers", view.drawn)
        self.assertNotIn("location_1001", view.drawn)
        self.assertIsNone(view.pinned, "what was shown is in another tab")
        self.assertEqual(list(view.band_titles), ["physics"])
        self.assertLess(len(view.drawn), everything / 2)
        self.assertIn("bold", str(view.tab["physics"].cget("font")))
        # The search goes to where what it found is
        view.toggle_spoilers()
        view.search.insert(0, "destroyers")
        view.search_changed()
        self.assertIn("tech_destroyers", view.found)
        while view.pinned != "tech_destroyers":
            view.search_next()
        self.assertEqual(self.settings.tab, "engineering")
        self.assertIn("tech_destroyers", view.drawn)
        view.set_tab(tracker.EVERYTHING)
        self.assertEqual(len(view.drawn), everything)

    def test_only_the_traditions_of_the_multiworld_are_listed(self):
        view = self.view
        traditions = [item["id"] for item in data.items() if item["kind"] == "tradition"]
        self.assertIn(f"tradition_{traditions[1]}", view.drawn)
        self.state.pool = frozenset(traditions[:1])
        view.refresh()
        self.assertIn(f"tradition_{traditions[0]}", view.drawn)
        self.assertNotIn(f"tradition_{traditions[1]}", view.tree.nodes)
        # Without shuffled traditions there is no tab for them
        self.settings.tab = tracker.TRADITIONS
        self.state.traditions = False
        view.refresh()
        self.assertEqual(view.shown_tab(), tracker.PICKS)
        self.assertFalse(view.tab[tracker.TRADITIONS].winfo_manager())

    def test_bands_fold(self):
        view = self.view
        view.pin("tech_destroyers")
        view.collapse("engineering")
        self.assertNotIn("tech_destroyers", view.drawn)
        self.assertIn("tech_lasers_2", view.drawn)
        self.assertIsNone(view.pinned, "what was shown is folded away")
        self.assertEqual(self.settings.collapsed, ["engineering"])
        self.assertTrue(view.canvas.itemcget(view.band_titles["engineering"], "text").startswith("▸"))
        view.collapse("engineering")
        self.assertIn("tech_destroyers", view.drawn)
        self.assertEqual(self.settings.collapsed, [])

    def test_a_pick_is_shown_with_every_area_folded(self):
        view = self.view
        for area in tracker.AREAS:
            view.collapse(area)
        self.assertEqual(view.canvas.find_withtag("edge"), ())
        view.pin("location_1001")
        self.assertEqual(view.shown, "location_1001")

    def test_themes_and_colours(self):
        view = self.view
        dark = view.canvas.cget("background")
        view.toggle_theme()
        self.assertEqual(self.settings.theme, "light")
        self.assertNotEqual(view.canvas.cget("background"), dark)
        self.assertEqual(view.canvas.cget("background"), THEMES["light"]["background"])
        self.assertEqual(view.info.cget("background"), THEMES["light"]["panel"])
        self.settings.set_colour("locked", "#abcdef")
        view.apply_theme()
        self.assertEqual(self.item("tech_cruisers", "box", "outline"), "#abcdef")

    def test_spoilers_are_off_until_asked_for(self):
        view = self.view
        destroyers, cruisers = view.tree.nodes["tech_destroyers"], view.tree.nodes["tech_cruisers"]
        self.state.checked.add(destroyers.location)
        self.state.holds[destroyers.location] = ("Ender Pearl", "Steve", "progression", None)
        self.state.holds[cruisers.location] = ("Blue Lasers", "Cerzix", "useful", "tech_lasers_2")
        self.assertFalse(self.settings.spoilers)
        self.assertIn("off", view.spoiler_button.cget("text"))
        view.refresh()
        self.assertEqual(self.item("tech_destroyers", "text", "text"), "Ender Pearl", "checked: it is known")
        self.assertEqual(self.item("tech_cruisers", "text", "text"), "Archipelago Item")
        self.assertEqual(self.item("tech_cruisers", "stripe", "state"), "hidden")
        view.search.insert(0, "blue lasers")
        view.search_changed()
        self.assertNotIn("tech_cruisers", view.found, "the search does not give it away")
        view.pin("tech_cruisers")
        self.assertIn("What it holds is hidden", view.info.get("1.0", "end"))
        view.clear()

        view.toggle_spoilers()
        self.assertTrue(self.settings.spoilers)
        self.assertIn("on", view.spoiler_button.cget("text"))
        self.assertEqual(self.item("tech_cruisers", "text", "text"), "Blue Lasers")
        self.assertEqual(self.item("tech_cruisers", "stripe", "fill"), self.settings.colour("useful"))
        view.toggle_spoilers()
        self.assertEqual(self.item("tech_cruisers", "text", "text"), "Archipelago Item")

    def test_the_legend_explains_every_look(self):
        view = self.view
        texts = [view.legend.itemcget(item, "text") for item in view.legend.find_all()
                 if view.legend.type(item) == "text"]
        self.assertEqual(texts[0], "Legend")
        self.assertEqual(texts[1:], [text for _, text in tracker.LEGEND])
        looks = [look for look, _ in tracker.LEGEND]
        for look in ("checked", "available", "locked", "base", "progression", "useful", "filler", "received",
                     "stellaris", "foreign", "match", "pinned"):
            self.assertIn(look, looks)
        colours = {view.legend.itemcget(item, "outline") for item in view.legend.find_all()
                   if view.legend.type(item) == "rectangle"}
        for name in ("checked", "available", "locked", "match"):
            self.assertIn(self.settings.colour(name), colours)
        # It follows the theme
        view.toggle_theme()
        self.assertEqual(view.legend.cget("background"), THEMES["light"]["panel"])
        self.assertIn(tracker.LEGEND_TECHNOLOGY, {technology["icon"] for technology in data.technologies()})

    def test_zoom_and_fit(self):
        view = self.view
        zoom = view.zoom
        view.zoom_by(0.5)
        self.assertLess(view.zoom, zoom)
        self.assertEqual(self.settings.zoom, view.zoom, "kept for the next time")
        self.assertEqual(len(view.drawn), len(view.tree.nodes), "drawn again")
        view.fit()
        self.assertGreaterEqual(view.zoom, tracker.MIN_ZOOM)
        view.close()
        self.assertTrue(view.closed)


if __name__ == "__main__":
    unittest.main()
