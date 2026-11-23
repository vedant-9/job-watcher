# AGENTS.md: set up and customize the job watcher

This file is for an AI coding assistant (or a person) helping someone run their own copy of this job watcher.
Read it fully before changing anything.

## What this project is

A small, free Python bot (standard library only, no pip installs) that runs on GitHub Actions twice a day.
It reads companies' official job boards, keeps only roles that match one person's preferences, and sends
**new** openings to Telegram. It also appends links to `jobs_log.md` and records each run in `status.md`.

Each person runs their **own private copy** (their own repo, secrets and `config.json`). Nothing is shared.

## Repo layout

| Path | Purpose | Edit it? |
|---|---|---|
| `config.json` | The person's preferences and company list | Yes, this is the main file |
| `watcher.py` | Main flow: config, state, log, status, collect, evaluate | Rarely |
| `filters.py` | Location, title and experience rules | Only to change the logic itself |
| `notifier.py` | Telegram and email sending | Rarely |
| `sources/` | One file per kind of career site (`greenhouse.py`, `lever.py`, `ashby.py`, `workday.py`, `smartrecruiters.py`, `eightfold.py`, `atlassian.py`, `apple.py`, plus `common.py`) | To add or fix a site type |
| `.github/workflows/main.yml` | Schedule (cron is in UTC) and manual-run options | To change times |
| `seen.json`, `jobs_log.md`, `status.md` | Created by the bot | Never edit by hand |

## Step 1: interview the person before touching config

Ask these, then write the answers into `config.json`. Do not guess. Ask all of them in one message.

1. **Experience:** total years of relevant experience (`my_years`, e.g. 3.5).
2. **Role types:** what titles do they want (backend, data, ML, SRE, security, fullstack, QA, ...)? What must
   be excluded (frontend, mobile, hardware, management, ...)?
3. **Level:** are they happy with senior titles, or only mid-level? (Most "senior", "lead", "staff" and
   "principal" titles are excluded by default.)
4. **Locations:** first-choice city, acceptable cities, and whether remote is acceptable.
5. **Companies:** a list of company names they want to track (or let the assistant suggest well-known,
   stable employers in their field).
6. **Strictness:** how tolerant of postings that do not state experience? Default: send them, labelled
   "exp not stated".
7. **Notifications:** Telegram (recommended) or email.

## Step 2: map the answers to `config.json`

Top-level keys:

| Key | Meaning |
|---|---|
| `my_years` | Their experience in years |
| `fit_slack` | A role passes if its minimum years is at most `my_years + fit_slack` (default 0.5) |
| `stretch_years` | Extra tolerance, default 0 |
| `min_required_years` | Roles asking for fewer years than this are dropped as too junior (default 2; lower it for juniors, raise it for seniors) |
| `send_unknown_experience` | `true`: send postings that do not state experience; `false`: drop them |
| `include_remote` | Include plain "Remote" roles only if the description mentions the country (default true) |
| `heartbeat` | Send a one-line "ran OK" message when nothing is new (default true) |
| `preferred_locations` | Lowercase city names ranked first (e.g. `["pune"]`) |
| `acceptable_locations` | Lowercase city names ranked second |
| `allow_generic_india` | Accept roles that just say "India" |
| `other_india_cities` | A **block list**: cities that stop a generic "India" role from being accepted. Keep cities the person does not want here |
| `include_title_regex` | A title must match this to be considered |
| `exclude_title_regex` | A title matching this is dropped (intern, lead, frontend, ...) |
| `senior_title_regex` | Titles like "senior ..." are dropped when experience is not stated |
| `fresher_desc_regex` | Descriptions that look like entry-level roles are dropped when experience is not stated |

Rules for editing:

- **Keep the filter strict. Never widen it silently.** If you loosen a regex or a location rule, say so
  plainly and tell the person what will now get through.
- Regexes are lowercase-matched Python regexes inside JSON, so every backslash is doubled (`\\b`).
- After any regex edit, test it with a few sample titles (see "Testing").
- Role types that need different titles (for example data engineer, SRE, security) mean editing
  `include_title_regex` and likely the `exclude_title_regex` words that currently block them
  (`data scientist`, `quality`, `support engineer`, `security analyst`, and so on).

**Not-India users:** location logic assumes India (generic "India" and "Remote (India)" handling are
hard-coded in `filters.py` and `watcher.py`). For another country, replace the `\bindia\b` patterns with that
country's name and update the labels in `write_log` in `watcher.py`. Test before relying on it.

## Step 3: choose companies

Each company is one entry in `config.json` under `companies`. Find its job board address, then use the
matching template:

| Job board address contains | Entry |
|---|---|
| `boards.greenhouse.io/<slug>` or `job-boards.greenhouse.io/<slug>` | `{"name": "X", "ats": "greenhouse", "slug": "<slug>"}` |
| `jobs.lever.co/<slug>` | `{"name": "X", "ats": "lever", "slug": "<slug>"}` |
| `jobs.ashbyhq.com/<slug>` | `{"name": "X", "ats": "ashby", "slug": "<slug>"}` |
| `<tenant>.wdN.myworkdayjobs.com/<site>` | `{"name": "X", "ats": "workday", "host": "<tenant>.wdN.myworkdayjobs.com", "tenant": "<tenant>", "site": "<site>", "search": "software engineer"}` |
| `jobs.smartrecruiters.com/<slug>` | `{"name": "X", "ats": "smartrecruiters", "slug": "<slug>"}` |

Other ready types: `atlassian`, `apple`, `eightfold` (see the entries already in `config.json`).

How to find the address: search the company's name plus "careers", open a job posting and look at the URL.
Companies whose site only loads jobs in the browser (many big tech companies and banks) are not covered
until a public feed is found; do not scrape their pages. Never guess a slug and leave it enabled: an entry
that returns 404 or 0 jobs is reported as failing, so either fix it or set `"enabled": false`.

Always verify a new entry with a `check` run (below) before trusting it.

## Step 4: set up the repo (the person does this part)

1. Create a **private** GitHub repo and upload everything in this project, including the hidden
   `.github/workflows/main.yml` and the whole `sources/` folder (use drag and drop on the GitHub upload
   page to keep folders).
2. Create a Telegram bot with @BotFather, send it any message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser to find the `chat.id`.
3. In the repo: Settings, Secrets and variables, Actions, and add two secrets: `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_CHAT_ID`.
4. Settings, Actions, General, Workflow permissions: **Read and write**.
5. Actions, job-watcher, **Run workflow**. The first normal run sends up to 100 matching openings and marks
   everything as seen; after that only new ones are sent.

Email is optional and uses the secrets `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` and `EMAIL_TO`.

**Never paste the bot token into a chat, a commit or a file.** If it leaks, revoke it in @BotFather and create a
new one.

## Schedule

`.github/workflows/main.yml` uses a cron in **UTC**. India time is UTC+5:30, so `30 2,14 * * *` means
8:00 AM and 8:00 PM IST. GitHub often starts scheduled runs hours late; run manually when something is urgent.

## Running and testing

Manual run options (Actions, job-watcher, Run workflow, "only" box):

- empty: normal run (only new jobs)
- `check`: tests every source and reports which work or fail
- a company name, e.g. `Mastercard`: lists all its current matching openings (does not change `seen.json`)

Local checks with Python 3.10+ (no installs needed). `watcher.py` supports:

```
python watcher.py --exp "3+ years of experience in Java"   # test the experience parser
python watcher.py --dry-run                                  # full run without sending or saving
```

Network access is needed for real runs. For a change to filters, test with sample titles and locations by
importing `filters.py` and calling `title_ok(title, cfg)`, `classify_location(loc, cfg)` and
`parse_experience(text)` with the loaded `config.json`. Keep a short list of titles that must pass and titles
that must be rejected, and re-run it after every regex edit.

## How it behaves (so you do not break it)

- **No silent loss:** if the Telegram message cannot be sent, the run exits with an error, the jobs are NOT
  marked as seen, and the next run retries. Do not change this.
- A source that fails never marks jobs as seen. It is listed in the Telegram message (names only) and in
  `status.md` (error, HTTP status, retries, timings).
- Failed sources get one more try after a pause at the end of the run. Permanent errors (404, 403) are not
  retried.
- Requests to one host are paced and retried with backoff, because Workday throttles bursts.
- A Workday source that returns 0 postings is treated as a failure (wrong site name or search text).
- `status.md` is rewritten every run. It also keeps the scheduled workflow from being disabled by GitHub
  for inactivity.
- Only titles and locations that pass the filter get a detail fetch (the job description), which is where
  the experience is read from.

## Adding a new kind of career site

Create `sources/<name>.py` with:

```python
def fetch(c):            # c is the company's config entry
    return [{"id": "...", "title": "...", "location": "...", "url": "..."}]   # "desc" optional

def detail(c, job):      # optional; used when "desc" is not provided
    return description_text, location_text_or_None
```

Use `http_json` / `http_text` from `sources/common.py` (they handle pacing, retries and diagnostics). Then add
the file name to `NAMES` in `sources/__init__.py`. A module that fails to load only marks its own companies as
failing.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `HTTP Error 404` | Wrong board name in `config.json`. Fix it or set `"enabled": false` |
| `HTTP Error 403` | The site blocks automated requests. Leave it disabled; use that company's own alerts. Do not try to get around the block |
| `Expecting value` or "bad reply ... empty body" | Throttling (common on Workday). Usually fixed by the built-in retries; if one source keeps failing, check `status.md` |
| "returned 0 postings" | Wrong Workday site name; check the career-page URL |
| No messages at all | Check the Actions tab for red runs, then the two secrets. A run that cannot send fails visibly |
| Too many irrelevant jobs | Tighten `exclude_title_regex`, lower `fit_slack`, or set `send_unknown_experience` to `false` |
| Too few jobs | First confirm sources are OK in `status.md`. Then ask the person before loosening anything |

## Principles for any assistant working here

1. Do not widen filters, add scraping of blocked sites, or add notification channels without being asked.
2. Do not claim a company is covered until a `check` run shows it as OK. Say "added, unverified" until then.
3. Prefer changing one small file (a `sources/` module or `config.json`) over rewriting `watcher.py`.
4. Never ask for, store or print secrets. Never put them in files.
5. When delivering changed files, list exactly which files to upload and where they go.
6. LinkedIn and Indeed are not scraped. Tell the person to use those sites' built-in job alerts.
