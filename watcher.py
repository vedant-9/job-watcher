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

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "seen.json"
LOG_PATH = HERE / "jobs_log.md"
STATUS_PATH = HERE / "status.md"
LOG_HEADER = "# Job openings log\n\nNewest run first. Each section lists the NEW openings found in that run.\n\n"
UA = "Mozilla/5.0 (job-watcher personal script)"
MAX_FIRST_RUN = 100
MULTI_LOC = re.compile(r"\b\d+\s+locations?\b", re.I)
STATS = []


# ---------- HTTP / text helpers ----------
def http_json(url, data=None, timeout=25, tries=4):
    """GET/POST JSON. Retries with backoff on empty/non-JSON replies, 429 and 5xx (Workday throttles bursts)."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"), strict=False)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ValueError) as e:   # ValueError covers bad JSON
            last = e
        if attempt < tries - 1:
            time.sleep(3 * (attempt + 1))
    raise last


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<(br|/p|/li|/div|/h\d|/ul)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s)


# ---------- Fetchers: list endpoints -> {id,title,location,url[,desc]} ----------
def _gh_host(c):
    return "boards-api.eu.greenhouse.io" if c.get("eu") else "boards-api.greenhouse.io"


def fetch_greenhouse(c):
    d = http_json(f"https://{_gh_host(c)}/v1/boards/{c['slug']}/jobs")
    return [{"id": str(j["id"]), "title": j.get("title", ""),
             "location": (j.get("location") or {}).get("name", ""),
             "url": j.get("absolute_url", "")} for j in d.get("jobs", [])]


def fetch_lever(c):
    d = http_json(f"https://api.lever.co/v0/postings/{c['slug']}?mode=json")
    out = []
    for j in d:
        parts = [j.get("descriptionPlain", ""), j.get("additionalPlain", "")]
        for lst in j.get("lists", []) or []:
            parts.append(lst.get("text", ""))
            parts.append(strip_html(lst.get("content", "")))
        out.append({"id": j["id"], "title": j.get("text", ""),
                    "location": " ; ".join(x for x in [(j.get("categories") or {}).get("location", "") or ""] + list((j.get("categories") or {}).get("allLocations", []) or []) if x),
                    "url": j.get("hostedUrl", ""), "desc": "\n".join(parts)})
    return out


def fetch_ashby(c):
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{c['slug']}")
    out = []
    for j in d.get("jobs", []):
        locs = [j.get("location", "") or ""]
        locs += [(s.get("location") if isinstance(s, dict) else str(s)) or ""
                 for s in j.get("secondaryLocations", []) or []]
        desc = j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", ""))
        out.append({"id": j["id"], "title": j.get("title", ""),
                    "location": " ; ".join(x for x in locs if x),
                    "url": j.get("jobUrl", ""), "desc": desc})
    return out


WD_CITIES = ["Pune", "Hyderabad", "Bengaluru", "Mumbai"]


def fetch_workday(c):
    """Workday search returns results by relevance and we only page through the first N, so big
    companies hide India roles. We therefore also search '<query> <city>' for each target city."""
    host, tenant, site = c["host"], c["tenant"], c["site"]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    base = c.get("search", "software engineer")
    searches = c.get("searches") or [base] + [f"{base} {city}" for city in WD_CITIES]
    out, seen_ids, limit = [], set(), 20
    for q in searches:
        offset = 0
        while offset < c.get("max_results", 80):
            time.sleep(0.4)   # be gentle: Workday throttles bursts
            d = http_json(api, {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": q})
            posts = d.get("jobPostings", [])
            if not posts:
                break
            for j in posts:
                path = j.get("externalPath", "")
                if path in seen_ids:
                    continue
                seen_ids.add(path)
                out.append({"id": path, "title": j.get("title", ""),
                            "location": j.get("locationsText", "") or "",
                            "url": f"https://{host}/en-US/{site}{path}"})
            offset += limit
            if len(posts) < limit:
                break
    return out


def fetch_eightfold(c):
    """Eightfold career sites (e.g. Amdocs): public /api/apply/v2/jobs endpoint."""
    host = c.get("host", "app.eightfold.ai")
    q = urllib.parse.quote(c.get("search", "software engineer"))
    loc = urllib.parse.quote(c.get("location", "India"))
    out, start, step = [], 0, 25
    while start < c.get("max_results", 100):
        d = http_json(f"https://{host}/api/apply/v2/jobs?domain={c['domain']}&start={start}&num={step}&query={q}&location={loc}")
        pos = d.get("positions", [])
        if not pos:
            break
        for j in pos:
            locs = j.get("locations") or [j.get("location", "")]
            job = {"id": str(j.get("id")), "title": j.get("name", ""),
                   "location": " ; ".join(x for x in locs if x),
                   "url": j.get("canonicalPositionUrl") or f"https://{host}/careers/job/{j.get('id')}?domain={c['domain']}"}
            if j.get("job_description"):
                job["desc"] = strip_html(j["job_description"])
            out.append(job)
        start += step
        if len(pos) < step:
            break
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever,
            "ashby": fetch_ashby, "workday": fetch_workday, "eightfold": fetch_eightfold}


# ---------- Detail fetch (only for NEW, title/location-matched jobs) ----------
def fetch_detail(c, job):
    """Return (description_text, location_text_or_None)."""
    if c["ats"] == "greenhouse":
        d = http_json(f"https://{_gh_host(c)}/v1/boards/{c['slug']}/jobs/{job['id']}")
        return strip_html(d.get("content", "")), None
    if c["ats"] == "workday":
        d = http_json(f"https://{c['host']}/wday/cxs/{c['tenant']}/{c['site']}{job['id']}")
        info = d.get("jobPostingInfo", {})
        locs = [info.get("location", "")] + list(info.get("additionalLocations", []) or [])
        locs.append((info.get("country") or {}).get("descriptor", ""))
        return strip_html(info.get("jobDescription", "")), " ; ".join(x for x in locs if x)
    return "", None


# ---------- Location ----------
def classify_location(loc, cfg):
    """Return (rank, label) or None. 0=preferred city, 1=acceptable city, 2=India generic, 3=multi."""
    s = (loc or "").lower()
    found, rank = [], 1
    for city in cfg["preferred_locations"] + cfg["acceptable_locations"]:
        if city in s:
            name = "Bengaluru" if city in ("bangalore", "bengaluru") else city.title()
            if name not in found:
                found.append(name)
            if city in cfg["preferred_locations"]:
                rank = 0
    if "Navi Mumbai" in found and "Mumbai" in found:
        found.remove("Mumbai")
    if found:
        return rank, " / ".join(found)
    if cfg.get("allow_generic_india", True) and re.search(r"\bindia\b", s):
        if not any(c in s for c in cfg["other_india_cities"]):
            return 2, ("Remote (India)" if "remote" in s else "India (city not stated)")
    if MULTI_LOC.search(s):
        return 3, "Multiple locations (check)"
    if cfg.get("include_remote", True) and re.search(r"\bremote\b|\banywhere\b|\bwork from home\b", s):
        return 4, "Remote (verify India eligibility)"
    return None


# ---------- Title filter ----------
def slug_text(job_id):
    """Workday ids are URL paths whose slug often carries the real title ('Tech-Lead--...')."""
    sid = str(job_id or "")
    return re.sub(r"[-_/]+", " ", sid) if sid.startswith("/") else ""


def title_ok(title, cfg, extra=""):
    t = title.lower()
    return bool(re.search(cfg["include_title_regex"], t)) and not re.search(cfg["exclude_title_regex"], t + " " + extra.lower())


# ---------- Experience ----------
_RANGE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:-|–|—|to)\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\b", re.I)
_SINGLE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(\+|plus|or more|and above|and more)?\s*(?:years?|yrs?)\b", re.I)
_EXP_WORD = re.compile(r"experience|exp\b|professional|hands[- ]on|working in|background", re.I)
_SOFT = re.compile(r"prefer|bonus|nice to have|desirable|good to have|a plus|is a plus|ideal", re.I)
_BOILER = re.compile(r"our company|our team|we have|we've|founded|since \d{4}|combined|years of history|in business", re.I)


def parse_experience(text, relaxed=False):
    """Return (min_years, max_years_or_None) for the dominant requirement, or None if unclear."""
    found, spans = [], []
    for m in _RANGE.finditer(text):
        found.append((m, float(m.group(1)), float(m.group(2))))
        spans.append(m.span())
    for m in _SINGLE.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        found.append((m, float(m.group(1)), None))
    reqs = []
    for m, lo, hi in found:
        if lo > 20 or (hi is not None and (hi > 25 or hi < lo)):
            continue
        before = text[max(0, m.start() - 70):m.start()]
        after = text[m.end():m.end() + 70]
        if not relaxed:
            if not _EXP_WORD.search(before + " " + after):
                continue
            sent_before = re.split(r"[.\n;]", before)[-1]   # same sentence only
            sent_after = re.split(r"[.\n;]", after)[0]
            if _SOFT.search(sent_before + " " + sent_after) or _BOILER.search(before + after):
                continue
        reqs.append((lo, hi))
    if not reqs:
        return None
    return max(reqs, key=lambda r: r[0])  # strictest minimum


def experience_verdict(req, cfg):
    """Return (label, text); label in fit|stretch|unknown|too_senior|too_junior."""
    me = cfg["my_years"]
    if req is None:
        return "unknown", "not stated"
    lo, hi = req
    txt = f"{lo:g}-{hi:g} yrs" if hi is not None else f"{lo:g}+ yrs"
    if lo < cfg.get("min_required_years", 2) or (hi is not None and hi < me - 0.5):
        return "too_junior", txt
    if lo <= me + cfg.get("fit_slack", 0.5):
        return "fit", txt
    if lo <= me + cfg.get("stretch_years", 0):
        return "stretch", txt
    return "too_senior", txt


# ---------- State ----------
def load_state():
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else None


def save_state(seen):
    STATE_PATH.write_text(json.dumps(sorted(seen), indent=0))


# ---------- Notify ----------
VERDICT_ICON = {"fit": "OK fits", "stretch": "STRETCH", "unknown": "exp not stated"}


def format_message(jobs, cfg):
    order = {"fit": 0, "unknown": 1, "stretch": 2}
    jobs = sorted(jobs, key=lambda j: (j["loc_rank"], order.get(j["exp_label"], 3), j["company"]))
    lines = [f"{len(jobs)} new job(s) (your exp: {cfg['my_years']:g} yrs):", ""]
    for j in jobs:
        lines.append(f"[{j['loc_label']}] {j['company']}: {j['title']}")
        lines.append(f"  Exp: {j['exp_text']} -> {VERDICT_ICON.get(j['exp_label'], j['exp_label'])}")
        lines.append(f"  {j['url']}")
        lines.append("")
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
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT") or "587")) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    return True


def notify(text, subject="Job watcher"):
    sent = False
    try:
        sent = send_telegram(text) or sent
    except Exception as e:
        print(f"[warn] telegram failed: {e}", file=sys.stderr)
    try:
        sent = send_email(subject, text) or sent
    except Exception as e:
        print(f"[warn] email failed: {e}", file=sys.stderr)
    if not sent:
        print(text)


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


def write_status(errors, n_new):
    """Overwrite status.md every run, so there is always proof the bot ran (and it keeps the repo active)."""
    now = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %I:%M %p IST")
    lines = ["# Watcher status", "", f"Last run: {now}",
             f"Sources read OK: {len(STATS)}", f"Sources failing: {len(errors)}",
             f"New matching jobs this run: {n_new}", ""]
    if errors:
        lines += ["Failing sources:"] + [f"- {n}: {str(e)[:100]}" for n, e in errors] + [""]
    STATUS_PATH.write_text("\n".join(lines))


# ---------- Pipeline ----------
def collect(cfg, verbose=True):
    results, errors = [], []
    for c in cfg["companies"]:
        if c.get("enabled", True) is False:
            continue
        fn = FETCHERS.get(c["ats"])
        if not fn:
            errors.append((c["name"], f"unknown ats {c['ats']}"))
            continue
        try:
            jobs = fn(c)
        except Exception as e:
            errors.append((c["name"], str(e)))
            continue
        matched = [j for j in jobs if title_ok(j["title"], cfg, slug_text(j["id"])) and classify_location(j["location"], cfg)]
        STATS.append((c["name"], len(jobs), len(matched)))
        if verbose:
            print(f"[ok] {c['name']}: {len(jobs)} total, {len(matched)} title+location match")
        for j in matched:
            j.update(company=c["name"], key=f"{c['name']}|{j['id']}", cfg=c)
            results.append(j)
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
        footer = ("\n\nSources that failed (fix the board name in config.json or "
                  "disable with \"enabled\": false):\n" + "\n".join(f"- {n}: {str(e)[:90]}" for n, e in errors))
    if keep:
        write_log(keep, cfg)
        to_send = keep
        if first_run and len(keep) > MAX_FIRST_RUN:
            to_send = sorted(keep, key=lambda j: (j["loc_rank"], {"fit": 0, "unknown": 1}.get(j["exp_label"], 2)))[:MAX_FIRST_RUN]
            print(f"[info] first run: sent {MAX_FIRST_RUN} of {len(keep)}; rest marked seen")
        notify(format_message(to_send, cfg) + (footer if first_run else ""), f"{len(to_send)} new job openings")
    elif cfg.get("heartbeat", True):
        notify(f"Job watcher ran OK: {len(STATS)} sources read, no new matching jobs." + footer, "Job watcher: no new jobs")
    else:
        print("No new matching jobs.")
    write_status(errors, len(keep))
    seen.update(j["key"] for j in results)
    save_state(seen)


if __name__ == "__main__":
    main()
