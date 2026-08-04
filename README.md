# Soldered Electronics — Product Datasheet Generator

A web tool that pulls live product data from `solde.red`, cleans it up, and renders a
print-ready A4 PDF datasheet. Two templates (one-pager and full), three languages
(EN/DE/HR), works for any SKU in the catalogue.

**Live: <https://solderedprojektdejak.onrender.com>** — no login, nothing to install.

It runs on Render's free tier, which sleeps after ~15 minutes idle. If you are the first
to open it in a while it takes 30–50 seconds to wake; after that a PDF renders in 3–9
seconds depending on how large the product photos are.

---

## Running it

**Docker** — WeasyPrint needs Pango and HarfBuzz at runtime, so this is the setup that
behaves the same everywhere:

```bash
docker build -t soldered-datasheet .
docker run --rm -p 5000:5000 soldered-datasheet   # http://127.0.0.1:5000
```

**Without Docker** — `pip install -r requirements.txt && python -m app.main`. On Windows
the UI works but PDFs will not: WeasyPrint cannot find `libgobject-2.0-0` without GTK. The
app detects this at import, keeps running, and offers the HTML preview instead of throwing
a 500.

**Regenerating the six deliverables and checking them:**

```bash
docker run --rm -w /app -e PYTHONPATH=/app \
  -v "$PWD/cache:/app/cache" -v "$PWD/deliverables:/app/deliverables" \
  soldered-datasheet python scripts/generate_deliverables.py

docker run --rm -w /app -e PYTHONPATH=/app -v "$PWD/cache:/app/cache" \
  soldered-datasheet python scripts/verify_sheets.py
```

`generate_deliverables.py` drives the app's own `/generate` endpoint, so the PDFs in
`deliverables/` are the same bytes a browser gets.

**Deploying** — `render.yaml` is a Render blueprint: connect the repo, pick "Blueprint",
done. It builds the Dockerfile, binds `$PORT` through gunicorn, health-checks `/healthz`.

---

## Why this stack

The task said how you decide to produce a PDF is itself part of the answer, so:

**WeasyPrint, not ReportLab or headless Chrome.** R4 wants a footer on every page, page
numbers, no table split across a break without its header, no stranded headings. With a
drawing library you implement all of that by hand. Headless Chrome renders well but drags
a ~400 MB browser into the image and has no running elements, so a repeating footer means
fighting CDP print options. WeasyPrint gives me `@page`, `counter(page)`,
`position: running()` and `display: table-header-group` directly — the whole
footer-and-pagination requirement is about fifteen lines of CSS. The price is that it is
not a browser and CSS grid is unreliable, so print layout is tables and flow. I hit that:
my first Resources section used grid and came out as one stacked column with big gaps.

**Flask + Jinja, no frontend framework.** The user is a colleague from the content team
picking a product and clicking a button; that is a form and a list. The real win is that
`/preview` and `/generate` render the *same* template, so I could iterate on layout in a
browser and the preview cannot drift from the download.

**Docker, which was not optional** — and where I lost the most time. Two failures stacked:
`docker build` could not pull the base image because my Docker config sets
`"credsStore": "desktop"` and `docker-credential-desktop.exe` was not on `PATH`; once that
was cleared, `apt-get` exited 100 because `python:3.12-slim` has moved to Debian trixie
where `libgdk-pixbuf2.0-0` is now `libgdk-pixbuf-2.0-0`. Fixing the second one, I also
dropped `build-essential` and the `-dev` packages from my first Dockerfile — WeasyPrint 60+
renders through Pango and dropped cairo in 53, so none were being used. Worth noting that
neither error message mentioned the actual subject, which was WeasyPrint's native
dependencies.

**Caching, because the task asks not to hammer the site.** `search_index.json` is fetched
once per day, so search is a local filter over ~270 products and costs no requests at all.
Product pages cache per SKU: cold 0.455 s and one request, warm 0.004 s and none. The
design point worth calling out is that one fetch of `solde.red/<SKU>` returns **all three
languages**, so B1 costs zero extra requests — fetching per language would have tripled
the load for nothing.

---

## Where the data comes from

Two sources, both plain `requests.get()`:

1. **`solde.red/search_index.json`** — the whole catalogue in one file, cached 24 h.
2. **`solde.red/<SKU>`** — the page carries `<script id="locales-data">` holding the full
   schema for all three languages. Direct `json.loads`, no CSS-selector fragility.

Four things need the HTML: box contents, resource links, images, last-updated. Those come
from stable `data-*` attributes and structural class names, not presentational ones.

### How complete the translations are

"Supports three languages" can mean several things, so precisely:

| Part of the sheet | DE / HR | Source |
|---|---|---|
| Name, descriptions, technical details | yes | Soldered's `locales-data` |
| Spec **group** names (Measurement → Mjerenje) | yes | Soldered's `locales-data` |
| Resource links and categories | yes | `data-loc-*` / `data-cat-label-*` |
| Section headings, footer, page counter | yes | `data/ui_strings.json`, written by me |
| Spec **field** labels (Supply Voltage) | **no** | Soldered publishes these in English only |
| Box contents, Typical applications | **no** | See [What is left out](#what-is-left-out) |

A Croatian sheet is genuinely Croatian in its prose, headings and navigation; the spec
table keeps English field labels because that is all the source has. The moment
`locales-data` carries translated field labels they will appear with no code change.

---

## Decisions

### R3 — missing data: hide the section

Products differ wildly. The NULA board has no software or compliance resources, the SHTC3
has no variants, only the Inkplate has a `display` group, and only two of the three have a
pinout.

**The rule: if there is no data, the section does not exist.** No empty tables, no `null`,
no "N/A" rows, no placeholder text for the content team to forget about.

This is a customer-facing document, not an internal form. A row reading "Touch support:
not applicable" spends a line of A4 telling the reader something they did not ask; a sheet
that simply does not mention touch says the same thing and reads like it was written for
that product rather than generated for any product. The cost is that the reader cannot
tell "we do not publish this" from "this product does not have it" — acceptable for a sales
document, and the full sheet prints the source URL and last-updated date so anything can
be traced back.

### R2 — what earns a place on the one-pager

My first version matched spec groups against a per-family whitelist. The SHTC3 proved that
wrong: the sensor keeps its readings in a `measurement` group that was in no whitelist, so
the most important block on a sensor datasheet was being dropped from its own one-pager. A
whitelist can only describe the families you have already seen.

`app/sections.py` **ranks rather than filters**. Every group the product has is rankable;
the family only decides what floats to the top:

| Family | Detected by | Leads with |
|---|---|---|
| Display | has a `display` group | display, connectivity, power, interface |
| Development board | has an `mcu` group | mcu, connectivity, interface, power |
| Sensor | has a `measurement` group | measurement, interface, power, connectivity |
| Anything else | fallback | interface, power, connectivity |

An unrecognised group key sorts into the middle instead of vanishing, so a family that does
not exist yet still produces a sensible sheet. Reference-only groups ("Other") sort last so
they cannot push a headline spec off the page, and the selection is capped by group and
field count because the page budget is fixed.

The full datasheet prints every group plus overview, technical details, the pinout,
variants and the complete resource list.

**The pinout is embedded, not linked.** R2 lists it as full-datasheet content and Soldered
publishes it as a plain PNG, and a URL is no use to someone holding a printout. The image
goes in and is dropped from Resources, where it would be a duplicate. Its height is capped
so the diagram never splits across a break — half a pinout is worse than none.

---

## What is wrong with the solde.red data

Everything here is a real case hit while building. The four that I think are worth someone
at Soldered actually looking at:

**1. A resource block that silently loses most of its content.** `.resource-card` is a
*category* container holding several `.resource-item` links. Reading one link per card —
the obvious first implementation — published 4 of Inkplate 6's 7 resources and lost the
NULA board's Pinout entirely. The card's own `data-count="2"` contradicts what a naive
parse produces, which is what made it findable.

**2. Specs that contradict their own descriptions.** The NULA DeepSleep description says
*"7µA deep sleep current"*; its `sleep_current_ua` field says `16`. Inkplate 6 does the
same internally: the overview says *"super-low-power (22uA)"* while both the spec field and
its own technical details say 25 µA. The tool prints the structured value and leaves the
prose alone, because it cannot know which is right.

**3. The naming migration is half-finished.** Structured fields are clean
(`qwiic_compatible`), but prose still carries retired terms — and in one place carries both
at once: Inkplate 6's technical details read *"qwiic/Qwiic compatibility"*, the old
easyC/Qwiic line with only the first half renamed. Worse, the SHTC3 pinout diagram has
"via easyC/Qwiic" **rendered into the PNG itself**. No text pipeline can fix that, and it
reaches customers until the image is regenerated.

**4. Two different pages sharing one label.** 333232 lists "Arduino: Get Started" twice
under software, pointing at `docs.soldered.com` and `inkplate.readthedocs.io`. Genuinely
different resources, so deduplicating loses one, but two identical link texts side by side
read like a bug on a printed sheet. The tool appends the host when a label repeats.

Beyond those, the structured data is written for machines rather than customers — the
literal case the tone-of-voice brief describes under *"a value that exists so software can
compare it is not automatically a value a person should read on a printed page"*:

| Problem | Example | What the tool does |
|---|---|---|
| Labels auto-title-cased from snake_case | `Mcu Part Number`, `Sd Card Slot`, `Sram (KB)`, `Wifi` | acronym map |
| Units in three different places | `unit` key / name suffix (`sleep_current_ua`) / free text (`-40 to 125 C`) | recovers and joins with a space |
| Values are enum codes | `wifi4`, `classic_and_ble`, `jst_2pin`, `3v3_or_5v` | value map |
| Part numbers written loosely | `ESP32 WROVER-E`, `ESP32-S3-WROOM-1(N8R8)` | corrected |
| Prose units missing a space | `22uA`, `1.26s`, `1200mAh` | spaced, `uA` → `µA` |
| `Qwiic` capitalised where the brief wants `qwiic` | `two Qwiic ports` | lowercased, but `SparkFun Qwiic` keeps its capital |
| SKU nested inside the box-contents name | `Inkplate 6 333232` | read from its own element |
| One spec group has an empty key | `""`, labelled "Other" | handled, sorts last |

Two I deliberately left alone: `Connectors: Qwiicx2` is a malformed value (`Qwiic x2` run
together) and rewriting it would mangle it further, and `easyC` inside the GitHub URL stays
because the repository really is called `...-easyC-Arduino-Library` — only the link text is
renamed.

---

## What I tested

`scripts/verify_sheets.py` renders through the app's own code path and asserts the R4
rules, so a regression fails a check instead of quietly shipping a four-page "one-pager":

```
[ok] 333232 onepager 1 page    [ok] 333232 full 3 pages
[ok] 333352 onepager 1 page    [ok] 333352 full 3 pages
[ok] 333032 onepager 1 page    [ok] 333032 full 3 pages
all checks passed
```

It checks the one-pager is exactly one page for every product, and that every page carries
the product footer and its page number.

| Case | Result |
|---|---|
| Nonexistent SKU `999999`, non-numeric `abc` | 200 with "Could not load SKU …: 404 Client Error" — no stack trace |
| Search with no matches | 200, "No products match that search." |
| `/generate` with no SKU | Redirects to the picker |
| Unknown template `poster` / language `fr` | Falls back to one-pager / EN, valid PDF |
| Variant SKU `333229` (Inkplate with enclosure) | Valid one-pager, 1 page |
| German one-pager, Croatian full sheet | Both valid, translated headings, labels and resources |
| Product with no pinout (`333232`) | Section skipped entirely, no empty heading (R3) |
| `SparkFun Qwiic` in prose | Left capitalised; only unqualified `Qwiic` is lowercased |
| `easyC` inside a GitHub URL | `href` untouched, link text renamed |
| WeasyPrint missing (Windows, no GTK) | App still starts; `/generate` explains why and links to the preview |
| Second fetch of the same SKU | Cold 0.455 s / 1 request, warm 0.004 s / 0 requests (`requests.get` counted) |

Checked by eye on the rendered PDFs: no table cut across a break, no heading stranded at
the bottom of a page, images scaled inside the text column, footer and page numbers
everywhere, nothing past the right margin.

Checked against the **deployed** instance, not just locally — `/healthz` returns
`{"status":"ok","weasyprint":true}`, and all six sheets return `application/pdf` in 3.3–9.3 s
at sizes matching the local build to within a few bytes of PDF metadata.

---

## How AI was used

Claude Code (Opus) wrote most of this, with me directing and reviewing. It was fast at the
mechanical parts — Jinja partials, the Dockerfile, the paged-media CSS — and least reliable
exactly where it sounded most confident. Every problem below was caught by running the
thing and reading the output, not by reading the code.

The worst was structural: it assumed `.resource-card` was one resource per card, producing
clean, plausible, working code that silently dropped 3 of Inkplate 6's 7 resources and the
NULA board's Pinout. Nothing errored. I only found it by dumping the parsed output next to
the page's own `data-count="2"` and noticing they disagreed. The same class of mistake
appeared when it "deduplicated" two identically-labelled Arduino links assuming they shared
a URL — they were different pages, and the dedupe would have deleted a real resource.

It also misdiagnosed confidently. When the footer printed only on the last page it
concluded WeasyPrint does not support running elements and proposed rewriting the
mechanism; a ten-line experiment showed they work fine and the real cause was document
order — a running element is only available from the point it appears, and the footer was
last in the body. Taking that diagnosis at face value would have meant rewriting working
code for nothing.

Three smaller ones: a regex meant to turn `125 C` into `125 °C` used `\s*` where it needed
`\s+` and so rewrote `I2C` into `I2°C`; a "defensive" fallback in the label formatter
returned the original string whenever it saw a bracket, which silently disabled the acronym
fix on every unit-bearing label — the safe-looking branch was the bug; and it wrote a commit
message asserting a wrong CSS path had been producing unstyled PDFs when the real failure
was a `FileNotFoundError`, which I checked in the container before it reached permanent
history.

The pattern is consistent: reliable on syntax, unreliable on assumptions about data it has
not looked at. The habit that caught all of it was cheap — render the artefact, read the
output, compare against the source page — and it is why `verify_sheets.py` exists instead
of a line in this README claiming the one-pager fits.

---

## What is left out

- **Cold starts.** Free tier sleeps after ~15 minutes. A paid instance or a keep-alive cron
  would fix it; pinging my own service to defeat the platform's cost control was not
  something I wanted to hand in.
- **Schematics.** Linked behind Hardware Details. Embedding them means following the link
  and parsing another page; I stopped at the product page.
- **Layout options (B2).** Not attempted. B1 came almost free with the data, B2 did not,
  and the core mattered more.
- **Typical applications is English-only and covers only the three graded SKUs.** Other
  products omit the section rather than print filler, which I think is the right failure.
  Translating three paragraphs is easy; having them checked by someone who writes
  Soldered's German is not, and shipping unchecked customer copy in a language I cannot
  verify seemed worse than shipping English.
- **The `data/` maps cover what these three products need.** A wider sweep would turn up
  more enum codes; unknown ones degrade gracefully rather than breaking, but they would not
  be perfect prose.
- **No unit tests** beyond `verify_sheets.py`. The normalizer's transformations are the
  obvious thing to test and there was not time.
- **My German section headings are not proofread.** The Croatian I stand behind. The German
  are standard datasheet terms (`Lieferumfang`, `Technische Daten`) but a native speaker
  should confirm the tone.
