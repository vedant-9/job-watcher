# Job watcher

Checks company career-board APIs every 4 hours, filters for SDE2-style backend/AI roles in
Pune, Hyderabad, Bengaluru and Mumbai, and messages you only about NEW openings.

Covers Greenhouse, Lever, Ashby and Workday boards. It does not scrape LinkedIn or Indeed;
keep using their native job alerts for those.

## Setup (about 10 minutes, free)

1. Create a **private** GitHub repo and push this folder to it (keep `.github/workflows/jobs.yml`
   at the repo root and `watcher.py`, `config.json` next to it).
2. Create a Telegram bot: message @BotFather -> /newbot -> copy the token. Send any message to
   your bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. In the repo: Settings -> Secrets and variables -> Actions -> add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   (Email alternative: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`; for Gmail use an app password.)
4. Run `python watcher.py --check` on your own machine first. It reports which company entries
   work. Fix or delete the failing ones in `config.json`.
5. Actions tab -> job-watcher -> Run workflow. The first run sends up to 60 current matches;
   after that you only get new ones. Schedule runs every 4 hours (UTC cron).

## Tuning

- `include_title_regex` / `exclude_title_regex` control which titles pass. "Senior" is excluded by
  default (SDE2 target); remove `\\bsenior\\b` to see senior roles too.
- `locations` is a substring match. Workday "N Locations" entries are kept so you don't miss them.
- Add a company: find its careers page. `boards.greenhouse.io/<slug>` -> greenhouse,
  `jobs.lever.co/<slug>` -> lever, `jobs.ashbyhq.com/<slug>` -> ashby,
  `<tenant>.wdN.myworkdayjobs.com/<site>` -> workday (host, tenant, site).
- Companies with their own career sites (Amazon, Microsoft, Google, Uber, Atlassian, banks,
  Visa, PayPal) aren't covered; use their official job alerts.

## Notes

- Scheduled GitHub workflows can pause after 60 days without repo activity; re-enable in the
  Actions tab if that happens.
- Respect each site's terms; this uses their public job-board endpoints at a low frequency.
