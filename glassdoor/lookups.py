"""Network lookups behind the resolvers in refs.py: a company name -> its
employer id, a place name -> a Glassdoor location, a job title -> its
Glassdoor title id. Each answer is
memoized in-process (fetch.memoized) for an hour."""
import re

from glassdoor import fetch
from glassdoor import refs

EMPLOYER_AC = "/autocomplete/employers"
JOB_TITLE_AC = "/autocomplete/jobTitle"
LOCATION_AC = "/autocomplete/location"
LOCATION_AC_TYPES = "CITY,STATE,COUNTRY"   # METRO is rejected with a 400


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def employer_suggestions(term):
    rows = fetch.memoized(("employers", _norm(term)),
                          lambda: fetch.get_json(EMPLOYER_AC, {"term": term}, label="company autocomplete"))
    return rows if isinstance(rows, list) else []


def _search_candidates(name):
    """Company search (ranked by relevance, carries review counts)."""
    from glassdoor import queries as Q
    body = {"employerName": name, "employerSearchRangeFilters": [], "industries": [], "sectors": [], "jobTitle": "",
            "location": None, "pageRequested": 1, "sGocIds": []}

    def build():
        data = fetch.graph(Q.EMPLOYER_RESOLVE, {"input": body}, label="company lookup", client="company-explorer")
        rows = ((data.get("employerSearchRG") or {}).get("employerResults")) or []
        out = []
        for row in rows:
            employer = (row or {}).get("employer") or {}
            if employer.get("id"):
                out.append({"id": int(employer["id"]), "names": (employer.get("shortName"), employer.get("name")),
                            "reviews": ((employer.get("counts") or {}).get("reviewCount")) or 0,
                            "row": {"id": employer["id"], "shortName": employer.get("shortName"),
                                    "name": employer.get("name"), "logoURL": employer.get("squareLogoUrl"),
                                    "websiteURL": employer.get("website")}})
        return out
    return fetch.memoized(("employer_search", _norm(name)), build)


def exact_matches(name):
    """Company-search rows whose name equals `name` (autocomplete-shaped),
    most-reviewed first."""
    wanted = _norm(name)
    try:
        rows = _search_candidates(name)
    except fetch.GlassdoorUpstreamError:
        return []
    rows = [c for c in rows if wanted in {_norm(n) for n in c["names"] if n}]
    return [c["row"] for c in sorted(rows, key=lambda c: -c["reviews"])]


def company_id(company):
    """refs.resolve_company output -> employer id. A name resolves over the
    company search AND the autocomplete (the autocomplete alone misses big
    names: "google" lists Google Cloud but not Google): an exact
    (case-insensitive) name match wins, the most-reviewed among several;
    otherwise the most-reviewed search hit, then the first suggestion."""
    if isinstance(company, int):
        return company
    name = (company or {}).get("name") or ""
    wanted = _norm(name)
    candidates = []
    try:
        candidates = _search_candidates(name)
    except fetch.GlassdoorUpstreamError:
        pass
    try:
        suggestions = employer_suggestions(name)
    except fetch.GlassdoorUpstreamError:
        if not candidates:
            raise
        suggestions = []
    for row in suggestions:
        if isinstance(row, dict) and row.get("id") and all(c["id"] != int(row["id"]) for c in candidates):
            candidates.append({"id": int(row["id"]), "names": (row.get("shortName"), row.get("name"), row.get("label")),
                               "reviews": 0})
    if not candidates:
        raise fetch.GlassdoorNotFound(f"no Glassdoor company matches '{name}'")
    exact = [c for c in candidates if wanted in {_norm(n) for n in c["names"] if n}]
    pool = exact or [c for c in candidates if c["reviews"]] or candidates
    return max(pool, key=lambda c: c["reviews"])["id"]


def job_title_suggestions(term):
    rows = fetch.memoized(("job_titles", _norm(term)),
                          lambda: fetch.get_json(JOB_TITLE_AC, {"term": term}, label="job title autocomplete"))
    return rows if isinstance(rows, list) else []


def job_title(term):
    """Free-text title -> {"id", "text"} of the matching Glassdoor title
    (exact match, else the top suggestion)."""
    rows = [r for r in job_title_suggestions(term) if isinstance(r, dict) and r.get("id")]
    if not rows:
        raise fetch.GlassdoorNotFound(f"no Glassdoor job title matches '{term}'")
    wanted = _norm(term)
    best = next((r for r in rows if _norm(r.get("jobTitle") or r.get("label")) == wanted), rows[0])
    return {"id": int(best["id"]), "text": best.get("jobTitle") or best.get("label")}


def location_suggestions(term, types=LOCATION_AC_TYPES, limit=10):
    key = ("locations", _norm(term), types, limit)
    rows = fetch.memoized(key, lambda: fetch.get_json(
        LOCATION_AC, {"locationTypeFilters": types, "maxLocationsToReturn": limit, "term": term},
        label="location autocomplete"))
    return rows if isinstance(rows, list) else []


def location(ref):
    """refs.resolve_location output (or None) -> {"type", "id", "name"} or None."""
    if not ref:
        return None
    if "id" in ref:
        return {"type": ref["type"], "id": int(ref["id"]), "name": None}
    rows = [r for r in location_suggestions(ref["query"]) if isinstance(r, dict) and r.get("locationId")]
    if not rows:
        raise fetch.GlassdoorNotFound(f"no Glassdoor location matches '{ref['query']}'")
    row = rows[0]
    return {"type": refs.LOCATION_TYPES.get(row.get("locationType"), "city"), "id": int(row["locationId"]),
            "name": row.get("longName") or row.get("label")}


# ---- request-shape adapters -----------------------------------------------------------------

_ID_KEYS = {"city": "cityId", "state": "stateId", "metro": "metroId", "country": "countryId"}
_LETTERS = {"city": "C", "state": "S", "metro": "M", "country": "N"}
_WORDS = {"city": "CITY", "state": "STATE", "metro": "METRO", "country": "COUNTRY"}


def location_ids(loc):
    """-> {"cityId": 1132348} (BFF / aggregatedSalaryEstimates shape); {} for none."""
    return {_ID_KEYS[loc["type"]]: loc["id"]} if loc else {}


def location_letter(loc):
    return _LETTERS.get(loc["type"]) if loc else None


def location_word(loc):
    return _WORDS.get(loc["type"]) if loc else None
