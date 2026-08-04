"""Generate the deliverable PDFs through the app's own /generate route.

The sheets that ship are produced by the tool, not touched up by hand, so this
drives the real Flask endpoint rather than calling WeasyPrint directly.

    docker compose run --rm app python scripts/generate_deliverables.py

or, without compose:

    docker run --rm -w /app -e PYTHONPATH=/app \
        -v "$PWD/cache:/app/cache" -v "$PWD/deliverables:/app/deliverables" \
        soldered-datasheet python scripts/generate_deliverables.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "deliverables"
DEFAULT_SKUS = ["333232", "333352", "333032"]


def main(skus: list[str]) -> int:
    OUT_DIR.mkdir(exist_ok=True)
    failures = 0
    with app.test_client() as client:
        for sku in skus:
            for template in ("onepager", "full"):
                resp = client.get(f"/generate?sku={sku}&template={template}&lang=en")
                ok = resp.status_code == 200 and resp.data[:4] == b"%PDF"
                if ok:
                    target = OUT_DIR / f"{sku}-{template}.pdf"
                    target.write_bytes(resp.data)
                    print(f"[ok  ] {target.name}  {len(resp.data):,} bytes")
                else:
                    failures += 1
                    print(f"[FAIL] {sku}-{template}.pdf  status={resp.status_code}")
                    print(resp.data[:500].decode("utf-8", "replace"))
    return failures


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1:] or DEFAULT_SKUS) else 0)
