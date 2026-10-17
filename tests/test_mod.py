"""Static checks of the mod, so that mistakes show up here instead of in game.

The checks against the game need a Stellaris install, and its script documentation
(written to logs/script_documentation by the console command "script_docs").
"""
import random
import tempfile
import re
import struct
import zipfile
from pathlib import Path
import unittest

from stellaris_ap import build_apworld, build_mod, data, extract, pdx
from stellaris_ap.bridge import DEATHS, GOALS, render_run_file
from stellaris_ap.mailbox import (BIND_RUN, DEATH_EFFECTS, DEATH_NOTICE, DOOM_CODES, MAX_RUN, MAX_SENDERS,
                                  RUN_FACTOR, SENDER_FACTOR, SIGNAL_FACTOR, SIGNAL_MODULO, VARIABLE, WRONG_RUN,
                                  doom_code)
from stellaris_ap.memory import variable_header
from stellaris_ap.paths import (APWORLD_DIR, DATA_DIR, HIDDEN_CONSOLE_MOD_DIR, MOD_DIR, stellaris_game_dir,
                                stellaris_user_dir)

GAME_DIR = stellaris_game_dir()
DOCS_DIR = stellaris_user_dir() / "logs" / "script_documentation"

# Keys of the script syntax itself, which are neither effects nor triggers
EVENT_KEYS = {"namespace", "event", "country_event", "id", "hide_window", "is_triggered_only", "immediate",
              "trigger", "limit", "which", "value", "tech", "message", "NOT",
              "title", "desc", "picture", "location", "option", "name", "CLASS", "days", "flag", "KEY", "on_action",
              "defined_text", "random", "text", "localization_key", "default",
              "modifier", "multiplier",
              # Scopes
              "owner", "from", "fromfrom", "planet_event",
              "show_notification", "CAPITAL", "OR", "years", "factor",
              # A scripted trigger of the game
              "crisis_happened_and_defeated"}
# The parsed form of build_mod.NOT_AI
NOT_AI = [("NOT", "=", [("has_country_flag", "=", "ap_ai")])]
TECHNOLOGY_KEYS = {"area", "cost", "tier", "category", "weight", "is_rare", "icon", "potential"}


def strip_comments(text: str) -> str:
    return re.sub(r"#.*", "", text)


def keys(text: str) -> set[str]:
    return set(re.findall(r"([A-Za-z_][\w:.@]*)\s*[=<>]", strip_comments(text)))


def top_level_keys(text: str) -> list[str]:
    return re.findall(r"^([A-Za-z_]\w*)\s*=\s*\{", strip_comments(text), flags=re.MULTILINE)


def script_files() -> list:
    """The mod's own script files. The other files in common/technology are copies of the game's."""
    return sorted(MOD_DIR.glob("common/**/ap_*.txt")) + sorted(MOD_DIR.glob("events/ap_*.txt"))


def mod_script(*folders: str) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for folder in folders
                     for path in sorted((MOD_DIR / folder).glob("ap_*.txt")))


class DataTest(unittest.TestCase):
    def test_ids_and_names_are_unique(self):
        """Archipelago tells items and locations apart by name."""
        for entries in (data.items(), data.locations()):
            for field in ("id", "name"):
                values = [entry[field] for entry in entries]
                self.assertEqual(len(values), len(set(values)), f"duplicate {field}")

    def test_ids_are_positive_integers(self):
        for entry in data.items() + data.locations():
            self.assertIsInstance(entry["id"], int)
            self.assertGreater(entry["id"], 0)

    def test_item_effects_have_balanced_braces(self):
        for item in data.items():
            self.assertEqual(item["effect"].count("{"), item["effect"].count("}"), item["name"])
            self.assertNotIn("#", item["effect"], "a comment would cut off the rest of the console command")

    def test_every_technology_item_has_a_location(self):
        technologies = [technology for technology in data.technologies() if technology["kind"] == "item"]
        self.assertGreater(len(technologies), 500)
        self.assertEqual([location["id"] for location in build_mod.of_kind(data.locations(), "technology")],
                         [technology["id"] for technology in technologies])
        granted = {item["effect"] for item in data.items()}
        for technology in technologies:
            self.assertIn(f"give_technology = {{ tech = {technology['key']} message = yes }}", granted)

    def test_there_is_an_item_for_every_location(self):
        pool = data.item_pool(random.Random(1))
        self.assertEqual(len(pool), len(data.locations()))
        self.assertLessEqual(set(pool), {item["id"] for item in data.items()})

    def test_traditions(self):
        trees = data.tradition_trees()
        self.assertEqual(len(data.normal_trees()), 20)
        self.assertEqual(len(trees), 32)
        items = {item["id"]: item for item in data.items()}
        for tree in trees:
            self.assertEqual([tradition["role"] for tradition in tree["traditions"]],
                             ["adopt"] + ["tradition"] * 5 + ["finish"], tree["key"])
            self.assertEqual(len(tree["traditions"]), data.TRADITIONS_PER_TREE)
            keys = {tradition["key"] for tradition in tree["traditions"]}
            for tradition in tree["traditions"]:
                self.assertLessEqual(set(tradition["requires"]), keys)
                # Items: the traditions of the normal trees, without the adoption and finish bonus
                self.assertEqual("id" in tradition, tree["kind"] == "normal" and tradition["role"] == "tradition")
                if "id" in tradition:
                    self.assertEqual(items[tradition["id"]]["effect"],
                                     f"ap_add_tradition = {{ KEY = {tradition['key']} }}")
        self.assertEqual(sum(item["kind"] == "tradition" for item in data.items()), 100)

    def test_dlcs_and_empires(self):
        """Read from what makes a technology or tree available, see requirements.py."""
        technologies = {technology["key"]: technology for technology in data.technologies()}
        self.assertEqual(technologies["tech_titans"]["dlc"], ["Apocalypse"])
        self.assertEqual(technologies["tech_destroyers"]["dlc"], [])
        self.assertEqual(technologies["tech_destroyers"]["empires"], list(data.EMPIRES))
        trees = {tree["key"]: tree for tree in data.tradition_trees()}
        self.assertEqual(trees["tradition_aptitude"]["dlc"], ["Galactic Paragons"])
        self.assertEqual(trees["tradition_harmony"]["empires"], ["regular"])
        self.assertEqual(trees["tradition_versatility"]["empires"], ["machine"])
        self.assertEqual(trees["tradition_synchronicity"]["empires"], ["hive", "machine"])
        self.assertEqual(trees["tradition_discovery"]["empires"], list(data.EMPIRES))
        self.assertIn("Apocalypse", data.dlcs())
        for entry in data.technologies() + data.tradition_trees():
            self.assertTrue(entry["empires"], entry["key"])
            self.assertLessEqual(set(entry["dlc"]), set(data.dlcs()))
        for item in data.items():
            self.assertIn("dlc", item)
            self.assertTrue(item["empires"], item["name"])
        # Without any DLC and for every kind of empire there is plenty left
        for empire in data.EMPIRES:
            usable = [item for item in data.items() if data.tables.usable(item, set(), empire)]
            self.assertGreater(len(usable), 400, empire)

    def test_the_mod_reports_dlcs_and_empire(self):
        effects = mod_script("common/scripted_effects")
        for number, dlc in enumerate(data.dlcs(), 1):
            self.assertIn(f'host_has_dlc = "{dlc}" }} log = "AP_DLC {number}"', effects)
        self.assertEqual(data.EMPIRES, ("regular", "hive", "machine"), "AP_EMPIRE 1, 2 and 3")
        for line in ('has_authority = auth_hive_mind } log = "AP_EMPIRE 2"',
                     'has_authority = auth_machine_intelligence } log = "AP_EMPIRE 3"', 'log = "AP_EMPIRE 1"'):
            self.assertIn(line, effects)

    def test_tradition_locations_do_not_depend_on_the_trees(self):
        locations = build_mod.of_kind(data.locations(), "tradition")
        self.assertEqual(len(locations), 49)
        self.assertEqual([location["id"] for location in locations], list(range(1001, 1050)))
        self.assertEqual(locations[0]["name"], "Tradition Tree 1: Adopted")
        self.assertEqual(locations[8]["name"], "Tradition Tree 2: Tradition 1")
        self.assertEqual(locations[-1]["name"], "Tradition Tree 7: Finished")
        for location in locations:
            self.assertEqual(data.tradition_location(location["slot"], location["position"]), location["id"])

    def test_ascension_perks(self):
        perks = build_mod.of_kind(data.locations(), "perk")
        self.assertEqual([location["number"] for location in perks], list(range(1, data.ASCENSION_PERK_SLOTS + 1)))
        slot = next(item for item in data.items() if item["name"] == data.PROGRESSIVE_ASCENSION)
        self.assertEqual(slot["count"], data.ASCENSION_PERK_SLOTS)
        self.assertEqual(data.item_pool(random.Random(1)).count(slot["id"]), data.ASCENSION_PERK_SLOTS)

    def test_check_traditions(self):
        """They do nothing, and are picked in the order of the tree they are in."""
        traditions = dict((key, value) for key, _, value in pdx.parse(
            build_mod.render_traditions(data.tradition_trees())))
        self.assertEqual(len(traditions), 140)
        for tree in data.normal_trees():
            for tradition in tree["traditions"]:
                check = traditions[build_mod.check_tradition(tradition["key"])]
                self.assertLessEqual({key for key, _, _ in check},
                                     {"possible", "custom_tooltip", "ai_weight", "tradition_swap"})
                self.assertEqual([value for _, _, value in pdx.get(check, "possible", [])],
                                 [build_mod.check_tradition(required) for required in tradition["requires"]])
        self.assertEqual((MOD_DIR / "common/traditions" / build_mod.TRADITIONS_FILE).read_text(encoding="utf-8"),
                         build_mod.render_traditions(data.tradition_trees()))

    def test_check_traditions_have_an_icon_and_name_their_item(self):
        """The name and tooltip of a tradition location depend on the number of its tree: a swap for each."""
        sprites = (MOD_DIR / "interface" / "ap_traditions.gfx").read_text(encoding="utf-8")
        self.assertEqual(sprites, build_mod.render_tradition_sprites(data.tradition_trees()))
        icon = (MOD_DIR / build_mod.TRADITION_ICON).read_bytes()
        self.assertEqual(struct.unpack_from("<2I", icon, 12), (45, 45))
        self.assertEqual(len(icon), 128 + 45 * 45 * 4)
        names = (MOD_DIR / "localisation/english/ap_l_english.yml").read_text(encoding="utf-8-sig")
        self.assertNotIn("[Get", names.replace("[Root.GetAP", ""), "names do not take scripted localisation")
        traditions = dict((key, value) for key, _, value in pdx.parse(
            build_mod.render_traditions(data.tradition_trees())))
        for tree in data.normal_trees():
            for position, tradition in enumerate(tree["traditions"]):
                key = build_mod.check_tradition(tradition["key"])
                self.assertIn(f'name = "GFX_{key}"\n\t\ttextureFile = "{build_mod.TRADITION_ICON}"', sprites)
                self.assertIn(f' {key}:0 "$ap_loc_none_name$"\n', names)
                swaps = [value for name, _, value in traditions[key] if name == "tradition_swap"]
                self.assertEqual(len(swaps), data.TREE_SLOTS)
                for slot, swapped in enumerate(swaps):
                    location = data.tradition_location(slot, position)
                    name = build_mod.swap_name(key, slot)
                    self.assertEqual(pdx.get(swapped, "name"), name)
                    self.assertEqual(pdx.get(swapped, "inherit_icon"), "yes")
                    self.assertEqual(pdx.get(swapped, "custom_tooltip"), f"ap_loc_{location}")
                    self.assertEqual(pdx.get(swapped, "trigger"), [("check_variable", "=", [
                        ("which", "=", f"ap_slot_{build_mod.short(tree)}"), ("value", "=", str(slot))])])
                    self.assertIn(f' {name}:0 "$ap_loc_{location}_name$"\n', names)
                    self.assertIn(f" {name}_delayed:0 ", names)

    def test_tradition_picks_are_reported_by_the_order_of_their_tree(self):
        """Plays ap_assign_tree_slots and ap_report_picks, as generated, for a player who adopts trees."""
        effects = dict((key, value) for key, _, value in pdx.parse(
            build_mod.render_effects(data.locations(), data.items())))
        owned, flags, variables, logged = set(), set(), {}, []

        def true(trigger) -> bool:
            for key, operator, value in trigger:
                if key == "has_tradition":
                    result = value in owned
                elif key == "has_country_flag":
                    result = value in flags
                elif key == "check_variable":
                    result = variables.get(pdx.get(value, "which")) == int(pdx.get(value, "value"))
                elif key == "NOT":
                    result = not true(value)
                elif key == "num_ascension_perks":
                    result = False
                else:
                    raise AssertionError(key)
                if not result:
                    return False
            return True

        def run(block) -> None:
            for key, _, value in block:
                if key == "if":
                    if true(pdx.get(value, "limit")):
                        run([entry for entry in value if entry[0] != "limit"])
                elif key == "set_country_flag":
                    flags.add(value)
                elif key == "set_variable":
                    amount = pdx.get(value, "value")
                    variables[pdx.get(value, "which")] = variables[amount] if amount in variables else int(amount)
                elif key == "change_variable":
                    variables[pdx.get(value, "which")] += int(pdx.get(value, "value"))
                elif key == "log":
                    if value.strip('"').startswith("AP_CHECK"):
                        logged.append(int(value.strip('"').split()[1]))
                else:
                    raise AssertionError(key)

        def pick(key: str) -> list[int]:
            owned.add(key)
            logged.clear()
            run(effects["ap_assign_tree_slots"])
            run(effects["ap_report_picks"])
            return sorted(logged)

        trees = {build_mod.short(tree): tree for tree in data.tradition_trees()}
        run(effects["ap_init_tree_slots"])
        discovery = build_mod.picked_keys(trees["discovery"])
        psionics = build_mod.picked_keys(trees["psionics"])
        self.assertEqual(psionics[0], "tr_psionics_adopt", "the tree of an ascension path keeps its traditions")
        self.assertEqual(pick(discovery[0]), [1001])
        self.assertEqual(variables["ap_slot_supremacy"], 1, "the next tree to adopt will be the second")
        self.assertEqual(pick(discovery[3]), [1001, 1004])
        self.assertEqual(pick(psionics[0]), [1001, 1004, 1008])
        self.assertEqual(pick(psionics[6]), [1001, 1004, 1008, 1014])
        self.assertEqual(variables["ap_slot_supremacy"], 2)
        self.assertEqual(variables["ap_slot_discovery"], 0)
        # A tradition received as an item is not a pick
        self.assertEqual(pick("tr_supremacy_adopt"), [1001, 1004, 1008, 1014])
        self.assertEqual(pick(build_mod.picked_keys(trees["supremacy"])[0]), [1001, 1004, 1008, 1014, 1015])

    def test_apworld_is_packed_with_the_data(self):
        """Fails until python -m stellaris_ap.build_apworld was run after a change."""
        with zipfile.ZipFile(build_apworld.APWORLD) as archive:
            names = set(archive.namelist())
            for name in build_apworld.DATA_FILES:
                self.assertEqual(archive.read(f"stellaris/data/{name}"), (DATA_DIR / name).read_bytes(), name)
            for path in APWORLD_DIR.glob("*.py"):
                self.assertEqual(archive.read(f"stellaris/{path.name}"), path.read_bytes(), path.name)
        self.assertIn("stellaris/__init__.py", names)
        self.assertFalse([name for name in names if "__pycache__" in name])

    def test_goal_items_exist(self):
        fragment = next(item for item in data.items() if item["name"] == data.tables.FRAGMENT)
        self.assertEqual(fragment["count"], 0, "only in the multiworld when it is the goal")
        self.assertNotIn(fragment["id"], data.item_pool(random.Random(1)))

    def test_base_technologies_are_not_items(self):
        """What an empire needs to play at all: ships, stations, colonies, research and the basic resources."""
        kinds = {technology["key"]: technology["kind"] for technology in data.technologies()}
        for key in ("tech_corvettes", "tech_starbase_1", "tech_space_construction", "tech_space_exploration",
                    "tech_colonization_1", "tech_hyper_drive_1", "tech_basic_science_lab_1", "tech_power_plant_1",
                    "tech_mechanized_mining", "tech_industrial_farming", "tech_basic_industry",
                    "tech_lasers_1", "tech_mass_drivers_1", "tech_missiles_1", "tech_assault_armies",
                    # Offered or given by the game's start of game scripts
                    "tech_planetary_unification", "tech_mountain_range"):
            self.assertEqual(kinds[key], "start", key)
        self.assertEqual(kinds["tech_destroyers"], "item")
        self.assertEqual(kinds["tech_repeatable_weapon_type_energy_damage"], "repeatable")

    def test_locations_can_be_researched(self):
        text = build_mod.render_technologies(data.locations())
        entries = [entry for entry in pdx.parse(text)]
        self.assertEqual(len(entries), len(build_mod.of_kind(data.locations(), "technology")))
        for _, _, technology in entries:
            self.assertIn(pdx.get(technology, "area"), ("physics", "society", "engineering"))
            self.assertIn(int(pdx.get(technology, "tier")), range(1, 6))
            self.assertTrue(0 < int(pdx.get(technology, "cost")) <= build_mod.MAX_COST)
            self.assertGreater(float(pdx.get(technology, "weight")), 0)
            self.assertEqual(pdx.get(technology, "potential"), NOT_AI)


class OverrideTest(unittest.TestCase):
    TEXT = (
        "@local = 3\n"
        "tech_plain = {\n\tweight = 10\n}\n"
        "tech_modified = {\n\tweight = 10\n\tweight_modifier = {\n\t\tmodifier = { add = 5 always = yes } # }\n\t}\n"
        "\tai_weight = { factor = 2 }\n}\n"
        "tech_kept = {\n\tweight = 10\n\tweight_modifier = { factor = 2 }\n}\n")

    def weight_modifiers(self, block: list) -> list:
        return [value for key, _, value in pdx.get(block, "weight_modifier", []) if key == "modifier"]

    def test_hidden_technologies_get_weight_zero_for_the_player(self):
        result = dict((key, value) for key, _, value in pdx.parse(
            build_mod.render_override(self.TEXT, {"tech_plain", "tech_modified"})))
        for key in ("tech_plain", "tech_modified"):
            last = self.weight_modifiers(result[key])[-1]
            self.assertEqual(last, [("factor", "=", "0")] + NOT_AI, key)
        self.assertEqual(len(self.weight_modifiers(result["tech_modified"])), 2)
        self.assertEqual(pdx.get(result["tech_modified"], "ai_weight"), [("factor", "=", "2")])

    def test_everything_else_is_untouched(self):
        result = build_mod.render_override(self.TEXT, {"tech_plain", "tech_modified"})
        self.assertEqual(result.replace(f"\t{build_mod.HIDE}\n\t", "").replace(
            f"\tweight_modifier = {{ {build_mod.HIDE} }}\n", "").split("\n", 2)[2], self.TEXT)
        self.assertEqual(pdx.parse(build_mod.render_override(self.TEXT, set())), pdx.parse(self.TEXT))


class GeneratedFilesTest(unittest.TestCase):
    """Fails if data/ was changed without running python -m stellaris_ap.build_mod."""

    def setUp(self):
        self.locations = data.locations()

    def test_technologies_are_up_to_date(self):
        self.assertEqual((MOD_DIR / "common/technology/ap_checks.txt").read_text(encoding="utf-8"),
                         build_mod.render_technologies(self.locations))

    def test_effects_are_up_to_date(self):
        generated = (MOD_DIR / "common/scripted_effects/ap_generated_effects.txt").read_text(encoding="utf-8")
        # The ascension perks are read from the game, the ones in the file are taken without it
        perks = build_mod.ascension_perks(GAME_DIR) if GAME_DIR else re.findall(r'"AP_PERK 0 (\w+)"', generated)
        self.assertEqual(generated, build_mod.render_effects(self.locations, data.items(), perks))

    def test_localisation(self):
        for language in build_mod.LANGUAGES:
            for name, expected in ((f"ap_l_{language}.yml", build_mod.render_localisation(language)),
                                   (f"ap_check_names_l_{language}.yml", None)):
                path = MOD_DIR / "localisation" / language / name
                self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"), f"{name} needs a UTF-8 BOM")
                text = path.read_text(encoding="utf-8-sig")
                self.assertEqual(text.splitlines()[0], f"l_{language}:")
                if expected:
                    self.assertEqual(text, expected)

    def test_every_check_has_a_name(self):
        """The client rewrites this file for every multiworld, so only its shape is checked."""
        text = (MOD_DIR / "localisation/english/ap_check_names_l_english.yml").read_text(encoding="utf-8-sig")
        named = set(re.findall(r'(?m)^ (\w+):0 ".+"$', text))
        for location in self.locations:
            if location["kind"] == "technology":
                self.assertIn(build_mod.tech_key(location), named)
                self.assertIn(build_mod.tech_key(location) + "_desc", named)
            elif location["kind"] == "tradition":
                self.assertIn(f"ap_loc_{location['id']}", named)
                self.assertIn(f"ap_loc_{location['id']}_name", named)

    def test_tradition_location_names(self):
        location = build_mod.of_kind(self.locations, "tradition")[3]
        text = build_mod.render_check_names([location], "english", {location["id"]: ("Ender Pearl", "Steve")})
        self.assertIn(f' ap_loc_{location["id"]}:0 "Sends §YEnder Pearl§! to §YSteve§!."\n', text)
        self.assertIn(f' ap_loc_{location["id"]}_name:0 "Archipelago: Ender Pearl"\n', text)
        self.assertIn(f' ap_loc_{location["id"]}:0 "Sends a check to the multiworld."\n',
                      build_mod.render_check_names([location], "english"))

    def test_check_names(self):
        first, second = self.locations[:2]
        text = build_mod.render_check_names(self.locations[:2], "english", {first["id"]: ('Ender "Dragon" [Shard]$', "Steve")})
        self.assertIn(f" {build_mod.tech_key(first)}:0 \"Archipelago: Ender 'Dragon' Shard\"\n", text)
        self.assertIn("to §YSteve§!", text)
        self.assertIn(f' {build_mod.tech_key(second)}:0 "Archipelago Check"\n', text)
        self.assertNotIn("Takes the place of", text)
        for line in text.splitlines()[1:]:
            self.assertRegex(line, r'^ \w+:0 "[^"]*"$')

    def test_icon_is_a_vanilla_style_dds(self):
        data = build_mod.ICON_PATH.read_bytes()
        size = build_mod.ICON_SIZE
        self.assertEqual(data[:4], b"DDS ")
        header_size, _, height, width = struct.unpack_from("<4I", data, 4)
        pixel_format_flags, _, bits, red, green, blue, alpha = struct.unpack_from("<7I", data, 80)
        self.assertEqual((header_size, height, width), (124, size, size))
        self.assertEqual((pixel_format_flags, bits), (0x41, 32))
        self.assertEqual((red, green, blue, alpha), (0xFF0000, 0xFF00, 0xFF, 0xFF000000))
        self.assertEqual(len(data), 128 + size * size * 4)
        self.assertTrue(any(data[131::4]), "the icon is fully transparent")

    def test_icon_is_used(self):
        self.assertIn(f"icon = {build_mod.ICON_NAME}\n", build_mod.render_technologies(self.locations))


class ScriptTest(unittest.TestCase):
    def test_braces_are_balanced(self):
        for path in script_files():
            text = strip_comments(path.read_text(encoding="utf-8"))
            self.assertEqual(text.count("{"), text.count("}"), path.name)
            self.assertEqual(text.count('"') % 2, 0, path.name)

    def test_events_referenced_by_on_actions_exist(self):
        defined = set(re.findall(r"\bid\s*=\s*(ap\.\d+)", mod_script("events")))
        referenced = set(re.findall(r"\bap\.\d+", strip_comments(mod_script("common/on_actions"))))
        self.assertTrue(referenced)
        self.assertLessEqual(referenced, defined)

    def test_scripted_effects_are_defined_once(self):
        defined = top_level_keys(mod_script("common/scripted_effects"))
        self.assertEqual(len(defined), len(set(defined)))
        called = {key for key in keys(mod_script("events", "common/scripted_effects") + render_run_file([]))
                  if key.startswith("ap_") and key not in ("ap_item_index",)}
        self.assertLessEqual(called, set(defined))

    def test_every_check_is_reported(self):
        effects = mod_script("common/scripted_effects")
        for location in build_mod.of_kind(data.locations(), "technology"):
            key = build_mod.tech_key(location)
            self.assertIn(f'has_technology = {key} }} log = "AP_CHECK {location["id"]}"', effects)
            self.assertIn(f'last_increased_tech = {key} }} log = "AP_CHECK {location["id"]}"', effects)
        picks = effects[effects.index("ap_report_picks = {"):effects.index("ap_grant_item = {")]
        for location in build_mod.of_kind(data.locations(), "perk"):
            self.assertIn(f'num_ascension_perks >= {location["number"]} }} log = "AP_CHECK {location["id"]}"', picks)
        for location in build_mod.of_kind(data.locations(), "tradition"):
            # Once for every tree
            self.assertEqual(picks.count(f'log = "AP_CHECK {location["id"]}"'), len(data.tradition_trees()))
        events = pdx.parse(mod_script("events"))
        picked = next(event for _, _, event in events if isinstance(event, list) and pdx.get(event, "id") == "ap.5")
        self.assertEqual(pdx.get(picked, "immediate"),
                         [("ap_assign_tree_slots", "=", "yes"), ("ap_report_picks", "=", "yes")])
        on_actions = dict((key, value) for key, _, value in pdx.parse(mod_script("common/on_actions")))
        for on_action in ("on_tradition_picked", "on_ascension_perk_picked"):
            self.assertEqual(pdx.values(pdx.get(on_actions[on_action], "events")), ["ap.5"])

    def test_every_item_can_be_granted(self):
        effects = mod_script("common/scripted_effects")
        for item in data.items():
            self.assertIn(f"which = ap_last_item value = {item['id']} }} }} {item['effect']} }}\n", effects)

    def test_every_item_and_sender_has_a_name_in_game(self):
        loc = build_mod.render_scripted_loc(data.items())
        self.assertEqual((MOD_DIR / "common/scripted_loc/ap_scripted_loc.txt").read_text(encoding="utf-8"), loc)
        names = (MOD_DIR / "localisation/english/ap_l_english.yml").read_text(encoding="utf-8-sig")
        senders = (MOD_DIR / "localisation/english/ap_check_names_l_english.yml").read_text(encoding="utf-8-sig")
        for item in data.items():
            self.assertIn(f"which = ap_last_item value = {item['id']} }} }} localization_key = ap_item_{item['id']} }}", loc)
            self.assertRegex(names, rf'(?m)^ ap_item_{item["id"]}:0 "[^"]+"$')
        for slot in (1, MAX_SENDERS):
            self.assertIn(f"which = ap_last_sender value = {slot} }} }} localization_key = ap_sender_{slot} }}", loc)
        for slot in (0, 1, MAX_SENDERS):
            self.assertRegex(senders, rf'(?m)^ ap_sender_{slot}:0 "[^"]+"$')
        for key in ("GetAPItemName", "GetAPSenderName"):
            self.assertIn(f"name = {key}\n", loc)
            self.assertIn(f"[Root.{key}]", build_mod.EVENT_TEXT["ap.20.desc"])

    def test_item_message_blocks_the_next_item_until_closed(self):
        effects = strip_comments(mod_script("common/scripted_effects"))
        events = strip_comments(mod_script("events"))
        self.assertIn("NOT = { has_country_flag = ap_message_open }", effects)
        self.assertIn("set_country_flag = ap_message_open", effects)
        message = events[events.index("id = ap.20"):]
        self.assertIn("remove_country_flag = ap_message_open", message[:message.index("id = ap.10")])
        self.assertIn(f"divide_variable = {{ which = ap_last_sender value = {SENDER_FACTOR} }}", effects)
        self.assertIn(f"modulo_variable = {{ which = ap_last_item value = {SENDER_FACTOR} }}", effects)

    def test_players_are_named(self):
        text = build_mod.render_check_names([], "english", players={2: 'Ste"ve'})
        self.assertIn(" ap_sender_2:0 \"Ste've\"\n", text)
        self.assertIn(' ap_sender_3:0 "Player 3"\n', text)

    def test_mailbox_variable_names_fit_the_memory_layout(self):
        """The client finds variables by name in the game's memory, which works for short names only."""
        self.assertEqual(variable_header(VARIABLE), b"ap_mailbox\0")
        self.assertIn(f"set_variable = {{ which = {VARIABLE} value = ap_mailbox_next }}",
                      mod_script("common/scripted_effects"))

    def test_doom_codes_match_the_client(self):
        effects = strip_comments(mod_script("common/scripted_effects"))
        for kind in DOOM_CODES:
            for capital, suffix in ((False, ""), (True, "_capital")):
                self.assertRegex(effects, rf"which = ap_mailbox value = {doom_code(kind, capital)} \}} \}}"
                                          rf"\s+ap_doom_{kind}{suffix} = yes")
        self.assertIn("OR = { is_capital = no always = $CAPITAL$ }", effects)
        for kind, code in DOOM_CODES.items():
            self.assertRegex(effects, rf"which = ap_mailbox value = {code} \}} \}}\s+ap_doom_{kind} = yes")
        self.assertIn(f"multiply_variable = {{ which = ap_mailbox_dooms value = {SIGNAL_FACTOR} }}", effects)

    def test_ai_countries_are_flagged(self):
        """Without the flag ap_ai a country gets locations to research instead of technologies."""
        self.assertEqual(pdx.parse(build_mod.NOT_AI), NOT_AI)
        events = pdx.parse(mod_script("events"))
        start = next(event for _, _, event in events if isinstance(event, list) and pdx.get(event, "id") == "ap.1")
        flagged = pdx.get(pdx.get(start, "immediate"), "every_country")
        self.assertEqual(flagged, [("limit", "=", [("is_ai", "=", "yes")]), ("set_country_flag", "=", "ap_ai")])
        monthly = next(event for _, _, event in events if isinstance(event, list) and pdx.get(event, "id") == "ap.4")
        self.assertEqual(pdx.get(monthly, "trigger"), [("is_ai", "=", "yes")] + NOT_AI)
        self.assertIn("on_monthly_pulse_country", top_level_keys(mod_script("common/on_actions")))

    def test_run_signals_match_the_client(self):
        effects = strip_comments(mod_script("common/scripted_effects"))
        self.assertIn(f"which = ap_mailbox value = {WRONG_RUN} }} }}", effects)
        self.assertIn(f"which = ap_mailbox value >= {BIND_RUN} }}", effects)
        self.assertIn(f"which = ap_mailbox value < {BIND_RUN + MAX_RUN + 1} }}", effects)
        self.assertIn(f"subtract_variable = {{ which = ap_run value = {BIND_RUN} }}", effects)
        self.assertIn(f"modulo_variable = {{ which = ap_mailbox_dooms value = {SIGNAL_MODULO} }}", effects)
        self.assertIn(f"multiply_variable = {{ which = ap_mailbox_run value = {RUN_FACTOR} }}", effects)
        self.assertIn("id = ap.13", mod_script("events"))

    def test_deaths_are_reported_but_not_the_ones_of_a_doom(self):
        events = dict((pdx.get(event, "id"), event) for _, _, event in pdx.parse(mod_script("events"))
                      if isinstance(event, list))
        on_actions = dict((key, pdx.values(pdx.get(value, "events", [])))
                          for key, _, value in pdx.parse(mod_script("common/on_actions")))
        text = mod_script("events")
        for on_action, event, numbers in (("on_leader_death", "ap.30", (1, 2)),
                                          ("on_fleet_destroyed_victim", "ap.31", (3,)),
                                          ("on_space_battle_lost", "ap.31", (3,)),
                                          ("on_planet_occupied", "ap.32", (4,)),
                                          ("on_colony_destroyed", "ap.33", (5,))):
            self.assertEqual(on_actions[on_action], [event])
            self.assertIn(event, events)
            for number in numbers:
                self.assertIn(number, DEATHS)
                self.assertRegex(text, rf'log = "AP_DEATH {number} \[\w+\.GetName\]"')
        self.assertEqual(len(DEATHS), 5)
        self.assertEqual(DEATHS[3], "battle")
        battle = events["ap.31"]
        self.assertIn(("exists", "=", "fromfrom"), pdx.get(battle, "trigger"), "the fleet may be gone")
        self.assertNotIn("fleet_size", repr(battle), "any military fleet counts")
        effects = strip_comments(mod_script("common/scripted_effects"))
        doom = effects[effects.index("ap_doom = {"):]
        self.assertLess(doom.index("set_country_flag = ap_dooming"), doom.index("destroy_colony = yes"))
        self.assertLess(doom.index("destroy_colony = yes"), doom.index("remove_country_flag = ap_dooming"))
        for event in ("ap.30", "ap.31", "ap.33"):
            self.assertIn("ap_dooming", repr(events[event]), event)

    def test_a_death_takes_something(self):
        effects = strip_comments(mod_script("common/scripted_effects"))
        self.assertIn(f"which = ap_mailbox value >= {DEATH_NOTICE} }}", effects)
        self.assertIn(f"which = ap_mailbox value < {DEATH_NOTICE + 30000} }}", effects)
        self.assertIn(f"subtract_variable = {{ which = ap_death_effect value = {DEATH_NOTICE} }}", effects)
        for effect, name in ((DEATH_EFFECTS["leader"], "ap_death_leader"), (DEATH_EFFECTS["fleet"], "ap_death_fleet")):
            self.assertRegex(effects, rf"which = ap_death_effect value = {effect} \}} \}}\s+{name} = yes")
        self.assertIn("kill_leader = { show_notification = yes }", effects)
        self.assertIn("destroy_fleet = this", effects)
        loc = build_mod.render_scripted_loc(data.items())
        names = (MOD_DIR / "localisation/english/ap_l_english.yml").read_text(encoding="utf-8-sig")
        for value in build_mod.DEATH_EFFECT_TEXTS:
            self.assertIn(f"which = ap_death_effect value = {value} }} }} localization_key = ap_death_effect_{value}", loc)
            self.assertIn(f" ap_death_effect_{value}:0 ", names)
        self.assertIn("[Root.GetAPDeathEffect]", build_mod.EVENT_TEXT["ap.12.desc"])
        self.assertIn("[Root.GetAPDeathEffect]", build_mod.EVENT_TEXT["ap.14.desc"])

    def test_random_events(self):
        effects = pdx.parse(strip_comments(mod_script("common/scripted_effects")))
        named = dict((key, value) for key, _, value in effects)
        outcomes = [value for _, _, value in pdx.get(named["ap_random_event"], "random_list")]
        fired = [pdx.get(pdx.get(outcome, "fire_on_action") or pdx.get(pdx.get(outcome, "random_owned_planet"),
                                                                       "fire_on_action"), "on_action")
                 for outcome in outcomes]
        self.assertEqual(sorted(fired), sorted(build_mod.RANDOM_EVENT_POOLS), "the game's own events, nothing made up")
        # An empire without a colony gets an event of the empire
        colony = next(outcome for outcome in outcomes if pdx.get(outcome, "random_owned_planet"))
        self.assertEqual(pdx.get(pdx.get(colony, "modifier"), "factor"), "0")
        on_actions = dict((key, value) for key, _, value in pdx.parse(mod_script("common/on_actions")))
        for name in build_mod.RANDOM_EVENT_POOLS:
            self.assertTrue(pdx.get(on_actions[name], "random_events"), name)
        script = mod_script("events") + mod_script("common/scripted_effects")
        for gone in ("ap.21", "ap.22", "ap_event_kind", "ap_random_event_roll"):
            self.assertNotIn(gone, script)
        item = next(item for item in data.items() if item["name"] == data.tables.RANDOM_EVENT)
        self.assertEqual((item["effect"], item["count"]), ("ap_random_event = yes", 0))
        self.assertNotIn(item["id"], data.item_pool(random.Random(1)), "only in a multiworld that asks for them")

    def test_a_death_takes_the_ruler_only_if_no_other_leader_is_left(self):
        effects = dict((key, value) for key, _, value in pdx.parse(strip_comments(mod_script("common/scripted_effects"))))
        leader = effects["ap_death_leader"]
        first, second = pdx.get(leader, "if"), pdx.get(leader, "else_if")
        self.assertEqual(pdx.get(pdx.get(first, "random_owned_leader"), "limit"), [("is_ruler", "=", "no")])
        self.assertEqual(pdx.get(pdx.get(second, "random_owned_leader"), "limit"), [("is_ruler", "=", "yes")])
        for block in (first, second):
            # Not a death to send on in turn
            keys = [entry[0] for entry in block]
            self.assertLess(keys.index("set_country_flag"), keys.index("random_owned_leader"))
            self.assertLess(keys.index("random_owned_leader"), keys.index("remove_country_flag"))

    def test_a_received_tradition_is_added_right_away(self):
        effects = dict((key, value) for key, _, value in pdx.parse(strip_comments(mod_script("common/scripted_effects"))))
        self.assertEqual(effects["ap_add_tradition"], [("add_tradition", "=", "$KEY$")])
        self.assertNotIn("remove_tradition_tree", mod_script("common/scripted_effects"))

    def test_seven_trees_are_counted_by_the_mod(self):
        """The game would count received traditions as trees: it lets an empire have as many as there can be, and
        the mod stops it at seven adopted ones."""
        defines = dict((key, value) for key, _, value in pdx.parse_file(MOD_DIR / "common/defines/ap_defines.txt"))
        self.assertEqual(defines["NGameplay"], [("TRADITION_CATEGORIES_MAX", "=",
                                                 str(data.TREE_SLOTS + len(data.normal_trees())))])
        trigger = dict((key, value) for key, _, value in pdx.parse_file(
            MOD_DIR / "common/scripted_triggers/ap_triggers.txt"))["ap_tree_slot_free"]
        counted = pdx.get(pdx.get(trigger, "NOT"), "calc_true_if")
        self.assertEqual(counted[0], ("amount", ">=", str(data.TREE_SLOTS)))
        adopted = {value for key, _, value in counted[1:] if key == "has_tradition"}
        for tree in data.tradition_trees():
            self.assertIn(build_mod.adoption(tree), adopted, "the AI's trees, and the ascension paths")
            if tree["kind"] == "normal":
                self.assertIn(build_mod.check_tradition(build_mod.adoption(tree)), adopted, "the player's trees")

    def test_a_new_game_starts_with_the_unlocks_of_its_run(self):
        items = {item["name"]: item for item in data.items()}
        technology = next(item for item in data.items() if item["kind"] == "technology")
        tradition = next(item for item in data.items() if item["kind"] == "tradition")
        received = [technology, items["Mineral Cache"], items[data.PROGRESSIVE_ASCENSION], tradition,
                    items["Random Event"], items[data.PROGRESSIVE_ASCENSION], items[data.tables.FRAGMENT]]
        start = dict((key, value) for key, _, value in pdx.parse(
            build_mod.render_session(77, received, [1001, 3, 2005, 3])))["ap_start_run"]
        self.assertEqual(start[0], ("set_variable", "=", [("which", "=", "ap_run"), ("value", "=", "77")]))
        self.assertEqual([entry for entry in start if entry[0] == "ap_add_ascension_slot"],
                         [("ap_add_ascension_slot", "=", "yes")] * 2)
        key = tradition["effect"].split("KEY = ")[1].split()[0]
        self.assertIn(("ap_add_tradition", "=", [("KEY", "=", key)]), start)
        given = [pdx.get(value, "tech") for key, _, value in start if key == "give_technology"]
        self.assertEqual(given, [technology["effect"].split("tech = ")[1].split()[0], "ap_check_3"],
                         "the technology received, and the one of the location that is done")
        # Resources too, and a new random event for every one received, without their messages
        self.assertEqual(sum(key == "add_resource" for key, _, _ in start), 2, "the cache and the fragment")
        keys = [key for key, _, _ in start]
        self.assertNotIn("ap_random_event", keys, "not all at once on the first day")
        self.assertIn(("country_event", "=", [("id", "=", "ap.23"), ("days", "=", str(build_mod.REPLAY_FIRST_DAY))]),
                      start)
        two = build_mod.render_session(77, [items["Random Event"]] * 2, [])
        self.assertIn(f"days = {build_mod.REPLAY_FIRST_DAY + build_mod.REPLAY_DAYS_APART} }}", two, "one after the other")
        self.assertNotIn("ap.23", build_mod.render_session(77, [technology], []), "only if there was one")
        self.assertIn("id = ap.23", mod_script("events"))
        # Traditions that are not shuffled: the player has the trees of the game
        self.assertNotIn(build_mod.VANILLA_TRADITIONS, build_mod.render_session(77, received, [3]))
        vanilla = dict((key, value) for key, _, value in pdx.parse(
            build_mod.render_session(77, [], [], vanilla_traditions=True)))["ap_start_run"]
        self.assertIn(("set_country_flag", "=", build_mod.VANILLA_TRADITIONS), vanilla)
        self.assertIn(("remove_modifier", "=", "ap_tradition_cost"), vanilla)
        self.assertNotIn("message = yes", build_mod.render_session(77, received, [3]))
        self.assertIn(("set_variable", "=", [("which", "=", "ap_item_index"), ("value", "=", "7")]), start,
                      "the game goes on after everything received")
        # Without a run nothing happens
        self.assertEqual(pdx.parse(build_mod.render_session())[0], ("ap_start_run", "=", []))

    def test_a_new_game_picks_again_what_the_run_picked(self):
        trees = {tree["key"]: tree for tree in data.tradition_trees()}
        expansion, genetics = trees["tradition_expansion"], trees["tradition_genetics"]
        location = data.tradition_location
        # Expansion as tree 0 with two traditions, Genetics as tree 2 adopted, tree 1 picked but never checked,
        # and two of the three perks reported with their locations done
        checked = [3, location(0, 0), location(0, 1), location(2, 0), data.PERK_ID_BASE + 1, data.PERK_ID_BASE + 2]
        picks = {"trees": {"0": "tradition_expansion", "1": "tradition_discovery", "2": "tradition_genetics",
                           "4": "tradition_gone"},
                 "perks": ["ap_engineered_evolution", "ap_technological_ascendancy", "ap_one_vision"]}
        start = dict((key, value) for key, _, value in pdx.parse(
            build_mod.render_session(77, [], checked, picks=picks)))["ap_start_run"]
        keys = [key for key, _, _ in start]
        self.assertEqual([value for key, _, value in start if key == "add_ascension_perk"],
                         ["ap_engineered_evolution", "ap_technological_ascendancy"], "as many as were checked")
        self.assertLess(keys.index("add_ascension_perk"), keys.index("add_tradition"), "a path's tree needs its perk")
        self.assertEqual([value for key, _, value in start if key == "add_tradition"],
                         build_mod.picked_keys(expansion)[:2] + build_mod.picked_keys(genetics)[:1])
        self.assertIn(("set_country_flag", "=", "ap_tree_expansion"), start)
        self.assertIn(("set_variable", "=", [("which", "=", "ap_slot_genetics"), ("value", "=", "2")]), start)
        self.assertNotIn(("set_country_flag", "=", "ap_tree_discovery"), start, "nothing of it was checked")
        self.assertIn(("set_variable", "=", [("which", "=", "ap_trees_adopted"), ("value", "=", "3")]), start)
        self.assertEqual(keys[-2:], ["ap_assign_tree_slots", "log"], "the trees not adopted get the next number")
        self.assertEqual(start[-1], ("log", "=", '"AP_START 5"'))
        self.assertEqual(build_mod.restored_count(set(checked), picks), 5)
        # Traditions that are not shuffled have no locations to pick again, perks do
        vanilla = build_mod.render_session(77, [], checked, vanilla_traditions=True, picks=picks)
        self.assertNotIn("add_tradition", vanilla)
        self.assertIn("add_ascension_perk = ap_engineered_evolution", vanilla)
        self.assertIn('log = "AP_START 0"', build_mod.render_session(77, [], []))

    def test_the_game_reports_its_trees_and_perks(self):
        effects = build_mod.render_effects(data.locations(), data.items(), ["ap_one_vision"])
        self.assertIn('log = "AP_PERK 0 ap_one_vision"', effects)
        for tree in data.tradition_trees():
            for number in range(data.TREE_SLOTS):
                self.assertIn(f'log = "AP_TREE {number} {tree["key"]}"', effects)
        with tempfile.TemporaryDirectory() as folder:
            perks = Path(folder) / "common" / "ascension_perks"
            perks.mkdir(parents=True)
            (perks / "00_a.txt").write_text("@x = 1\nap_one = {\n}\nap_two = { a = b }\n", encoding="utf-8")
            self.assertEqual(build_mod.ascension_perks(Path(folder)), ["ap_one", "ap_two"])

    def test_only_a_new_game_starts_the_run(self):
        effects = dict((key, value) for key, _, value in pdx.parse(strip_comments(mod_script("common/scripted_effects"))))
        setup = effects["ap_setup_player"]
        first = setup[1][2]
        self.assertEqual(pdx.get(first, "limit"), [("NOT", "=", [("has_country_flag", "=", "ap_player")])])
        self.assertIn(("set_country_flag", "=", "ap_new_game"), first)
        start = next(value for key, _, value in setup if key == "if"
                     and pdx.get(value, "limit") == [("has_country_flag", "=", "ap_new_game")])
        self.assertIn(("ap_start_run", "=", "yes"), start)
        self.assertIn(("remove_country_flag", "=", "ap_new_game"), start)
        ready = [index for index, (key, _, value) in enumerate(setup)
                 if key == "if" and "ap_run_ready" in repr(value) or key == "if" and "ap_traditions_ready" in repr(value)]
        self.assertLess(max(ready), setup.index(("if", "=", start)), "after the variables it sets are there")
        self.assertIn("ap_start_run", effects)

    def test_goals_about_the_galaxy_are_reported(self):
        effects = dict((key, value) for key, _, value in pdx.parse(strip_comments(mod_script("common/scripted_effects"))))
        self.assertEqual(GOALS, {1: "crisis", 2: "crisis_and_fallen_empires"})
        report = pdx.get(effects["ap_report_goals"], "if")
        self.assertEqual(pdx.get(report, "limit"), [("crisis_happened_and_defeated", "=", "yes")])
        self.assertEqual(pdx.get(report, "log"), '"AP_GOAL 1"')
        fallen = pdx.get(report, "if")
        self.assertEqual(pdx.get(fallen, "limit"), [("NOT", "=", [("any_country", "=", [
            ("is_country_type", "=", "awakened_fallen_empire")])])])
        self.assertEqual(pdx.get(fallen, "log"), '"AP_GOAL 2"')
        self.assertIn(("ap_report_goals", "=", "yes"), effects["ap_setup_player"], "also when a save is loaded")
        on_actions = dict((key, pdx.values(pdx.get(value, "events", [])))
                          for key, _, value in pdx.parse(mod_script("common/on_actions")))
        self.assertIn("ap.6", on_actions["on_monthly_pulse_country"])

    def test_poll_event_keeps_itself_going(self):
        events = strip_comments(mod_script("events"))
        poll = events[events.index("id = ap.3"):events.index("id = ap.10")]
        self.assertIn("ap_poll_mailbox = yes", poll)
        self.assertIn("country_event = { id = ap.3 days = 1 }", poll)
        self.assertIn("country_event = { id = ap.3 days = 1 }", mod_script("common/scripted_effects"))

    def test_technologies_only_use_known_keys(self):
        self.assertLessEqual(keys(mod_script("common/technology")) - set(top_level_keys(mod_script("common/technology"))),
                             TECHNOLOGY_KEYS | {"NOT", "has_country_flag"})

    def test_run_file_applies_each_item_once(self):
        """Plays the run file against a save's ap_item_index, like the game would."""
        effects = [f"give_item_{number} = yes" for number in range(1, 6)]

        def run(text: str, item_index: int) -> tuple[list[str], int]:
            applied = []
            for line in text.splitlines():
                guard = re.search(r"value < (\d+) \} \} (.+) set_variable = \{ which = ap_item_index value = (\d+) \}",
                                  line)
                if guard and item_index < int(guard.group(1)):
                    applied.append(guard.group(2))
                    item_index = int(guard.group(3))
            return applied, item_index

        applied, index = run(render_run_file(effects[:3]), 0)
        self.assertEqual((applied, index), (effects[:3], 3))
        self.assertEqual(run(render_run_file(effects[:3]), index), ([], 3), "running the file twice")
        self.assertEqual(run(render_run_file(effects), index), (effects[3:], 5), "two more items arrived")
        self.assertEqual(run(render_run_file(effects), 1), (effects[1:], 5), "an older save was loaded")


@unittest.skipUnless(GAME_DIR, "Stellaris is not installed")
class GameFilesTest(unittest.TestCase):
    def vanilla(self, folder: str) -> str:
        return "\n".join(path.read_text(encoding="utf-8-sig", errors="replace")
                         for path in sorted((GAME_DIR / folder).glob("*.txt")))

    def test_on_actions_exist(self):
        vanilla = set(top_level_keys(self.vanilla("common/on_actions")))
        for on_action in top_level_keys(mod_script("common/on_actions")):
            # The mod fires its own by itself
            if on_action not in build_mod.RANDOM_EVENT_POOLS:
                self.assertIn(on_action, vanilla)

    def test_random_events_are_the_ones_of_the_game(self):
        """Fails when a game update changes its lists of random events: run build_mod again."""
        generated = (MOD_DIR / "common" / "on_actions" / build_mod.RANDOM_EVENTS_FILE).read_text(encoding="utf-8")
        self.assertEqual(generated, build_mod.render_random_events(GAME_DIR))
        events = self.vanilla("events")
        vanilla = set(top_level_keys(self.vanilla("common/on_actions")))
        pools = dict((key, pdx.get(value, "random_events")) for key, _, value in pdx.parse(generated))
        self.assertEqual(set(pools), set(build_mod.RANDOM_EVENT_POOLS))
        for name, sources in build_mod.RANDOM_EVENT_POOLS.items():
            self.assertLessEqual(set(sources), vanilla, "an on_action of the game is gone")
            self.assertGreater(len(pools[name]), 10, name)
            for weight, _, event in pools[name]:
                self.assertGreater(int(weight), 0)
                self.assertRegex(events, rf"\bid\s*=\s*{re.escape(event)}\b", "the game has no such event")

    def test_data_is_up_to_date(self):
        """Fails after a game update, until python -m stellaris_ap.extract was run."""
        self.assertEqual(extract.read_technologies(GAME_DIR), data.technologies())

    def test_technology_files_are_up_to_date(self):
        """The copies of the game's technology files must match the installed game."""
        expected = build_mod.render_overrides(GAME_DIR)
        folder = MOD_DIR / "common" / "technology"
        self.assertEqual({path.name for path in folder.glob("*.txt")}, set(expected) | {build_mod.CHECKS_FILE})
        for name, text in expected.items():
            self.assertEqual((folder / name).read_text(encoding="utf-8"), text, name)

    def test_only_item_technologies_are_hidden(self):
        hidden = build_mod.hidden_technologies()
        kinds = {technology["key"]: technology["kind"] for technology in data.technologies()}
        self.assertTrue(all(kinds[key] == "item" for key in hidden))
        count = 0
        for name in build_mod.render_overrides(GAME_DIR):
            copy = pdx.parse_file(MOD_DIR / "common" / "technology" / name)
            original = pdx.parse_file(GAME_DIR / "common" / "technology" / name)
            self.assertEqual([key for key, _, _ in copy], [key for key, _, _ in original], name)
            for (key, _, mine), (_, _, theirs) in zip(copy, original):
                if not isinstance(mine, list):
                    continue
                modifiers = pdx.get(mine, "weight_modifier", [])
                zeroed = bool(modifiers) and modifiers[-1][0] == "modifier" and \
                    modifiers[-1][2] == [("factor", "=", "0")] + NOT_AI
                self.assertEqual(zeroed, key in hidden, key)
                count += zeroed
                self.assertEqual([entry for entry in mine if entry[0] != "weight_modifier"],
                                 [entry for entry in theirs if entry[0] != "weight_modifier"], key)
        self.assertEqual(count, len(hidden))

    def test_technology_categories_exist(self):
        vanilla = set(top_level_keys(self.vanilla("common/technology/category")))
        self.assertLessEqual({location["technology"]["category"]
                              for location in build_mod.of_kind(data.locations(), "technology")}, vanilla)

    def test_tradition_data_is_up_to_date(self):
        """Fails after a game update, until python -m stellaris_ap.extract was run."""
        self.assertEqual(extract.read_traditions(GAME_DIR), data.tradition_trees())

    def test_tradition_tree_files_are_up_to_date(self):
        expected = build_mod.render_tradition_categories(GAME_DIR)
        folder = MOD_DIR / "common" / "tradition_categories"
        self.assertEqual({path.name for path in folder.glob("*.txt")}, set(expected))
        for name, text in expected.items():
            self.assertEqual((folder / name).read_text(encoding="utf-8"), text, name)

    def test_ai_keeps_the_real_tradition_trees(self):
        self.assertEqual(len(build_mod.render_tradition_categories(GAME_DIR)), len(data.normal_trees()))
        for tree in data.normal_trees():
            original = dict((key, value) for key, _, value in pdx.parse_file(
                GAME_DIR / "common" / "tradition_categories" / tree["file"]))[tree["key"]]
            mine = dict((key, value) for key, _, value in pdx.parse_file(
                MOD_DIR / "common" / "tradition_categories" / tree["file"]))
            real = mine[build_mod.real_tree(tree["key"])]
            adopt = build_mod.adoption(tree)
            self.assertEqual(pdx.get(real, "potential"),
                             [("OR", "=", [("has_country_flag", "=", "ap_ai"),
                                           ("has_country_flag", "=", build_mod.VANILLA_TRADITIONS)]),
                              ("OR", "=", [("has_tradition", "=", adopt), ("ap_tree_slot_free", "=", "yes")])]
                             + pdx.get(original, "potential", []), tree["key"])
            checks = mine[tree["key"]]
            self.assertEqual(pdx.get(checks, "potential")[:3],
                             [("NOT", "=", [("has_country_flag", "=", "ap_ai")]),
                              ("NOT", "=", [("has_country_flag", "=", build_mod.VANILLA_TRADITIONS)]),
                              ("OR", "=", [("has_tradition", "=", build_mod.check_tradition(adopt)),
                                           ("ap_tree_slot_free", "=", "yes")])], tree["key"])
            self.assertEqual([entry for entry in real if entry[0] != "potential"],
                             [entry for entry in original if entry[0] != "potential"], tree["key"])
            # The player's tree: the same, with locations as its traditions
            player = mine[tree["key"]]
            self.assertEqual(pdx.get(player, "potential")[3:], pdx.get(original, "potential", []), tree["key"])
            self.assertEqual([pdx.get(player, "adoption_bonus").strip('"')]
                             + pdx.values(pdx.get(player, "traditions"))
                             + [pdx.get(player, "finish_bonus").strip('"')], build_mod.picked_keys(tree))
            self.assertEqual(pdx.get(player, "tree_template"), pdx.get(original, "tree_template"))

    def test_the_game_has_seven_tradition_trees_and_eight_ascension_perks(self):
        """The locations are counted with the limits of the game. The mod keeps the one of the trees itself."""
        vanilla = (GAME_DIR / "common" / "defines" / "00_defines.txt").read_text(encoding="utf-8-sig", errors="replace")
        self.assertRegex(vanilla, rf"TRADITION_CATEGORIES_MAX\s*=\s*{data.TREE_SLOTS}\b")
        self.assertRegex(vanilla, rf"ASCENSION_PERKS_SLOTS\s*=\s*{data.ASCENSION_PERK_SLOTS}\b")

    def test_ascension_paths_take_a_tree_counted_by_the_mod(self):
        mine = (MOD_DIR / "common/ascension_perks" / build_mod.ASCENSION_PATHS_FILE).read_text(encoding="utf-8")
        theirs = (GAME_DIR / "common/ascension_perks" / build_mod.ASCENSION_PATHS_FILE).read_text(encoding="utf-8-sig")
        self.assertEqual(mine, build_mod.render_ascension_paths(theirs), "up to date with the game")
        self.assertNotIn("num_tradition_categories", mine)
        self.assertEqual(mine.count("ap_tree_slot_free = yes"), theirs.count("@max_tradition_trees"))
        # The game uses its limit nowhere else
        uses = [path for path in (GAME_DIR / "common").rglob("*.txt")
                if "@max_tradition_trees" in path.read_text(encoding="utf-8-sig", errors="replace")
                and "scripted_variables" not in path.parts]
        self.assertEqual([path.name for path in uses], [build_mod.ASCENSION_PATHS_FILE])

    def test_the_tradition_window_scrolls(self):
        mine = (MOD_DIR / "interface" / build_mod.TRADITION_WINDOW_FILE).read_text(encoding="utf-8")
        theirs = (GAME_DIR / "interface" / build_mod.TRADITION_WINDOW_FILE).read_text(encoding="utf-8-sig")
        self.assertEqual(mine, build_mod.render_tradition_window(theirs), "up to date with the game")
        # The other one is in the window to pick a tree, which scrolls in the game already, the same way
        self.assertEqual(mine.count('name = "tradition_category_gridbox"'), 2)
        scroll = mine[mine.index('name = "ap_tradition_category_scroll"'):]
        grid = scroll[:scroll.index("format")]
        self.assertIn('verticalScrollbar = "right_vertical_slider"', grid)
        self.assertIn('name = "tradition_category_gridbox"', grid, "inside the area that scrolls")
        rows = -(-build_mod.trees_max() // build_mod.TILES_IN_A_ROW)
        self.assertIn(f"height = {rows * build_mod.TILE_HEIGHT}", grid, "room for every tree")
        self.assertBalanced(mine)

    def assertBalanced(self, text):
        depth = 0
        for character in strip_comments(text):
            depth += {"{": 1, "}": -1}.get(character, 0)
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)

    def test_tradition_icons_are_sprites(self):
        """The game looks for the sprite GFX_<tradition>."""
        vanilla = (GAME_DIR / "interface" / "traditions.gfx").read_text(encoding="utf-8-sig")
        self.assertIn('name = "GFX_tr_adaptability_recycling"', vanilla)

    def test_check_traditions_do_not_clash(self):
        vanilla = set(top_level_keys(self.vanilla("common/traditions")))
        vanilla |= set(top_level_keys(self.vanilla("common/tradition_categories")))
        mine = set(top_level_keys(mod_script("common/traditions")))
        mine |= {build_mod.real_tree(tree["key"]) for tree in data.tradition_trees()}
        self.assertFalse(mine & vanilla)

    def test_static_modifiers_exist(self):
        modifiers = (DOCS_DIR / "modifiers.log").read_text(encoding="utf-8", errors="replace")
        for _, _, block in pdx.parse_file(MOD_DIR / "common" / "static_modifiers" / "ap_static_modifiers.txt"):
            for key, _, _ in block:
                self.assertIn(f"- {key},", modifiers)

    def test_no_clash_with_vanilla_names(self):
        for folder in ("common/technology", "common/scripted_effects"):
            clashes = set(top_level_keys(mod_script(folder))) & set(top_level_keys(self.vanilla(folder)))
            self.assertFalse(clashes, folder)
        self.assertNotIn("namespace = ap\n", self.vanilla("events"))

    def test_item_technologies_exist(self):
        vanilla = set(top_level_keys(self.vanilla("common/technology")))
        for item in data.items():
            for tech in re.findall(r"\btech\s*=\s*(\w+)", item["effect"]):
                self.assertIn(tech, vanilla, item["name"])

    def test_item_resources_exist(self):
        vanilla = set(top_level_keys(self.vanilla("common/strategic_resources")))
        for item in data.items():
            for block in re.findall(r"add_resource\s*=\s*\{([^}]*)\}", item["effect"]):
                for resource in keys(block):
                    self.assertIn(resource, vanilla, item["name"])

    def test_the_game_knows_a_defeated_crisis_and_awakened_empires(self):
        self.assertIn("crisis_happened_and_defeated", top_level_keys(self.vanilla("common/scripted_triggers")))
        self.assertIn("awakened_fallen_empire", top_level_keys(self.vanilla("common/country_types")))

    def test_descriptors_match_the_installed_version(self):
        installed = re.search(r'"rawVersion":\s*"v(\d+\.\d+)',
                              (GAME_DIR / "launcher-settings.json").read_text(encoding="utf-8")).group(1)
        for mod_dir in (MOD_DIR, HIDDEN_CONSOLE_MOD_DIR):
            self.assertIn(f'supported_version="v{installed}.*"',
                          (mod_dir / "descriptor.mod").read_text(encoding="utf-8"), mod_dir.name)

    def test_event_pictures_exist(self):
        vanilla = "\n".join(path.read_text(encoding="utf-8-sig", errors="replace")
                            for path in (GAME_DIR / "interface").glob("*.gfx"))
        for picture in re.findall(r"\bpicture\s*=\s*(\w+)", mod_script("events")):
            self.assertIn(f'"{picture}"', vanilla)

    def test_doom_deposits_and_planet_classes_exist(self):
        effects = strip_comments(mod_script("common/scripted_effects"))
        deposits = set(top_level_keys(self.vanilla("common/deposits")))
        classes = set(top_level_keys(self.vanilla("common/planet_classes")))
        self.assertLessEqual(set(re.findall(r"add_deposit\s*=\s*(\w+)", effects)), deposits)
        self.assertLessEqual(set(re.findall(r"\bpc_\w+", effects)), classes)

    def test_hidden_console_is_the_vanilla_console_moved_off_screen(self):
        """Fails when a game update changes the console, the override then has to be redone."""
        def normalise(text: str) -> str:
            text = re.sub(r"\s+", "", strip_comments(text))
            return re.sub(r'(name="console_wnd"position=)\{[^}]*\}', r"\1{}", text)

        vanilla = (GAME_DIR / "interface" / "console.gui").read_text(encoding="utf-8-sig")
        hidden = (HIDDEN_CONSOLE_MOD_DIR / "interface" / "console.gui").read_text(encoding="utf-8")
        self.assertEqual(normalise(hidden), normalise(vanilla))
        self.assertIn("position = { x = -5000 y = -5000 }", hidden)


class StartOfAGameTest(unittest.TestCase):
    def test_leaders_the_game_throws_away_at_the_start_are_no_deaths(self):
        effects = (MOD_DIR / "common" / "scripted_effects" / "ap_effects.txt").read_text(encoding="utf-8")
        events = (MOD_DIR / "events" / "ap_events.txt").read_text(encoding="utf-8")
        setup = effects[effects.index("set_country_flag = ap_new_game"):effects.index("ap_mailbox_ready")]
        self.assertRegex(setup, r"set_timed_country_flag = \{ flag = ap_starting days = \d+ \}")
        leader = events[events.index("id = ap.30"):events.index("id = ap.31")]
        self.assertIn("NOT = { has_country_flag = ap_starting }", leader[:leader.index("immediate")])


@unittest.skipUnless((DOCS_DIR / "effects.log").is_file(), "no script documentation, run script_docs in the console")
class ScriptDocumentationTest(unittest.TestCase):
    """Every effect and trigger the mod and the run file use must be known to the game."""

    def test_effects_and_triggers_exist(self):
        documented = set()
        for name in ("effects.log", "triggers.log"):
            text = (DOCS_DIR / name).read_text(encoding="utf-8", errors="replace")
            documented |= set(re.findall(r"^(\w+) - ", text, flags=re.MULTILINE))
        items = data.items()
        script = mod_script("events", "common/scripted_effects") + render_run_file([i["effect"] for i in items])
        resources = {key for item in items
                     for block in re.findall(r"add_resource\s*=\s*\{([^}]*)\}", item["effect"]) for key in keys(block)}
        own = set(top_level_keys(mod_script("common/scripted_effects"))) | {"event_target:ap_player", "effect"}
        unknown = keys(script) - documented - EVENT_KEYS - resources - own
        self.assertFalse(unknown, "not an effect or trigger")


if __name__ == "__main__":
    unittest.main()
