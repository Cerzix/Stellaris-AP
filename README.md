# Stellaris Archipelago

An [Archipelago](https://archipelago.gg) multiworld integration for Stellaris: the technologies,
traditions and ascension perk slots of the game are shuffled into the multiworld.

Windows and single player only. Made for Stellaris 4.5 and Archipelago 0.6.7 or newer.

## Installing

You need [Python](https://www.python.org/downloads/) 3.10 or newer (tick "Add python.exe to PATH" in
its installer) and the zip of a [release](../../releases).

1. Unpack the zip anywhere, and keep the folder: the game loads the mod from it.
2. Copy `stellaris.apworld` into the `custom_worlds` folder of Archipelago, and make your YAML with
   Archipelago's Options Creator. Generate and host the multiworld as for any other game.
3. Double click `Play Stellaris Archipelago.bat`. The first time it installs what it needs by itself,
   and registers the mod with the Stellaris launcher.
4. In the Stellaris launcher, add the mod "Archipelago" to your playset and enable it. This is needed
   once.

## Playing

1. Double click `Play Stellaris Archipelago.bat`. In the window that opens, enter the address of the
   server, the name of your slot and its password, and press Connect. The client names the
   technologies and traditions in game after what they send; then "Start Stellaris" starts the game.
   Connect before starting the game: it reads those names once, at its start.
2. Start a new game. It belongs to the multiworld slot it was started under, and its saves keep
   that: with another multiworld connected, a save sends and receives nothing, and says so in game.
3. Research the "Archipelago: ..." technologies and adopt traditions to send checks. What you receive
   arrives with a message in game, while the game is not paused.
4. The window stays open while you play. It shows what happens (checks, items, hints, deaths), and
   what you type at the bottom goes to the multiworld: `!hint <item>` asks for a hint, `/help` lists
   the rest. The same is written to `client.log`.
5. "Tracker" opens the technology tree of the game with what every technology holds, what is
   checked and what you have received. Drag to move, use the wheel to zoom, click a technology to
   keep it shown.
6. If you lose, start a new game while connected to the same slot: it starts with everything the
   multiworld has given you so far.

`event ap.100` in the game's console opens a small Archipelago menu.

## How it works

- Every technology is an Archipelago item, except the ones the game hands out at the start
  (corvettes, starbases, colony ships, labs, the basic resources and weapons) and the repeatable
  ones. The player is never offered the item technologies as research. In their place there is a
  location to research for each of them, in the same area and tier and at the same cost, named
  after the item it holds.
- The tradition screen stays as it is: 7 trees, picked from the ones the empire can normally
  have. In the normal trees every tradition is a location, with the Archipelago icon and a
  tooltip that says what it sends. The 49 locations are told apart by the order in which the
  trees were adopted and the place of the tradition in its tree, so they can all be reached
  whichever trees the player picks. The real traditions arrive as items (not the adoption and
  finish bonuses). The trees of the ascension paths keep their traditions, and count as one of
  the 7 trees.
- Ascension perk slots only come from the item "Progressive Ascension". Picking a perk is a location.
- `mod/archipelago` is the Stellaris mod. Researching a location writes `AP_CHECK <n>` to
  `game.log`, which the client reads.
- `stellaris_ap` is the client. Stellaris cannot receive data while it runs, so the client writes
  the id of each received item into a script variable (`ap_mailbox`) in the memory of the running
  game. The mod looks into that mailbox once a day and grants the item.
- `data/` holds the item and location tables shared by the mod, the client and the world.

## The Archipelago world

`apworld/stellaris` is the world, packed into `stellaris.apworld`. Its options:

- `goal`: collect Precursor Fragments (`fragment_count`, `fragments_required`), send a share of your
  locations (`locations_required`), defeat the endgame crisis, or defeat it with no awakened fallen
  empire left.
- `owned_dlc`, `empire_type`: technologies and traditions the player cannot use stay out of the
  multiworld. The locations are the same for everyone.
- `early_progression`: the late game (technologies of tier 4 and 5, tradition trees 5 to 7,
  ascension perks 5 to 8) only holds filler.
- `random_events`: how many Random Events are mixed in, which do something good or bad on arrival.
- DeathLink: `death_link`, what sends a death (`death_on_ruler`, `death_on_leader`,
  `death_on_colony`, `death_on_battle`), what a received death takes (`death_effect`), and the doom
  that destroys a colony after some deaths (`deaths_per_doom`, `doom`, `doom_capital`).

## Development

- `python -m stellaris_ap.extract` reads the technologies and traditions from the installed game
  into `data/`, `python -m stellaris_ap.build_mod` generates the mod from them, and
  `python -m stellaris_ap.build_apworld --install` packs the world and copies it into Archipelago.
  Run all three after a game update.
- `python -m unittest discover -s tests` runs the tests. The ones that compare with the game are
  skipped where it is not installed.
- `python -m stellaris_ap.client --offline` is the client without a window and without a server, and
  `python tools/try_server.py <address> <slot>` plays a few checks against a server without the game.
- A tag `v*` on master makes a release: the zip with everything needed to play, and the world.
