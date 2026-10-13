#!/usr/bin/env python3
"""Job watcher: polls company career-board APIs, filters for SDE2-style backend roles
in your target cities, remembers what it has seen, and notifies you of NEW roles only.

Usage:
  python watcher.py --check      # test every company in config.json (reports OK / error + job count)
  python watcher.py --dry-run    # fetch + filter, print results, don't notify or save state
  python watcher.py              # normal run: notify about new matches, save state

Notifications (set env vars; any combination works, otherwise prints to stdout):
  Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Email:    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS, EMAIL_TO
Standard library only. No scraping of LinkedIn/Indeed (use their native alerts for those).
"""
import argparse
import json
import os
import re
import smtplib
import sys
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "seen.json"
UA = "Mozilla/5.0 (job-watcher personal script)"
MAX_FIRST_RUN = 60  # cap on first-run notification size


# ---------- HTTP ----------
def http_json(url, data=None, timeout=25):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ---------- Fetchers: each returns list of dicts {id,title,location,url} ----------
def fetch_greenhouse(c):
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs")
    return [
        {"id": str(j["id"]), "title": j.get("title", ""),
         "location": (j.get("location") or {}).get("name", ""), "url": j.get("absolute_url", "")}
        for j in d.get("jobs", [])
    ]


def fetch_lever(c):
    d = http_json(f"https://api.lever.co/v0/postings/{c['slug']}?mode=json")
    return [
        {"id": j["id"], "title": j.get("text", ""),
         "location": (j.get("categories") or {}).get("location", "") or "", "url": j.get("hostedUrl", "")}
        for j in d
    ]


def fetch_ashby(c):
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{c['slug']}")
    return [
        {"id": j["id"], "title": j.get("title", ""),
         "location": j.get("location", "") or "", "url": j.get("jobUrl", "")}
        for j in d.get("jobs", [])
    ]


def fetch_workday(c):
    host, tenant, site = c["host"], c["tenant"], c["site"]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    out, offset, limit = [], 0, 20
    max_results = c.get("max_results", 100)
    while offset < max_results:
        d = http_json(api, {"appliedFacets": {}, "limit": limit, "offset": offset,
                            "searchText": c.get("search", "software engineer")})
        posts = d.get("jobPostings", [])
        if not posts:
            break
        for j in posts:
            path = j.get("externalPath", "")
            out.append({"id": path, "title": j.get("title", ""),
                        "location": j.get("locationsText", "") or "",
                        "url": f"https://{host}/en-US/{site}{path}"})
        offset += limit
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever,
            "ashby": fetch_ashby, "workday": fetch_workday}


# ---------- Filtering ----------
def location_ok(loc, cfg):
    loc_l = (loc or "").lower()
    if any(x in loc_l for x in cfg["locations"]):
        return True
    # Workday often says "3 Locations" -> unknown, keep it so you don't miss it
    if re.search(r"\b\d+\s+locations?\b", loc_l):
        return True
    return False


def title_ok(title, cfg):
    t = title.lower()
    if not re.search(cfg["include_title_regex"], t):
        return False
    if re.search(cfg["exclude_title_regex"], t):
        return False
    return True


def filter_jobs(jobs, cfg):
    return [j for j in jobs if title_ok(j["title"], cfg) and location_ok(j["location"], cfg)]


# ---------- State ----------
def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return None  # None => first run


def save_state(seen):
    STATE_PATH.write_text(json.dumps(sorted(seen), indent=0))


# ---------- Notify ----------
def format_message(new_jobs):
    lines = [f"{len(new_jobs)} new job(s):", ""]
    for j in new_jobs:
        lines.append(f"- {j['company']}: {j['title']} ({j['location'] or 'n/a'})\n  {j['url']}")
    return "\n".join(lines)


def chunk(text, size=3800):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


def send_telegram(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return False
    for part in chunk(text):
        http_json(f"https://api.telegram.org/bot{tok}/sendMessage",
                  {"chat_id": chat, "text": part, "disable_web_page_preview": True})
    return True


def send_email(subject, text):
    host, to = os.getenv("SMTP_HOST"), os.getenv("EMAIL_TO")
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not (host and to and user and pw):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(text)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    return True


def notify(new_jobs):
    text = format_message(new_jobs)
    sent = False
    try:
        sent = send_telegram(text) or sent
    except Exception as e:
        print(f"[warn] telegram failed: {e}", file=sys.stderr)
    try:
        sent = send_email(f"{len(new_jobs)} new job openings", text) or sent
    except Exception as e:
        print(f"[warn] email failed: {e}", file=sys.stderr)
    if not sent:
        print(text)
    return sent


# ---------- Main ----------
def collect(cfg, verbose=True):
    results, errors = [], []
    for c in cfg["companies"]:
        fn = FETCHERS.get(c["ats"])
        if not fn:
            errors.append((c["name"], f"unknown ats {c['ats']}"))
            continue
        try:
            jobs = fn(c)
        except Exception as e:
            errors.append((c["name"], str(e)))
            continue
        matched = filter_jobs(jobs, cfg)
        if verbose:
            print(f"[ok] {c['name']}: {len(jobs)} total, {len(matched)} match")
        for j in matched:
            j["company"] = c["name"]
            j["key"] = f"{c['name']}|{j['id']}"
            results.append(j)
    for name, err in errors:
        print(f"[error] {name}: {err}", file=sys.stderr)
    return results, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="test each company source")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(CONFIG_PATH.read_text())

    if args.check:
        _, errors = collect(cfg)
        print(f"\n{len(cfg['companies']) - len(errors)} OK, {len(errors)} failing "
              "(fix slugs/hosts in config.json or remove the entries)")
        return

    results, _ = collect(cfg)
    seen = load_state()
    first_run = seen is None
    seen = set(seen or [])
    new = [j for j in results if j["key"] not in seen]

    if args.dry_run:
        print(format_message(new) if new else "No new jobs.")
        return

    if new:
        to_send = new[:MAX_FIRST_RUN] if first_run else new
        notify(to_send)
        if first_run and len(new) > MAX_FIRST_RUN:
            print(f"[info] first run: sent {MAX_FIRST_RUN} of {len(new)}; rest marked seen")
    else:
        print("No new jobs.")
    seen.update(j["key"] for j in results)
    save_state(seen)


if __name__ == "__main__":
    main()
