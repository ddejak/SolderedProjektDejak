from typing import Iterable

ONEPAGER_GROUP_PRIORITY = ["display", "mcu", "connectivity", "interface", "power", "other"]
ONEPAGER_PRESETS = {
    "display": ["display", "connectivity", "power"],
    "development": ["mcu", "connectivity", "interface", "power"],
    "breakout": ["connectivity", "interface", "power"],
}


def get_onepager_group_keys(spec_groups: Iterable[dict]) -> list[str]:
    keys = [group.get("key") for group in spec_groups if group.get("key")]
    if "display" in keys:
        return [key for key in ONEPAGER_PRESETS["display"] if key in keys]
    if "mcu" in keys:
        return [key for key in ONEPAGER_PRESETS["development"] if key in keys]
    return [key for key in ONEPAGER_PRESETS["breakout"] if key in keys]


def select_onepager_groups(spec_groups: list[dict]) -> list[dict]:
    group_keys = set(get_onepager_group_keys(spec_groups))
    return [group for group in spec_groups if group.get("key") in group_keys]
