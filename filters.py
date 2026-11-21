"""Location, title and experience filters."""
import re

MULTI_LOC = re.compile(r"\b\d+\s+locations?\b", re.I)


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


def slug_text(job_id):
    """Workday ids are URL paths whose slug often carries the real title ('Tech-Lead--...')."""
    sid = str(job_id or "")
    return re.sub(r"[-_/]+", " ", sid) if sid.startswith("/") else ""


def title_ok(title, cfg, extra=""):
    t = title.lower()
    return bool(re.search(cfg["include_title_regex"], t)) and not re.search(cfg["exclude_title_regex"], t + " " + extra.lower())


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
