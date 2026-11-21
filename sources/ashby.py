"""Ashby job boards (api.ashbyhq.com). Descriptions come with the list, so there is no detail step."""
from .common import http_json, strip_html


def fetch(c):
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



