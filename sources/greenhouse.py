"""Greenhouse job boards (boards-api.greenhouse.io; set "eu": true for the EU server)."""
from .common import http_json, strip_html


def _gh_host(c):
    return "boards-api.eu.greenhouse.io" if c.get("eu") else "boards-api.greenhouse.io"


def fetch(c):
    d = http_json(f"https://{_gh_host(c)}/v1/boards/{c['slug']}/jobs")
    return [{"id": str(j["id"]), "title": j.get("title", ""),
             "location": (j.get("location") or {}).get("name", ""),
             "url": j.get("absolute_url", "")} for j in d.get("jobs", [])]


def detail(c, job):
    d = http_json(f"https://{_gh_host(c)}/v1/boards/{c['slug']}/jobs/{job['id']}")
    return strip_html(d.get("content", "")), None
