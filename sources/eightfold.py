"""Eightfold career sites (/api/apply/v2/jobs). Descriptions come with the list when available."""
import urllib.parse

from .common import http_json, strip_html


def fetch(c):
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



