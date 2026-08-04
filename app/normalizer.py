import json
import re
from pathlib import Path
from typing import Any


class Normalizer:
    UNIT_EXCEPTIONS = {"%", "°C", "°F"}

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
        for source, replacement in self.naming_map.items():
            pattern = re.compile(r"\b" + re.escape(source) + r"\b", flags=re.IGNORECASE)
            patterns.append((pattern, replacement))
        return patterns

    def normalize(self, raw: dict) -> dict:
        return {
            "sku": raw.get("sku"),
            "locales": {locale: self._normalize_locale(locale_data) for locale, locale_data in raw.get("locales", {}).items()},
            "variants": raw.get("variants", []),
            "images": raw.get("images", []),
            "box_contents": raw.get("box_contents", []),
            "resources": raw.get("resources", {}),
            "last_updated": raw.get("last_updated"),
            "typical_applications": self.typical_applications,
        }

    def _normalize_locale(self, locale_data: dict) -> dict:
        normalized = {
            "name": locale_data.get("name"),
            "short_description_html": self._normalize_html_text(locale_data.get("short_description", "")),
            "long_description_html": self._normalize_html_text(locale_data.get("long_description", "")),
            "technical_details_html": self._normalize_html_text(locale_data.get("technical_details", "")),
            "spec_groups": self._normalize_spec_groups(locale_data.get("spec_groups", [])),
        }
        return normalized

    def _normalize_spec_groups(self, groups: list[dict]) -> list[dict]:
        normalized_groups = []
        for group in groups:
            fields = [self._normalize_field(field) for field in group.get("fields", []) if field]
            fields = [field for field in fields if field.get("display_value")]
            if not fields:
                continue
            label = group.get("label") or self._humanize_key(group.get("key", ""))
            normalized_groups.append({"key": group.get("key"), "label": self._normalize_label(label), "fields": fields})
        return normalized_groups

    def _normalize_field(self, field: dict) -> dict:
        name = field.get("name")
        label = self._normalize_label(field.get("label") or self._humanize_key(name or ""))
        display_value = field.get("display_value") or field.get("value") or ""
        display_value = self._normalize_value(display_value)
        unit = field.get("unit") or ""
        if unit:
            display_value = self._join_unit(display_value, unit)
        return {"name": name, "label": label, "display_value": display_value}

    def _normalize_label(self, label: str) -> str:
        if not label:
            return label
        parts = re.split(r"[\s_()\-]+", label)
        normalized_parts = [self.abbrev_map.get(part.lower(), part) for part in parts]
        return self._rejoin_label(normalized_parts, label)

    def _rejoin_label(self, parts: list[str], original: str) -> str:
        if "_" in original:
            return "_".join(parts)
        if "(" in original or ")" in original:
            return original
        return " ".join(parts)

    def _normalize_value(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if text in self.value_map:
            return self.value_map[text]
        lower = text.lower()
        if lower in self.value_map:
            return self.value_map[lower]
        if text.replace("_", " ").replace("-", " ") != text:
            return text.replace("_", " ").replace("-", " ")
        return text

    def _join_unit(self, value: str, unit: str) -> str:
        unit = unit.strip()
        if not value:
            return unit
        if unit in self.UNIT_EXCEPTIONS:
            return f"{value}{unit}"
        return f"{value} {unit}"

    def _humanize_key(self, key: str) -> str:
        if not key:
            return ""
        return " ".join([part.capitalize() for part in re.split(r"[_\-]+", key)])

    def _normalize_html_text(self, html: str) -> str:
        normalized = html
        for pattern, replacement in self.naming_patterns:
            normalized = pattern.sub(replacement, normalized)
        return normalized
