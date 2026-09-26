"""/glassdoor/jobs/* — job search and job details.

  search   /job-search-next/bff/jobSearchResultsQuery: 30 listings a page with
           every filter the site's search bar offers (filterParams)
  details  /graph JobDetailQuery (jobView): the full description, salary
           estimate, skills, map point and the employer's profile

Job search pages are cursor-linked: each answer lists the cursors of the
next few pages, so the cursors are memoized per search and walked forward
for a page that was not advertised yet."""
from glassdoor import fetch
from glassdoor import lookups as L
from glassdoor import parsers as P
from glassdoor import queries as Q

SEARCH_PATH = "/job-search-next/bff/jobSearchResultsQuery"
JOBS_PER_PAGE = 30
MAX_PAGE = 30          # Glassdoor stops serving results past ~900 listings
DEFAULT_LOCATION = {"type": "country", "id": 1, "name": "United States"}

DATE_POSTED = {"any": None, "last_day": "1", "last_3_days": "3", "last_week": "7", "last_2_weeks": "14",
               "last_month": "30"}
JOB_TYPES = {"full_time": "fulltime", "part_time": "parttime", "contract": "contract", "internship": "internship",
             "temporary": "temporary"}
SENIORITY = {"internship": "internship", "entry_level": "entrylevel", "mid_senior_level": "midseniorlevel",
             "director": "director", "executive": "executive"}
COMPANY_SIZES = {"1_to_200": "1", "201_to_500": "2", "501_to_1000": "3", "1001_to_5000": "4", "5001_plus": "5"}


def _filter_params(date_posted, easy_apply_only, remote_only, job_type, seniority, min_salary, max_salary,
                   min_rating, company_size, industry, job_function, company_id, radius, sort):
    params = []

    def add(key, value):
        # identity checks: radius=0 ("exact location") must not be dropped as == False
        if value is not None and value is not False and value != "":
            params.append({"filterKey": key, "values": str(value)})
    add("fromAge", DATE_POSTED.get(date_posted or "any"))
    add("applicationType", "1" if easy_apply_only else None)
    add("remoteWorkType", "1" if remote_only else None)
    add("jobType", JOB_TYPES.get(job_type) if job_type else None)
    add("seniorityType", SENIORITY.get(seniority) if seniority else None)
    add("minSalary", min_salary)
    add("maxSalary", max_salary)
    add("minRating", f"{float(min_rating):.1f}" if min_rating else None)
    add("employerSizes", COMPANY_SIZES.get(company_size) if company_size else None)
    add("industryNId", (industry or {}).get("sector"))
    add("sgocId", job_function)
    add("companyId", company_id)
    add("radius", radius)
    add("sortBy", "date_desc" if sort == "most_recent" else None)
    return params


def _search_page(query, loc, params, page_number, cursor):
    body = {"excludeJobListingIds": [], "filterParams": params, "includeIndeedJobAttributes": True,
            "keyword": query or "", "locationId": loc["id"] if loc else 0,
            "locationType": L.location_word(loc) or "", "numJobsToShow": JOBS_PER_PAGE,
            "originalPageUrl": f"{fetch.SITE}/Job/index.htm", "pageCursor": cursor or "", "pageNumber": page_number,
            "pageType": "SERP", "parameterUrlInput": "", "queryString": "", "seoFriendlyUrlInput": "", "seoUrl": False}
    return fetch.bff(SEARCH_PATH, body, label="job search", data_key="jobListings", referer="/Job/index.htm")


def search(query=None, location=None, radius=None, date_posted="any", easy_apply_only=None, remote_only=None,
           job_type=None, seniority=None, min_salary=None, max_salary=None, min_rating=None, company_size=None,
           industry=None, job_function=None, company=None, sort="relevant", page=1):
    if industry and "industry" in industry:
        raise ValueError("Job search filters by sector (e.g. Information Technology); see /glassdoor/industries.")
    # the backend rejects a search with no location; the site itself falls
    # back to the visitor's country
    loc = L.location(location) or DEFAULT_LOCATION
    company_id = L.company_id(company) if company is not None else None
    params = _filter_params(date_posted, easy_apply_only, remote_only, job_type, seniority, min_salary, max_salary,
                            min_rating, company_size, industry, job_function, company_id, radius, sort)
    key = ("job_search_cursors", query, repr(loc), repr(params))
    # a copy: the memoized dict is shared with concurrent requests
    cursors = dict(fetch.memo_get(key) or {1: ""})
    start = max(n for n in cursors if n <= page)
    data = None
    for number in range(start, page + 1):
        if number not in cursors:
            raise fetch.GlassdoorNotFound(f"page {page} is past the last page of results")
        data = _search_page(query, loc, params, number, cursors[number])
        for link in (data.get("jobListings") or {}).get("paginationCursors") or []:
            if link.get("pageNumber") and link.get("cursor"):
                cursors[int(link["pageNumber"])] = link["cursor"]
        fetch.memo_put(key, cursors)
    out = P.job_search(data, page, JOBS_PER_PAGE)
    out["pagination"]["total_pages"] = min(out["pagination"]["total_pages"], MAX_PAGE)
    return out


def details(job):
    data = fetch.graph(Q.JOB_VIEW, {"jl": job, "queryString": "", "pageTypeEnum": "SERP"}, label=f"job {job}",
                       client="job-search-next", data_key="jobview")
    out = P.job_details(data)
    if not out:
        raise fetch.GlassdoorNotFound(f"glassdoor has no job listing {job}")
    return out
