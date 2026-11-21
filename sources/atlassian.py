"""Atlassian's public listings feed. Descriptions come with the list, so there is no detail step."""
from .common import http_json, strip_html


def fetch(c):
    """Atlassian publishes all its listings as one public JSON feed (descriptions included)."""
    d = http_json("https://www.atlassian.com/endpoint/careers/listings")
    out = []
    for j in d:
        locs = j.get("locations") or []
        desc = strip_html("\n".join(str(j.get(k) or "") for k in ("overview", "responsibilities", "qualifications")))
        out.append({"id": str(j["id"]), "title": j.get("title", ""), "location": " ; ".join(locs),
                    "url": f"https://www.atlassian.com/company/careers/details/{j['id']}", "desc": desc})
    return out



