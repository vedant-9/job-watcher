"""SmartRecruiters public posting API (api.smartrecruiters.com)."""
from .common import http_json, strip_html


def fetch(c):
    """SmartRecruiters public posting API (e.g. Arista): /v1/companies/<slug>/postings."""
    out, off = [], 0
    while off < c.get("max_results", 300):
        d = http_json(f"https://api.smartrecruiters.com/v1/companies/{c['slug']}/postings?limit=100&offset={off}&country={c.get('country', 'in')}")
        items = d.get("content", [])
        if not items:
            break
        for j in items:
            loc = j.get("location") or {}
            country = "India" if str(loc.get("country", "")).lower() == "in" else loc.get("country", "")
            text = " ".join(x for x in [loc.get("city"), loc.get("region"), country] if x)
            if loc.get("remote"):
                text += " Remote"
            out.append({"id": str(j["id"]), "title": j.get("name", ""), "location": text,
                        "url": f"https://jobs.smartrecruiters.com/{c['slug']}/{j['id']}"})
        off += 100
        if len(items) < 100:
            break
    return out


def detail(c, job):
    d = http_json(f"https://api.smartrecruiters.com/v1/companies/{c['slug']}/postings/{job['id']}")
    secs = (d.get("jobAd") or {}).get("sections") or {}
    return strip_html("\n".join((secs.get(k) or {}).get("text", "") for k in
                      ("jobDescription", "qualifications", "additionalInformation"))), None
