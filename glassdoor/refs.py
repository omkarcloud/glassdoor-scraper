"""Glassdoor input parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrIdField convention — never a sibling `url` / `id`
pair). Resolvers are pure (no network) and return plain JSON values, so the
validated params stay usable as a response-cache key; a name that needs a
lookup is returned as {"name": ...} / {"query": ...} and resolved by the
endpoint (glassdoor/lookups.py).

  company   9079 | https://www.glassdoor.com/Reviews/Google-Reviews-E9079.htm
            | …/Overview/Working-at-Google-EI_IE9079.11,17.htm | any Glassdoor
            page of the company (-E<id>, _E<id>, EI_IE<id>) on any TLD
            | Google (a name -> the best autocomplete match)
            -> 9079 | {"name": "Google"}
  job       1010259346403 | …/job-listing/…-JV_…_KE….htm?jl=1010259346403
            | any link carrying jl= / jobListingId=  -> 1010259346403
  location  IC1132348 / IS428 / IM615 / IN1 (Glassdoor's own city / state /
            metro / country tokens, as /glassdoor/locations/autocomplete
            returns them) | a Glassdoor search link carrying one
            | New York (a place name)
            -> {"type": "city", "id": 1132348} | {"query": "New York"}
  country   US | us | United States -> 1 (Glassdoor's country id)
  industry  10013 | Information Technology (a sector) | 200063 | Internet &
            Web Services (an industry) -> {"sector": 10013} | {"industry": 200063}
  job_function  1007 | Engineering -> 1007
  bowl      technology | 55375ce690f5eebe1d2a0f88 | …/Community/technology
            -> "technology" | "55375ce690f5eebe1d2a0f88"
  post      6aa2bc4e05d31bb5a9cbecff | …/Community/<bowl>/<post-handle>
            | <post-handle> -> the id or handle
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

from glassdoor import refdata

SITE = "https://www.glassdoor.com"

_EMPLOYER_RE = re.compile(r"(?:EI_IE|[-_]IE|[-_]E)(\d{1,10})(?=[._,\-]|$)")
_LOCATION_TOKEN_RE = re.compile(r"^I([CSMN])(\d{1,10})$", re.I)
_LOCATION_IN_URL_RE = re.compile(r"_I([CSMN])(\d{1,10})(?=[._,\-]|$)")
_JOB_ID_RE = re.compile(r"^\d{6,20}$")
_MONGO_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,199}$")

LOCATION_TYPES = {"C": "city", "S": "state", "M": "metro", "N": "country"}
LOCATION_TOKENS = {name: letter for letter, name in LOCATION_TYPES.items()}

COMPANY_HINT = "Must be a Glassdoor company id (9079), a Glassdoor company link or a company name."
JOB_HINT = "Must be a Glassdoor job listing id (1010259346403) or a job link carrying jl=<id>."
LOCATION_HINT = ("Must be a place name (New York), a Glassdoor location id from "
                 "/glassdoor/locations/autocomplete (IC1132348) or a Glassdoor search link.")


def _is_link(value):
    low = value.lower()
    return low.startswith(("http://", "https://", "//", "www.glassdoor.", "glassdoor."))


def _parse_link(value):
    url = value if "://" in value else "https://" + value.lstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "glassdoor" not in host.split("."):
        raise ValueError("Must be a glassdoor.com link (any Glassdoor country site works).")
    return parsed


# ---- companies ------------------------------------------------------------------------

def resolve_company(value):
    """-> int employer id, or {"name": text} for a name to look up."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError(COMPANY_HINT)
    if raw.isdigit():
        employer_id = int(raw)
        if employer_id <= 0:
            raise ValueError(COMPANY_HINT)
        return employer_id
    if _is_link(raw):
        parsed = _parse_link(raw)
        match = _EMPLOYER_RE.search(unquote(parsed.path))
        if match:
            return int(match.group(1))
        raise ValueError("That Glassdoor link names no company (company links contain -E<id> or EI_IE<id>).")
    if len(raw) > 120:
        raise ValueError("Company names are at most 120 characters.")
    return {"name": " ".join(raw.split())}


def resolve_companies(value, min_items=2, max_items=5):
    """'9079, Microsoft,https://…-E1138.htm' -> [9079, {"name": "Microsoft"}, 1138]."""
    out = []
    for item in re.split(r"[,\n]", value or ""):
        item = item.strip()
        if not item:
            continue
        ref = resolve_company(item)
        if ref not in out:
            out.append(ref)
    if len(out) < min_items:
        raise ValueError(f"List at least {min_items} companies, comma-separated (ids, links or names).")
    if len(out) > max_items:
        raise ValueError(f"At most {max_items} companies.")
    return out


# ---- jobs --------------------------------------------------------------------------------

def resolve_job(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError(JOB_HINT)
    if _JOB_ID_RE.match(raw):
        return int(raw)
    if _is_link(raw):
        parsed = _parse_link(raw)
        query = parse_qs(parsed.query)
        for key in ("jl", "jobListingId"):
            candidate = (query.get(key) or [""])[0]
            if _JOB_ID_RE.match(candidate):
                return int(candidate)
        match = re.search(r"-(\d{10,20})\.htm$", parsed.path)
        if match:
            return int(match.group(1))
    raise ValueError(JOB_HINT)


# ---- locations ---------------------------------------------------------------------------

def location_token(kind, location_id):
    """("city", 1132348) -> "IC1132348"."""
    letter = LOCATION_TOKENS.get(kind)
    return f"I{letter}{location_id}" if letter and location_id else None


def resolve_location(value):
    """-> {"type": "city"|"state"|"metro"|"country", "id": int} or {"query": text}."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError(LOCATION_HINT)
    match = _LOCATION_TOKEN_RE.match(raw)
    if match:
        return {"type": LOCATION_TYPES[match.group(1).upper()], "id": int(match.group(2))}
    if _is_link(raw):
        parsed = _parse_link(raw)
        found = _LOCATION_IN_URL_RE.findall(unquote(parsed.path))
        if found:
            # the most specific token wins (a city link also carries its country)
            order = {"C": 0, "M": 1, "S": 2, "N": 3}
            letter, loc_id = sorted(found, key=lambda f: order[f[0].upper()])[0]
            return {"type": LOCATION_TYPES[letter.upper()], "id": int(loc_id)}
        raise ValueError("That Glassdoor link carries no location (_IC<id>, _IS<id>, _IM<id> or _IN<id>).")
    if len(raw) > 100:
        raise ValueError("Location names are at most 100 characters.")
    return {"query": " ".join(raw.split())}


# ---- countries / industries / job functions -----------------------------------------------

def _key(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower().replace("&", " and ")).strip()


_COUNTRY_ALIASES = {"uk": "GB", "great britain": "GB", "england": "GB", "usa": "US", "america": "US",
                    "united states of america": "US", "korea": "KR", "uae": "AE", "holland": "NL"}


def resolve_country(value):
    """ISO alpha-2 or English name -> Glassdoor country id."""
    raw = (value or "").strip()
    iso = raw.upper()
    if iso in refdata.COUNTRIES:
        return refdata.COUNTRIES[iso][0]
    key = _key(raw)
    if key in _COUNTRY_ALIASES:
        return refdata.COUNTRIES[_COUNTRY_ALIASES[key]][0]
    for code, (country_id, name) in refdata.COUNTRIES.items():
        if _key(name) == key:
            return country_id
    raise ValueError(f"'{value}' is not a country Glassdoor serves (use an ISO code like US, GB, IN, DE).")


def country_iso(country_id):
    for code, (cid, _) in refdata.COUNTRIES.items():
        if cid == country_id:
            return code
    return None


def resolve_industry(value):
    """A sector or industry by id or name -> {"sector": id} | {"industry": id}."""
    raw = (value or "").strip()
    if raw.isdigit():
        num = int(raw)
        if num in refdata.SECTORS:
            return {"sector": num}
        if num in refdata.INDUSTRIES:
            return {"industry": num}
    key = _key(raw)
    for sector_id, name in refdata.SECTORS.items():
        if _key(name) == key:
            return {"sector": sector_id}
    for industry_id, (name, _) in refdata.INDUSTRIES.items():
        if _key(name) == key:
            return {"industry": industry_id}
    raise ValueError(f"'{value}' is not a Glassdoor sector or industry (see /glassdoor/industries).")


def resolve_job_function(value):
    raw = (value or "").strip()
    if raw.isdigit() and int(raw) in refdata.JOB_FUNCTIONS:
        return int(raw)
    key = _key(raw)
    for function_id, name in refdata.JOB_FUNCTIONS.items():
        if _key(name) == key:
            return function_id
    names = ", ".join(refdata.JOB_FUNCTIONS.values())
    raise ValueError(f"'{value}' is not a Glassdoor job function ({names}).")


# ---- community --------------------------------------------------------------------------------

def _community_parts(raw):
    parsed = _parse_link(raw)
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts or parts[0].lower() != "community" or len(parts) < 2:
        raise ValueError("Community links look like glassdoor.com/Community/<bowl>[/<post>].")
    return parts[1:]


def resolve_bowl(value):
    raw = (value or "").strip()
    if _is_link(raw):
        parts = _community_parts(raw)
        raw = parts[0]
    low = raw.lower()
    if _MONGO_ID_RE.match(low) or _HANDLE_RE.match(low):
        return low
    raise ValueError("Must be a Glassdoor Community bowl handle (technology), its id or its link.")


def resolve_post(value):
    raw = (value or "").strip()
    if _is_link(raw):
        parts = _community_parts(raw)
        if len(parts) < 2:
            raise ValueError("That is a bowl link; a post link is glassdoor.com/Community/<bowl>/<post>.")
        raw = parts[1]
    low = raw.lower()
    if _MONGO_ID_RE.match(low) or (_HANDLE_RE.match(low) and "-" in low):
        return low
    raise ValueError("Must be a Glassdoor Community post id, its link or its handle.")


# ---- links ---------------------------------------------------------------------------------------

def absolute(path):
    """'/Reviews/x.htm' -> 'https://www.glassdoor.com/Reviews/x.htm'."""
    if not path:
        return None
    path = str(path)
    if path.startswith("http"):
        return path
    return SITE + (path if path.startswith("/") else "/" + path)


def slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-") or "company"


def company_link(employer_id, name=None):
    """The company's Overview page."""
    if not employer_id:
        return None
    s = slug(name)
    return f"{SITE}/Overview/Working-at-{s}-EI_IE{employer_id}.11,{11 + len(s)}.htm"


def company_reviews_link(employer_id, name=None):
    return f"{SITE}/Reviews/{slug(name)}-Reviews-E{employer_id}.htm" if employer_id else None


def review_link(review_id, employer_id=None, name=None):
    if not review_id:
        return None
    if employer_id:
        return f"{SITE}/Reviews/Employee-Review-{slug(name)}-E{employer_id}-RVW{review_id}.htm"
    return f"{SITE}/Reviews/Employee-Review-RVW{review_id}.htm"


def interview_link(interview_id, employer_id=None, name=None):
    if not interview_id:
        return None
    if employer_id:
        return f"{SITE}/Interview/{slug(name)}-Interview-E{employer_id}-RVW{interview_id}.htm"
    return f"{SITE}/Interview/Interview-RVW{interview_id}.htm"


def job_link(listing_id):
    """Fallback when Glassdoor sends no SEO link: the job search page opens
    the listing's detail pane for ?jl=<id>."""
    return f"{SITE}/Job/index.htm?jl={listing_id}" if listing_id else None


def bowl_link(handle):
    return f"{SITE}/Community/{handle}" if handle else None


def post_link(bowl_handle, post_handle):
    if not post_handle:
        return None
    return f"{SITE}/Community/{bowl_handle or 'post'}/{post_handle}"
