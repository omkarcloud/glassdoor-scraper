"""/glassdoor/companies/* — employer profiles and everything hanging off one.

Upstreams (glassdoor/fetch.py): /graph for the profile and offices
(`employer`), search (`employerSearchRG`), reviews and ratings
(`employerReviewsRG`), interviews (`employerInterviewsIG`), salaries
(`aggregatedSalaryEstimates`) and photos (`employerPhotos`); the
company-compare BFF for benefits, the industry benchmark and the
side-by-side compare; job search (companyId filter) for open jobs;
/autocomplete/employers for suggestions; Fishbowl's GetFederationPosts for
community posts that mention the company."""
import config
from glassdoor import fetch
from glassdoor import lookups as L
from glassdoor import parsers as P
from glassdoor import queries as Q

CC = "/bff/company-compare/"

REVIEWS_PER_PAGE = 10
INTERVIEWS_PER_PAGE = 10
SALARIES_PER_PAGE = 20
PHOTOS_PER_PAGE = 18

REVIEW_SORTS = {"most_recent": "DATE", "oldest": "DATE_ASC", "popular": "RELEVANCE",
                "highest_rating": "RATING", "lowest_rating": "RATING_ASC"}
REVIEW_STARS = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}
INTERVIEW_SORTS = {"most_recent": "DATE", "oldest": "DATE_ASC", "popular": "RELEVANCE",
                   "most_difficult": "DIFFICULTY", "easiest": "DIFFICULTY_ASC"}
SALARY_SORTS = {"popular": "POPULAR", "highest_pay": "TOTAL_PAY_DESC", "lowest_pay": "TOTAL_PAY_ASC",
                "most_reports": "UGC_SALARY_COUNT_DESC"}


def _company(company):
    return L.company_id(company)


def _employer(employer_id):
    data = fetch.graph(Q.EMPLOYER, {"id": employer_id}, label=f"company {employer_id}", data_key="employer")
    if not (data.get("employer") or {}).get("id"):
        raise fetch.GlassdoorNotFound(f"glassdoor has no company {employer_id}")
    return data


def _company_ref(employer_id):
    """The compact company object for an employer (profile memoized 30 min)."""
    data = fetch.memoized(("employer", employer_id), lambda: _employer(employer_id), ttl=1800)
    employer = data["employer"]
    return P.company_ref(employer.get("id"), employer.get("shortName"), employer.get("squareLogoUrl"))


def _with_company(employer_id, body, ref=None):
    """Prefix a sub-resource answer with the compact company it belongs to."""
    return {"company": ref or _company_ref(employer_id), **body}


# ---- lookup ---------------------------------------------------------------------------------

def autocomplete(query):
    """Glassdoor's typeahead, led by exact-name matches from company search
    (the typeahead alone omits some big employers: "google" -> no Google)."""
    rows = L.employer_suggestions(query)
    seen = {str(r.get("id")) for r in rows if isinstance(r, dict)}
    exact = [r for r in L.exact_matches(query) if str(r["id"]) not in seen]
    return {"companies": P.company_autocomplete(exact + rows)}


def search(query=None, location=None, job_title=None, min_rating=None, page=1):
    loc = L.location(location)
    filters = []
    if min_rating:
        filters.append({"filterType": "RATING_OVERALL", "minInclusive": min_rating, "maxInclusive": 5})
    body = {"employerName": query or "", "employerSearchRangeFilters": filters, "industries": [], "sectors": [],
            "jobTitle": job_title or "", "sGocIds": [], "pageRequested": page,
            "location": {"locationId": loc["id"], "locationType": L.location_letter(loc)} if loc else None}
    data = fetch.graph(Q.EMPLOYER_SEARCH, {"input": body}, label="company search", data_key="employerSearchRG",
                       client="company-explorer", referer="/Explore/browse-companies.htm")
    return P.company_search(data, page)


# ---- profile ----------------------------------------------------------------------------------

def details(company):
    employer_id = _company(company)
    data = fetch.memoized(("employer", employer_id), lambda: _employer(employer_id), ttl=1800)
    return P.company_details(data)


def locations(company):
    employer_id = _company(company)
    data = fetch.graph(Q.EMPLOYER_OFFICES, {"id": employer_id}, label=f"offices {employer_id}", data_key="employer")
    if not (data.get("employer") or {}).get("id"):
        raise fetch.GlassdoorNotFound(f"glassdoor has no company {employer_id}")
    return _with_company(employer_id, P.offices(data))


# ---- reviews / ratings ------------------------------------------------------------------------------

def _review_input(employer_id, page=1, per_page=REVIEWS_PER_PAGE, sort="most_recent", rating=None, job_title=None,
                  location=None, employment_status=None, current_employees_only=None, query=None):
    """employerReviewsRG input. `language` must be set or every filter
    returns 0 rows (the site always sends "eng": English-language reviews)."""
    loc = L.location(location)
    return {
        "employer": {"id": employer_id}, "page": {"num": page, "size": per_page},
        "sort": Q.Enum(REVIEW_SORTS.get(sort, "DATE")), "applyDefaultCriteria": True, "language": "eng",
        "overallRating": Q.Enum(REVIEW_STARS[rating]) if rating else None,
        "employmentStatuses": [Q.Enum(s.upper()) for s in employment_status] if employment_status else None,
        "onlyCurrentEmployees": True if current_employees_only else None,
        "jobTitle": {"text": job_title} if job_title else None,
        "location": L.location_ids(loc),
        "textSearch": query or None,
    }


def _reviews_graph(employer_id, label, **filters):
    query = Q.REVIEWS % {"input": Q.literal(_review_input(employer_id, **filters))}
    return fetch.graph(query, label=label, data_key="employerReviewsRG",
                       referer=f"/Reviews/x-Reviews-E{employer_id}.htm")


def reviews(company, page=1, sort="most_recent", rating=None, job_title=None, location=None,
            employment_status=None, current_employees_only=None, query=None):
    employer_id = _company(company)
    data = _reviews_graph(employer_id, f"reviews {employer_id}", page=page, sort=sort, rating=rating,
                          job_title=job_title, location=location, employment_status=employment_status,
                          current_employees_only=current_employees_only, query=query)
    ref = _company_ref(employer_id)
    return _with_company(employer_id, P.reviews_page(data, page, REVIEWS_PER_PAGE, ref), ref)


def ratings(company, job_title=None, location=None, employment_status=None):
    employer_id = _company(company)
    results = fetch.run_parallel([
        lambda: _reviews_graph(employer_id, f"ratings {employer_id}", per_page=1, sort="popular",
                               job_title=job_title, location=location, employment_status=employment_status),
        lambda: fetch.bff(CC + "employer-ratings-benchmark", {"employerId": employer_id}, label="industry benchmark"),
        lambda: fetch.memoized(("employer", employer_id), lambda: _employer(employer_id), ttl=1800),
    ], workers=3)
    status, reviews_data = results[0]
    if status == "error":
        raise reviews_data
    benchmark = results[1][1] if results[1][0] == "ok" else {}
    employer = results[2][1] if results[2][0] == "ok" else {}
    return _with_company(employer_id, P.company_ratings(reviews_data, benchmark, employer))


# ---- interviews ----------------------------------------------------------------------------------------

def interviews(company, page=1, sort="most_recent", job_title=None, location=None, outcome=None, experience=None):
    employer_id = _company(company)
    loc = L.location(location)
    body = {"employer": {"id": employer_id}, "page": {"num": page, "size": INTERVIEWS_PER_PAGE},
            "sort": Q.Enum(INTERVIEW_SORTS.get(sort, "DATE")),
            "outcomes": [Q.Enum(o.upper()) for o in outcome] if outcome else None,
            "experiences": [Q.Enum(e.upper()) for e in experience] if experience else None,
            "jobTitle": {"text": job_title} if job_title else None, "location": L.location_ids(loc) or None}
    data = fetch.graph(Q.INTERVIEWS % {"input": Q.literal(body)}, label=f"interviews {employer_id}",
                       data_key="employerInterviewsIG", referer=f"/Interview/x-Interview-Questions-E{employer_id}.htm")
    ref = _company_ref(employer_id)
    return _with_company(employer_id, P.interviews_page(data, page, INTERVIEWS_PER_PAGE, ref), ref)


# ---- salaries / benefits / photos ------------------------------------------------------------------------

def salaries(company, job_title=None, location=None, pay_period=None, sort="popular", page=1):
    employer_id = _company(company)
    loc = L.location(location)
    body = {"employer": {"id": employer_id}, "location": L.location_ids(loc),
            "page": {"num": page, "size": SALARIES_PER_PAGE}}
    if job_title:
        body["jobTitle"] = {"text": job_title}
    if pay_period:
        body["payPeriod"] = pay_period.upper()
    if sort and sort != "popular":
        body["sort"] = SALARY_SORTS[sort]
    data = fetch.graph(Q.COMPANY_SALARIES, {"input": body}, label=f"salaries {employer_id}",
                       data_key="aggregatedSalaryEstimates")
    return _with_company(employer_id, P.company_salaries(data, page, SALARIES_PER_PAGE))


def benefits(company, country=1):
    employer_id = _company(company)
    data = fetch.bff(CC + "get-benefit-categories", {"benefitsInput": {"employerId": employer_id, "countryId": country}},
                     label=f"benefits {employer_id}", data_key="benefitsOverviewForCountry")
    from glassdoor import refs
    return _with_company(employer_id, {"country": refs.country_iso(country), **P.benefits(data)})


def photos(company, page=1):
    employer_id = _company(company)
    query = Q.PHOTOS % {"employer_id": employer_id, "page": Q.literal({"num": page, "size": PHOTOS_PER_PAGE})}
    data = fetch.graph(query, label=f"photos {employer_id}", data_key="employerPhotos",
                       referer=f"/Photos/x-Office-Photos-E{employer_id}.htm")
    return _with_company(employer_id, P.photos(data, page, PHOTOS_PER_PAGE))


# ---- open jobs ---------------------------------------------------------------------------------------------

def jobs(company, query=None, location=None, date_posted="any", sort="relevant", job_function=None, page=1):
    """The company's open jobs = job search filtered to the employer (the
    company-page jobs backend, /bff/employer-profile-mono/*, is challenged
    from datacenter egress; job search is not)."""
    from glassdoor import jobs as job_search
    employer_id = _company(company)
    ref = _company_ref(employer_id)
    out = job_search.search(query=query, location=location, date_posted=date_posted, job_function=job_function,
                            company=employer_id, sort=sort, page=page)
    return _with_company(employer_id, out, ref)


# ---- compare -----------------------------------------------------------------------------------------------

def _compare_one(employer_id):
    results = fetch.run_parallel([
        lambda: fetch.memoized(("employer", employer_id), lambda: _employer(employer_id), ttl=1800),
        lambda: fetch.bff(CC + "employer-interviews", {"employerId": employer_id}, label="compare interviews"),
        lambda: fetch.bff(CC + "get-benefit-categories", {"benefitsInput": {"employerId": employer_id, "countryId": 1}},
                          label="compare benefits"),
    ], workers=3)
    status, employer = results[0]
    if status == "error":
        raise employer
    details = P.company_details(employer)
    interview = P.interview_stats((results[1][1] or {}).get("employerInterviews")) if results[1][0] == "ok" else None
    benefit = P.benefits(results[2][1]) if results[2][0] == "ok" else None
    return {
        "id": details["id"], "name": details["name"], "link": details["link"], "logo": details["logo"],
        "headquarters": details["headquarters"], "size": details["size"], "revenue": details["revenue"],
        "industry": details["industry"], "founded_year": details["founded_year"],
        "ratings": details["ratings"], "ceo": details["ceo"], "counts": details["counts"],
        "interviews": {k: interview[k] for k in ("interviews_count", "average_difficulty", "experience")} if interview else None,
        "benefits": {"overall_rating": benefit["overall_rating"], "reviews_count": benefit["reviews_count"]} if benefit else None,
    }


def compare(companies, job_title=None):
    ids = []
    for company in companies:
        employer_id = _company(company)
        if employer_id not in ids:
            ids.append(employer_id)
    if len(ids) < 2:
        raise ValueError("Compare needs at least two different companies.")
    results = fetch.run_parallel([lambda e=e: _compare_one(e) for e in ids], workers=config.GLASSDOOR_COMPARE_WORKERS)
    rows, failed = [], []
    for employer_id, (status, value) in zip(ids, results):
        if status == "ok":
            rows.append(value)
        else:
            failed.append({"id": employer_id, "reason": "not_found" if isinstance(value, fetch.GlassdoorNotFound) else "failed",
                           "error": str(value)})
    if not rows:
        raise fetch.GlassdoorUpstreamError("every compare lookup failed: " + "; ".join(f["error"] for f in failed))
    salaries = None
    if job_title:
        data = fetch.bff(CC + "employer-salary-comparison",
                         {"employers": [{"id": r["id"]} for r in rows], "jobTitle": job_title, "pageNum": 1,
                          "pageSize": 8, "payPeriod": "ANNUAL"}, label="salary comparison")
        salaries = P.salary_comparison(data, {r["id"]: P.company_ref(r["id"], r["name"], r["logo"]) for r in rows})
    return {"companies": rows, "salary_comparison": salaries, "failed": failed}


# ---- community ----------------------------------------------------------------------------------------------

def community_posts(company, limit=20):
    employer_id = _company(company)
    data = fetch.graph(Q.document("federation_posts"),
                       {"query": {"employerId": employer_id, "count": limit, "sorting": "timeBasedPoints",
                                  "excludeCategory": ["dating_and_sex", "job_matching"]}},
                       label=f"community posts {employer_id}", client="fishbowl", data_key="getFederationPosts")
    posts = [p for p in (P.federation_post(r) for r in (data.get("getFederationPosts") or {}).get("posts") or []) if p]
    return _with_company(employer_id, {"posts": posts})
