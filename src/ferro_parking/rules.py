"""Load config/rules.toml (R1-R10). See docs/PP_rules_and_pilot.md for sources."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("config/rules.toml")


def norm_chain_key(name):
    """Match osm_match.norm/chain_key: lowercase, apostrophes dropped, one space."""
    s = (name or "").lower().replace("&", " and ").replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@dataclass
class Rules:
    r1_category_defaults: dict
    r3_own_brand_names: set
    r6_chains: dict                  # normalised chain key -> {who_can_park?, cost_type?, operator?}
    r7_risky_cost_types: set
    r7_risky_who_can_park: set
    r9_explicit_no_parking_phrases: list
    r10_nearby_car_park_radius_m: float
    r10_large_formats: list      # list of word-lists; all words must appear in the name
    r10_convenience_formats: list
    r10_small_venue_categories: set

    def is_own_brand_operator(self, operator_tag):
        return norm_chain_key(operator_tag) in self.r3_own_brand_names

    def chain_for(self, location_name):
        """The R6 chain rule for a location's first word(s), or None."""
        words = norm_chain_key(location_name).split()
        for n in (2, 1):
            key = " ".join(words[:n])
            if key in self.r6_chains:
                return self.r6_chains[key]
        return None

    def format_for(self, location_name):
        """R10: "large", "convenience", or None, matched against the
        location name (the format, e.g. "Superstore", rarely shows up in
        Type (as captured), only in the name itself: "Tesco Acton
        Superstore"). Each pattern is a list of words that must all appear
        somewhere in the normalised name; large formats checked first."""
        words = set(norm_chain_key(location_name).split())
        if any(all(w in words for w in pattern) for pattern in self.r10_large_formats):
            return "large"
        if any(all(w in words for w in pattern) for pattern in self.r10_convenience_formats):
            return "convenience"
        return None


def load_rules(path=DEFAULT_PATH):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    chains = {norm_chain_key(k): v for k, v in data.get("r6", {}).get("chains", {}).items()}
    return Rules(
        r1_category_defaults=data["r1_category_defaults"],
        r3_own_brand_names={norm_chain_key(n) for n in data["r3_own_brand_operators"]["names"]},
        r6_chains=chains,
        r7_risky_cost_types=set(data["r7"]["risky_cost_types"]),
        r7_risky_who_can_park=set(data["r7"]["risky_who_can_park"]),
        r9_explicit_no_parking_phrases=[p.lower() for p in data["r9"]["explicit_no_parking_phrases"]],
        r10_nearby_car_park_radius_m=data["r10"]["nearby_car_park_radius_m"],
        r10_large_formats=[[w.lower() for w in pattern] for pattern in data["r10"]["large_formats"]],
        r10_convenience_formats=[[w.lower() for w in pattern]
                                  for pattern in data["r10"]["convenience_formats"]],
        r10_small_venue_categories={c.lower() for c in data["r10"]["small_venue_categories"]},
    )
