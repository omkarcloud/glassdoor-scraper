"""/glassdoor/salaries/* — market pay by job title (not tied to one company).

  estimate    /graph occSalaryEstimates: base / additional / total pay
              percentiles for a title in a place, by experience and industry
  by-company  /graph aggregatedSalaryEstimates for a title: the employers
              paying it, with their pay percentiles
  reports     recent-salaries BFF: individual (anonymised) salary reports
              for a title, optionally at one company"""
from glassdoor import fetch
from glassdoor import lookups as L
from glassdoor import parsers as P
from glassdoor import queries as Q
from glassdoor import refdata

EP = "/bff/employer-profile-mono/"
REPORTS_PER_PAGE = 10
BY_COMPANY_PER_PAGE = 10

EXPERIENCE = refdata.YEARS_OF_EXPERIENCE


def _industry_id(industry):
    if not industry:
        return 0
    if "sector" in industry:
        raise ValueError("Salary estimates filter by industry, not sector: pick an industry from /glassdoor/industries.")
    return industry["industry"]


def estimate(job_title, location=None, years_of_experience="all", industry=None):
    loc = L.location(location)
    industry_id = _industry_id(industry)
    body = {"jobTitle": {"text": job_title}, "location": L.location_ids(loc),
            "yearsOfExperience": Q.Enum(EXPERIENCE[years_of_experience]),
            "industry": {"id": industry_id} if industry_id else None}
    data = fetch.graph(Q.SALARY_ESTIMATE % {"input": Q.literal(body)}, label="salary estimate",
                       data_key="occSalaryEstimates", referer="/Salaries/index.htm")
    out = P.salary_estimate(data)
    if not out:
        raise fetch.GlassdoorNotFound(f"glassdoor has no salary estimate for '{job_title}'")
    return out


def by_company(job_title, location=None, page=1):
    loc = L.location(location)
    body = {"jobTitle": {"text": job_title}, "location": L.location_ids(loc),
            "page": {"num": page, "size": BY_COMPANY_PER_PAGE}}
    data = fetch.graph(Q.TITLE_SALARIES % {"input": Q.literal(body)}, label="salaries by company",
                       data_key="aggregatedSalaryEstimates", referer="/Salaries/index.htm")
    return P.salaries_by_company(data, page, BY_COMPANY_PER_PAGE)


def reports(job_title, company=None, location=None, pay_period="annual", years_of_experience="all", page=1):
    """Individual reports come only from the recent-salaries backend (no
    GraphQL root found for them); from datacenter egress it is challenged
    and the call falls through to the browser fallback."""
    title = L.job_title(job_title)
    loc = L.location(location)
    args = {"jobTitleId": title["id"], "page": page, "pageSize": REPORTS_PER_PAGE, "payPeriod": pay_period.upper(),
            "yearsOfExperience": EXPERIENCE[years_of_experience], **L.location_ids(loc)}
    if company is not None:
        args["employerId"] = L.company_id(company)
    data = fetch.bff(EP + "recent-salaries", args, label="salary reports", data_key="salaryRecords",
                     referer="/Salaries/index.htm")
    return {"job_title": {"id": title["id"], "name": title["text"]}, **P.salary_reports(data, page, REPORTS_PER_PAGE)}
