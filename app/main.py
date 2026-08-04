from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, redirect, render_template, request, send_file, url_for

from app.normalizer import Normalizer
from app.pdf import WEASYPRINT_AVAILABLE, WEASYPRINT_ERROR, render_pdf
from app.scraper import ProductPage, SearchIndex
from app.sections import select_onepager_groups

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR = ROOT / "app" / "templates"
STATIC_DIR = ROOT / "app" / "static"
CSS_PATH = STATIC_DIR / "brand.css"

app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(TEMPLATE_DIR))
search_index = SearchIndex(CACHE_DIR)
product_page = ProductPage(CACHE_DIR)
normalizer = Normalizer(DATA_DIR)

LANGUAGES = ["en", "de", "hr"]
TEMPLATES = ["onepager", "full"]
MAX_RESULTS = 40


def _clean_params():
    """Read sku/template/lang off the query string, falling back to defaults."""
    sku = request.args.get("sku", "").strip()
    template_name = request.args.get("template", "onepager")
    language = request.args.get("lang", "en")
    return (
        sku,
        template_name if template_name in TEMPLATES else "onepager",
        language if language in LANGUAGES else "en",
    )


def _build_context(sku: str, template_name: str, language: str) -> dict:
    """Fetch, normalize and assemble everything a datasheet template needs."""
    product = normalizer.normalize(product_page.fetch(sku))
    spec_groups = product["locales"][language].get("spec_groups", [])
    return {
        "product": product,
        "lang": language,
        "selected_lang": language,
        "selected_template": template_name,
        "onepager_groups": select_onepager_groups(spec_groups),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    sku, template_name, language = _clean_params()
    product = None
    onepager_groups = []
    product_error = None

    try:
        products = search_index.search(query)
    except Exception as exc:
        products = []
        product_error = f"Failed to load the product index: {exc}"

    if sku:
        try:
            context = _build_context(sku, template_name, language)
            product = context["product"]
            onepager_groups = context["onepager_groups"]
        except Exception as exc:
            product_error = f"Could not load SKU {sku}: {exc}"

    return render_template(
        "index.html",
        query=query,
        products=products[:MAX_RESULTS],
        result_count=len(products),
        max_results=MAX_RESULTS,
        product=product,
        product_error=product_error,
        selected_sku=sku,
        selected_template=template_name,
        selected_lang=language,
        template_choices=TEMPLATES,
        language_choices=LANGUAGES,
        onepager_groups=onepager_groups,
        weasyprint_available=WEASYPRINT_AVAILABLE,
    )


@app.route("/generate")
def generate_pdf():
    sku, template_name, language = _clean_params()
    if not sku:
        return redirect(url_for("index"))

    context = _build_context(sku, template_name, language)

    # Without the native libraries there is no PDF to hand back, so say why and
    # point at the HTML preview instead of failing with a 500.
    if not WEASYPRINT_AVAILABLE:
        return render_template(
            "pdf_error.html",
            message=str(WEASYPRINT_ERROR),
            sku=sku,
            template=template_name,
            lang=language,
        )

    pdf_stream = render_pdf(f"{template_name}.html", context, TEMPLATE_DIR, CSS_PATH)
    return send_file(
        pdf_stream,
        as_attachment=True,
        download_name=f"{sku}-{template_name}.pdf",
        mimetype="application/pdf",
    )


@app.route("/preview")
def preview():
    """The same template as the PDF, served as HTML for quick iteration."""
    sku, template_name, language = _clean_params()
    if not sku:
        return redirect(url_for("index"))
    return render_template(f"{template_name}.html", **_build_context(sku, template_name, language))


@app.route("/healthz")
def healthz():
    return {"status": "ok", "weasyprint": WEASYPRINT_AVAILABLE}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
