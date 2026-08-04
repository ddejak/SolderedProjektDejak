"""WeasyPrint wrapper.

The import is attempted once at module load rather than inside a request, so a
machine without the native Pango/HarfBuzz libraries still starts the app and can
report why PDF output is unavailable instead of raising a 500 per request.
"""

from io import BytesIO
from pathlib import Path

from flask import render_template

try:
    from weasyprint import CSS, HTML

    WEASYPRINT_AVAILABLE = True
    WEASYPRINT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on the host system
    HTML = None
    CSS = None
    WEASYPRINT_AVAILABLE = False
    WEASYPRINT_ERROR = exc


def render_html(template_name: str, context: dict) -> str:
    """The exact markup that goes into the PDF. Needs a Flask app context."""
    return render_template(template_name, **context)


def render_pdf(template_name: str, context: dict, template_dir: Path, css_path: Path) -> BytesIO:
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError(
            "WeasyPrint is unavailable. On Windows the native GTK/Pango libraries are "
            "missing; run the app in Docker or WSL. "
            f"Original import error: {WEASYPRINT_ERROR}"
        )
    # base_url lets relative asset paths in the templates resolve.
    document = HTML(string=render_html(template_name, context), base_url=str(template_dir))
    return BytesIO(document.write_pdf(stylesheets=[CSS(filename=str(css_path))]))
