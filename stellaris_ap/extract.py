"""Reads the technologies and tradition trees from the installed game into data/.

    python -m stellaris_ap.extract

Run again after a game update, then python -m stellaris_ap.build_mod.

Every technology has a kind:
- "start": the game hands it out at the start (start_tech = yes), or its start of game scripts give
  or offer it to some empires, like Societal Unification or the technologies that clear the
  blockers of the homeworld. These are the base technologies, they stay as they are.
- "repeatable": the endless technologies, they stay as they are.
- "item": everything else. These are Archipelago items, and each gives one location to research.

Technologies and tradition trees also get the DLCs they need ("dlc") and the kinds of empire that can
use them ("empires"), see requirements.py. A technology needs what the technologies before it need.
"""
import argparse
import json
import re
import sys

from . import pdx
from .paths import DATA_DIR, stellaris_game_dir
from .requirements import Requirements

# The trees of the ascension paths. The other files hold the trees an empire can simply adopt
ASCENSION_TREE_FILES = "01_*.txt"
# Tradition items have the ids above this. Below are the technologies and the locations
TRADITION_ID_BASE = 1100
START_SCRIPTS =("events/game_start.txt", "common/scripted_effects/01_start_of_game_effects.txt")
LOCALISATION_LINE =re.compile(r'^\s*([\w.\-]+):\d*\s*"(.*)"\s*$')


def scripted_variables(game_dir) -> dict[str, str]:
    variables = {}
    for path in sorted((game_dir / "common" / "scripted_variables").glob("*.txt")):
        for key, _, value in pdx.parse_file(path):
            if key.startswith("@") and isinstance(value, str):
                variables[key] = value
    return variables


def number(value, variables: dict[str, str]) -> float:
    if isinstance(value, list):
        # A computed value: cost = { base = 1000 ... }
        value = pdx.get(value, "base")
    while value in variables:
        value = variables[value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def english_names(game_dir) -> dict[str, str]:
    names = {}
    for path in sorted((game_dir / "localisation" / "english").rglob("*.yml")):
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            match = LOCALISATION_LINE.match(line)
            if match:
                names[match.group(1)] = match.group(2)
    return names


def display_name(key: str, names: dict[str, str]) -> str:
    name = names.get(key, key)
    # Names can refer to other names: "$tech_lasers_1$ II"
    for _ in range(5):
        name, replaced = re.subn(r"\$([\w.\-]+)\$", lambda match: names.get(match.group(1), match.group(1)), name)
        if not replaced:
            break
    # Colour codes and icons
    name = re.sub(r"§.|£\w+£?", "", name)
    return " ".join(name.split()) or key


def start_script_technologies(game_dir) -> set[str]:
    """The technologies the game's own scripts give or offer to an empire when the game starts."""
    found = set()
    for name in START_SCRIPTS:
        text = re.sub(r"#.*", "", (game_dir / name).read_text(encoding="utf-8-sig", errors="replace"))
        found.update(re.findall(r'\badd_research_option\s*=\s*"?(\w+)', text))
        found.update(re.findall(r'\bgive_technology\s*=\s*\{\s*tech\s*=\s*"?(\w+)', text))
    return found


def read_technologies(game_dir) -> list[dict]:
    variables = scripted_variables(game_dir)
    names = english_names(game_dir)
    from_start_scripts = start_script_technologies(game_dir)
    requirements = Requirements(game_dir)
    prerequisites = {}
    technologies = []
    for path in sorted((game_dir / "common" / "technology").glob("*.txt")):
        local = dict(variables)
        for key, _, value in pdx.parse_file(path):
            if key.startswith("@"):
                local[key] = value
                continue
            if not isinstance(value, list):
                continue
            if pdx.get(value, "start_tech") == "yes" or key in from_start_scripts:
                kind = "start"
            elif pdx.get(value, "levels") is not None:
                kind = "repeatable"
            else:
                kind = "item"
            technologies.append({
                "key": key,
                "name": display_name(key, names),
                "kind": kind,
                "area": pdx.get(value, "area"),
                "tier": int(number(pdx.get(value, "tier"), local)),
                "category": pdx.values(pdx.get(value, "category", []))[0],
                "cost": int(number(pdx.get(value, "cost"), local)),
                "weight": number(pdx.get(value, "weight"), local),
                "file": path.name,
                "dlc": requirements.dlcs(pdx.get(value, "potential", [])),
                "empires": requirements.empires(pdx.get(value, "potential", [])),
            })
            prerequisites[key] = pdx.values(pdx.get(value, "prerequisites", []))
    technologies.sort(key=lambda technology: technology["key"])
    # The technologies that come before it in the game's tree, for the tracker
    known = {technology["key"] for technology in technologies}
    for technology in technologies:
        technology["prerequisites"] = [key for key in prerequisites[technology["key"]] if key in known]

    # A technology that follows one of a DLC, or one closed to a kind of empire, is no use without it either
    by_key = {technology["key"]: technology for technology in technologies}
    changed = True
    while changed:
        changed = False
        for technology in technologies:
            for required in prerequisites[technology["key"]]:
                before = by_key.get(required)
                if before is None:
                    continue
                dlc = sorted(set(technology["dlc"]) | set(before["dlc"]))
                empires = [empire for empire in technology["empires"] if empire in before["empires"]]
                if dlc != technology["dlc"] or empires != technology["empires"]:
                    technology["dlc"], technology["empires"] = dlc, empires
                    changed = True

    # Archipelago needs unique names
    count = {}
    for technology in technologies:
        count[technology["name"]] = count.get(technology["name"], 0) + 1
    for technology in technologies:
        if count[technology["name"]] > 1:
            technology["name"] = f"{technology['name']} ({technology['key'].removeprefix('tech_')})"
    for number_, technology in enumerate((t for t in technologies if t["kind"] == "item"), 1):
        technology["id"] = number_
    return technologies


def required_traditions(block) -> list[str]:
    """Every tradition a trigger asks for with has_tradition."""
    found = []
    for key, _, value in block:
        if key == "has_tradition":
            found.append(value.strip('"'))
        elif isinstance(value, list):
            found.extend(required_traditions(value))
    return found


def read_traditions(game_dir) -> list[dict]:
    """The tradition trees. Each lists its traditions in order: the adoption bonus, the traditions, the finish bonus.

    kind "normal": a tree an empire can simply adopt. For the player its traditions are locations, and
    the traditions in between the adoption and finish bonus are items.
    kind "ascension": the tree of an ascension path, which stays as it is.
    """
    names = english_names(game_dir)
    requirements = Requirements(game_dir)
    definitions = {}
    for path in sorted((game_dir / "common" / "traditions").glob("*.txt")):
        definitions.update((key, value) for key, _, value in pdx.parse_file(path) if isinstance(value, list))
    trees = []
    for path in sorted((game_dir / "common" / "tradition_categories").glob("*.txt")):
        for key, _, value in pdx.parse_file(path):
            # A tree nobody can adopt holds traditions for tooltips
            if not isinstance(value, list) or pdx.get(pdx.get(value, "potential", []), "always") == "no":
                continue
            adopt = pdx.get(value, "adoption_bonus").strip('"')
            finish = pdx.get(value, "finish_bonus").strip('"')
            keys = [adopt] + pdx.values(pdx.get(value, "traditions")) + [finish]
            traditions = []
            for tradition in keys:
                definition = definitions[tradition]
                traditions.append({
                    "key": tradition,
                    "name": display_name(tradition, names),
                    "role": "adopt" if tradition == adopt else "finish" if tradition == finish else "tradition",
                    "requires": [required for required in required_traditions(pdx.get(definition, "possible", []))
                                 if required in keys],
                })
            trees.append({"key": key, "name": display_name(key, names), "file": path.name,
                          "kind": "ascension" if path.match(ASCENSION_TREE_FILES) else "normal",
                          "dlc": requirements.dlcs(pdx.get(value, "potential", [])),
                          "empires": requirements.empires(pdx.get(value, "potential", [])),
                          "template": pdx.get(value, "tree_template").strip('"'), "traditions": traditions})
    trees.sort(key=lambda tree: tree["key"])
    items = [tradition for tree in trees if tree["kind"] == "normal"
             for tradition in tree["traditions"] if tradition["role"] == "tradition"]
    count = {}
    for tradition in items:
        count[tradition["name"]] = count.get(tradition["name"], 0) + 1
    for number_, tradition in enumerate(items, TRADITION_ID_BASE + 1):
        if count[tradition["name"]] > 1:
            tradition["name"] = f"{tradition['name']} ({tradition['key'].removeprefix('tr_')})"
        tradition["id"] = number_
    return trees


def write_json(name: str, entries: list[dict]) -> None:
    with open(DATA_DIR / f"{name}.json", "w", encoding="utf-8", newline="\n") as f:
        f.write("[\n" + ",\n".join("\t" + json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n]\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game-dir", help="Stellaris install directory (default: found through Steam)")
    args = parser.parse_args()
    game_dir = stellaris_game_dir(args.game_dir)
    if game_dir is None:
        sys.exit("Stellaris install not found, pass --game-dir")
    technologies = read_technologies(game_dir)
    write_json("technologies", technologies)
    kinds = {kind: sum(t["kind"] == kind for t in technologies) for kind in ("start", "repeatable", "item")}
    print(f"{len(technologies)} technologies: {kinds}")
    trees = read_traditions(game_dir)
    write_json("traditions", trees)
    print(f"{len(trees)} tradition trees, {sum(tree['kind'] == 'normal' for tree in trees)} of them normal")


if __name__ == "__main__":
    main()
