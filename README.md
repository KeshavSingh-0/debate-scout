# Debate Scout

Upload a tournament pairings PDF, paste your opencaselist login and a Jev
(TypeSafe.ai) API key, and this app scouts every opponent on the sheet: it
logs into [opencaselist.com](https://opencaselist.com), finds each team's
posted affirmative, and classifies it as a **K-aff** or **Policy aff** (and,
for policy affs, which country the plan is about). Results show up live on
the page, grouped by tournament, and export as a sheet you can paste
straight into Google Sheets or Excel.

No command line, no cloning a repo to use it -- once it's deployed (see
below), it's just a webpage: upload a PDF, paste two sets of credentials,
click **Start scouting**.

## Using it

1. Open the deployed app URL.
2. Fill in the tournament name, pick the section (**NDT-CEDA** or **NSDA-HS
   Policy**), and paste the **caselist URL slug** -- log into
   opencaselist.com yourself once, look at the URL for your circuit (it
   looks like `opencaselist.com/ndtceda26` or `opencaselist.com/hspolicy26`),
   and copy the slug (`ndtceda26`, `hspolicy26`, etc. -- the year suffix
   changes each season).
3. Enter your opencaselist username/password (used once for this run, never
   stored) and your Jev API key from
   [console.typesafe.ai/keys](https://console.typesafe.ai/keys).
4. Upload the tournament's entry list PDF (e.g. Tabroom's "fieldsort" export
   -- Institution / Debaters / Entry Code table). A "Team A vs Team B"
   pairing sheet works too, just with less context per entry.
5. Click **Start scouting**. A table fills in live as each team is scraped,
   parsed, and classified.
6. When you're ready to hand results off, click **Copy for Sheets / Excel**
   (puts a tab-separated table on your clipboard -- paste directly into a
   spreadsheet) or **Download CSV**.

Re-uploading a pairings PDF for a tournament you already ran (e.g. with a
few new entries added after a round of eliminations) only scouts the *new*
teams -- anything already scouted is skipped.

## When something fails: Debug Mode

Check **Debug Mode** above the results table (it's safe to leave on) and a
log console appears showing exactly what the scraper and Jev are doing --
every navigation, click, and request, step by step. If a team errors out or
a run won't connect, click **Copy debug logs** and paste that straight into
a message to Claude; it has enough detail (the exact page it was on, which
click failed, what Jev said) to diagnose the actual failure rather than
guessing from the one-line error shown in the results table.

This is separate from Render's own Logs tab: Debug Mode always captures
full detail for the app's own buffer regardless of the `LOG_LEVEL`
environment variable (which only controls what shows up in Render's
stdout logs).

## Deploying it (one time, by whoever's setting this up)

This needs a real backend (file parsing, a database, and browser automation
to log into opencaselist), so it can't live on GitHub Pages alone -- GitHub
Pages only serves static files. The whole app is set up to deploy as a
single [Render](https://render.com) web service instead, which is still a
few clicks with no local setup:

1. Push this repo to GitHub (if it isn't already).
2. In the Render dashboard: **New +** &rarr; **Blueprint**, point it at this
   repo. Render reads `render.yaml` and provisions both the web service and
   a free Postgres database automatically.
3. Once it finishes deploying, Render gives you a URL
   (`https://debate-scout-xxxx.onrender.com`) -- that's the link to share.
   Nobody who uses it needs GitHub, Render, or anything else.

Render's free tier spins down when idle and takes ~30-60s to wake back up
on the first request after a while -- fine for occasional tournament
scouting, worth a paid instance if this gets used constantly.

## Where credentials go

Your opencaselist username/password are used only to log in for that one
scouting run (inside a headless browser on the server) and are never
written to the database or to disk. Your Jev API key is sent with each
classification request and likewise never stored. Only the *results*
(school, team, aff type, country, confidence, a link back to the source
file) are persisted, in the Postgres database Render provisions.

## Known limitations / first-run caveats

- **The opencaselist scraper is grounded in real saved pages.** The example
  files this was built against (`example/`) include real saved opencaselist
  pages -- the logged-out homepage/login form, the caselist listing, a
  school page, and a team page -- so `app/scraper.py` is written against
  actual markup, not guesses. That's also how two non-obvious things were
  caught: opencaselist's own team codes (e.g. "CoVi") don't match a
  tournament's entry codes for the same team (e.g. "CV"), which is why
  teams are matched by debater last names instead; and login happens at
  opencaselist's root URL itself (there's no separate `/login` route) with
  a Tabroom.com username/password. If a run still fails somewhere, the
  error names the step and a debug screenshot is saved alongside the
  download folder.
- **Teams need debater names to match reliably.** If a pairings PDF isn't a
  Tabroom-style entry-list table (see `app/pairing_parser.py`), debater
  names aren't available and the scraper falls back to matching by
  tournament team code instead -- less reliable, since that code doesn't
  always match opencaselist's own.
- **.docx case files condense much better than PDF ones.** The whole point
  of the parsing step is to hand the LLM only the tags and the
  highlighted/underlined "read" portions of each card, not the full file.
  That relies on Word formatting (bold tags, underline/highlight on read
  text) that a PDF export usually loses; PDF case files fall back to a
  bold-text-only heuristic (`app/pdf_card_parser.py`) that keeps tags and
  cites but not card bodies.
- **The pairings parser's primary path is a real Tabroom entry-list table**
  (Institution / Location / Debaters / Entry Code / Mode / Record), parsed
  with `pdfplumber.extract_tables()` and validated against a real tournament
  export. A "Team A vs Team B" style pairing sheet (or any PDF that isn't a
  parseable table) falls back to a line-based heuristic that won't have
  debater names -- see the limitation above.
- **"Export to Google Sheets" is copy/paste, not a live API integration.**
  The TSV export pastes perfectly into a Sheets or Excel selection; wiring
  up the real Google Sheets API would mean every user granting this app
  OAuth access to their Drive, which felt like more friction than it's
  worth for a scouting tool. Easy to add later if that trade-off changes.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env
uvicorn app.main:app --reload
```

Then open http://localhost:8000.

Run the test suite (covers the file parsers and the export format, which
don't need network access or real credentials):

```bash
pip install pytest
pytest
```

## Why Jev / TypeSafe.ai

This project doubles as a small case study in "type-safe" LLM calls. Jev
isn't a text-generation model you parse JSON out of -- you hand it a
`state` (here, the condensed case text) plus typed questions (`Choice`,
`Noul`, ...), and it returns typed answers with calibrated probabilities
directly, no prompt engineering a JSON schema and hoping the model honors
it.

`app/jev_client.py` follows TypeSafe's own integration guidance (installed
here as the `typesafe-ai` Claude Code skill): all three questions --
K-aff vs. policy aff, whether the plan is about one specific country, and
which country -- share the same state, so they're asked in a *single*
request instead of two or three. The country Choice and its "is this
country-specific at all" Noul are asked speculatively in the same call;
code only uses the Choice's answer when the Noul clears a threshold,
instead of baking an "All/Non-Specified" catch-all into the Choice's own
options, which tends to bias the other options' probabilities.
