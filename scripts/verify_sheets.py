"""Assert the hard print rules from R4 instead of checking them by eye.

Renders through the same code path the web app uses and verifies that the
one-pager really is one page for every product, and that every page carries the
product footer and a page number.

    docker run --rm -w /app -e PYTHONPATH=/app -v "$PWD/cache:/app/cache" \
        soldered-datasheet python scripts/verify_sheets.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weasyprint import CSS, HTML  # noqa: E402

from app.main import CSS_PATH, TEMPLATE_DIR, _build_context, app  # noqa: E402
from app.pdf import render_html  # noqa: E402

DEFAULT_SKUS = ["333232", "333352", "333032"]


def page_texts(document) -> list[str]:
    """Flatten the text on each page, margin boxes (the footer) included."""
    pages = []
    for page in document.pages:
        found: list[str] = []

        def walk(box):
            for child in getattr(box, "all_children", lambda: [])():
                if getattr(child, "text", None):
                    found.append(child.text)
                walk(child)

        walk(page._page_box)
        pages.append(" ".join(found))
    return pages


def check(sku: str, template: str) -> list[str]:
    with app.app_context():
        context = _build_context(sku, template, "en")
        html = render_html(f"{template}.html", context)

    document = HTML(string=html, base_url=str(TEMPLATE_DIR)).render(
        stylesheets=[CSS(filename=str(CSS_PATH))]
    )
    pages = page_texts(document)

    problems = []
    if template == "onepager" and len(pages) != 1:
        problems.append(f"one-pager must be exactly 1 page, got {len(pages)}")
    for number, text in enumerate(pages, start=1):
        if sku not in text:
            problems.append(f"page {number} is missing the product footer")
        if f"Page {number} of {len(pages)}" not in text:
            problems.append(f"page {number} is missing its page number")

    print(f'[{"FAIL" if problems else "ok":4s}] {sku} {template:9s} {len(pages)} page(s)')
    for problem in problems:
        print(f"         - {problem}")
    return problems


if __name__ == "__main__":
    failed = sum(
        bool(check(sku, template))
        for sku in (sys.argv[1:] or DEFAULT_SKUS)
        for template in ("onepager", "full")
    )
    print("\nall checks passed" if not failed else f"\n{failed} check(s) failed")
    sys.exit(1 if failed else 0)
