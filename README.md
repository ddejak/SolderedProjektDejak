# Soldered Electronics — Product Datasheet Generator

A Flask web tool that fetches live product data from `solde.red`, normalizes it, and renders print-ready PDF datasheets using WeasyPrint.

## Live deployment
Pending deployment. This repo is prepared for Docker-based hosting on Render.com or Railway.

## Run locally
1. Create a Python environment.
2. Install dependencies:
   ```bash
   pip install flask requests beautifulsoup4 weasyprint
   ```
3. Start the app:
   ```bash
   python -m app.main
   ```
4. Open `http://127.0.0.1:5000`

## What it does
- Loads `https://solde.red/search_index.json` and caches it locally.
- Fetches `https://solde.red/<SKU>` and extracts the `locales-data` JSON payload.
- Normalizes field labels, machine-readable values, units, and retired names.
- Supports one-pager and full datasheet templates.
- Generates A4 PDFs with page footers and brand colours.

## Design decisions
- Missing sections are hidden rather than shown empty. This keeps PDFs clean and avoids placeholders.
- One-pager content is driven by the product's spec groups and chosen template, not hard-coded fields.
- Machine-readable enum values and old naming are converted before rendering.

## Notes on solde.red data
- Some labels are generated from snake_case and need acronym fixes, e.g. `Mcu Part Number` → `MCU Part Number`.
- The values may contain coded enums like `wifi4` or `classic_and_ble`, which are mapped to readable strings.
- Textual descriptions can include retired terms such as `easyC` and `Dasduino`.

## AI usage
- Used AI to draft the `typical_applications` copy and shape the README.
- Verified all generated text against product details and corrected errors manually.

## Outstanding work
- Live deployment URL not yet available.
- One-pager and full datasheet generation logic may need further polish for every product family.
