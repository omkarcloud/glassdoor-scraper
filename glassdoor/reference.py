"""/glassdoor/job-titles/autocomplete, /glassdoor/locations/autocomplete and
/glassdoor/industries — the lookups that feed the other routes' params."""
from glassdoor import fetch
from glassdoor import lookups as L
from glassdoor import parsers as P
from glassdoor import queries as Q

LOCATION_TYPES = {"all": L.LOCATION_AC_TYPES, "city": "CITY", "state": "STATE", "country": "COUNTRY"}


def job_titles(query):
    return {"job_titles": P.job_title_suggestions(L.job_title_suggestions(query))}


def locations(query, type="all"):
    rows = L.location_suggestions(query, types=LOCATION_TYPES[type])
    return {"locations": P.location_suggestions(rows)}


def industries():
    data = fetch.graph(Q.INDUSTRIES, {}, label="industries", data_key="sectors")
    return P.industries(data)
