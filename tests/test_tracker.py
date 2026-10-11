import tkinter
import unittest

from stellaris_ap import data, tracker
from stellaris_ap.tracker import TrackerState, build_tree


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
        self.assertEqual([title for title, _ in self.tree.bands],
                         ["Traditions and ascension perks", "Physics", "Society", "Engineering"])
        bands = dict(self.tree.bands)
        for technology in data.technologies():
            area = tracker.AREA_NAMES[technology["area"]]
            later = [y for title, y in self.tree.bands if y > bands[area]]
            y = self.tree.nodes[technology["key"]].y
            self.assertGreater(y, bands[area])
            if later:
                self.assertLess(y, min(later))

    def test_a_cycle_in_the_data_does_not_hang(self):
        technologies = [{"key": "a", "tier": 1, "prerequisites": ["b"]}, {"key": "b", "tier": 1, "prerequisites": ["a"]}]
        self.assertEqual(set(tracker.columns(technologies)), {"a", "b"})


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tree = build_tree(data.technologies(), data.locations())
        self.destroyers = self.tree.nodes["tech_destroyers"]
        self.state = TrackerState(
            checked={self.destroyers.location, 1001, 2001},
            holds={self.destroyers.location: ("Ender Pearl", "Steve", "progression"),
                   self.tree.nodes["tech_cruisers"].location: ("Mineral Cache", "Cerzix", "filler")},
            received={self.tree.nodes["tech_cruisers"].item})

    def test_counts(self):
        counts = tracker.summary(self.state, data.locations())
        self.assertEqual(counts["all"], (3, len(data.locations())))
        self.assertEqual((counts["technology"][0], counts["tradition"], counts["perk"]), (1, (1, 49), (1, 8)))
        text = tracker.summary_text(self.state, data.locations())
        self.assertIn(f"3 of {len(data.locations())} locations checked (0%)", text)
        self.assertIn("Items received 1", text)
        everything = TrackerState(checked={location["id"] for location in data.locations()}, goal="Goal: done")
        text = tracker.summary_text(everything, data.locations())
        self.assertIn("(100%)", text)
        self.assertTrue(text.endswith("Goal: done"))

    def test_colours(self):
        cruisers = self.tree.nodes["tech_cruisers"]
        self.assertEqual(tracker.colours(self.destroyers, self.state)[:2], tracker.CHECKED)
        self.assertEqual(tracker.colours(cruisers, self.state)[1], tracker.KIND_COLOUR["filler"])
        self.assertEqual(tracker.colours(self.tree.nodes["tech_corvettes"], self.state)[:2], tracker.BASE)
        self.state.holds[cruisers.location] = ("Trap", "Steve", "trap")
        self.assertEqual(tracker.colours(cruisers, self.state)[1], tracker.KIND_COLOUR["trap"])
        battleships = self.tree.nodes["tech_battleships"]
        self.assertEqual(tracker.colours(battleships, self.state)[1], tracker.KIND_COLOUR["filler"], "not known yet")

    def text(self, key: str) -> str:
        return "".join(text for text, _ in tracker.describe(self.tree.nodes[key], self.state))

    def test_what_is_said_about_a_node(self):
        self.destroyers.before = ["Corvettes"]
        text = self.text("tech_destroyers")
        self.assertIn("Destroyers\nEngineering, tier 2", text)
        self.assertIn("Location: checked", text)
        self.assertIn("Holds Ender Pearl for Steve", text)
        self.assertIn("The technology itself: not received yet", text)
        self.assertIn("Comes after\n  Corvettes", text)
        text = self.text("tech_cruisers")
        self.assertIn("Location: not checked yet", text)
        self.assertIn("The technology itself: received", text)
        self.assertIn("What it holds is not known yet", self.text("tech_battleships"))
        self.assertIn("A base technology", self.text("tech_corvettes"))
        self.assertIn("A repeatable technology", self.text("tech_repeatable_weapon_type_energy_damage"))
        self.assertIn("Needs Apocalypse", self.text("tech_titans"))
        self.assertIn("Tradition Tree 1: Adopted", self.text("location_1001"))

    def test_find(self):
        self.assertEqual(tracker.find(self.tree, self.state, "ender pearl"), "tech_destroyers", "by what it holds")
        first = tracker.find(self.tree, self.state, "destroyer")
        second = tracker.find(self.tree, self.state, "destroyer", after=first)
        self.assertNotEqual(first, second)
        self.assertIn("destroyer", self.tree.nodes[second].label.lower())
        self.assertIsNone(tracker.find(self.tree, self.state, "no such thing"))
        self.assertIsNone(tracker.find(self.tree, self.state, "  "))


class WindowTest(unittest.TestCase):
    def test_the_window_follows_the_run(self):
        root = tkinter.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        state = TrackerState()
        view = tracker.TrackerWindow(root, lambda: state)
        self.addCleanup(lambda: view.closed or view.close())
        root.update()
        self.assertEqual(len(view.drawn), len(view.tree.nodes))
        box, _, dot = view.drawn["tech_destroyers"]
        self.assertEqual(view.canvas.itemcget(box, "fill"), tracker.OPEN)
        self.assertEqual(view.canvas.itemcget(dot, "state"), "hidden")

        node = view.tree.nodes["tech_destroyers"]
        state.checked.add(node.location)
        state.received.add(node.item)
        view.refresh()
        root.update()
        self.assertEqual(view.canvas.itemcget(box, "fill"), tracker.CHECKED[0])
        self.assertEqual(view.canvas.itemcget(dot, "state"), "normal")
        self.assertIn("1 of", view.summary.cget("text"))

        view.search.insert(0, "destroyers")
        view.search_next()
        root.update()
        self.assertEqual(view.pinned, "tech_destroyers")
        self.assertIn("Location: checked", view.info.get("1.0", "end"))
        # Finding zooms in, which draws the tree again
        box = view.drawn["tech_destroyers"][0]
        self.assertEqual(view.canvas.itemcget(box, "outline"), "#ffffff")
        lit = view.canvas.find_withtag("from_tech_destroyers")
        self.assertTrue(lit)
        self.assertEqual(view.canvas.itemcget(lit[0], "fill"), tracker.EDGE_LIT)

        zoom = view.zoom
        view.zoom_by(0.5)
        self.assertLess(view.zoom, zoom)
        self.assertEqual(len(view.drawn), len(view.tree.nodes), "drawn again")
        view.pin(None)
        self.assertIn("Tracker", view.info.get("1.0", "end"))
        view.close()
        self.assertTrue(view.closed)


if __name__ == "__main__":
    unittest.main()
