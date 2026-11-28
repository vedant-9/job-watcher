#!/usr/bin/env python3
"""Job watcher v2: polls company career-board APIs, keeps India roles in your target cities,
checks the experience requirement against your years of experience, remembers what it has
seen, and notifies you of NEW matching roles only.

Usage:
  python watcher.py --check            # test every company in config.json
  python watcher.py --dry-run          # fetch + filter + print, no notify, no state saved
  python watcher.py                    # normal run
  python watcher.py --exp "3-5 years of experience in Java"   # test the experience parser

Notifications (env vars; otherwise prints to stdout):
  Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Email:    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS, EMAIL_TO
Standard library only.
"""
import argparse
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from filters import (MULTI_LOC, classify_location, experience_verdict, parse_experience,  # noqa: F401
                     slug_text, title_ok)
from notifier import chunk, format_message, notify  # noqa: F401
from sources import FETCHERS, IMPORT_ERRORS, fetch_detail

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "seen.json"
LOG_PATH = HERE / "jobs_log.md"
STATUS_PATH = HERE / "status.md"
LOG_HEADER = "# Job openings log\n\nNewest run first. Each section lists the NEW openings found in that run.\n\n"
MAX_FIRST_RUN = 100
STATS = []
DETAILS = []   # one row per source for status.md: (name, ats, ok, listed, matched, seconds, note)


# ---------- HTTP / text helpers ----------


# ---------- Fetchers: list endpoints -> {id,title,location,url[,desc]} ----------


# ---------- Detail fetch (only for NEW, title/location-matched jobs) ----------


# ---------- Location ----------


# ---------- Title filter ----------


# ---------- Experience ----------


# ---------- State ----------
def load_state():
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else None


def save_state(seen):
    STATE_PATH.write_text(json.dumps(sorted(seen), indent=0))


# ---------- Notify ----------


# ---------- Link log (jobs_log.md) ----------
def _md_link(title, url):
    t = title.replace("[", "\\[").replace("]", "\\]")
    u = (url or "").replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return f"[{t}]({u})"


def write_log(jobs, cfg, label=None):
    """Put a new section of job links at the top of jobs_log.md (newest first)."""
    now = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %I:%M %p IST")
    groups = {0: "Pune", 1: "Hyderabad / Bengaluru / Mumbai", 2: "India, city not stated / Remote (India)", 3: "Multiple locations (check)",
              4: "Remote (verify India eligibility)"}
    order = {"fit": 0, "unknown": 1}
    lines = [f"## {now} - {label or str(len(jobs)) + ' new job(s)'}", ""]
    for rank in sorted(groups):
        grp = sorted((j for j in jobs if j["loc_rank"] == rank),
                     key=lambda j: (order.get(j["exp_label"], 2), j["company"], j["title"]))
        if not grp:
            continue
        lines += [f"### {groups[rank]} ({len(grp)})", ""]
        for j in grp:
            exp = "exp not stated" if j["exp_label"] == "unknown" else j["exp_text"]
            lines.append(f"- **{j['company']}**: {_md_link(j['title'], j['url'])} - {j['loc_label']} - {exp}")
        lines.append("")
    old = LOG_PATH.read_text() if LOG_PATH.exists() else ""
    rest = old[len(LOG_HEADER):] if old.startswith(LOG_HEADER) else old
    LOG_PATH.write_text(LOG_HEADER + "\n".join(lines) + "\n---\n\n" + rest)


IST = timezone(timedelta(hours=5, minutes=30))


def _last_run_time():
    """Time of the last committed run, read from status.md (None if unknown)."""
    try:
        text = STATUS_PATH.read_text()
        raw = re.search(r"Last run: (.+)", text).group(1).replace(" IST", "").strip()
        return datetime.strptime(raw, "%d %b %Y, %I:%M %p").replace(tzinfo=IST)
    except Exception:
        return None


def _too_soon(cfg):
    """Scheduled runs are skipped if the last run was less than min_gap_hours ago. This lets the workflow
    fire every 2 hours (GitHub drops or delays some runs) and still gives about 4 real runs a day.
    Manual runs and check/only runs are never skipped."""
    gap = cfg.get("min_gap_hours", 0)
    if not gap or os.getenv("GITHUB_EVENT_NAME") != "schedule":
        return False
    last = _last_run_time()
    if not last:
        return False
    age = datetime.now(IST) - last
    if age < timedelta(hours=gap):
        print(f"[skip] last run was {age.total_seconds() / 3600:.1f}h ago (min_gap_hours={gap}); nothing to do.")
        return True
    return False


def _heartbeat_due(cfg):
    """heartbeat: true = every quiet run, false = never, "daily" = only the first run of each IST day."""
    hb = cfg.get("heartbeat", True)
    if hb != "daily":
        return bool(hb)
    try:
        last = re.search(r"Last run: (\d{2} \w{3} \d{4})", STATUS_PATH.read_text()).group(1)
    except Exception:
        return True
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y")
    return last != today


def write_status(errors, n_new):
    """Overwrite status.md every run: proof the bot ran, plus per-source details to investigate problems."""
    now = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %I:%M %p IST")
    lines = ["# Watcher status", "", f"Last run: {now}",
             f"Sources read OK: {len(STATS)}", f"Sources failing: {len(errors)}",
             f"New matching jobs this run: {n_new}", ""]
    if errors:
        lines += ["## Failing sources", ""] + [f"- **{n}**: {str(e)[:400]}" for n, e in errors] + [""]
    if DETAILS:
        lines += ["## All sources (this run)", "", "| Company | Type | Result | Listed | Match | Secs |", "|---|---|---|---|---|---|"]
        for name, ats, ok, listed, matched, secs, _ in sorted(DETAILS, key=lambda d: (d[2], d[0].lower())):
            lines.append(f"| {name} | {ats} | {'OK' if ok else 'FAIL'} | {listed if ok else '-'} | {matched if ok else '-'} | {secs:.1f} |")
        lines.append("")
    STATUS_PATH.write_text("\n".join(lines))


# ---------- Pipeline ----------
def _read_source(c, cfg):
    """Read one company. Returns (jobs, None) or (None, error_text)."""
    fn = FETCHERS.get(c["ats"])
    if not fn:
        return None, f"source module '{c['ats']}' unavailable: {IMPORT_ERRORS.get(c['ats'], 'unknown type')}"
    try:
        return fn(c), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def collect(cfg, verbose=True):
    results, errors, secs = [], {}, {}
    todo = [c for c in cfg["companies"] if c.get("enabled", True) is not False]
    raw = {}
    for c in todo:
        t0 = time.time()
        jobs, err = _read_source(c, cfg)
        secs[c["name"]] = time.time() - t0
        if err:
            errors[c["name"]] = err
        else:
            raw[c["name"]] = jobs
    if errors:   # second pass: give throttled sources a cooldown and one more go
        print(f"[retry] {len(errors)} source(s) failed; retrying once after a short pause: {', '.join(errors)}")
        time.sleep(25)
        for c in todo:
            if c["name"] not in errors or re.match(r"HTTPError: HTTP Error 40[0-8]", errors[c["name"]]):
                continue   # permanent errors (404, 403, ...) will not change on a second try
            t0 = time.time()
            jobs, err = _read_source(c, cfg)
            secs[c["name"]] += time.time() - t0
            if err:
                errors[c["name"]] = err + " (failed on retry too)"
            else:
                del errors[c["name"]]
                raw[c["name"]] = jobs
                print(f"[retry] {c['name']}: recovered on second pass")
    for c in todo:
        name = c["name"]
        if name in errors:
            DETAILS.append((name, c["ats"], False, 0, 0, secs[name], errors[name]))
            continue
        jobs = raw[name]
        matched = [j for j in jobs if title_ok(j["title"], cfg, slug_text(j["id"])) and classify_location(j["location"], cfg)]
        STATS.append((name, len(jobs), len(matched)))
        DETAILS.append((name, c["ats"], True, len(jobs), len(matched), secs[name], ""))
        if verbose:
            print(f"[ok] {name}: {len(jobs)} total, {len(matched)} title+location match ({secs[name]:.1f}s)")
        for j in matched:
            j.update(company=name, key=f"{name}|{j['id']}", cfg=c)
            results.append(j)
    errors = list(errors.items())
    for name, err in errors:
        print(f"[error] {name}: {err}", file=sys.stderr)
    return results, errors


def evaluate(job, cfg):
    """Enrich a new job and decide keep/drop. Returns (keep: bool, reason: str)."""
    desc, extra_loc = job.get("desc"), None
    if desc is None:
        try:
            desc, extra_loc = fetch_detail(job["cfg"], job)
        except Exception as e:
            desc = ""
            print(f"[warn] detail fetch failed for {job['company']} {job['title']}: {e}", file=sys.stderr)
    if extra_loc:
        job["location"] = extra_loc
    loc = classify_location(job["location"], cfg)
    if not loc:
        return False, "location not in target"
    job["loc_rank"], job["loc_label"] = loc
    if loc[0] == 4 and not re.search(r"\bindia\b", (desc or "").lower()):
        return False, "remote role with no mention of India"
    req = parse_experience(desc or "")
    treq = parse_experience(job["title"] + " " + slug_text(job["id"]), relaxed=True)
    if treq and (req is None or treq[0] > req[0]):
        req = treq
    label, txt = experience_verdict(req, cfg)
    job["exp_label"], job["exp_text"] = label, txt
    if label == "unknown" and not cfg.get("send_unknown_experience", True):
        return False, "experience not stated"
    if label in ("too_senior", "too_junior"):
        return False, f"experience {txt}"
    if label == "unknown" and re.search(cfg.get("senior_title_regex", r"$^"), job["title"].lower()):
        return False, "senior title and experience not stated"
    if label == "unknown" and re.search(cfg.get("fresher_desc_regex", r"$^"), (desc or "").lower()):
        return False, "looks like a fresher / entry-level role"
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--exp", help="test the experience parser on a text snippet")
    ap.add_argument("--only", help="list ALL current matching jobs for one company (ignores seen.json, saves nothing)")
    args = ap.parse_args()
    cfg = json.loads(CONFIG_PATH.read_text())

    if args.exp:
        req = parse_experience(args.exp)
        print(req, experience_verdict(req, cfg))
        return
    if args.check:
        _, errors = collect(cfg)
        ok = [f"{n}: {t} listed, {m} match title+location" for n, t, m in STATS]
        bad = [f"{n}: {e[:120]}" for n, e in errors]
        msg = (f"Source check: {len(ok)} OK, {len(bad)} failing\n\nFAILING:\n" + ("\n".join(bad) or "none")
               + "\n\nOK:\n" + "\n".join(ok))
        notify(msg, "Job watcher: source check")
        return

    if args.only:
        cfg["companies"] = [c for c in cfg["companies"] if c["name"].lower() == args.only.lower()]
        if not cfg["companies"]:
            sys.exit(f"No company named {args.only!r} in config.json")
        results, errors = collect(cfg)
        keep = []
        for j in results:
            ok, reason = evaluate(j, cfg)
            if ok:
                keep.append(j)
            else:
                print(f"[skip] {j['title']} ({reason})")
        if keep:
            write_log(keep, cfg, f"{args.only}: all current openings")
        if errors:
            notify(f"{args.only}: could not read the official job board: {errors[0][1]}", "Job watcher")
        elif keep:
            notify(format_message(keep, cfg), f"{args.only}: {len(keep)} current openings")
        else:
            notify(f"{args.only}: board read OK, but no current openings match your filters.", "Job watcher")
        return

    if _too_soon(cfg):
        return
    results, errors = collect(cfg)
    seen = load_state()
    first_run = seen is None
    seen = set(seen or [])
    new = [j for j in results if j["key"] not in seen]

    keep = []
    for j in new:
        ok, reason = evaluate(j, cfg)
        if ok:
            keep.append(j)
        else:
            print(f"[skip] {j['company']}: {j['title']} ({reason})")

    if args.dry_run:
        print(format_message(keep, cfg) if keep else "No new matching jobs.")
        return

    footer = ""
    if errors:
        footer = (f"\n\n{len(errors)} source(s) failed: " + ", ".join(n for n, _ in errors)
                  + ". Details: status.md in the repo.")
    if keep:
        to_send = keep
        if first_run and len(keep) > MAX_FIRST_RUN:
            to_send = sorted(keep, key=lambda j: (j["loc_rank"], {"fit": 0, "unknown": 1}.get(j["exp_label"], 2)))[:MAX_FIRST_RUN]
            print(f"[info] first run: sent {MAX_FIRST_RUN} of {len(keep)}; rest marked seen")
        delivered = notify(format_message(to_send, cfg) + (footer if first_run else ""), f"{len(to_send)} new job openings")
        if not delivered:
            print("[error] notification FAILED. Jobs are NOT marked as seen, so the next run retries.", file=sys.stderr)
            write_status(errors, len(keep))
            sys.exit(1)
        write_log(keep, cfg)
    elif _heartbeat_due(cfg):
        notify(f"Job watcher ran OK: {len(STATS)} sources read, no new matching jobs." + footer, "Job watcher: no new jobs")
    else:
        print("No new matching jobs.")
    write_status(errors, len(keep))
    seen.update(j["key"] for j in results)
    save_state(seen)


if __name__ == "__main__":
    main()
