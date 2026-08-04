import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

SEARCH_INDEX_URL = "https://solde.red/search_index.json"
SKU_URL_TEMPLATE = "https://solde.red/{sku}"
LOCALES = ("en", "de", "hr")
DEFAULT_TTL_SECONDS = 60 * 60 * 24
USER_AGENT = "SolderedDatasheetBot/1.0 (+https://solde.red)"


class SearchIndex:
    def __init__(self, cache_dir: Path, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.cache_dir = cache_dir
        self.index_path = cache_dir / "search_index.json"
        self.ttl_seconds = ttl_seconds
        self.index = None

    def _is_fresh(self):
        return self.index_path.exists() and (datetime.utcnow() - datetime.utcfromtimestamp(self.index_path.stat().st_mtime)).total_seconds() < self.ttl_seconds

    def load(self):
        if self.index is not None:
            return self.index
        if self._is_fresh():
            with open(self.index_path, "r", encoding="utf-8") as handle:
                self.index = json.load(handle)
        else:
            response = requests.get(SEARCH_INDEX_URL, headers={"User-Agent": USER_AGENT}, timeout=15)
            response.raise_for_status()
            self.index = response.json()
            self.index_path.write_text(json.dumps(self.index, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.index

    def all_products(self):
        items = self.load().get("items", []) if isinstance(self.load(), dict) else self.load()
        return sorted(
            [{"sku": item.get("sku"), "name": item.get("name") or item.get("names", {}).get("en", "")} for item in items],
            key=lambda item: item["name"].lower(),
        )

    def search(self, query: str):
        items = self.all_products()
        if not query:
            return items
        needle = query.lower()
        return [item for item in items if needle in item["sku"].lower() or needle in item["name"].lower()]


class ProductPage:
    def __init__(self, cache_dir: Path, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds

    def _cache_path(self, sku: str) -> Path:
        return self.cache_dir / f"{sku}.json"

    def _is_fresh(self, cache_path: Path):
        return cache_path.exists() and (datetime.utcnow() - datetime.utcfromtimestamp(cache_path.stat().st_mtime)).total_seconds() < self.ttl_seconds

    def fetch(self, sku: str) -> dict:
        cache_path = self._cache_path(sku)
        if self._is_fresh(cache_path):
            with open(cache_path, "r", encoding="utf-8") as handle:
                return json.load(handle)

        url = SKU_URL_TEMPLATE.format(sku=sku)
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        response.raise_for_status()
        raw_text = response.text
        payload = self._parse_page(raw_text, sku)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _parse_page(self, html: str, sku: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        locale_script = soup.find("script", id="locales-data", type="application/json")
        if not locale_script or not locale_script.string:
            raise ValueError("Unable to locate locales-data JSON on product page.")
        locales = json.loads(locale_script.string)
        variants = self._parse_variants(soup)
        images = self._parse_images(soup, html)
        box_contents = self._parse_box_contents(soup)
        resources = self._parse_resources(soup)
        last_updated = self._parse_last_updated(soup)
        return {
            "sku": sku,
            "locales": locales,
            "variants": variants,
            "images": images,
            "box_contents": box_contents,
            "resources": resources,
            "last_updated": last_updated,
        }

    def _parse_variants(self, soup: BeautifulSoup) -> list:
        script = soup.find("script", id="variants-data", type=True)
        if not script or not script.string:
            return []
        try:
            return json.loads(script.string)
        except Exception:
            return []

    def _parse_images(self, soup: BeautifulSoup, html: str) -> list:
        images = []
        for thumb in soup.select(".hero-img-thumbs img"):
            src = thumb.get("src") or thumb.get("data-src")
            if src:
                images.append(src)
        if images:
            return images
        match = re.search(r"const\s+images\s*=\s*(\[.*?\]);", html, re.S)
        if match:
            try:
                candidate = json.loads(match.group(1))
                for entry in candidate:
                    if isinstance(entry, str):
                        images.append(entry)
                    elif isinstance(entry, dict) and entry.get("src"):
                        images.append(entry["src"])
            except Exception:
                pass
        return images

    def _parse_box_contents(self, soup: BeautifulSoup) -> list:
        boxes = []
        for card in soup.select(".packing-card"):
            qty = 1
            qty_node = card.select_one(".packing-qty")
            if qty_node:
                qty_match = re.search(r"(\d+)", qty_node.get_text())
                if qty_match:
                    qty = int(qty_match.group(1))

            name_node = card.select_one(".packing-name")
            if not name_node:
                continue
            # The SKU is nested inside .packing-name; pull it out before reading
            # the name, otherwise it ends up glued on as "Inkplate 6 333232".
            sku_node = name_node.select_one(".packing-sku")
            sku = sku_node.get_text(strip=True) if sku_node else None
            if sku_node:
                sku_node.extract()

            name = " ".join(name_node.stripped_strings)
            desc_node = card.select_one(".packing-desc")
            description = " ".join(desc_node.stripped_strings) if desc_node else None

            boxes.append({"qty": qty, "name": name, "sku": sku, "description": description})
        return boxes

    def _parse_resources(self, soup: BeautifulSoup) -> list:
        # A .resource-card is a category container holding several .resource-item
        # links, not a single resource. Iterating the card only would silently
        # drop every resource after the first.
        categories: dict[str, dict] = {}
        for card in soup.select(".resource-card"):
            category = (card.get("data-cat") or "other").strip().lower()
            title = card.select_one(".resource-card-title")
            if category not in categories:
                fallback = title.get_text(strip=True) if title else category.capitalize()
                categories[category] = {
                    "key": category,
                    "labels": {
                        locale: ((title.get(f"data-cat-label-{locale}") if title else None) or fallback).strip()
                        for locale in LOCALES
                    },
                    "items": [],
                }
            for item in card.select(".resource-item"):
                label_node = item.select_one(".resource-item-label")
                if label_node is None:
                    continue
                fallback = label_node.get_text(strip=True)
                labels = {
                    locale: (label_node.get(f"data-loc-{locale}") or fallback).strip()
                    for locale in LOCALES
                }
                badge_node = item.select_one(".resource-item-badge")
                categories[category]["items"].append(
                    {
                        "labels": labels,
                        "href": item.get("href"),
                        "badge": badge_node.get_text(strip=True) if badge_node else None,
                    }
                )

        result = []
        for category in categories.values():
            items = self._dedupe_by_href(category["items"])
            self._disambiguate_labels(items)
            category["items"] = items
            if items:
                result.append(category)
        return result

    def _dedupe_by_href(self, items: list) -> list:
        seen = set()
        unique = []
        for item in items:
            key = item["href"] or item["labels"]["en"]
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _disambiguate_labels(self, items: list) -> None:
        """Append the host when one label covers two different resources.

        333232 lists "Arduino: Get Started" twice under software, once for
        docs.soldered.com and once for inkplate.readthedocs.io. They are
        genuinely different pages, so dropping one loses a resource, but two
        identical link texts side by side read like a bug on a printed sheet.
        """
        counts = Counter(item["labels"]["en"] for item in items)
        for item in items:
            if counts[item["labels"]["en"]] < 2 or not item["href"]:
                continue
            host = urlparse(item["href"]).netloc.removeprefix("www.")
            if not host:
                continue
            for locale in LOCALES:
                item["labels"][locale] = f'{item["labels"][locale]} ({host})'

    def _parse_last_updated(self, soup: BeautifulSoup) -> str:
        node = soup.select_one(".last-updated")
        if node and node.get("data-last-updated"):
            return node.get("data-last-updated")
        return datetime.utcnow().isoformat() + "Z"
