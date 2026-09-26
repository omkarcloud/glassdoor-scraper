"""The 25 Glassdoor endpoints. Every path is served with and without the
`/glassdoor` prefix, so code generated against the hosted API on RapidAPI
(paths like /companies/reviews) runs unchanged against this server.

Params are validated by the marshmallow schemas in glassdoor/schemas.py:
unknown or invalid params answer 400 with the reason."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from glassdoor import community, companies, jobs, reference, salaries
from glassdoor import schemas as S
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Zürich" would arrive as "ZÃ¼rich")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _page_link(params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "")}
    query["page"] = page
    host = request.headers.get("Host") or "localhost"
    return f"{request.urlparts.scheme}://{host}{request.path}?{urlencode(query)}"


def paginate(result, params):
    """Lift the `pagination` block into count / per_page / current_page /
    total_pages / next / previous, like the hosted API."""
    pagination = result.pop("pagination", None) or {}
    page = int(pagination.get("page") or params.get("page") or 1)
    total_pages = int(pagination.get("total_pages") or 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(params, page + 1 if page < total_pages else None),
        "previous": _page_link(params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema, fn, paginated):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    retries exhausted / blocked -> 500."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = fn(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"glassdoor rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:
        return json_response({"error": f"glassdoor {label} failed: {e}"}, 500)
    return json_response(paginate(result, raw) if paginated else result)


ENDPOINTS = [
    # (path, schema, function, paginated)
    ("/companies/reviews", S.CompanyReviewsSchema, companies.reviews, True),
    ("/companies/details", S.CompanySchema, companies.details, False),
    ("/companies/salaries", S.CompanySalariesSchema, companies.salaries, True),
    ("/companies/interviews", S.CompanyInterviewsSchema, companies.interviews, True),
    ("/companies/ratings", S.CompanyRatingsSchema, companies.ratings, False),
    ("/companies/benefits", S.CompanyBenefitsSchema, companies.benefits, False),
    ("/companies/compare", S.CompanyCompareSchema, companies.compare, False),
    ("/companies/jobs", S.CompanyJobsSchema, companies.jobs, True),
    ("/companies/photos", S.CompanyPhotosSchema, companies.photos, True),
    ("/companies/locations", S.CompanySchema, companies.locations, False),
    ("/companies/community-posts", S.CompanyCommunitySchema, companies.community_posts, False),
    ("/companies/autocomplete", S.AutocompleteSchema, companies.autocomplete, False),
    ("/companies/search", S.CompanySearchSchema, companies.search, True),
    ("/jobs/search", S.JobSearchSchema, jobs.search, True),
    ("/jobs/details", S.JobDetailsSchema, jobs.details, False),
    ("/salaries/estimate", S.SalaryEstimateSchema, salaries.estimate, False),
    ("/salaries/by-company", S.SalaryByCompanySchema, salaries.by_company, True),
    ("/job-titles/autocomplete", S.JobTitleAutocompleteSchema, reference.job_titles, False),
    ("/locations/autocomplete", S.LocationAutocompleteSchema, reference.locations, False),
    ("/industries", S.EmptySchema, reference.industries, False),
    ("/community/bowls/details", S.BowlSchema, community.bowl_details, False),
    ("/community/bowls/related", S.BowlSchema, community.related_bowls, False),
    ("/community/bowls/posts", S.BowlPostsSchema, community.bowl_posts, False),
    ("/community/posts/details", S.PostSchema, community.post_details, False),
    ("/community/posts/comments", S.PostCommentsSchema, community.post_comments, True),
]


def mount(path, schema, fn, paginated):
    """Serve a handler at /path and /glassdoor/path."""
    def handler():
        return call(path.strip("/"), schema, fn, paginated)
    handler.__name__ = "glassdoor_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/glassdoor" + path, method="GET")(handler)


for _path, _schema, _fn, _paginated in ENDPOINTS:
    mount(_path, _schema, _fn, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [e[0] for e in ENDPOINTS]})
