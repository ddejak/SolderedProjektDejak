import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SEARCH_INDEX_URL = "https://solde.red/search_index.json"
SKU_URL_TEMPLATE = "https://solde.red/{sku}"
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
            text = " ".join(card.stripped_strings)
            qty = 1
            qty_match = re.search(r"(\d+)\s*[x×]", text)
            if qty_match:
                qty = int(qty_match.group(1))
                text = text.replace(qty_match.group(0), "", 1).strip()
            name = text
            boxes.append({"qty": qty, "name": name})
        return boxes

    def _parse_resources(self, soup: BeautifulSoup) -> dict:
        categories = {"technical": [], "documentation": [], "software": [], "compliance": []}
        for card in soup.select(".resource-card"):
            category = card.get("data-cat", "technical").strip().lower()
            category = category if category in categories else "technical"
            href = None
            label = None
            badge = None
            link = card.find("a", href=True)
            if link:
                href = link.get("href")
                label = link.get_text(strip=True)
            if not label:
                label = card.get("data-loc-en") or card.get("data-loc-de") or card.get("data-loc-hr") or card.get_text(strip=True)
            badge_node = card.select_one(".badge")
            if badge_node:
                badge = badge_node.get_text(strip=True)
            elif card.get("data-badge"):
                badge = card["data-badge"].strip()
            categories[category].append({"label": label, "href": href, "badge": badge})
        return categories

    def _parse_last_updated(self, soup: BeautifulSoup) -> str:
        node = soup.select_one(".last-updated")
        if node and node.get("data-last-updated"):
            return node.get("data-last-updated")
        return datetime.utcnow().isoformat() + "Z"
