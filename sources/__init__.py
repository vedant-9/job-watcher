"""Job sources. Each module here reads one kind of career site and defines:

    fetch(c)          -> list of {id, title, location, url[, desc]}
    detail(c, job)    -> (description_text, location_text_or_None)     (optional)

If one module breaks (or fails to import), only the companies that use it are reported as failing.
To add a new kind of site: create <name>.py here and add its name to NAMES below.
"""
import importlib

NAMES = ["greenhouse", "lever", "ashby", "workday", "eightfold", "smartrecruiters", "atlassian", "apple"]

_MODULES, IMPORT_ERRORS = {}, {}
for _n in NAMES:
    try:
        _MODULES[_n] = importlib.import_module(f"{__name__}.{_n}")
    except Exception as _e:   # a broken source module must not take the others down
        IMPORT_ERRORS[_n] = f"{type(_e).__name__}: {_e}"

FETCHERS = {n: m.fetch for n, m in _MODULES.items()}


def fetch_detail(c, job):
    """Return (description_text, location_text_or_None) for one job."""
    fn = getattr(_MODULES.get(c["ats"]), "detail", None)
    return fn(c, job) if fn else ("", None)
