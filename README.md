# Soldered Electronics — Product Datasheet Generator

A web tool that pulls live product data from `solde.red`, cleans it up, and renders a
print-ready A4 PDF datasheet. Two templates (one-pager and full), three languages
(EN/DE/HR), works for any SKU in the catalogue.

**Live: <https://solderedprojektdejak.onrender.com>**

No login, nothing to install. Pick a product, choose a template and a language, download
the PDF.

One thing to expect: it runs on Render's free tier, which sleeps the service after about
15 minutes of no traffic. If you are the first to open it in a while, the page takes
30–50 seconds to wake up. After that it is immediate — a PDF renders in about 4 seconds,
6 for the NULA board because its photos are larger. That is a hosting-tier tradeoff, not
the tool being slow, and I have said more about why I accepted it under
[Why this stack](#why-this-stack).

---

## Running it

### Docker (recommended)

WeasyPrint needs Pango and HarfBuzz at runtime. The image installs them, so this is the
only setup that works the same everywhere:

```bash
docker build -t soldered-datasheet .
docker run --rm -p 5000:5000 soldered-datasheet
```

Open <http://127.0.0.1:5000>.

### Locally, without Docker

```bash
pip install -r requirements.txt
python -m app.main
```

On Windows this starts and serves the UI, but PDF generation will not work: WeasyPrint
cannot find `libgobject-2.0-0` without a GTK install. The app detects this at import,
keeps running, and offers the HTML preview instead of failing with a 500. Use Docker or
WSL if you need the PDFs.

### Regenerating the deliverables

```bash
docker run --rm -w /app -e PYTHONPATH=/app \
  -v "$PWD/cache:/app/cache" -v "$PWD/deliverables:/app/deliverables" \
  soldered-datasheet python scripts/generate_deliverables.py

docker run --rm -w /app -e PYTHONPATH=/app -v "$PWD/cache:/app/cache" \
  soldered-datasheet python scripts/verify_sheets.py
```

`generate_deliverables.py` drives the app's own `/generate` endpoint, so the six PDFs in
`deliverables/` are the same bytes a user gets from the browser. `verify_sheets.py`
asserts the R4 rules automatically — see [What I tested](#what-i-tested).

### Deploying

`render.yaml` is a Render blueprint. Connect the repo at
<https://github.com/ddejak/SolderedProjektDejak>, pick "Blueprint", deploy. It builds the
Dockerfile, binds `$PORT` through gunicorn, and health-checks `/healthz`. No console
setup, no environment variables to fill in.

The disk is ephemeral on the free tier, so the cache starts empty after every restart and
the first request for a product refetches it from solde.red. That costs about half a
second once per product, and it is why `/healthz` reports whether WeasyPrint loaded — if
the image is ever built without the native libraries, that endpoint says so instead of
the first PDF download failing in front of a customer.

---

## Why this stack

The task left the stack open, and said how you decide to produce a PDF is itself part of
the answer. So here is the reasoning, including the parts that cost me time.

### PDF: WeasyPrint, not a headless browser or a PDF library

The three real options were a drawing library (ReportLab/fpdf2), headless Chrome
(Playwright/Puppeteer), or an HTML-to-PDF engine that implements CSS Paged Media.

I ruled out drawing libraries first. R4 asks for a footer on every page, page numbers, no
table split across a break that loses its header, and no heading stranded at the bottom of
a page. With ReportLab you implement all of that yourself — you are measuring text and
deciding where pages end. That is a lot of fiddly code for a problem the print world
solved decades ago, and it would have eaten the whole time budget.

Headless Chrome renders beautifully and I know it well, but it drags a ~400 MB browser
into the image and its paged-media support is the weakest part of it: no running elements,
so a repeating footer means injecting the header/footer HTML through the CDP print options
and hoping the margins line up.

WeasyPrint gets `@page`, `@bottom-left`, `counter(page)`, `position: running()` and
`display: table-header-group` for free, which is precisely the R4 list. The whole footer
and pagination requirement is about fifteen lines of CSS, and `<thead>` repeats across a
break with no code at all. The cost is that it is not a browser — CSS grid is unreliable
and flexbox is partial — so the print layout is tables and normal flow. I hit that: my
first Resources section used grid and rendered as one stacked column with big gaps. Tables
fixed it, and honestly a spec sheet wants tables anyway.

### Flask + Jinja, no frontend framework

The user is a colleague from the content team who picks a product and clicks a button.
That is a form and a list. React would add a build step and a second language for zero
benefit to that person.

Jinja earns its place for a different reason: the PDF and the browser preview render from
the *same* template. `/preview` serves the exact markup that goes into the PDF, so I could
iterate on layout in a browser without waiting on a PDF round trip, and there is no risk
of the preview and the download drifting apart.

### Docker, and why it was not optional

This is where I lost the most time, so it is worth being specific.

WeasyPrint links Pango and HarfBuzz at runtime. On Windows those are not there, and
installing GTK by hand is exactly the "clone it and install dependencies" ritual the task
says evaluators will not do. Containerising was the only way to make my machine, the
grader's machine and Render behave identically.

Two problems stacked on top of each other:

1. `docker build` failed pulling `python:3.12-slim` because my Docker config sets
   `"credsStore": "desktop"` and `docker-credential-desktop.exe` was not on `PATH`. The
   fix was one line — prepend `C:\Program Files\Docker\Docker\resources\bin` — not the
   throwaway-config workaround I first tried.
2. With that cleared, `apt-get` exited 100: `python:3.12-slim` has moved to Debian trixie,
   where `libgdk-pixbuf2.0-0` is now `libgdk-pixbuf-2.0-0`. While fixing the name I also
   dropped `build-essential`, `libcairo2-dev` and the other `-dev` packages that were in
   my first Dockerfile — WeasyPrint 60+ renders through Pango and dropped cairo back in
   53, so none of them were being used. The image got smaller and the build faster.

The takeaway I would carry to a real project: the first error message was about
credentials and the second was about a package name, and neither mentioned the actual
subject, which was WeasyPrint's native dependencies.

### Render free tier

Free, Docker-native, and a blueprint file means the deploy is reproducible rather than
a sequence of clicks I would have to document. The 15-minute sleep is the price. I
considered a paid instance or a keep-alive ping, but a cron pinging my own service to
defeat the platform's cost control felt like the wrong thing to hand in, so I documented
the cold start at the top of this file instead.

### Caching

The task asks not to hammer the site. `search_index.json` is fetched once and cached for
24 hours, so searching is a local filter over ~270 products and costs no requests at all.
Product pages cache per SKU on disk. Measured: cold fetch 0.455 s and one request, warm
0.004 s and none.

The one design point worth calling out is that a single fetch of `solde.red/<SKU>` returns
**all three languages**. `locales-data` carries EN/DE/HR together and the resource links
carry `data-loc-en/de/hr`, so the language selector costs zero extra requests. If I had
fetched per language, B1 would have tripled the load on the site for no reason.

---

## Where the data comes from

No HTML scraping for the bulk of it. Two sources, both plain `requests.get()`:

1. **`solde.red/search_index.json`** — the whole catalogue (~270 products) in one file.
   Cached with a 24-hour TTL; search is a local filter, so typing in the box costs nothing.
2. **`solde.red/<SKU>`** — the product page carries `<script id="locales-data">` holding
   the full canonical schema for all three languages at once. Parsed with a direct
   `json.loads`, no CSS-selector fragility.

Four things are not in that JSON and do need the HTML: what's in the box, the resource
links, the image list, and the last-updated timestamp. Those are read from stable
`data-*` attributes and structural class names rather than presentational ones.

Because `locales-data` and the `data-loc-*` attributes carry all three languages in a
single response, the language selector (B1) costs one fetch, not three.

### How complete the translations actually are

Worth being precise, because "supports three languages" can mean several things. What is
translated, and by whom:

| Part of the sheet | EN | DE / HR | Source |
|---|---|---|---|
| Product name, descriptions, technical details | yes | yes | Soldered's `locales-data` |
| Spec **group** names (Measurement → Mjerenje) | yes | yes | Soldered's `locales-data` |
| Resource links and their categories | yes | yes | `data-loc-*` / `data-cat-label-*` |
| Section headings, footer, page counter | yes | yes | `data/ui_strings.json`, written by me |
| Spec **field** labels (Supply Voltage) | yes | **no** | Soldered publishes these in English only |
| Box contents | yes | **no** | Only rendered in the fetched page's language |
| Typical applications (R6) | yes | **no** | Written by me, English only |

So a Croatian sheet is genuinely Croatian in its prose, headings and navigation, but the
spec table keeps English field labels because that is all the source has. That is a
Soldered-side gap, not a tool-side one — the moment `locales-data` carries translated
field labels, they will appear with no code change.

---

## Decisions

### R3 — missing data: hide the section

Products differ wildly in what they have. The NULA board has no software or compliance
resources; the SHTC3 has no variants; only the Inkplate has a `display` group.

**The rule: if there is no data, the section does not exist.** A spec group whose fields
are all empty is dropped, a category with no resources is dropped, and a section whose
source field is blank is never opened. No empty tables, no `null`, no "N/A" columns, no
placeholder text for the content team to forget about.

The reasoning is that this is a customer-facing document, not an internal form. A row
reading "Touch support: not applicable" spends a line of an A4 page telling the reader
something they did not ask. A datasheet that simply does not mention touch says the same
thing and reads like it was written for this product rather than generated for any
product. The cost is that the reader cannot distinguish "we do not publish this" from
"this product does not have it" — acceptable for a sales document, and the full sheet
prints the source URL and last-updated date so anything can be traced back.

The one deliberate exception is a value that exists but is empty inside a group that
otherwise has data: that field is dropped, not printed as a blank cell.

### R2 — what earns a place on the one-pager

The first version matched spec groups against a per-family whitelist. That was wrong, and
the SHTC3 proved it: the sensor keeps its readings in a `measurement` group that appeared
in no whitelist, so the most important block on a sensor datasheet was being dropped from
its own one-pager. A whitelist can only describe the families you have already seen.

`app/sections.py` now **ranks rather than filters**. Every group the product actually has
is rankable; the family only decides what floats to the top:

| Family | Detected by | Leads with |
|---|---|---|
| Display | has a `display` group | display, connectivity, power, interface |
| Development board | has an `mcu` group | mcu, connectivity, interface, power |
| Sensor | has a `measurement` group | measurement, interface, power, connectivity |
| Anything else | fallback | interface, power, connectivity |

An unrecognised group key sorts into the middle instead of vanishing, so a product family
that does not exist yet still produces a sensible one-pager. Reference-only groups
("Other") sort last so they cannot push a headline spec off the page. The selection is
then capped by group and field count, dropping from the bottom of the ranking, because
the page budget is fixed.

The full datasheet prints every group in source order and adds overview, technical
details, variants and the full resource list.

---

## What is wrong with the solde.red data

This is the part I would actually want to talk about. Everything below is a real case hit
while building, not a hypothetical.

**A resource block that silently loses most of its content.** `.resource-card` is a
*category* container holding several `.resource-item` links. Reading one link per card —
the obvious first implementation — published 4 of Inkplate 6's 7 resources and lost the
NULA board's Pinout entirely. The card's own `data-count="2"` attribute contradicts what
a naive parse produces, which is what made it findable.

**Two different pages sharing one label.** 333232 lists "Arduino: Get Started" twice under
software, pointing at `docs.soldered.com` and `inkplate.readthedocs.io`. They are genuinely
different resources, so deduplicating loses one, but two identical link texts side by side
read like a bug on a printed sheet. The tool appends the host when a label repeats.

**A spec that contradicts its own description.** The NULA DeepSleep short description says
*"7µA deep sleep current"*; its `sleep_current_ua` field says `16`. Inkplate 6 has the same
problem internally: the overview says *"super-low-power (22uA)"*, while both the spec field
and the technical details say 25 µA. The tool prints the structured field and leaves the
prose alone — it cannot know which is right. **Worth someone at Soldered checking.**

**The naming migration is half-finished.** The structured fields are clean (`qwiic_compatible`),
but the prose still carries retired terms, and in one case carries both at once: Inkplate 6's
technical details read *"qwiic/Qwiic compatibility"*, which is the old easyC/Qwiic line with
only the first half renamed. The tone-of-voice brief says qwiic is compatible with SparkFun
Qwiic, so writing both is redundant and looks like a typo.

**Labels are auto-title-cased from snake_case**, which mangles every acronym: `Mcu Part
Number`, `Sd Card Slot`, `Rtc Onboard`, `Ic Part Number`, `Sram (KB)`, `Wifi`.

**Units live in three different places.** Sometimes in the `unit` key (`display_size_inch`
→ `inch`), sometimes only as a name suffix with `unit` empty (`sleep_current_ua`,
`supply_voltage_min_v`), sometimes inside free text (`Temperature -40 to 125 C`). The
third form also drops the degree sign.

**Values are enum codes**: `wifi4`, `classic_and_ble`, `jst_2pin`, `3v3_5v`, `3v3_or_5v`,
`grayscale`. This is the literal case the tone-of-voice brief describes under "What this
means for machine-readable data": *"A value that exists so software can compare it is not
automatically a value a person should read on a printed page."*

**Part numbers get damaged by naive cleanup.** `ESP32 WROVER-E` is written with a space
where the real part number has a hyphen, and `ESP32-S3-WROOM-1(N8R8)` is missing a space
before the bracket.

**Prose units have no space**: `22uA`, `1.26s`, `1200mAh`, against a brief that explicitly
requires `3.3 V`.

**The box contents nest the SKU inside the name element**, so the obvious
`" ".join(stripped_strings)` yields `Inkplate 6 333232`.

**One spec group has an empty key** (`""`, labelled "Other") on all three products, so any
code that keys groups by identifier has to handle the empty string.

---

## What I tested

`scripts/verify_sheets.py` renders through the app's own code path and asserts the R4
rules, so a regression fails a check instead of quietly producing a four-page one-pager:

```
[ok  ] 333232 onepager  1 page(s)      [ok  ] 333232 full  3 page(s)
[ok  ] 333352 onepager  1 page(s)      [ok  ] 333352 full  2 page(s)
[ok  ] 333032 onepager  1 page(s)      [ok  ] 333032 full  2 page(s)
all checks passed
```

It checks that the one-pager is exactly one page for every product, and that every page of
every sheet carries the product footer and its page number.

Edge cases run by hand against the routes, with the actual result:

| Case | Result |
|---|---|
| Nonexistent SKU `999999` | 200, message "Could not load SKU 999999: 404 Client Error" — no stack trace |
| Non-numeric SKU `abc` | 200, same handled message |
| Search with no matches | 200, "No products match that search." |
| `/generate` with no SKU | Redirects to the picker |
| Unknown template `poster` | Falls back to one-pager, valid PDF |
| Unknown language `fr` | Falls back to EN, valid PDF |
| Variant SKU `333229` (Inkplate with enclosure) | Valid one-pager, 1 page |
| German one-pager, Croatian full sheet | Both valid, translated labels and resources |
| WeasyPrint missing (Windows, no GTK) | App still starts; `/generate` explains why and links to the HTML preview |
| Second fetch of the same SKU | Cold 0.455 s / 1 request, warm 0.004 s / 0 requests (measured with `requests.get` counted) |

Things I checked by eye on the rendered PDFs: tables not cut across page breaks, no
heading stranded at the bottom of a page, images scaled inside the text column, footer
and page numbers on all pages, no overflow past the right margin.

Checked against the deployed instance, not just locally:

| Case | Result |
|---|---|
| `GET /healthz` | `{"status":"ok","weasyprint":true}` — the native libraries loaded in the deployed image |
| `333232` one-pager, EN | 200, `application/pdf`, 228,747 bytes in 3.9 s — byte-identical size to the local build |
| `333032` full sheet, HR | 200, `application/pdf`, 193,204 bytes in 4.8 s |
| `333352` one-pager, DE | 200, `application/pdf`, 1,021,277 bytes in 6.8 s (larger product photos) |

Those timings are on a warm instance and include fetching the product from solde.red,
because the free tier starts with an empty cache.

---

## How AI was used

Claude Code (Opus) wrote most of this, with me directing and reviewing. It was genuinely
fast at the mechanical parts — the Jinja partials, the Dockerfile, the paged-media CSS.
It was least reliable exactly where it sounded most confident, and every one of the
following was caught by running the thing and reading the output rather than by reading
the code.

The worst error was structural. It assumed `.resource-card` was one resource per card,
which produced clean, plausible, working code that silently dropped 3 of Inkplate 6's 7
resources and all of the NULA board's Pinout link. Nothing errored. I only caught it by
dumping the parsed output next to the page's own `data-count="2"` attribute and noticing
they disagreed. The same class of mistake showed up when it "deduplicated" two
identically-labelled Arduino links on the assumption they were the same URL — they were
two different pages, and the dedupe would have deleted a real resource.

It also misdiagnosed confidently. When the footer printed only on the last page, it
concluded WeasyPrint does not support running elements and proposed rewriting the
mechanism. A ten-line experiment showed running elements work fine and the real cause was
document order: a running element is only available from the point it appears, and the
footer was last in the body. Moving it to the top fixed it. Had I taken the diagnosis at
face value I would have rewritten working code for no reason.

Three smaller ones. A regex meant to turn `125 C` into `125 °C` used `\s*` where it needed
`\s+`, so it also rewrote `I2C` into `I2°C` — visible immediately in the spec table, invisible
in the source. A "defensive" fallback in the label formatter returned the original string
whenever it saw a bracket, which silently disabled the acronym fix on every unit-bearing
label; the safe-looking branch was the bug. And it wrote a commit message asserting the
wrong CSS path had been producing unstyled PDFs, when the real failure was a
`FileNotFoundError`; I checked the claim in the container before it went into permanent
history.

The pattern is consistent: it is reliable on syntax and unreliable on assumptions about
data it has not looked at. The habit that caught everything was cheap — render the
artefact, read the actual output, compare against the source page — and it is why
`verify_sheets.py` exists rather than a note in this README saying the one-pager fits.

---

## What is left out

- **Cold starts.** The free tier sleeps after ~15 minutes, so the first visit in a while
  takes 30–50 seconds. Everything after that is fast. A paid instance or a keep-alive
  cron would fix it; neither felt right for a task submission.
- **Pinout images.** The NULA and SHTC3 pages expose a pinout PNG under technical
  resources. It is linked but not embedded; on a datasheet it deserves a page. This is
  the thing I would do first with more time — R2 explicitly lists pinout as full-datasheet
  content, and I am linking it rather than showing it.
- **Layout options (B2).** Not attempted. B1 (language) came almost free with the data, B2
  did not, and the core mattered more.
- **Typical applications exists only for the three graded SKUs, and only in English.** Any
  other product omits the section rather than printing a generic filler paragraph, which
  I think is the right failure. Translating three paragraphs would be easy; having them
  checked by someone who writes Soldered's German is not, and shipping unchecked customer
  copy in a language I cannot verify seemed worse than shipping it in English.
- **`data/` maps cover what the three products need.** A wider sweep of the catalogue would
  certainly turn up more enum codes; they degrade gracefully (underscores become spaces)
  rather than breaking, but they would not be perfect prose.
- **No automated test suite** beyond `verify_sheets.py`. The normalizer's transformations
  are the obvious thing to unit-test and there was not time.
- **My German section headings are not proofread.** The Croatian ones I stand behind. The
  German are standard datasheet terms (`Lieferumfang`, `Technische Daten`) but a native
  speaker should confirm the tone before this goes to a customer.
