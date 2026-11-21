"""Lever job boards (api.lever.co). Descriptions come with the list, so there is no detail step."""
from .common import http_json, strip_html


def fetch(c):
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



