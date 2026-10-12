from dataclasses import dataclass

from Options import Choice, DeathLink, DefaultOnToggle, OptionSet, PerGameCommonOptions, Range, Toggle

from . import content


class Goal(Choice):
    """What it takes to win.

    fragments: collect Precursor Fragments, which are found all over the multiworld.
    locations: send a share of your own locations (technologies, traditions and ascension perks).
    crisis: an endgame crisis has appeared in your galaxy and was defeated, by you or by anyone else.
    crisis_and_fallen_empires: the same, and no awakened fallen empire is left."""
    display_name = "Goal"
    option_fragments = 0
    option_locations = 1
    option_crisis = 2
    option_crisis_and_fallen_empires = 3
    default = 0


class FragmentCount(Range):
    """Goal fragments: how many Precursor Fragments there are in the multiworld."""
    display_name = "Precursor Fragments"
    range_start = 1
    range_end = 50
    default = 12


class FragmentsRequired(Range):
    """Goal fragments: how many Precursor Fragments it takes to win. Not more than there are."""
    display_name = "Precursor Fragments Required"
    range_start = 1
    range_end = 50
    default = 10


class LocationsRequired(Range):
    """Goal locations: the percentage of your locations you have to send to win."""
    display_name = "Locations Required (Percent)"
    range_start = 5
    range_end = 100
    default = 40


class OwnedDLC(OptionSet):
    """The DLCs you own. Technologies and traditions of the others stay out of the multiworld, since they
    would do nothing for you. Your locations do not depend on your DLCs."""
    display_name = "Owned DLC"
    valid_keys = frozenset(content.DLCS)
    default = frozenset(content.DLCS)


class EmpireType(Choice):
    """The kind of empire you play. Technologies and traditions the others cannot use stay out of the multiworld."""
    display_name = "Empire Type"
    option_regular = 0
    option_hive = 1
    option_machine = 2
    default = 0


class RandomizeTraditions(DefaultOnToggle):
    """Whether the traditions are shuffled into the multiworld. If they are, every tradition you adopt is a
    location, and the real traditions arrive as items and work whichever trees you have adopted.
    If they are not, the tradition trees are the ones of the game and have nothing to do with the multiworld.
    Ascension perk slots come from Progressive Ascension either way."""
    display_name = "Randomize Traditions"


class EarlyProgression(DefaultOnToggle):
    """Keeps everything a player needs to win out of your late game: technologies of tier 4 and 5,
    the fifth to seventh tradition tree and the fifth to eighth ascension perk only hold filler."""
    display_name = "Early Progression"


class RandomEvents(Range):
    """How many Random Events are mixed into the multiworld. When one arrives, one of the random events of
    Stellaris itself comes up: the kind the game otherwise brings up on a colony or in an empire every few
    years, good or bad."""
    display_name = "Random Events"
    range_start = 0
    range_end = 50
    default = 10


class DeathOnRuler(DefaultOnToggle):
    """DeathLink: when your ruler dies, that is a death for everyone."""
    display_name = "Send a Death: Ruler Dies"


class DeathOnLeader(Toggle):
    """DeathLink: when any other of your leaders dies, that is a death for everyone."""
    display_name = "Send a Death: Leader Dies"


class DeathOnColony(DefaultOnToggle):
    """DeathLink: when one of your colonies is invaded or destroyed, that is a death for everyone."""
    display_name = "Send a Death: Colony Lost"


class DeathOnBattle(DefaultOnToggle):
    """DeathLink: when one of your military fleets loses a battle, that is a death for everyone. At most one
    death a minute is sent, so a battle of many fleets is one."""
    display_name = "Send a Death: Battle Lost"


class DeathEffect(Choice):
    """DeathLink: what a death in the multiworld takes from you.

    leader_or_fleet: one or the other.
    leader: one of your leaders dies, but not your ruler.
    fleet: one of your military fleets is destroyed.
    none: nothing, it only counts towards a doom."""
    display_name = "Death Effect"
    # Not called random: in a YAML that word picks one of the options at random
    option_leader_or_fleet = 0
    option_leader = 1
    option_fleet = 2
    option_none = 3
    default = 0


class DeathsPerDoom(Choice):
    """DeathLink: how many deaths in the multiworld it takes for a doom, which destroys one of your colonies."""
    display_name = "Deaths per Doom"
    option_every_death = 1
    option_every_2_deaths = 2
    option_every_3_deaths = 3
    option_every_5_deaths = 5
    option_every_10_deaths = 10
    option_never = 0
    default = 3


class Doom(Choice):
    """DeathLink: what happens to the colony.

    cracked: the planet is shattered for good.
    tomb: it becomes a tomb world covered in ruins, which can be settled again."""
    display_name = "Doom"
    option_cracked = 0
    option_tomb = 1
    default = 0


class DoomCapital(Toggle):
    """DeathLink: whether a doom may strike your capital too. If it is your only planet, that is the end."""
    display_name = "Doom Can Strike the Capital"


@dataclass
class StellarisOptions(PerGameCommonOptions):
    goal: Goal
    fragment_count: FragmentCount
    fragments_required: FragmentsRequired
    locations_required: LocationsRequired
    owned_dlc: OwnedDLC
    empire_type: EmpireType
    randomize_traditions: RandomizeTraditions
    early_progression: EarlyProgression
    death_link: DeathLink
    random_events: RandomEvents
    death_on_ruler: DeathOnRuler
    death_on_leader: DeathOnLeader
    death_on_colony: DeathOnColony
    death_on_battle: DeathOnBattle
    death_effect: DeathEffect
    deaths_per_doom: DeathsPerDoom
    doom: Doom
    doom_capital: DoomCapital
