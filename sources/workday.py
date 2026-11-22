"""Workday career sites (POST /wday/cxs/<tenant>/<site>/jobs)."""
import time

from .common import http_json, strip_html


WD_CITIES = ["Pune", "Hyderabad", "Bengaluru", "Mumbai"]


def fetch(c):
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
    if not out:
        # A real big-company board is never empty; this usually means a wrong site name or search text.
        raise RuntimeError(f"Workday answered but returned 0 postings for all {len(searches)} searches "
                           f"(site '{site}' on {host}); check the site name in the career-page URL")
    return out


def detail(c, job):
    d = http_json(f"https://{c['host']}/wday/cxs/{c['tenant']}/{c['site']}{job['id']}")
    info = d.get("jobPostingInfo", {})
    locs = [info.get("location", "")] + list(info.get("additionalLocations", []) or [])
    locs.append((info.get("country") or {}).get("descriptor", ""))
    return strip_html(info.get("jobDescription", "")), " ; ".join(x for x in locs if x)
