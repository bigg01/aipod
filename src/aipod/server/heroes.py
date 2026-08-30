"""A small Marvel super-hero roster used by the ``*_hero*`` tools.

The data here is a handful of widely-known, factual attributes (publisher-stated
team affiliations, broad power categories, first-appearance years). It exists to
give the reference server a second, more relatable domain to exercise structured
output, resource templates, argument completion, and sampling against - it is not
an authoritative or complete character database.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Hero(BaseModel):
    """One character in the roster."""

    codename: str = Field(description="The hero's public alias, lower-case-slug form (e.g. 'spider-man')")
    name: str = Field(description="Civilian / birth name")
    teams: list[str] = Field(description="Team affiliations")
    powers: list[str] = Field(description="Broad power / skill categories")
    origin: str = Field(description="One-sentence origin summary")
    first_appearance: int = Field(description="Year the character first appeared in print")


class HeroRoster(BaseModel):
    """A list of heroes plus its length, returned by the listing / search tools."""

    count: int
    heroes: list[Hero]


class TeamPick(BaseModel):
    codename: str
    reason: str = Field(description="Why this hero fits the stated threat")


class MissionTeam(BaseModel):
    """The output of ``assemble_team``."""

    threat: str
    members: list[TeamPick]


_ROSTER: list[Hero] = [
    Hero(
        codename="spider-man",
        name="Peter Parker",
        teams=["Avengers"],
        powers=["superhuman strength", "wall-crawling", "agility", "precognitive spider-sense"],
        origin="Gained his abilities after a bite from a radioactive spider.",
        first_appearance=1962,
    ),
    Hero(
        codename="iron-man",
        name="Tony Stark",
        teams=["Avengers"],
        powers=["powered armor", "flight", "energy repulsors", "genius-level intellect"],
        origin="Built the first Iron Man armor to escape captivity and stay alive.",
        first_appearance=1963,
    ),
    Hero(
        codename="captain-america",
        name="Steve Rogers",
        teams=["Avengers"],
        powers=["peak human strength", "enhanced endurance", "vibranium shield", "master tactician"],
        origin="A frail volunteer transformed by the experimental Super-Soldier Serum.",
        first_appearance=1941,
    ),
    Hero(
        codename="thor",
        name="Thor Odinson",
        teams=["Avengers"],
        powers=["god-like strength", "flight", "weather and lightning control", "near-invulnerability"],
        origin="The Asgardian god of thunder, wielder of the enchanted hammer Mjolnir.",
        first_appearance=1962,
    ),
    Hero(
        codename="hulk",
        name="Bruce Banner",
        teams=["Avengers"],
        powers=["limitless strength that scales with rage", "regeneration", "durability"],
        origin="A physicist caught in the blast of his own gamma bomb.",
        first_appearance=1962,
    ),
    Hero(
        codename="black-widow",
        name="Natasha Romanoff",
        teams=["Avengers"],
        powers=["master espionage", "hand-to-hand combat", "marksmanship", "acrobatics"],
        origin="A former intelligence operative trained from childhood in the Red Room.",
        first_appearance=1964,
    ),
    Hero(
        codename="black-panther",
        name="T'Challa",
        teams=["Avengers"],
        powers=["enhanced senses", "enhanced agility", "vibranium habit", "peak combat skill"],
        origin="King of Wakanda, empowered by the heart-shaped herb.",
        first_appearance=1966,
    ),
    Hero(
        codename="captain-marvel",
        name="Carol Danvers",
        teams=["Avengers"],
        powers=["flight", "superhuman strength", "energy projection", "energy absorption"],
        origin="An Air Force pilot whose physiology was fused with Kree genetics.",
        first_appearance=1968,
    ),
    Hero(
        codename="doctor-strange",
        name="Stephen Strange",
        teams=["Avengers", "Masters of the Mystic Arts"],
        powers=["sorcery", "astral projection", "dimensional travel", "time manipulation"],
        origin="A surgeon who sought healing at Kamar-Taj and became Sorcerer Supreme.",
        first_appearance=1963,
    ),
    Hero(
        codename="scarlet-witch",
        name="Wanda Maximoff",
        teams=["Avengers", "X-Men"],
        powers=["chaos magic", "reality warping", "telekinesis", "energy manipulation"],
        origin="A reality-altering mutant and practitioner of chaos magic.",
        first_appearance=1964,
    ),
    Hero(
        codename="storm",
        name="Ororo Munroe",
        teams=["X-Men"],
        powers=["weather manipulation", "flight", "lightning control"],
        origin="A mutant able to command the weather, once revered as a goddess.",
        first_appearance=1975,
    ),
    Hero(
        codename="wolverine",
        name="Logan",
        teams=["X-Men"],
        powers=["accelerated healing", "adamantium claws", "enhanced senses", "heightened stamina"],
        origin="A mutant whose skeleton was bonded with adamantium by the Weapon X program.",
        first_appearance=1974,
    ),
]

ROSTER: dict[str, Hero] = {hero.codename: hero for hero in _ROSTER}

# Every distinct team name, for argument completion.
TEAMS: list[str] = sorted({team for hero in _ROSTER for team in hero.teams})


def _slug(value: str) -> str:
    return value.strip().lower().replace(" ", "-").replace("_", "-")


def get(codename: str) -> Hero:
    """Look a hero up by codename (case- and separator-insensitive)."""

    try:
        return ROSTER[_slug(codename)]
    except KeyError:
        raise ValueError(
            f"unknown hero {codename!r}; known codenames: {', '.join(sorted(ROSTER))}"
        ) from None


def all_heroes(team: str | None = None) -> list[Hero]:
    if team is None:
        return list(_ROSTER)
    needle = team.strip().lower()
    return [h for h in _ROSTER if any(needle in t.lower() for t in h.teams)]


def by_power(power: str) -> list[Hero]:
    needle = power.strip().lower()
    return [h for h in _ROSTER if any(needle in p.lower() for p in h.powers)]


def assemble_team(threat: str, size: int = 3) -> MissionTeam:
    """Deterministically pick the heroes whose powers best match ``threat``."""

    size = max(1, min(size, len(_ROSTER)))
    words = {w for w in "".join(c if c.isalnum() else " " for c in threat.lower()).split() if len(w) > 3}

    def score(hero: Hero) -> tuple[int, int]:
        blob = " ".join(hero.powers + [hero.origin]).lower()
        hits = sum(1 for w in words if w in blob)
        # Break ties by seniority (earlier first appearance first).
        return (hits, -hero.first_appearance)

    ranked = sorted(_ROSTER, key=score, reverse=True)[:size]
    members = []
    for hero in ranked:
        blob = " ".join(hero.powers + [hero.origin]).lower()
        matched = sorted(w for w in words if w in blob)
        reason = (
            f"matches on {', '.join(matched)}"
            if matched
            else f"all-rounder: {hero.powers[0]}"
        )
        members.append(TeamPick(codename=hero.codename, reason=reason))
    return MissionTeam(threat=threat, members=members)
