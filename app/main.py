import json
from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import Flask, redirect, render_template, request, send_file, url_for

from app.normalizer import Normalizer
from app.scraper import ProductPage, SearchIndex
from app.sections import get_onepager_group_keys

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR = ROOT / "app" / "templates"
STATIC_DIR = ROOT / "app" / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(TEMPLATE_DIR))
search_index = SearchIndex(CACHE_DIR)
normalizer = Normalizer(DATA_DIR)

LANGUAGES = ["en", "de", "hr"]
TEMPLATES = ["onepager", "full"]


@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    sku = request.args.get("sku", "").strip()
    template_name = request.args.get("template", "onepager")
    language = request.args.get("lang", "en")
    language = language if language in LANGUAGES else "en"
    product = None
    product_error = None

    try:
        products = search_index.search(query)
    except Exception as exc:
        products = []
        product_error = f"Failed to load product index: {exc}"

    if sku:
        try:
            raw = ProductPage(CACHE_DIR).fetch(sku)
            product = normalizer.normalize(raw)
        except Exception as exc:
            product_error = str(exc)

    onepager_groups = []
    if product:
        locale_data = product["locales"].get(language, {})
        onepager_groups = get_onepager_group_keys(locale_data.get("spec_groups", []))

    return render_template(
        "index.html",
        query=query,
        products=products,
        product=product,
        product_error=product_error,
        selected_sku=sku,
        selected_template=template_name,
        selected_lang=language,
        template_choices=TEMPLATES,
        language_choices=LANGUAGES,
        onepager_groups=onepager_groups,
    )


@app.route("/generate")
def generate_pdf():
    sku = request.args.get("sku", "").strip()
    template_name = request.args.get("template", "onepager")
    language = request.args.get("lang", "en")
    language = language if language in LANGUAGES else "en"
    if not sku:
        return redirect(url_for("index"))
    if template_name not in TEMPLATES:
        template_name = "onepager"

    raw = ProductPage(CACHE_DIR).fetch(sku)
    product = normalizer.normalize(raw)
    html_template = f"{template_name}.html"
    rendered = render_template(
        html_template,
        product=product,
        lang=language,
        languages=LANGUAGES,
        selected_lang=language,
        selected_template=template_name,
        onepager_group_keys=get_onepager_group_keys(product["locales"][language].get("spec_groups", [])),
        generated_at=datetime.utcnow().isoformat() + "Z",
    )

    from weasyprint import HTML, CSS
    css_path = ROOT / "static" / "brand.css"
    pdf_bytes = HTML(string=rendered, base_url=str(ROOT)).write_pdf(stylesheets=[CSS(filename=str(css_path))])

    filename = f"{sku}-{template_name}.pdf"
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
