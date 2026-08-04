"""Decides which specification groups earn a place on the one-pager (R2).

The three graded products do not share a spec vocabulary: a display has
`display`, a dev board has `mcu`, a sensor has `measurement`. Earlier versions
matched against a fixed whitelist per family, which silently dropped
`measurement` — the single most important group on a sensor datasheet.

The rule here is therefore ordering, not filtering: every group the product has
is rankable, the family only decides what floats to the top, and unknown group
keys land in the middle rather than disappearing. A product family we have
never seen still produces a sensible one-pager.
"""

from typing import Iterable

# What the customer needs to decide whether the product fits, per family.
# Anything not named here keeps its source order after the ranked groups.
FAMILY_PRIORITY = {
    "display": ["display", "connectivity", "power", "interface"],
    "development": ["mcu", "connectivity", "interface", "power"],
    "sensor": ["measurement", "interface", "power", "connectivity"],
    "generic": ["interface", "power", "connectivity"],
}

# A product belongs to the first family whose marker group it has.
FAMILY_MARKERS = [("display", "display"), ("sensor", "measurement"), ("development", "mcu")]

# Groups that are reference material rather than decision material. They stay in
# the full datasheet but never push a headline spec off the single page.
ONEPAGER_DEPRIORITISED = {"other", ""}

# A one-pager has to fit on one A4 page for every product (R4), so the spec
# block is capped. Groups are dropped from the bottom of the ranking, never
# from the middle, so what survives is always the highest-value set.
ONEPAGER_MAX_GROUPS = 4
ONEPAGER_MAX_FIELDS = 16


def detect_family(spec_groups: Iterable[dict]) -> str:
    keys = {group.get("key") for group in spec_groups}
    for family, marker in FAMILY_MARKERS:
        if marker in keys:
            return family
    return "generic"


def get_onepager_group_keys(spec_groups: Iterable[dict]) -> list[str]:
    """Rank the product's own group keys; never invent or drop one silently."""
    groups = [group for group in spec_groups if group.get("fields")]
    if not groups:
        return []

    priority = FAMILY_PRIORITY[detect_family(groups)]

    def rank(group: dict) -> tuple[int, int]:
        key = group.get("key") or ""
        if key in ONEPAGER_DEPRIORITISED:
            return (2, 0)
        if key in priority:
            return (0, priority.index(key))
        return (1, 0)

    ordered = sorted(groups, key=rank)

    selected: list[str] = []
    field_budget = ONEPAGER_MAX_FIELDS
    for group in ordered[:ONEPAGER_MAX_GROUPS]:
        count = len(group.get("fields", []))
        if selected and count > field_budget:
            break
        selected.append(group.get("key") or "")
        field_budget -= count
    return selected


def select_onepager_groups(spec_groups: list[dict]) -> list[dict]:
    """Groups for the one-pager, in ranked order rather than source order."""
    wanted = get_onepager_group_keys(spec_groups)
    by_key = {group.get("key") or "": group for group in spec_groups}
    return [by_key[key] for key in wanted if key in by_key]
