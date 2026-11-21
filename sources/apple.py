"""Apple: no public API, so this reads the India search pages. If Apple changes its site, fix only this file."""
import json
import re
import time
import urllib.parse

from .common import http_text, strip_html


def _apple_data(page):
    """Apple's job pages embed their data as JSON.parse("...") in window.__staticRouterHydrationData."""
    m = re.search(r'__staticRouterHydrationData\s*=\s*JSON\.parse\(("(?:[^"\\]|\\.)*")\)', page)
    if not m:
        return None
    try:
        return json.loads(json.loads(m.group(1)))
    except ValueError:
        return None


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def fetch(c):
    """Apple has no public job API. Read the server-rendered India search pages (20 jobs per page)."""
    out, seen_ids = [], set()
    for q in c.get("searches") or [c.get("search", "software engineer")]:
        for page_no in range(1, c.get("max_pages", 5) + 1):
            time.sleep(0.5)
            page = http_text("https://jobs.apple.com/en-in/search?search=" + urllib.parse.quote(q)
                             + f"&location=india-INDC&page={page_no}")
            batch = []
            data = _apple_data(page)
            if data:
                for d in _walk(data):
                    if "positionId" in d and "postingTitle" in d:
                        names = [(l.get("name") or l.get("city") or "") for l in (d.get("locations") or []) if isinstance(l, dict)]
                        batch.append({"id": str(d["positionId"]), "title": d["postingTitle"],
                                      "location": " ; ".join(f"{n}, India" for n in names if n) or "India",
                                      "url": f"https://jobs.apple.com/en-in/details/{d['positionId']}/{d.get('transformedPostingTitle', '')}"})
            if not batch:   # fallback: read the job links straight from the page
                for m in re.finditer(r'href="/en-in/details/(\d+(?:-\d+)?)/([^"?/]+)', page):
                    batch.append({"id": m.group(1), "title": m.group(2).replace("-", " ").title(),
                                  "location": "India",
                                  "url": f"https://jobs.apple.com/en-in/details/{m.group(1)}/{m.group(2)}"})
            new = [j for j in batch if j["id"] not in seen_ids]
            if not new:
                break
            for j in new:
                seen_ids.add(j["id"])
                out.append(j)
    return out


def detail(c, job):
    parts = []
    data = _apple_data(http_text(job["url"]))
    for d in _walk(data or {}):
        for k in ("jobSummary", "description", "minimumQualifications"):
            if isinstance(d.get(k), str):
                parts.append(d[k])
    return strip_html("\n".join(parts)), None
