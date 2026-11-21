"""Shared HTTP helpers for all sources."""
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (job-watcher personal script)"


_last_hit = {}          # host -> time of last request (polite pacing per host)
MIN_GAP = 0.6           # seconds between requests to the same host


class BadReply(ValueError):
    """The server answered, but not with usable JSON (empty body, HTML block page, ...)."""


def _pace(url):
    host = urllib.parse.urlparse(url).netloc
    wait = _last_hit.get(host, 0) + MIN_GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


def _snip(raw):
    return re.sub(r"\s+", " ", raw[:90].decode("utf-8", "replace")).strip()


def _request(url, headers, body, timeout, tries, as_json):
    """Shared GET/POST with pacing, retries and a diagnosis of the last failure."""
    host = urllib.parse.urlparse(url).netloc
    last, why = None, ""
    for attempt in range(tries):
        _pace(url)
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                status, ctype = r.status, r.headers.get("Content-Type", "?")
            text = raw.decode("utf-8", "replace")
            if not as_json:
                return text
            try:
                return json.loads(text, strict=False)
            except ValueError:
                why = (f"HTTP {status}, {ctype.split(';')[0]}, {len(raw)} bytes"
                       + (", empty body" if not raw.strip() else f", starts: {_snip(raw)!r}"))
                last = BadReply(f"bad reply from {host} ({why}); {attempt + 1} tries")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            why = f"HTTP {e.code}"
            last = urllib.error.HTTPError(url, e.code, f"HTTP {e.code} from {host}; {attempt + 1} tries", e.headers, None)
        except (urllib.error.URLError, TimeoutError) as e:
            why = type(e).__name__
            last = type(e)(f"{e} (host {host}); {attempt + 1} tries") if isinstance(e, TimeoutError) else e
        if attempt < tries - 1:
            time.sleep(4 * 2 ** attempt)          # 4s, 8s, 16s: empty replies are usually throttling
    if isinstance(last, BadReply):
        last = BadReply(f"bad reply from {host} ({why}); gave up after {tries} tries")
    raise last


def http_json(url, data=None, timeout=25, tries=4):
    """GET/POST JSON. Paced per host; retries with backoff on empty/non-JSON replies, 429 and 5xx."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    return _request(url, headers, body, timeout, tries, True)


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<(br|/p|/li|/div|/h\d|/ul)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s)


def http_text(url, timeout=25, tries=4):
    """GET a web page as text, with the same pacing/retry/diagnosis as http_json."""
    return _request(url, {"User-Agent": UA, "Accept": "text/html"}, None, timeout, tries, False)
