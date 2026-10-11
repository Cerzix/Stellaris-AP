# Changelog

## 0.1.0

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
- A tag `v*` on master makes a release with a zip of everything needed to play, and the world.
