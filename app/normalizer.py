"""Turns the raw solde.red payload into something printable (R5).

The site stores specs for machines, not for customers: labels are auto
title-cased from snake_case names, values are enum codes, and units live in
three different places depending on the field. The Tone of Voice brief is
explicit that such data "needs converting into real words, correct units, and
the naming above, before it goes into a document with our logo on it".

Every transformation here is driven by a JSON map in data/ rather than
hard-coded, so a new abbreviation or enum is a data change, not a code change.
"""

import json
import re
from pathlib import Path
from typing import Any

# Units the brief says take no space: "25°C", "100%". Everything else is
# "3.3 V", "100 kΩ", "5 mm".
UNIT_NO_SPACE = {"%", "°C", "°F", "%RH"}

# Some fields carry their unit as a name suffix and leave the `unit` key empty
# (sleep_current_ua, supply_voltage_min_v). The auto title-caser then renders it
# as a word: "Sleep Current Ua". Recover the unit so the value reads "25 µA".
UNIT_BY_NAME_SUFFIX = {
    "_ua": "µA",
    "_ma": "mA",
    "_mhz": "MHz",
    "_khz": "kHz",
    "_kb": "KB",
    "_mb": "MB",
    "_gb": "GB",
    "_mm": "mm",
    "_seconds": "s",
    "_inch": "inch",
    "_v": "V",
}

# Prose carries units the brief would not accept: "22uA", "1.26s", "1200mAh".
# Only unambiguous unit tokens are listed. Bare "A", "V" and "W" are left alone
# because they turn up inside part numbers (PCF85063A), and a bare "s" is only
# spaced after a decimal so "the 1990s" survives.
PROSE_UNIT_TOKENS = ["mAh", "uA", "µA", "mA", "ms", "mm", "cm", "kHz", "MHz", "GHz", "KB", "MB", "GB"]
PROSE_UNIT_RE = re.compile(r"(?<=\d)(" + "|".join(PROSE_UNIT_TOKENS) + r")\b")
PROSE_SECONDS_RE = re.compile(r"\b(\d+\.\d+)s\b")

# Fields that only make sense read as a pair. Printing "Display Resolution W"
# and "Display Resolution H" on separate rows is how a database thinks, not how
# a datasheet reads.
PAIRED_FIELDS = [
    {
        "names": ("display_resolution_w", "display_resolution_h"),
        "label": "Display Resolution",
        "template": "{0} × {1} px",
    },
    {
        "names": ("supply_voltage_min_v", "supply_voltage_max_v"),
        "label": "Supply Voltage",
        "template": "{0}–{1} V",
    },
]


class Normalizer:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.abbrev_map = self._load_json("abbrev_fix.json")
        self.value_map = self._load_json("value_fix.json")
        self.naming_map = self._load_json("naming_map.json")
        self.typical_applications = self._load_json("typical_applications.json")
        self.naming_patterns = self._compile_naming_patterns()

    def _load_json(self, file_name: str) -> dict:
        path = self.data_dir / file_name
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _compile_naming_patterns(self) -> list[tuple[re.Pattern, str]]:
        patterns = []
        # Longest first, so "Dasduino NULA" wins over "Dasduino".
        for source in sorted(self.naming_map, key=len, reverse=True):
            pattern = re.compile(r"\b" + re.escape(source) + r"\b", flags=re.IGNORECASE)
            patterns.append((pattern, self.naming_map[source]))
        return patterns

    def normalize(self, raw: dict) -> dict:
        sku = raw.get("sku")
        return {
            "sku": sku,
            "locales": {
                locale: self._normalize_locale(data)
                for locale, data in raw.get("locales", {}).items()
            },
            "variants": raw.get("variants", []),
            "images": raw.get("images", []),
            "box_contents": self._normalize_box(raw.get("box_contents", [])),
            "resources": raw.get("resources", []),
            "last_updated": raw.get("last_updated"),
            "typical_applications": self.typical_applications,
        }

    def _normalize_locale(self, locale_data: dict) -> dict:
        return {
            "name": locale_data.get("name"),
            "short_description_html": self._normalize_html_text(locale_data.get("short_description", "")),
            "long_description_html": self._normalize_html_text(locale_data.get("long_description", "")),
            "technical_details_html": self._normalize_html_text(locale_data.get("technical_details", "")),
            "spec_groups": self._normalize_spec_groups(locale_data.get("spec_groups", [])),
        }

    # ------------------------------------------------------------------ specs

    def _normalize_spec_groups(self, groups: list[dict]) -> list[dict]:
        normalized = []
        for group in groups:
            fields = [self._normalize_field(f) for f in group.get("fields", []) if f]
            fields = [f for f in fields if f.get("display_value")]
            fields = self._merge_paired_fields(fields)
            # R3: a group with nothing left in it is dropped rather than printed
            # as a heading over an empty table.
            if not fields:
                continue
            label = group.get("label") or self._humanize_key(group.get("key", ""))
            normalized.append(
                {"key": group.get("key") or "", "label": self._normalize_label(label), "fields": fields}
            )
        return normalized

    def _normalize_field(self, field: dict) -> dict:
        name = field.get("name") or ""
        unit = (field.get("unit") or "").strip()
        suffix_unit = "" if unit else self._unit_from_name(name)
        unit = unit or suffix_unit

        label = field.get("label") or self._humanize_key(name)
        label = self._normalize_label(label)
        label = self._strip_unit_from_label(label, unit, suffix_unit)

        value = field.get("display_value")
        if value in (None, ""):
            value = field.get("value")
        display_value = self._normalize_value(value)
        if unit and display_value:
            display_value = self._join_unit(display_value, unit)

        return {"name": name, "label": label, "display_value": display_value}

    def _unit_from_name(self, name: str) -> str:
        # Longest suffix wins, so sleep_current_ua does not match "_a".
        for suffix in sorted(UNIT_BY_NAME_SUFFIX, key=len, reverse=True):
            if name.endswith(suffix):
                return UNIT_BY_NAME_SUFFIX[suffix]
        return ""

    def _merge_paired_fields(self, fields: list[dict]) -> list[dict]:
        by_name = {f["name"]: f for f in fields}
        for pair in PAIRED_FIELDS:
            first, second = pair["names"]
            if first not in by_name or second not in by_name:
                continue
            values = [self._strip_units(by_name[n]["display_value"]) for n in pair["names"]]
            merged = {
                "name": first,
                "label": pair["label"],
                "display_value": pair["template"].format(*values),
            }
            fields = [f for f in fields if f["name"] != second]
            fields = [merged if f["name"] == first else f for f in fields]
        return fields

    def _strip_units(self, value: str) -> str:
        """Drop a trailing unit so a merged pair does not read '3.3 V–5 V'."""
        return re.split(r"\s+(?=[A-Za-zµ°%])", value.strip(), maxsplit=1)[0]

    # ----------------------------------------------------------------- labels

    def _normalize_label(self, label: str) -> str:
        if not label:
            return label
        # Split but keep the separators, so "Mcu Clock (MHz)" survives the round
        # trip. The previous version bailed out whenever it saw a bracket, which
        # silently disabled the acronym fix on every unit-bearing label.
        parts = re.split(r"([\s_()\-/]+)", label)
        fixed = [self.abbrev_map.get(part.lower(), part) if part.strip() else part for part in parts]
        return "".join(fixed)

    def _strip_unit_from_label(self, label: str, unit: str, suffix_unit: str = "") -> str:
        """Remove "(MHz)" once the value already reads "240 MHz"."""
        if not unit:
            return label
        trimmed = re.sub(r"\s*\(\s*" + re.escape(unit) + r"\s*\)\s*$", "", label, flags=re.IGNORECASE)
        if trimmed != label:
            return trimmed.strip()
        if not suffix_unit:
            return label
        # A unit recovered from the name suffix was title-cased into a trailing
        # word that no longer matches the real symbol: sleep_current_ua yields
        # the unit "µA" but the label reads "Sleep Current Ua". Match on the
        # ASCII spelling from the name, not on the symbol.
        ascii_unit = suffix_unit.replace("µ", "u")
        return re.sub(r"\s+" + re.escape(ascii_unit) + r"$", "", label, flags=re.IGNORECASE).strip()

    # ----------------------------------------------------------------- values

    def _normalize_value(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""

        for candidate in (text, text.lower()):
            if candidate in self.value_map:
                return self.value_map[candidate]

        text = self._fix_free_text_units(text)
        # Underscores are enum syntax; hyphens are part of real part numbers
        # ("ESP32-S3"), so only the former may be blown away.
        if "_" in text:
            text = text.replace("_", " ")
        text = self._normalize_html_text(text)
        return self._sentence_case(text)

    def _fix_free_text_units(self, text: str) -> str:
        text = text.replace("+/-", "±")
        # "-40 to 125 C" is Celsius written without its degree sign. The space is
        # required: without it the C in "I2C" gets promoted to "I2°C".
        text = re.sub(r"(?<=\d)\s+C\b", "°C", text)
        # The brief allows a decimal point only, in every language we publish in.
        text = re.sub(r"(?<=\d),(?=\d)", ".", text)
        return text

    def _sentence_case(self, text: str) -> str:
        # Only touch all-lowercase single words ("grayscale", "none"). Anything
        # with existing capitals is a part number or proper noun; leave it be.
        if text.islower() and " " not in text:
            return text.capitalize()
        return text

    def _join_unit(self, value: str, unit: str) -> str:
        if unit in UNIT_NO_SPACE:
            return f"{value}{unit}"
        return f"{value} {unit}"

    # ------------------------------------------------------------------ other

    def _normalize_box(self, items: list[dict]) -> list[dict]:
        normalized = []
        for item in items:
            normalized.append(
                {
                    "qty": item.get("qty", 1),
                    "name": self._normalize_html_text(item.get("name") or ""),
                    "sku": item.get("sku"),
                    "description": self._normalize_html_text(item.get("description") or ""),
                }
            )
        return normalized

    def _humanize_key(self, key: str) -> str:
        if not key:
            return ""
        return " ".join(part.capitalize() for part in re.split(r"[_\-]+", key))

    def _normalize_html_text(self, html: str) -> str:
        """Apply the retired-naming map to prose only, never to markup.

        The repository behind "Arduino Library" really is called
        Soldered-...-easyC-Arduino-Library. Rewriting easyC to qwiic inside the
        href would produce a dead link, so tags are held out of the substitution
        and only the text between them is rewritten.
        """
        if not html:
            return ""
        parts = re.split(r"(<[^>]+>)", html)
        for index, part in enumerate(parts):
            if part.startswith("<"):
                continue
            for pattern, replacement in self.naming_patterns:
                part = pattern.sub(replacement, part)
            parts[index] = self._space_prose_units(part)
        return "".join(parts)

    def _space_prose_units(self, text: str) -> str:
        """"22uA" -> "22 µA". The brief wants a space between number and unit."""
        text = PROSE_UNIT_RE.sub(lambda m: " " + m.group(1).replace("uA", "µA"), text)
        return PROSE_SECONDS_RE.sub(r"\1 s", text)
