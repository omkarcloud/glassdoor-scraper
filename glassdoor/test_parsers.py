"""Offline tests: every parser against real captured payloads
(glassdoor/fixtures/*.json, captured 2026-09-26), the input resolvers, and
junk-tolerance (a parser must never crash on a partial answer).

    python -m pytest glassdoor/test_parsers.py -q
"""
import json
import os

import pytest

from glassdoor import parsers as P
from glassdoor import refs

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fx(name):
    with open(os.path.join(FIXTURES, name + ".json")) as f:
        return json.load(f)


def no_blank_strings(obj):
    """Missing values are null, never "" (the API convention)."""
    if isinstance(obj, dict):
        return all(no_blank_strings(v) for v in obj.values())
    if isinstance(obj, list):
        return all(no_blank_strings(v) for v in obj)
    return obj != ""


# ---- resolvers ----------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("9079", 9079),
    ("https://www.glassdoor.com/Reviews/Google-Reviews-E9079.htm", 9079),
    ("https://www.glassdoor.co.uk/Overview/Working-at-Google-EI_IE9079.11,17.htm", 9079),
    ("https://www.glassdoor.com/Reviews/Google-Reviews-E9079_P2.htm?sort.sortType=RD", 9079),
    ("glassdoor.co.in/Benefits/Google-US-Benefits-EI_IE9079.0,6_IL.7,9_IN1.htm", 9079),
    ("https://www.glassdoor.com/Jobs/Google-Jobs-E9079.htm", 9079),
    ("Google", {"name": "Google"}),
    ("  Tata   Consultancy ", {"name": "Tata Consultancy"}),
])
def test_resolve_company(value, expected):
    assert refs.resolve_company(value) == expected


@pytest.mark.parametrize("value", ["", "0", "https://www.linkedin.com/company/google",
                                   "https://www.glassdoor.com/Community/index.htm"])
def test_resolve_company_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_company(value)


def test_resolve_companies():
    assert refs.resolve_companies("9079, Microsoft,https://www.glassdoor.com/Reviews/Apple-Reviews-E1138.htm") == \
        [9079, {"name": "Microsoft"}, 1138]
    with pytest.raises(ValueError):
        refs.resolve_companies("9079")


@pytest.mark.parametrize("value,expected", [
    ("1010259346403", 1010259346403),
    ("https://www.glassdoor.com/job-listing/sde-amazon-JV_IC1132348_KO0,53_KE54,73.htm?jl=1010259346403", 1010259346403),
    ("https://www.glassdoor.com/partner/jobListing.htm?pos=101&jobListingId=1010259346403", 1010259346403),
])
def test_resolve_job(value, expected):
    assert refs.resolve_job(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("IC1132348", {"type": "city", "id": 1132348}),
    ("in1", {"type": "country", "id": 1}),
    ("https://www.glassdoor.com/Job/new-york-software-engineer-jobs-SRCH_IL.0,8_IC1132348_KO9,26.htm",
     {"type": "city", "id": 1132348}),
    ("New York", {"query": "New York"}),
])
def test_resolve_location(value, expected):
    assert refs.resolve_location(value) == expected


def test_resolve_misc():
    assert refs.resolve_country("gb") == 2 and refs.resolve_country("United States") == 1
    assert refs.resolve_country("uk") == 2
    assert refs.resolve_industry("Information Technology") == {"sector": 10013}
    assert refs.resolve_industry("200063") == {"industry": 200063}
    assert refs.resolve_job_function("engineering") == 1007
    assert refs.resolve_bowl("https://www.glassdoor.com/Community/technology/some-post") == "technology"
    assert refs.resolve_post("https://www.glassdoor.com/Community/technology/some-post-handle") == "some-post-handle"
    assert refs.resolve_post("6AA2BC4E05D31BB5A9CBECFF") == "6aa2bc4e05d31bb5a9cbecff"
    for bad, fn in [("Atlantis", refs.resolve_country), ("Underwater Basket", refs.resolve_industry),
                    ("https://www.glassdoor.com/Community/technology", refs.resolve_post)]:
        with pytest.raises(ValueError):
            fn(bad)


# ---- companies ----------------------------------------------------------------------------

def test_company_details():
    out = P.company_details(fx("employer"))
    assert out["id"] == 1651 and out["name"] == "Microsoft" and out["legal_name"] == "Microsoft Corporation"
    assert out["link"].startswith("https://www.glassdoor.com/Overview/")
    assert out["founded_year"] == 1975 and out["stock_ticker"] == "MSFT"
    assert out["ratings"]["overall"] == 4.0 and 0 < out["ratings"]["ceo_approval_rate"] <= 1
    assert out["ceo"]["name"] == "Satya Nadella" and out["counts"]["reviews"] > 1000
    assert out["competitors"][0]["name"] == "Google" and out["subsidiaries"]
    assert out["recognitions"]["best_places_to_work"][0]["year"] >= 2020
    assert out["links"]["reviews"].endswith("-E1651.htm")
    assert no_blank_strings(out)


def test_company_search_and_autocomplete():
    out = P.company_search(fx("search"), 1)
    assert out["pagination"]["total_count"] > 1000 and len(out["companies"]) == 10
    first = out["companies"][0]
    assert first["id"] and first["ratings"]["overall"] and first["demographic_ratings"]["gender"]
    rows = P.company_autocomplete(fx("ac_employers"))
    assert rows[0] == {**rows[0], "id": 9079, "name": "Google"} and rows[0]["logo"]


def test_reviews_and_ratings():
    page = P.reviews_page(fx("reviews"), 1, 10, P.company_ref(9079, "Google"))
    assert page["pagination"]["total_count"] == page["filtered_reviews_count"]
    review = page["reviews"][0]
    assert review["id"] and review["link"].endswith(f"RVW{review['id']}.htm")
    assert review["pros"] and review["cons"] and 1 <= review["rating"] <= 5 and review["date"][:2] == "20"
    assert review["employment_status"] == "regular"
    located = next(r for r in page["reviews"] if r["location"])
    assert located["location"]["id"].startswith("IC") and located["location"]["type"] == "city"
    ratings = P.company_ratings(fx("reviews"), fx("benchmark"), {"employer": {"ceo": {"name": "Sundar Pichai", "title": "CEO"}}})
    assert ratings["ratings"]["overall"] == 4.4 and ratings["ceo"]["name"] == "Sundar Pichai"
    assert set(ratings["distribution"]["overall"]) == {"1", "2", "3", "4", "5"}
    assert ratings["distribution"]["recommend_to_friend"]["recommend"] > 0
    assert ratings["industry_benchmark"]["overall"] == 3.83


def test_interviews():
    page = P.interviews_page(fx("interviews"), 1, 10, P.company_ref(1138, "Apple"))
    stats = page["stats"]
    assert stats["interviews_count"] > 1000 and 1 <= stats["average_difficulty"] <= 5
    assert abs(sum(e["share"] for e in stats["experience"]) - 1) < 0.01
    interview = page["interviews"][0]
    assert interview["link"] == f"https://www.glassdoor.com/Interview/Apple-Interview-E1138-RVW{interview['id']}.htm"
    assert interview["difficulty"] and interview["outcome"] and interview["process"]
    asked = next(i for i in page["interviews"] if i["questions"])
    assert asked["questions"][0]["question"] and asked["questions"][0]["id"]


def test_salaries():
    page = P.company_salaries(fx("company_salaries"), 1, 20)
    row = page["salaries"][0]
    assert row["job_title"]["name"] == "Software Engineer" and row["currency"] == "USD"
    assert row["total_pay"]["p10"] < row["total_pay"]["p50"] < row["total_pay"]["p90"]
    assert page["location"] == {"id": "IN1", "name": "United States", "type": "country"}
    est = P.salary_estimate(fx("occ"))
    assert est["location"]["id"] == "IC1132348" and est["base_pay"]["p50"] and est["confidence"] == "confident"
    by = P.salaries_by_company(fx("by_company"), 1)
    assert by["salaries"][0]["company"]["name"] and by["salaries"][0]["total_pay"]["p50"]
    assert by["salaries"][0]["base_pay"]["p50"] and by["salaries"][0]["salaries_count"]
    reports = P.salary_reports(fx("recent"), 1, 10)
    assert reports["reports"][0]["total_pay_range"]["min"] and reports["reports"][0]["currency"] == "USD"
    assert reports["reports"][0]["years_of_experience"] in {"all", "less_than_1", "1_to_3", "4_to_6", "7_to_9",
                                                            "10_to_14", "15_or_more"}
    comparison = P.salary_comparison(fx("cc_salary"), {})
    assert comparison[0]["companies"][0]["median_pay"]["total"] > 0


def test_benefits_photos_offices():
    out = P.benefits(fx("benefits"))
    assert out["overall_rating"] == 4.7 and out["categories"][0]["name"] != "Overview"
    benefit = out["categories"][0]["benefits"][0]
    assert 1 <= benefit["rating"] <= 5 and 0 < benefit["offered_rate"] <= 1
    photos = P.photos(fx("photos"), 1, 5)
    assert photos["pagination"]["total_count"] == 621 and photos["photos"][0]["image"].startswith("https://")
    offices = P.offices(fx("offices"))
    assert offices["offices_count"] == len(offices["offices"]) > 10
    assert all(o["postal_code"] != "00000" for o in offices["offices"])


# ---- jobs ------------------------------------------------------------------------------------

def test_job_search():
    page = P.job_search(fx("job_search"), 1, 30)
    job = page["jobs"][0]
    assert job["id"] and job["title"] and job["link"].startswith("https://www.glassdoor.com/job-listing/")
    assert job["company"]["name"] and job["location"]["id"] == "IC1132348"
    assert job["salary"]["currency"] == "USD" and job["salary"]["min"] <= job["salary"]["max"]


def test_job_details():
    out = P.job_details(fx("job_view"))
    assert out["id"] == 1010259346403 and out["description"] and "<" not in out["description"]
    assert out["company"]["id"] == 7470741 and out["company"]["ratings"]["overall"]
    assert out["location"]["latitude"] and out["salary"]["median"]
    assert "full_time" in out["job_types"] and out["skills"]
    assert "guid=" not in out["apply_link"] and "jobListingId=1010259346403" in out["apply_link"]


def test_reference():
    titles = P.job_title_suggestions(fx("ac_job_titles"))
    assert titles[0] == {"id": 119899, "name": "Data Scientist"}
    places = P.location_suggestions(fx("ac_locations"))
    assert places[0]["id"] == "IC1147401" and places[0]["country_code"] == "US"
    industries = P.industries(fx("industries"))
    assert len(industries["sectors"]) == 25 and industries["job_functions"][0]["id"] == 1001


# ---- community --------------------------------------------------------------------------------

def test_community():
    bowl = P.bowl(fx("bowl")["getBowlDetailsCG"])
    assert bowl["handle"] == "technology" and bowl["link"].endswith("/Community/technology")
    post = P.post(fx("bowl_posts")["getBowlPostsCG"]["posts"][0], bowl_handle="technology")
    assert post["text"] and post["link"].startswith("https://www.glassdoor.com/Community/technology/")
    assert post["reactions"]["like"] >= 0 and post["author"]["type"] == "title"
    detail = P.post(fx("post")["getFishbowlPostCG"])
    assert detail["bowl"]["handle"] == "technology" and detail["top_comment"]["text"]
    comments = [P.comment(c) for c in fx("comments")["getFishbowlPostComments"]["comments"]]
    assert comments[0]["replies"] and comments[0]["author"]["type"] == "title"
    related = [P.bowl(b) for b in fx("related_bowls")["getExploreBowlsCG"]["bowls"]]
    assert related[0]["members_count"] > 0
    company_posts = [P.federation_post(p) for p in fx("company_posts")["getFederationPosts"]["posts"]]
    assert company_posts[0]["bowl"]["link"] and company_posts[0]["created_at"].endswith("Z")


# ---- robustness -------------------------------------------------------------------------------

@pytest.mark.parametrize("junk", [None, {}, [], "x", {"data": None}, {"employer": {"id": None}}])
def test_parsers_survive_junk(junk):
    page_parsers = [P.reviews_page, P.interviews_page, P.company_salaries, P.photos, P.job_search, P.salary_reports]
    for fn in page_parsers:
        out = fn(junk, 1, 10)
        assert out["pagination"]["page"] == 1
    for fn in (P.company_details, P.salary_estimate, P.job_details, P.bowl, P.post, P.comment, P.federation_post,
               P.company_search_item, P.review, P.interview, P.job_listing):
        fn(junk)
    P.benefits(junk), P.offices(junk), P.company_ratings(junk, junk), P.industries(junk)
    P.company_search(junk, 1), P.salaries_by_company(junk, 1), P.salary_comparison(junk, {})
    P.company_autocomplete(junk), P.job_title_suggestions(junk), P.location_suggestions(junk)
