# Changelog

## 1.1.0

From the first full test in the game.

### Changed

- Random Events are events of Stellaris itself now, not ones made up for this: the kind the game
  brings up on a colony that is a few years old, or in an empire every few years. Which one comes up
  is up to the game, and it brings its own message. In a new game of a run they are played again one
  after the other over the first years, each with its own message, instead of all at once.
- A tradition received as an item no longer leaves its tree in the tradition window, where it took
  the place of a tree to adopt. The traditions you have received are listed in the tracker, under
  "Archipelago Traditions". Whether the game lets a tree be taken away like this is not tested yet:
  the client's log says which it was, the first time a tradition arrives.
- A death from the multiworld takes the ruler if no other leader is left.

### Added

- The option `randomize_traditions`. Turned off, the tradition trees are the ones of the game.
- The tracker shows how far the goal is on a line of its own, counts the locations to two decimals,
  and has a Refresh button that reads everything again.
- `/status` and the line under the connection show your hint points and what a hint costs, as the
  server counts them.

### Fixed

- The first leader a new game throws away is not a death for everyone.
- The client no longer takes the log Stellaris left behind the last time for a game that is loaded now.
  Without the game running it reported an empire and DLCs of that earlier game, and warned about them.
- The search of the tracker does not light up a location whose item is hidden.
- When the client is started a second time, the window of the first one closes.

## 1.0.0

The first release: Stellaris in an Archipelago multiworld.

### The randomizer

- Every technology is an item, apart from the ones an empire starts with and the repeatable ones. In
  the place of each there is a location to research, named in game after the item it holds.
- The traditions of the seven trees an empire adopts are locations, and the real traditions are items.
- Ascension perk slots are the item Progressive Ascension, and picking a perk is a location.
- Random Events can be mixed in, which do something good or bad when they arrive.
- Goals: collect Precursor Fragments, send a share of your locations, defeat the endgame crisis, or
  defeat it with no awakened fallen empire left.
- Technologies and traditions of DLC you do not own, or of another kind of empire than yours, stay
  out of the multiworld.
- DeathLink: a ruler or leader who dies, a lost colony or a lost battle is a death for everyone. A
  death you receive takes a leader or a fleet, and after some deaths a doom destroys a colony.

### The client

- One window: connect to a multiworld, start the game from it, and watch what happens in a log.
  What you type goes to the multiworld, so `!hint <item>` asks for a hint.
- A tracker: the technology tree of the game with what every technology holds, what is checked,
  what can come up as research right now and what you have received. It shows the icons of the
  technologies, can be moved, zoomed, searched as you type and filtered by kind, its parts fold
  away, and it counts the locations done. It has a dark and a light theme, its colours can be
  changed, and a legend explains what its boxes mean. What a location holds stays hidden until it
  is checked, unless spoilers are turned on.
- Items arrive in the running game in the background, with a message that says who sent them.
- A save belongs to the multiworld slot it was started under. Loaded with another one connected, it
  sends and receives nothing.
- A new game of a multiworld you already play starts with everything it has given you so far: the
  technologies, traditions, ascension perk slots and resources, the technologies of the locations
  that are done, and a new Random Event for each one received.
- What was checked without a connection is sent when it is back, and what was received while away
  arrives when the save is loaded.
- The client installs the packages it needs and registers the mod with the Stellaris launcher by
  itself.

### For development

- The tests run on GitHub for every push and pull request.
- A version tag like `1.0.0` on master makes a release with a zip of everything needed to play, and
  the world.
