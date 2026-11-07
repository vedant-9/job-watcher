# Job watcher

Checks company job boards twice a day (8 AM and 8 PM IST) and reports only NEW openings that are:

- in India: Pune first, then Hyderabad / Bengaluru / Mumbai (or "India" with no city stated)
- remote roles: "Remote (India)" is listed with the India group. A plain "Remote" role is listed under
  "Remote (verify India eligibility)" only if its description mentions India (turn off with
  `"include_remote": false`)
- SDE2-style backend / AI roles (no lead, staff, principal, frontend, mobile, hardware, fresher or intern roles)
- within your experience (`my_years` = 3.5 in `config.json`; a role passes if its minimum years is at most
  `my_years + fit_slack`). Experience is read from the description, title and URL. If a posting
  doesn't state it, it is sent as "exp not stated".

New openings are written to `jobs_log.md` (clickable links, newest run first, grouped by city) and,
if Telegram is set up, also sent as a Telegram message.

Sources: Greenhouse, Lever, Ashby and Workday job boards (the companies' own boards). LinkedIn and
Indeed are not scraped; keep using their built-in alerts. Companies with custom career sites
(Microsoft, Google, Amazon, Uber, Atlassian, Flipkart, Swiggy, most banks) are not covered.

## Files

- `watcher.py`: the bot
- `config.json`: your settings and the company list
- `.github/workflows/main.yml`: the schedule (runs on GitHub, free)
- `jobs_log.md`: created by the bot; the job links
- `seen.json`: created by the bot; its memory of jobs already handled (do not edit)

## Setup

1. Private GitHub repo with the files above (`watcher.py` and `config.json` at the top level).
2. Optional Telegram: create a bot with @BotFather, send it a message, open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat.id`. In the repo go to
   Settings -> Secrets and variables -> Actions and add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   Never paste the token anywhere public.
3. Settings -> Actions -> General -> Workflow permissions -> Read and write (so it can save `seen.json`
   and `jobs_log.md`).
4. Actions -> job-watcher -> Run workflow.

## Run options (Actions -> job-watcher -> Run workflow -> "only" box)

- empty: normal run (only new jobs)
- `check`: tests every company source and reports which work or fail
- a company name, e.g. `Walmart`: lists ALL of that company's current matching openings (does not
  change `seen.json`)

Delete `seen.json` only if you want every current match re-sent as new.

## Tuning (`config.json`)

- `my_years`, `fit_slack`, `min_required_years`: experience rules
- `send_unknown_experience`: `false` drops postings that don't state experience
- `preferred_locations`, `acceptable_locations`, `other_india_cities`, `allow_generic_india`: locations
- `include_title_regex`, `exclude_title_regex`, `senior_title_regex`: which titles pass
- Add a company by its job-board address:
  - `boards.greenhouse.io/<slug>` -> `{"name": "X", "ats": "greenhouse", "slug": "<slug>"}`
  - `jobs.lever.co/<slug>` -> `{"name": "X", "ats": "lever", "slug": "<slug>"}`
  - `<tenant>.wdN.myworkdayjobs.com/<site>` -> `{"name": "X", "ats": "workday", "host": "<tenant>.wdN.myworkdayjobs.com", "tenant": "<tenant>", "site": "<site>", "search": "software engineer"}`
- Disable a company with `"enabled": false`.

## Notes

- GitHub pauses scheduled workflows after 60 days without repo activity; the bot's own commits keep it
  active, but if it ever pauses, re-enable it in the Actions tab.
- Scheduled runs can start a few minutes late.
- Always confirm a posting on the company's own page before applying or asking for a referral.
