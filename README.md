# Stellaris Archipelago

An [Archipelago](https://archipelago.gg) multiworld integration for Stellaris. Work in progress:
so far this is the bridge prototype between the game and a client, without a server connection.

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
  game. The mod looks into that mailbox once a day and grants the item. Nothing happens on screen,
  and items arrive while the game is not paused. Windows and single player only.
- `data/` holds the item and location tables shared by the mod and the client.
  `python -m stellaris_ap.extract` reads the technologies from the installed game, and
  `python -m stellaris_ap.build_mod` generates the mod from them. Run both after a game update.

As a fallback the client also writes all received items to `ap.txt` in the Stellaris user
directory, which can be run with the console command `run ap.txt`. `--delivery console` makes the
client do that itself by pressing keys in the game; `mod/archipelago_hidden_console` is an
optional mod that moves the console off screen for that mode.

## The Archipelago world

`apworld/stellaris` is the world, which `python -m stellaris_ap.build_apworld --install` packs into
`stellaris.apworld` and copies into Archipelago's `custom_worlds` folder. Its options:

- `goal`: collect Precursor Fragments (`fragment_count`, `fragments_required`), or send a share of
  your locations (`locations_required`).
- `owned_dlc`, `empire_type`: technologies and traditions the player cannot use stay out of the
  multiworld. The locations are the same for everyone.
- `early_progression`: the late game (technologies of tier 4 and 5, tradition trees 5 to 7,
  ascension perks 5 to 8) only holds filler.
- `death_link`, `deaths_per_doom`, `doom`.

## Playing

Requires Python 3.10+ on Windows. The one package the client needs (`websockets`) is installed by
itself at the first start.

1. `python -m stellaris_ap.build_mod --install`, then enable "Archipelago" in the Stellaris launcher.
2. Double click `Play Stellaris Archipelago.bat`. In the window that opens, enter the address of
   the server, the name of your slot and its password, and press Connect. The client names the
   technologies and traditions in game after what they send, then "Start Stellaris" starts the game.
   "Offline" plays a randomizer of the client's own instead, without a server.
3. The window stays open while you play. It shows what happens (checks, items, hints, deaths), and
   what you type at the bottom goes to the multiworld: `!hint <item>` asks for a hint, `/help`
   lists the rest. The same is written to `client.log`.
4. A new game belongs to the multiworld slot (or offline shuffle) it was started under, and its
   saves keep that: with another one connected, a save sends and receives nothing, and says so in
   game.
5. In game, items arrive with a message. `event ap.100` in the console opens the Archipelago menu.

`python -m stellaris_ap.client --offline` is the client without a window, for testing, and
`python tools/try_server.py <address> <slot>` plays a few checks against a server without the game.

Tests: `python -m unittest discover -s tests`
