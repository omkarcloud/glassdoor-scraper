"""Raw Glassdoor JSON (GraphQL / BFF / autocomplete) -> the public
/glassdoor/* shapes. Pure functions, no network; every parser tolerates
missing, null and junk fields (partial answers never crash a route).

Conventions: snake_case keys; identity (id, name, link) first, then the
content, then ratings / stats, then nested objects; `link` for page URLs;
booleans read as questions (is_*, has_*); ratings on Glassdoor's 1-5 scale;
`*_rate` values are 0-1 fractions (0.83 = 83 % approve); dates are ISO
YYYY-MM-DD, community timestamps ISO-8601 UTC; money is a number plus a
separate `currency`; a missing value is null, never "" or an absent key.

Dropped on purpose: `__typename`, tracking keys (jobResultTrackingKey,
gaTrackerData, adOrderId, importConfigId, indeedCtk, guid / cs / cb query
junk inside partner links), viewer-state flags that are always false for a
logged-out caller (isJoined, myReaction, canEdit, canDelete, followedByUser,
votedByCurrentUser, isAuthor, userPushState), CSS colours, the salary
chart's extreme tails (P005 / P05 / P95 / P995 — only chart axes) and the
benefit `score` (an undocumented sort weight).
"""
import html
import re

from glassdoor import refdata
from glassdoor import refs
from glassdoor.values import iso_date, num, rounded, text, to_int


# ---- primitives --------------------------------------------------------------------------

def _d(value):
    return value if isinstance(value, dict) else {}


def _l(value):
    return value if isinstance(value, list) else []


def rating(value):
    """A 1-5 star rating; 0 / negative / junk (Glassdoor's "no rating") -> None."""
    out = num(value)
    return round(out, 2) if out is not None and out > 0 else None


def rate(value):
    """A 0-1 fraction (approval, recommend); negative (missing) -> None."""
    out = num(value)
    if out is None or out < 0:
        return None
    return round(out / 100.0, 4) if out > 1 else round(out, 4)


def count(value):
    out = to_int(value)
    return out if out is not None and out >= 0 else None


def positive(value):
    out = to_int(value)
    return out if out else None


def money(value):
    out = num(value)
    return round(out, 2) if out is not None and out > 0 else None


def iso_datetime(value):
    """'2026-09-24T21:59:49.611Z' / epoch millis -> '2026-09-24T21:59:49Z' (UTC)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        from datetime import datetime, timezone
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return None
    match = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", str(value))
    return f"{match.group(1)}T{match.group(2)}Z" if match else iso_date(value)


def enum(value):
    """'ACCEPT_OFFER' -> 'accept_offer'; '' / None -> None."""
    out = text(value)
    return out.lower() if out else None


def clean_text(value):
    """Multi-line text with paragraph breaks kept, runs of blanks collapsed."""
    if value is None:
        return None
    lines = [" ".join(line.split()) for line in str(value).replace("\r", "").split("\n")]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out or None


def partner_link(path):
    """Glassdoor's apply/partner redirect with tracking junk removed."""
    if not path:
        return None
    from urllib.parse import parse_qsl, urlencode, urlsplit
    parts = urlsplit(refs.absolute(path))
    keep = [(k, v) for k, v in parse_qsl(parts.query) if k in ("jobListingId", "pos", "ao", "tgt", "s", "t", "ea")]
    return f"{parts.scheme}://{parts.netloc}{parts.path}" + (f"?{urlencode(keep)}" if keep else "")


_PERCENTILES = {"P10": "p10", "P_10TH": "p10", "P25": "p25", "P_25TH": "p25", "P50": "p50", "P_50TH": "p50",
                "P75": "p75", "P_75TH": "p75", "P90": "p90", "P_90TH": "p90"}


def percentiles(rows):
    """[{ident|percentile: 'P10', value}] -> {p10, p25, p50, p75, p90}; None when empty."""
    out = {"p10": None, "p25": None, "p50": None, "p75": None, "p90": None}
    for row in _l(rows):
        row = _d(row)
        key = _PERCENTILES.get(str(row.get("ident") or row.get("percentile") or "").upper())
        if key:
            out[key] = money(row.get("value"))
    return out if any(v is not None for v in out.values()) else None


def pay_statistics(stats):
    """{mean, percentiles} -> {p10..p90}. Glassdoor's `mean` equals its P50
    on every row checked (it is the median the site displays), so it is
    not repeated; p50 is that median."""
    stats = _d(stats)
    return percentiles(stats.get("percentiles")) if stats else None


# ---- shared blocks ----------------------------------------------------------------------------

RATING_KEYS = (
    ("overall", "overallRating"),
    ("career_opportunities", "careerOpportunitiesRating"),
    ("compensation_and_benefits", "compensationAndBenefitsRating"),
    ("culture_and_values", "cultureAndValuesRating"),
    ("diversity_and_inclusion", "diversityAndInclusionRating"),
    ("senior_management", "seniorManagementRating"),
    ("work_life_balance", "workLifeBalanceRating"),
)


def ratings(raw):
    """Glassdoor's rating object -> stars + approval rates; None when empty."""
    raw = _d(raw)
    out = {key: rating(raw.get(src)) for key, src in RATING_KEYS}
    out["ceo_approval_rate"] = rate(raw.get("ceoRating"))
    out["recommend_to_friend_rate"] = rate(raw.get("recommendToFriendRating"))
    out["positive_business_outlook_rate"] = rate(raw.get("businessOutlookRating"))
    if "ceoRatingsCount" in raw:
        out["ceo_ratings_count"] = count(raw.get("ceoRatingsCount"))
    return out if any(v is not None for v in out.values()) else None


def company_ref(employer_id, name=None, logo=None, rating_value=None, legal_name=None):
    """The compact company object nested everywhere."""
    if not employer_id and not name:
        return None
    out = {"id": to_int(employer_id) or None, "name": text(name), "link": refs.company_link(employer_id, name),
           "logo": logo or None}
    if legal_name is not None:
        out["legal_name"] = text(legal_name)
    if rating_value is not None:
        out["rating"] = rating(rating_value)
    return out


def industry(raw):
    raw = _d(raw)
    if not raw.get("industryId") and not raw.get("industryName"):
        return None
    return {"id": to_int(raw.get("industryId")), "name": text(raw.get("industryName"))}


def sector(raw):
    raw = _d(raw)
    if not raw.get("sectorId") and not raw.get("sectorName"):
        return None
    return {"id": to_int(raw.get("sectorId")), "name": text(raw.get("sectorName"))}


def location(raw):
    """{id, name, type: 'CITY' | 'C'} -> {id: 'IC1132348', name, type: 'city'}."""
    raw = _d(raw)
    if not raw.get("name") and not raw.get("id"):
        return None
    kind = str(raw.get("type") or "").upper()
    kind = refs.LOCATION_TYPES.get(kind[:1] if kind in ("C", "S", "M", "N") else
                                   {"CITY": "C", "STATE": "S", "METRO": "M", "COUNTRY": "N"}.get(kind, ""), None)
    return {"id": refs.location_token(kind, to_int(raw.get("id"))), "name": text(raw.get("name") or raw.get("shortName")),
            "type": kind}


def employer_responses(rows):
    out = []
    for row in _l(rows):
        row = _d(row)
        response = clean_text(row.get("response"))
        if not response:
            continue
        out.append({"response": response, "date": iso_date(row.get("responseDateTime") or row.get("date")),
                    "responder_title": text(row.get("userJobTitle") or row.get("jobTitle"))})
    return out


def pagination(page, per_page, total_count, total_pages=None):
    total_count = count(total_count)
    if total_pages is None and total_count is not None and per_page:
        total_pages = -(-total_count // per_page)
    return {"page": page, "items_per_page": per_page, "total_pages": count(total_pages) or 0,
            "total_count": total_count}


# ---- companies ------------------------------------------------------------------------------------

def _recognitions(employer):
    bptw = []
    for row in _l(employer.get("bestPlacesToWork")):
        row = _d(row)
        year = to_int(row.get("timePeriod"))
        if year:
            bptw.append({"year": year, "rank": positive(row.get("rank"))})
    led = sorted({to_int(_d(r).get("timePeriod")) for r in _l(employer.get("bestLedCompanies"))} - {None}, reverse=True)
    return {
        "best_places_to_work": sorted(bptw, key=lambda r: -r["year"]),
        "best_led_companies_years": led,
        "top_ceo_awards_count": len(_l(employer.get("bestPlacesToWorkCEO"))),
    }


def _company_links(links):
    links = _d(links)
    names = (("reviews", "reviewsUrl"), ("salaries", "salariesUrl"), ("interviews", "interviewUrl"),
             ("benefits", "benefitsUrl"), ("jobs", "jobsUrl"), ("photos", "photosUrl"),
             ("faq", "faqUrl"), ("locations", "locationsUrl"))
    out = {key: refs.absolute(links.get(src)) for key, src in names}
    return out if any(out.values()) else None


def company_details(data):
    employer = _d(_d(data).get("employer"))
    if not employer.get("id"):
        return None
    eid = to_int(employer.get("id"))
    name = text(employer.get("shortName") or employer.get("name"))
    overview = _d(employer.get("overview"))
    counts = _d(employer.get("counts"))
    ceo = _d(employer.get("ceo"))
    raw_ratings = _d(employer.get("ratings"))
    links = _d(employer.get("links"))
    return {
        "id": eid,
        "name": name,
        "legal_name": text(employer.get("name")),
        "link": refs.absolute(links.get("overviewUrl")) or refs.company_link(eid, name),
        "website": text(employer.get("website")),
        "logo": employer.get("squareLogoUrl") or None,
        "cover_photo": _d(employer.get("coverPhoto")).get("hiResUrl") or None,
        "description": clean_text(overview.get("description")),
        "mission": clean_text(overview.get("mission")),
        "headquarters": text(employer.get("headquarters")),
        "size": text(employer.get("size")),
        "size_category": enum(employer.get("sizeCategory")),
        "revenue": text(employer.get("revenue")),
        "type": text(employer.get("type")),
        "founded_year": positive(employer.get("yearFounded")),
        "stock_ticker": text(employer.get("stock")),
        "status": enum(employer.get("activeStatus")),
        "industry": industry(employer.get("primaryIndustry")),
        "sector": sector(employer.get("primaryIndustry")),
        "ratings": ratings(raw_ratings),
        "ceo": {"name": text(ceo.get("name")), "title": text(ceo.get("title")),
                "photo": ceo.get("photoUrl") or None} if ceo.get("name") else None,
        "counts": {
            "reviews": count(counts.get("reviewCount")),
            "salaries": count(counts.get("salaryCount")),
            "benefits": count(counts.get("benefitCount")),
            "photos": count(counts.get("photoCount")),
            "open_jobs": count(_d(counts.get("globalJobCount")).get("jobCount")),
        },
        "awards": [{"name": text(_d(a).get("name")), "source": text(_d(a).get("source")),
                    "year": positive(_d(a).get("year")), "is_featured": bool(_d(a).get("featured"))}
                   for a in _l(employer.get("awards")) if _d(a).get("name")],
        "recognitions": _recognitions(employer),
        "competitors": [company_ref(_d(c).get("id"), _d(c).get("shortName"), _d(c).get("squareLogoUrl"))
                        for c in _l(employer.get("competitors")) if _d(c).get("id")],
        "parent_company": company_ref(_d(_d(employer.get("parent")).get("employer")).get("id"),
                                      _d(_d(employer.get("parent")).get("employer")).get("shortName")),
        "subsidiaries": [company_ref(_d(_d(s).get("employer")).get("id"), _d(_d(s).get("employer")).get("shortName"))
                         for s in _l(employer.get("subsidiaries")) if _d(_d(s).get("employer")).get("id")],
        "legal_actions": [text(_d(b).get("headerText")) for b in _l(employer.get("legalActionBadges"))
                          if text(_d(b).get("headerText"))],
        "links": _company_links(links),
    }


def company_search_item(row):
    row = _d(row)
    employer = _d(row.get("employer"))
    if not employer.get("id"):
        return None
    eid = to_int(employer.get("id"))
    name = text(employer.get("shortName") or employer.get("name"))
    counts = _d(employer.get("counts"))
    demographics = {}
    for group in _l(row.get("demographicRatings")):
        group = _d(group)
        category = enum(re.sub(r"(?<!^)(?=[A-Z])", "_", str(group.get("category") or "")))
        values = {}
        for cr in _l(group.get("categoryRatings")):
            cr = _d(cr)
            key = enum(re.sub(r"(?<!^)(?=[A-Z])", "_", str(cr.get("categoryValue") or "")))
            if key:
                values[key] = rating(_d(cr.get("ratings")).get("overallRating"))
        if category and values:
            demographics[category] = values
    return {
        "id": eid,
        "name": name,
        "legal_name": text(employer.get("name")),
        "link": refs.company_link(eid, name),
        "website": text(employer.get("website")),
        "logo": employer.get("squareLogoUrl") or None,
        "description": clean_text(_d(employer.get("overview")).get("description")),
        "headquarters": text(employer.get("headquarters")),
        "size": text(employer.get("size")),
        "size_category": enum(employer.get("sizeCategory")),
        "industry": industry(employer.get("primaryIndustry")),
        "sector": sector(employer.get("primaryIndustry")),
        "ratings": ratings(employer.get("ratings")),
        "counts": {"reviews": count(counts.get("reviewCount")), "salaries": count(counts.get("salaryCount")),
                   "open_jobs": count(_d(counts.get("globalJobCount")).get("jobCount"))},
        "demographic_ratings": demographics or None,
        "is_best_place_to_work": bool(_l(employer.get("bestPlacesToWork"))),
    }


def company_search(data, page):
    result = _d(_d(data).get("employerSearchRG"))
    items = [i for i in (company_search_item(r) for r in _l(result.get("employerResults"))) if i]
    return {"pagination": pagination(page, 10, result.get("numOfRecordsAvailable"), result.get("numOfPagesAvailable")),
            "companies": items}


def company_autocomplete(rows):
    out = []
    for row in _l(rows):
        row = _d(row)
        if not row.get("id"):
            continue
        name = text(row.get("shortName") or row.get("label") or row.get("name"))
        out.append({"id": to_int(row.get("id")), "name": name, "legal_name": text(row.get("name")),
                    "link": refs.company_link(row.get("id"), name), "website": text(row.get("websiteURL")),
                    "logo": row.get("logoURL") or None})
    return out


# ---- reviews / ratings -----------------------------------------------------------------------------

_SUB_RATINGS = (
    ("career_opportunities", "ratingCareerOpportunities"),
    ("compensation_and_benefits", "ratingCompensationAndBenefits"),
    ("culture_and_values", "ratingCultureAndValues"),
    ("diversity_and_inclusion", "ratingDiversityAndInclusion"),
    ("senior_management", "ratingSeniorLeadership"),
    ("work_life_balance", "ratingWorkLifeBalance"),
)
_OPINIONS = {"POSITIVE": "positive", "NEGATIVE": "negative", "NEUTRAL": "neutral", "APPROVE": "approve",
             "DISAPPROVE": "disapprove", "NO_OPINION": "no_opinion", "RECOMMEND": "recommend",
             "DONT_RECOMMEND": "do_not_recommend", "WONT_RECOMMEND": "do_not_recommend"}


def _opinion(value):
    if value in (None, ""):
        return None
    key = str(value).upper()
    return _OPINIONS.get(key, key.lower())


def review(raw, company=None):
    raw = _d(raw)
    if not raw.get("reviewId"):
        return None
    employer = _d(raw.get("employer")) or {"id": (company or {}).get("id"), "shortName": (company or {}).get("name")}
    sub = {key: rating(raw.get(src)) for key, src in _SUB_RATINGS}
    return {
        "id": to_int(raw.get("reviewId")),
        "link": refs.review_link(raw.get("reviewId"), employer.get("id"), employer.get("shortName")),
        "title": text(raw.get("summary")),
        "pros": clean_text(raw.get("pros")),
        "cons": clean_text(raw.get("cons")),
        "advice_to_management": clean_text(raw.get("advice")),
        "rating": rating(raw.get("ratingOverall")),
        "date": iso_date(raw.get("reviewDateTime")),
        "job_title": text(_d(raw.get("jobTitle")).get("text")),
        "location": location(raw.get("location")),
        "employment_status": enum(raw.get("employmentStatus")),
        "is_current_employee": raw.get("isCurrentJob") if isinstance(raw.get("isCurrentJob"), bool) else None,
        "years_employed": positive(raw.get("lengthOfEmployment")),
        "sub_ratings": sub if any(v is not None for v in sub.values()) else None,
        "recommends_company": {"POSITIVE": True, "NEGATIVE": False}.get(str(raw.get("ratingRecommendToFriend") or "").upper()),
        "ceo_opinion": _opinion(raw.get("ratingCeo")),
        "business_outlook": _opinion(raw.get("ratingBusinessOutlook")),
        "helpful_count": count(raw.get("countHelpful")),
        "not_helpful_count": count(raw.get("countNotHelpful")),
        "is_featured": bool(raw.get("featured")),
        "employer_responses": employer_responses(raw.get("employerResponses")),
    }


def _root(data, *names):
    """The first present root object (GraphQL root or its BFF alias)."""
    data = _d(data)
    for name in names:
        if isinstance(data.get(name), dict):
            return data[name]
    return {}


def reviews_page(data, page, per_page, company=None):
    result = _root(data, "employerReviewsRG", "employerReviews")
    items = [r for r in (review(x, company) for x in _l(result.get("reviews"))) if r]
    return {
        "pagination": pagination(page, per_page, result.get("filteredReviewsCount"), result.get("numberOfPages")),
        "reviews_count": count(result.get("allReviewsCount")),
        "filtered_reviews_count": count(result.get("filteredReviewsCount")),
        "reviews": items,
    }


_DIST_KEYS = (("overall", "overall"), ("career_opportunities", "careerOpportunities"),
              ("compensation_and_benefits", "compensationAndBenefits"), ("culture_and_values", "cultureAndValues"),
              ("diversity_and_inclusion", "diversityAndInclusion"), ("senior_management", "seniorManagement"),
              ("work_life_balance", "workLifeBalance"))


def rating_distribution(raw):
    raw = _d(raw)
    out = {}
    for key, src in _DIST_KEYS:
        stars = _d(raw.get(src))
        if stars:
            out[key] = {str(n): count(stars.get(f"_{n}")) or 0 for n in range(5, 0, -1)}
    rec = _d(raw.get("recommendToFriend"))
    if rec:
        out["recommend_to_friend"] = {"recommend": count(rec.get("RECOMMEND")) or 0,
                                      "do_not_recommend": count(rec.get("WONT_RECOMMEND")) or 0}
    return out or None


def company_ratings(reviews_data, benchmark_data, employer_data=None):
    result = _root(reviews_data, "employerReviewsRG", "employerReviews")
    raw = _d(result.get("ratings"))
    ceo = _d(raw.get("ratedCeo")) or _d(_d(_d(employer_data).get("employer")).get("ceo"))
    return {
        "ratings": ratings(raw),
        "ceo": {"name": text(ceo.get("name")), "title": text(ceo.get("title")),
                "photo": ceo.get("regularPhoto") or ceo.get("photoUrl") or None} if ceo.get("name") else None,
        "reviews_count": count(result.get("allReviewsCount")),
        "filtered_reviews_count": count(result.get("filteredReviewsCount")),
        "rated_reviews_count": count(result.get("ratedReviewsCount")),
        "distribution": rating_distribution(result.get("ratingCountDistribution")),
        "industry_benchmark": ratings(_d(benchmark_data).get("industryBenchmarkRatings")),
    }


# ---- interviews -------------------------------------------------------------------------------------

def _question(row):
    row = _d(row)
    question = clean_text(row.get("question") or row.get("text"))
    if not question:
        return None
    return {"id": to_int(row.get("id")), "question": question, "answers_count": count(row.get("answerCount"))}


def interview(raw, company=None):
    raw = _d(raw)
    if not raw.get("id"):
        return None
    employer = _d(raw.get("employer")) or {"id": (company or {}).get("id"), "shortName": (company or {}).get("name")}
    questions = [q for q in (_question(x) for x in _l(raw.get("userQuestions"))) if q]
    return {
        "id": to_int(raw.get("id")),
        "link": refs.interview_link(raw.get("id"), employer.get("id"), employer.get("shortName")),
        "job_title": text(_d(raw.get("jobTitle")).get("text")),
        "location": location(raw.get("location")),
        "date": iso_date(raw.get("reviewDateTime")),
        "interview_date": iso_date(raw.get("interviewDateTime")),
        "process": clean_text(raw.get("processDescription")),
        "questions": questions,
        "difficulty": enum(raw.get("difficulty")),
        "experience": enum(raw.get("experience")),
        "outcome": enum(raw.get("outcome")),
        "how_obtained": enum(raw.get("source")),
        "duration_days": positive(raw.get("durationDays")),
        "helpful_count": count(raw.get("countHelpful")),
        "not_helpful_count": count(raw.get("countNotHelpful")),
        "is_featured": bool(raw.get("featured")),
        "employer_responses": employer_responses(raw.get("employerResponses")),
    }


_DIFFICULTY_SCALE = "1 = very easy, 5 = very difficult"


def interview_stats(raw):
    raw = _d(raw)
    submissions = count(raw.get("difficultySubmissionCount")) or 0
    total_exp = sum(count(_d(e).get("count")) or 0 for e in _l(raw.get("interviewExperienceCounts")))
    total_ch = sum(count(_d(e).get("count")) or 0 for e in _l(raw.get("interviewObtainedChannelCounts")))

    def shares(rows, total):
        out = []
        for row in _l(rows):
            row = _d(row)
            n = count(row.get("count")) or 0
            out.append({"type": enum(row.get("type")), "count": n, "share": round(n / total, 4) if total else None})
        return sorted(out, key=lambda r: -r["count"])
    return {
        "interviews_count": count(raw.get("totalInterviewCount")),
        "filtered_interviews_count": count(raw.get("filteredInterviewCount")),
        "questions_count": count(raw.get("interviewQuestionCount")),
        "average_difficulty": rounded(num(raw.get("difficultySum")) / submissions, 2) if submissions and num(raw.get("difficultySum")) else None,
        "difficulty_scale": _DIFFICULTY_SCALE,
        "experience": shares(raw.get("interviewExperienceCounts"), total_exp),
        "how_candidates_got_interviews": shares(raw.get("interviewObtainedChannelCounts"), total_ch),
        "newest_interview_date": iso_date(raw.get("newestReviewDate")),
    }


def interviews_page(data, page, per_page, company=None):
    raw = _root(data, "employerInterviewsIG", "employerInterviews")
    return {
        "pagination": pagination(page, per_page, raw.get("filteredInterviewCount"), raw.get("totalNumberOfPages")),
        "stats": interview_stats(raw),
        "interviews": [i for i in (interview(x, company) for x in _l(raw.get("interviews"))) if i],
    }


# ---- salaries ------------------------------------------------------------------------------------------

def _currency(raw):
    code = text(_d(raw).get("code"))
    return code.upper() if code else None


def company_salary(row):
    row = _d(row)
    title = _d(row.get("jobTitle"))
    if not title.get("text"):
        return None
    return {
        "job_title": {"id": to_int(title.get("id")), "name": text(title.get("text"))},
        "salaries_count": count(row.get("salaryCount")),
        "pay_period": enum(row.get("payPeriod")),
        "currency": _currency(row.get("currency")),
        "base_pay": pay_statistics(row.get("basePayStatistics")),
        "additional_pay": pay_statistics(row.get("totalAdditionalPayStatistics")),
        "total_pay": pay_statistics(row.get("totalPayStatistics")),
    }


def company_salaries(data, page, per_page):
    raw = _d(_d(data).get("aggregatedSalaryEstimates"))
    return {
        "pagination": pagination(page, per_page, raw.get("resultCount"), raw.get("numPages")),
        "location": location(raw.get("queryLocation")),
        "salaries": [s for s in (company_salary(r) for r in _l(raw.get("results"))) if s],
    }


def salary_estimate(data):
    raw = _d(_d(data).get("occSalaryEstimates"))
    title = _d(raw.get("jobTitle"))
    if not title and not raw.get("totalPayPercentiles"):
        return None
    return {
        "job_title": {"id": to_int(title.get("id")), "name": text(title.get("text"))} if title else None,
        "location": location(raw.get("queryLocation")),
        "pay_period": enum(raw.get("payPeriod")),
        "currency": _currency(raw.get("currency")),
        "base_pay": percentiles(raw.get("basePayPercentiles")),
        "additional_pay": percentiles(raw.get("additionalPayPercentiles")),
        "total_pay": percentiles(raw.get("totalPayPercentiles")),
        "salaries_count": count(raw.get("salariesCount")),
        "confidence": enum(raw.get("confidence")),
        "updated_on": iso_date(raw.get("estimateSourceUpdateTime")),
    }


def salaries_by_company(data, page, per_page=10):
    raw = _d(_d(data).get("aggregatedSalaryEstimates"))
    items = []
    for row in _l(raw.get("results")):
        row = _d(row)
        employer = _d(row.get("employer"))
        if not employer.get("id"):
            continue
        title = _d(row.get("jobTitle"))
        company = company_ref(employer.get("id"), employer.get("shortName"), employer.get("squareLogoUrl"),
                              rating_value=_d(employer.get("ratings")).get("overallRating"))
        company["open_jobs"] = count(_d(_d(employer.get("counts")).get("globalJobCount")).get("jobCount"))
        items.append({
            "company": company,
            "job_title": {"id": to_int(title.get("id")), "name": text(title.get("text"))} if title else None,
            "salaries_count": count(row.get("salaryCount")),
            "pay_period": enum(row.get("payPeriod")),
            "currency": _currency(row.get("currency")),
            "base_pay": pay_statistics(row.get("basePayStatistics")),
            "additional_pay": pay_statistics(row.get("totalAdditionalPayStatistics")),
            "total_pay": pay_statistics(row.get("totalPayStatistics")),
        })
    return {"pagination": pagination(page, per_page, raw.get("resultCount")),
            "location": location(raw.get("queryLocation")), "salaries": items}


_CURRENCY_IDS = {1: "USD"}     # employerSalaryComparison sends a currency id only


def _median(stats):
    """employerSalaryComparison's `mean` — the same figure the site shows as
    the median (it equals the company salaries' P50)."""
    return money(_d(stats).get("mean"))


def salary_comparison(data, companies):
    """employerSalaryComparison -> per job title, each company's median pay
    split by component. `companies` maps employer id -> compact company."""
    raw = _d(_d(data).get("employerSalaryComparison"))
    titles = []
    for group in _l(raw.get("jobTitles")):
        group = _d(group)
        title = _d(group.get("jobTitle"))
        rows = []
        for row in _l(group.get("results")):
            row = _d(row)
            eid = to_int(_d(row.get("employer")).get("id"))
            rows.append({
                "company": companies.get(eid) or company_ref(eid),
                "salaries_count": count(row.get("salaryCount")),
                "pay_period": enum(row.get("payPeriod")),
                "currency": _CURRENCY_IDS.get(to_int(_d(row.get("currency")).get("id"))),
                "confidence": enum(row.get("confidence")),
                "median_pay": {
                    "total": _median(row.get("totalPayStatistics")),
                    "base": _median(row.get("basePayStatistics")),
                    "additional": _median(row.get("totalAdditionalPayStatistics")),
                    "cash_bonus": _median(row.get("cashBonusStatistics")),
                    "stock_bonus": _median(row.get("stockBonusStatistics")),
                    "profit_sharing": _median(row.get("profitSharingStatistics")),
                    "sales_commission": _median(row.get("salesCommissionStatistics")),
                    "tips": _median(row.get("tipsStatistics")),
                },
            })
        if title.get("text"):
            titles.append({"job_title": {"id": to_int(title.get("id")), "name": text(title.get("text"))},
                           "salaries_count": count(group.get("salaryCount")), "companies": rows})
    return titles


_EXPERIENCE_KEYS = {token: key for key, token in refdata.YEARS_OF_EXPERIENCE.items()}


def salary_report(row, currency=None):
    """One reported salary. Title-wide reports carry `payForPayPeriod`
    (usually an anonymised total-pay range); company-scoped reports carry
    annual base / cash bonus / stock bonus amounts."""
    row = _d(row)
    pay = _d(row.get("payForPayPeriod"))
    low = money(pay.get("totalPayAnonymityMinAmount") or row.get("annualTotalPayAnonymityMinAmount"))
    high = money(pay.get("totalPayAnonymityMaxAmount") or row.get("annualTotalPayAnonymityMaxAmount"))
    base = money(pay.get("basePayAmount") or row.get("annualBasePayAmount"))
    cash = money(row.get("annualCashBonusAmount"))
    stock = money(row.get("annualStockBonusAmount"))
    additional = money(pay.get("totalAdditionalPayAmount"))
    if additional is None and (cash or stock):
        additional = round((cash or 0) + (stock or 0), 2)
    return {
        "job_title": text(row.get("jobTitle")),
        "location": {
            "city": text(_d(row.get("city")).get("name")),
            "metro": text(_d(row.get("metro")).get("name")),
            "state": text(_d(row.get("state")).get("name")),
            "country": text(_d(row.get("country")).get("name")),
        },
        "years_of_experience": _EXPERIENCE_KEYS.get(str(row.get("yearsOfExperience") or "").upper()),
        "pay_period": enum(pay.get("payPeriod") or row.get("payPeriod")),
        "currency": currency,
        "base_pay": base,
        "cash_bonus": cash,
        "stock_bonus": stock,
        "additional_pay": additional,
        "total_pay": round(base + (additional or 0), 2) if base else None,
        # Glassdoor shows anonymised reports as a total-pay range only
        "total_pay_range": {"min": low, "max": high} if low or high else None,
        "is_anonymized": bool(row.get("displayAnonymityPayAmounts")),
        "reported_on": iso_date(row.get("reviewDate")),
    }


def salary_reports(data, page, per_page):
    records = _d(_d(data).get("salaryRecords"))
    raw = _d(records.get("individualSalariesForJobTitle")) or _d(records.get("individualSalariesForGoc"))
    currency = _currency(raw.get("currency"))
    items = []
    for row in _l(raw.get("results")):
        items.append(salary_report(row, currency))
    return {"pagination": pagination(page, per_page, raw.get("totalNumberOfRecords"), raw.get("totalNumberOfPages")),
            "reports": items}


# ---- benefits / photos / offices ---------------------------------------------------------------------

def benefits(data):
    raw = _d(_d(data).get("benefitsOverviewForCountry"))
    categories = []
    for group in _l(raw.get("benefitsCategoryToStatisticAggregates")):
        group = _d(group)
        cat = _d(group.get("benefitCategory"))
        if not cat.get("name") or to_int(cat.get("id")) == 0:      # id 0 = the "Overview" roll-up
            continue
        items = []
        for row in _l(group.get("benefitStatisticAggregateList")):
            row = _d(row)
            benefit = _d(row.get("benefit"))
            if not benefit.get("name"):
                continue
            denominator = num(row.get("benefitRatingDenominator"))
            numerator = num(row.get("benefitRatingNumerator"))
            reporting = num(row.get("reportingDenominator"))
            reported = num(row.get("reportingNumerator"))
            items.append({
                "id": to_int(benefit.get("id")),
                "name": text(benefit.get("name")),
                "rating": rating(numerator / denominator) if denominator and numerator is not None else None,
                "ratings_count": count(row.get("benefitRatingDenominator")),
                "comments_count": count(row.get("totalComments")),
                # share of employees who reported having this benefit
                "offered_rate": round(reported / reporting, 4) if reporting and reported is not None else None,
                "is_verified_by_employer": bool(row.get("verified")),
                "verified_on": iso_date(row.get("verifiedDate")) if row.get("verified") else None,
            })
        categories.append({"id": to_int(cat.get("id")), "name": text(cat.get("name")), "benefits": items})
    return {"overall_rating": rating(raw.get("overallBenefitRating")),
            "reviews_count": count(raw.get("totalBenefitReviews")), "categories": categories}


def photos(data, page, per_page):
    raw = _root(data, "employerPhotos")
    items = []
    for row in _l(raw.get("photos")):
        row = _d(row)
        if not row.get("photoId"):
            continue
        items.append({"id": to_int(row.get("photoId")), "caption": text(row.get("caption")),
                      "link": refs.absolute(row.get("photoLink")), "image": row.get("photoUrlLarge") or None,
                      "image_2x": row.get("photoUrl2x") or None, "location": text(row.get("location"))})
    return {"pagination": pagination(page, per_page, raw.get("totalCount")), "photos": items}


def offices(data):
    employer = _d(_d(data).get("employer"))
    items = []
    for row in _l(employer.get("officeAddresses")):
        row = _d(row)
        postal = text(row.get("postalCode"))
        items.append({
            "id": to_int(row.get("id") or row.get("officeLocationId")),
            "address_line_1": text(row.get("addressLine1")),
            "address_line_2": text(row.get("addressLine2")),
            "city": text(row.get("cityName")),
            "state": text(row.get("administrativeAreaName1")),
            "postal_code": None if not postal or set(postal) == {"0"} else postal,
            "country": text(row.get("countryName")),
        })
    return {"link": refs.absolute(_d(employer.get("links")).get("locationsUrl")), "offices_count": len(items),
            "offices": items}


# ---- jobs --------------------------------------------------------------------------------------------------

def _salary(header):
    header = _d(header)
    pay = _d(header.get("payPeriodAdjustedPay"))
    low, mid, high = money(pay.get("p10")), money(pay.get("p50")), money(pay.get("p90"))
    if low is None and mid is None and high is None:
        return None
    return {"min": low, "median": mid, "max": high, "currency": text(header.get("payCurrency")),
            "period": enum(header.get("payPeriod")), "source": enum(header.get("salarySource"))}


def _attributes(header):
    attr = _d(_d(header).get("indeedJobAttribute"))
    values = [text(_d(a).get("value")) for a in _l(attr.get("extractedJobAttributes"))]
    return [v for v in values if v]


def _job_location(header):
    header = _d(header)
    name = text(header.get("locationName"))
    kind = refs.LOCATION_TYPES.get(str(header.get("locationType") or "").upper()[:1])
    loc_id = to_int(header.get("locId"))
    if not name and not loc_id:
        return None
    return {"id": refs.location_token(kind, loc_id) if loc_id and loc_id > 0 else None, "name": name, "type": kind}


def job_listing(row):
    jobview = _d(_d(row).get("jobview"))
    header = _d(jobview.get("header"))
    job = _d(jobview.get("job"))
    listing_id = to_int(job.get("listingId"))
    if not listing_id:
        return None
    employer = _d(header.get("employer"))
    overview = _d(jobview.get("overview"))
    fragments = [clean_text(f) for f in _l(job.get("descriptionFragmentsText"))]
    name = text(employer.get("shortName") or overview.get("shortName") or header.get("employerNameFromSearch"))
    company = {"id": to_int(employer.get("id")) or None, "name": name,
               "link": refs.company_link(employer.get("id"), name) if employer.get("id") else None,
               "logo": overview.get("squareLogoUrl") or None,
               "rating": rating(_d(employer.get("ratings")).get("overallRating"))} if name else None
    return {
        "id": listing_id,
        "title": text(job.get("jobTitleText") or header.get("jobTitleText")),
        "link": header.get("seoJobLink") or refs.job_link(listing_id),
        "company": company,
        "posted_by": text(header.get("employerNameFromSearch")),
        "location": _job_location(header),
        "salary": _salary(header),
        "occupation": text(header.get("goc")),
        "snippet": " ".join(f for f in fragments if f) or None,
        "attributes": _attributes(header),
        "posted_days_ago": count(header.get("ageInDays")),
        "is_easy_apply": bool(header.get("easyApply")),
        "is_sponsored": bool(header.get("isSponsoredJob")),
        "is_expired": bool(header.get("expired")),
    }


def job_search(data, page, per_page):
    raw = _d(_d(data).get("jobListings"))
    items = [j for j in (job_listing(r) for r in _l(raw.get("jobListings"))) if j]
    return {"pagination": pagination(page, per_page, raw.get("totalJobsCount")), "jobs": items}


# 'search-jobs.job-type-options.fulltime' -> the /glassdoor/jobs/search `job_type` spelling
_JOB_TYPES = {"fulltime": "full_time", "parttime": "part_time", "contract": "contract", "internship": "internship",
              "temporary": "temporary", "permanent": "permanent"}


def job_details(data):
    view = _d(_d(data).get("jobview"))
    header = _d(view.get("header"))
    job = _d(view.get("job"))
    listing_id = to_int(job.get("listingId"))
    if not listing_id:
        return None
    overview = _d(view.get("overview"))
    employer = _d(header.get("employer"))
    geo = _d(view.get("map"))
    attr = _d(header.get("indeedJobAttribute"))
    eid = overview.get("id") or employer.get("id")
    name = overview.get("shortName") or employer.get("shortName")
    company = None
    if eid:
        ceo = _d(overview.get("ceo"))
        company = {
            **company_ref(eid, name, overview.get("squareLogoUrl") or employer.get("squareLogoUrl"),
                          legal_name=overview.get("name") or employer.get("name")),
            "website": text(overview.get("website")),
            "headquarters": text(overview.get("headquarters")),
            "size": text(overview.get("size")),
            "revenue": text(overview.get("revenue")),
            "type": text(overview.get("type")),
            "founded_year": positive(overview.get("yearFounded")),
            "industry": industry(overview.get("primaryIndustry")),
            "sector": sector(overview.get("primaryIndustry")),
            "ceo": {"name": text(ceo.get("name")), "photo": ceo.get("photoUrl") or None} if ceo.get("name") else None,
            "ratings": ratings(overview.get("ratings")),
            "links": _company_links(overview.get("links")),
        }
    lat, lng = num(geo.get("lat")), num(geo.get("lng"))
    return {
        "id": listing_id,
        "title": text(job.get("jobTitleText") or header.get("jobTitleText")),
        "link": header.get("seoJobLink") or refs.job_link(listing_id),
        "apply_link": partner_link(header.get("applyUrl") or header.get("jobLink")),
        "description_html": job.get("description") or None,
        "description": clean_text(html.unescape(re.sub(r"<[^>]+>", "\n", job.get("description") or ""))),
        "company": company,
        "posted_by": text(header.get("employerNameFromSearch")),
        "location": {
            **(_job_location(header) or {}),
            "city": text(geo.get("cityName")),
            "state": text(geo.get("stateName")),
            "country": text(geo.get("country")),
            "postal_code": text(geo.get("postalCode")),
            "address": text(geo.get("address")),
            "latitude": lat if lat else None,
            "longitude": lng if lng else None,
        },
        "salary": _salary(header),
        "occupation": text(header.get("goc")),
        "job_types": [_JOB_TYPES.get(k.rsplit(".", 1)[-1], k.rsplit(".", 1)[-1]) for k in _l(header.get("jobTypeKeys"))
                      if isinstance(k, str) and k],
        "remote_work_types": [enum(r) for r in _l(header.get("remoteWorkTypes")) if r],
        "skills": [text(s) for s in _l(attr.get("skillsLabel")) if text(s)],
        "education": [text(s) for s in _l(attr.get("educationLabel")) if text(s)],
        "years_of_experience": [text(s) for s in _l(attr.get("yearsOfExperienceLabel")) if text(s)],
        "attributes": _attributes(header),
        "posted_on": iso_date(job.get("discoverDate")),
        "posted_days_ago": count(header.get("ageInDays")),
        "is_easy_apply": bool(header.get("easyApply")),
        "is_sponsored": bool(header.get("isSponsoredJob")),
        "is_expired": bool(header.get("expired")),
        "similar_job_titles": [text(_d(s).get("relatedJobTitle")) for s in _l(view.get("similarJobs"))
                               if text(_d(s).get("relatedJobTitle"))],
    }


# ---- autocomplete / reference --------------------------------------------------------------------------------

def job_title_suggestions(rows):
    out = []
    for row in _l(rows):
        row = _d(row)
        if row.get("id"):
            out.append({"id": to_int(row.get("id")), "name": text(row.get("jobTitle") or row.get("label"))})
    return out


def location_suggestions(rows):
    out = []
    for row in _l(rows):
        row = _d(row)
        kind = refs.LOCATION_TYPES.get(str(row.get("locationType") or "").upper()[:1])
        loc_id = to_int(row.get("locationId"))
        if not loc_id or not kind:
            continue
        out.append({
            "id": refs.location_token(kind, loc_id),
            "name": text(row.get("label") or row.get("locationName")),
            "long_name": text(row.get("longName")),
            "type": kind,
            "city": text(row.get("cityName")),
            "state": text(row.get("stateName")),
            "state_code": text(row.get("stateAbbreviation")),
            "country": text(row.get("countryName")),
            "country_code": text(row.get("country2LetterIso")),
        })
    return out


def industries(data):
    data = _d(data)
    by_sector = {}
    for row in _l(data.get("industries")):
        row = _d(row)
        by_sector.setdefault(to_int(row.get("parentSectorId")), []).append(
            {"id": to_int(row.get("industryId")), "name": text(row.get("industryName"))})
    sectors = []
    for row in _l(data.get("sectors")):
        row = _d(row)
        sid = to_int(row.get("sectorId"))
        sectors.append({"id": sid, "name": text(row.get("sectorName")),
                        "industries": sorted(by_sector.get(sid, []), key=lambda i: i["name"] or "")})
    return {"sectors": sorted(sectors, key=lambda s: s["name"] or ""),
            "job_functions": [{"id": k, "name": v} for k, v in refdata.JOB_FUNCTIONS.items()]}


# ---- community (Fishbowl) -------------------------------------------------------------------------------------

def bowl(raw):
    raw = _d(raw)
    if not raw.get("_id"):
        return None
    handle = text(raw.get("handleUrl"))
    ui = _d(raw.get("uiConfig"))
    hidden = bool(raw.get("hideNumberOfUsers"))
    return {
        "id": raw.get("_id"),
        "handle": handle,
        "name": text(raw.get("name")),
        "link": refs.bowl_link(handle or raw.get("_id")),
        "description": clean_text(raw.get("description")),
        "type": enum(raw.get("type")),
        "members_count": None if hidden else count(raw.get("numberOfUsers")),
        "icon": ui.get("icon") or None,
        "cover_image": ui.get("coverPic") or None,
        "join_mode": enum(raw.get("joinMode")),
        "is_locked": bool(raw.get("isLocked")),
        "has_posts": bool(raw.get("hasPosts")),
        "created_at": iso_datetime(raw.get("creationDate")),
        "last_post_at": iso_datetime(_d(raw.get("feedState")).get("lastMessageDate")),
    }


def _author(sign):
    sign = _d(sign)
    if not sign.get("name") and not sign.get("signType"):
        return None
    return {"name": text(sign.get("name")), "type": enum(sign.get("signType") or sign.get("type"))}


def _reactions(counters):
    counters = {str(k).lower(): v for k, v in _d(counters).items()}
    keys = ("like", "helpful", "smart", "funny", "uplifting")
    return {k: count(counters.get(k)) or 0 for k in keys}


def _link_preview(meta):
    meta = _d(meta)
    if not meta.get("url"):
        return None
    return {"link": meta.get("url"), "domain": text(meta.get("domain")), "title": text(meta.get("title")),
            "description": text(meta.get("description")), "image": meta.get("imageUrl") or None}


def _message(message_type, data):
    """Text + media of any Fishbowl message type."""
    data = _d(data)
    images = [_d(i).get("url") for i in _l(data.get("images")) + _l(data.get("multiImages"))
              if _d(i).get("url")]
    images += [_d(i).get("image3xUrl") or _d(i).get("image2xUrl") or _d(i).get("imageUrl")
               for i in _l(data.get("imageUrls")) if _d(i)]
    poll = None
    if data.get("answers"):
        poll = {"total_votes": count(data.get("totalVotes")), "ends_at": iso_datetime(data.get("voteEndDate")),
                "options": [{"text": text(_d(a).get("text")), "votes": count(_d(a).get("totalVotes"))}
                            for a in _l(data.get("answers"))]}
    elif data.get("options"):
        poll = {"total_votes": count(data.get("totalVotes")), "ends_at": None,
                "options": [{"text": text(_d(o).get("text")), "votes": count(_d(o).get("numberOfVotes"))}
                            for o in _l(data.get("options"))]}
    video = None
    if data.get("videoId"):
        video = {"id": data.get("videoId"), "status": enum(data.get("videoStatus")),
                 "thumbnail": _d(data.get("thumbnail")).get("url") or None}
    return {
        "text": clean_text(data.get("text")),
        "subline": clean_text(data.get("subline")),
        "images": [i for i in images if i],
        "poll": poll,
        "video": video,
        "link_preview": _link_preview(data.get("linkMetadata")),
    }


def _mentions(raw):
    raw = _d(raw)
    companies = []
    for m in _l(raw.get("companyMentions")):
        m = _d(m)
        if m.get("employerId") or m.get("name"):
            companies.append(company_ref(m.get("employerId"), m.get("name"), m.get("icon")))
    titles = sorted({text(_d(m).get("title")) for m in _l(raw.get("nerTitleMentions"))} - {None})
    places = sorted({text(_d(m).get("locationName")) for m in _l(raw.get("nerLocationMentions"))} - {None})
    return {"companies": companies, "job_titles": titles, "locations": places}


def comment(raw):
    raw = _d(raw)
    comment_id = raw.get("_id") or raw.get("id")
    if not comment_id:
        return None
    message = _message(raw.get("messageType"), raw.get("messageData"))
    reactions = raw.get("reactionCounters")
    if not reactions and raw.get("reactions"):
        reactions = {_d(r).get("reactionType"): _d(r).get("count") for r in _l(raw.get("reactions"))}
    replies = [c for c in (comment(r) for r in _l(_d(raw.get("replies")).get("comments"))) if c]
    return {
        "id": comment_id,
        "text": message["text"],
        "images": message["images"],
        "link_preview": message["link_preview"],
        "author": _author(raw.get("sign") or raw.get("author")),
        "type": enum(raw.get("commentType")),
        "created_at": iso_datetime(raw.get("date")),
        "reactions": _reactions(reactions),
        "likes_count": count(raw.get("likesCount")) if "likesCount" in raw else _reactions(reactions)["like"],
        "replies_count": count(raw.get("repliesCount")) or 0,
        "is_by_post_author": bool(raw.get("isPostAuthor")),
        "replies": replies,
    }


def post(raw, bowl_handle=None):
    raw = _d(raw)
    if not raw.get("_id"):
        return None
    handle = text(raw.get("handleUrl"))
    bowl_obj = bowl(raw.get("bowl")) if _d(raw.get("bowl")).get("_id") else None
    bowl_handle = (bowl_obj or {}).get("handle") or bowl_handle
    message = _message(raw.get("messageType"), raw.get("messageData"))
    return {
        "id": raw.get("_id"),
        "handle": handle,
        "link": refs.absolute(raw.get("canonicalURL")) or refs.post_link(bowl_handle, handle or raw.get("_id")),
        "type": enum(raw.get("messageType")),
        **message,
        "author": _author(raw.get("sign")),
        "created_at": iso_datetime(raw.get("date")),
        "reactions": _reactions(raw.get("reactionCounters")),
        "comments_count": count(raw.get("commentsCount")) or 0,
        "shares_count": count(raw.get("sharesCount")),
        "mentions": _mentions(raw),
        "categories": [text(_d(c).get("categoryName")) for c in _l(raw.get("ppcCategories")) if text(_d(c).get("categoryName"))],
        "tags": [enum(t) for t in _l(raw.get("tagsInFeed")) if t],
        "top_comment": comment(raw.get("topComment")),
        "bowl": bowl_obj,
    }


def federation_post(raw):
    """GetFederationPosts rows (the company page's community module)."""
    raw = _d(raw)
    if not raw.get("_id"):
        return None
    b = _d(raw.get("bowl"))
    handle = text(raw.get("handleUrl"))
    return {
        "id": raw.get("_id"),
        "handle": handle,
        "link": refs.post_link(b.get("handleUrl"), handle or raw.get("_id")),
        "type": enum(raw.get("messageType")),
        "text": clean_text(_d(raw.get("messageData")).get("text")),
        "author": _author(raw.get("sign")),
        "created_at": iso_datetime(raw.get("date")),
        "reactions": _reactions(raw.get("reactionCounters")),
        "comments_count": count(raw.get("commentsCount")) or 0,
        "categories": [text(_d(c).get("categoryName")) for c in _l(raw.get("ppcCategories")) if text(_d(c).get("categoryName"))],
        "bowl": {"id": b.get("_id"), "handle": text(b.get("handleUrl")), "name": text(b.get("name")),
                 "link": refs.bowl_link(b.get("handleUrl")), "members_count": count(b.get("numberOfUsers")),
                 "icon": _d(b.get("uiConfig")).get("icon") or None} if b.get("_id") else None,
    }
