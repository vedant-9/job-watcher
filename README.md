# Job watcher

Checks company job boards twice a day (8 AM and 8 PM IST; GitHub can start runs a few hours late) and
reports only NEW openings that are:

- in India: Pune first, then Hyderabad / Bengaluru / Mumbai, or "Remote (India)". A plain "Remote" role is
  listed under "Remote (verify India eligibility)" only if its description mentions India
  (`"include_remote": false` turns this off)
- SDE2-style backend / AI roles (no lead, staff, principal, frontend, mobile, hardware, fresher, intern or
  "associate" roles)
- within your experience (`my_years` in `config.json`; a role passes if its minimum years is at most
  `my_years + fit_slack`). Experience is read from the description, title and URL. If a posting doesn't
  state it, it is sent as "exp not stated".

New openings go to Telegram and to `jobs_log.md` (clickable links, newest run first, grouped by city).
When nothing is new you get a one-line "ran OK" message (`"heartbeat": false` turns this off), and
`status.md` records the last run.

## Sources

The companies' own job boards: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Eightfold and
Atlassian's public feed, and Apple (read from its India search pages, so it can break if Apple changes
its site). LinkedIn and Indeed are not scraped; keep using their built-in alerts.
Companies whose career sites only load jobs in the browser (Microsoft, Google, Uber, Flipkart, Swiggy, most
banks) are added one at a time when a public job feed is found for them. Until then, use their own job
alerts and referrals.

## Reliability

- If a Telegram message cannot be sent, the run fails (red in the Actions tab) and the jobs are NOT marked
  as seen, so the next run retries. `jobs_log.md` is written only after a successful send.
- A source that fails is listed in the status message with its error. A failed source never marks jobs as
  seen. Workday and others are retried automatically.

## Files

- `watcher.py`: the main flow (config, state, log, status)
- `sources/`: one small file per kind of career site (`greenhouse.py`, `workday.py`, `apple.py`, ...).
  If one site type breaks, fix or replace only that file; the others keep working
- `filters.py`: location, title and experience rules
- `notifier.py`: Telegram / email sending
- `config.json`: your settings and the company list
- `.github/workflows/main.yml`: the schedule (runs on GitHub, free)
- `jobs_log.md`, `seen.json`, `status.md`: created by the bot (do not edit `seen.json`)

## Setup

1. Private GitHub repo with the files above.
2. Telegram: create a bot with @BotFather, send it a message, open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat.id`. In the repo go to
   Settings -> Secrets and variables -> Actions and add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   Never paste the token anywhere public.
3. Settings -> Actions -> General -> Workflow permissions -> Read and write.
4. Actions -> job-watcher -> Run workflow.

## Run options (Actions -> job-watcher -> Run workflow -> "only" box)

- empty: normal run (only new jobs)
- `check`: tests every source and reports which work or fail
- a company name, e.g. `Walmart`: lists ALL of that company's current matching openings (does not change
  `seen.json`)

## Tuning (`config.json`)

- `my_years`, `fit_slack`, `min_required_years`: experience rules
- `send_unknown_experience`: `false` drops postings that don't state experience
- `preferred_locations`, `acceptable_locations`, `other_india_cities`, `allow_generic_india`: locations
- `include_title_regex`, `exclude_title_regex`, `senior_title_regex`: which titles pass
- Add a company by its job-board address:
  - `boards.greenhouse.io/<slug>`: `{"name": "X", "ats": "greenhouse", "slug": "<slug>"}`
  - `jobs.lever.co/<slug>`: `{"name": "X", "ats": "lever", "slug": "<slug>"}`
  - `jobs.ashbyhq.com/<slug>`: `{"name": "X", "ats": "ashby", "slug": "<slug>"}`
  - `<tenant>.wdN.myworkdayjobs.com/<site>`: `{"name": "X", "ats": "workday", "host": "<tenant>.wdN.myworkdayjobs.com", "tenant": "<tenant>", "site": "<site>", "search": "software engineer"}`
  - `careers.smartrecruiters.com/<slug>`: `{"name": "X", "ats": "smartrecruiters", "slug": "<slug>"}`
- Disable a company with `"enabled": false`.

## Adding a new kind of site

Create `sources/<name>.py` with `fetch(c)` (returns a list of `{id, title, location, url}`) and optionally
`detail(c, job)`, then add `<name>` to `NAMES` in `sources/__init__.py`. A module that fails to load only
marks its own companies as failing.

## If a source fails

The status message lists each failing source with its error. A source that fails never marks jobs as seen,
so nothing is lost. Common causes: a wrong board name in `config.json` (fix it or set `"enabled": false`),
or a site that blocks automated requests (HTTP 403; leave it off and use that company's own alerts).
