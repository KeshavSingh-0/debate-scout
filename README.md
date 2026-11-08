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
   looks like `opencaselist.com/caselist/hspolicy25`), and copy the
   `hspolicy25` part.
3. Enter your opencaselist username/password (used once for this run, never
   stored) and your Jev API key from
   [console.typesafe.ai/keys](https://console.typesafe.ai/keys).
4. Upload the tournament's pairings or entry-list PDF.
5. Click **Start scouting**. A table fills in live as each team is scraped,
   parsed, and classified.
6. When you're ready to hand results off, click **Copy for Sheets / Excel**
   (puts a tab-separated table on your clipboard -- paste directly into a
   spreadsheet) or **Download CSV**.

Re-uploading a pairings PDF for a tournament you already ran (e.g. with a
few new entries added after a round of eliminations) only scouts the *new*
teams -- anything already scouted is skipped.

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

- **The opencaselist scraper is best-effort.** opencaselist is a
  login-gated, JavaScript-rendered site, and this project had no test
  credentials available while building it, so the Playwright selectors in
  `app/scraper.py` are written defensively (by visible text/role, not CSS
  classes) but untested against the live DOM. If a run fails partway, the
  error message names the step that failed and a debug screenshot is saved
  alongside the download folder -- that's the fastest way to spot which
  selector needs a one-line tweak.
- **.docx case files condense much better than PDF ones.** The whole point
  of the parsing step is to hand the LLM only the tags and the
  highlighted/underlined "read" portions of each card, not the full file.
  That relies on Word formatting (bold tags, underline/highlight on read
  text) that a PDF export usually loses; PDF case files fall back to a
  bold-text-only heuristic (`app/pdf_card_parser.py`) that keeps tags and
  cites but not card bodies.
- **The pairings PDF parser is format-tolerant, not format-specific.** It
  handles both "Team A vs Team B" pairing sheets and plain entry lists,
  using the standard "School Name + debater initials" team-code convention
  (e.g. "Georgetown KM"). An unusual export format may need a regex tweak
  in `app/pairing_parser.py`.
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
`state` (here, the condensed case text) plus typed `Choice` questions, and
it returns a typed answer plus a confidence score directly, no prompt
engineering a JSON schema and hoping the model honors it. See
`app/jev_client.py` for exactly how that's used here (one `Choice` question
for K-aff vs. policy aff, and a second one for country, skipped entirely
for K-affs to save tokens).
