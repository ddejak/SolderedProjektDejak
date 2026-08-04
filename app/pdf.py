from pathlib import Path
from io import BytesIO

from flask import render_template

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
    WEASYPRINT_ERROR = None
except Exception as exc:
    HTML = None
    CSS = None
    WEASYPRINT_AVAILABLE = False
    WEASYPRINT_ERROR = exc


def render_pdf(template_name: str, context: dict, template_dir: Path, css_path: Path) -> BytesIO:
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError(
            "WeasyPrint is unavailable. On Windows, install the native GTK/Pango dependencies or run the app in Docker/WSL. "
            f"Original import error: {WEASYPRINT_ERROR}"
        )
    rendered = render_template(template_name, **context)
    html = HTML(string=rendered, base_url=str(template_dir))
    pdf_bytes = html.write_pdf(stylesheets=[CSS(filename=str(css_path))])
    return BytesIO(pdf_bytes)
