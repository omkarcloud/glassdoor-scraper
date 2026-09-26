"""Live endpoint smoke tests: every /glassdoor/* route against a running
service, with example values proven to return data (2026-09-26). The
listing tooling reads each route's FIRST call from this file's AST as its
working example, so the values stay literals.

Skipped unless GLASSDOOR_BASE points at a running service:

    ONLY_SCRAPER=glassdoor python run.py
    GLASSDOOR_BASE=http://127.0.0.1:6002 python -m pytest glassdoor/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("GLASSDOOR_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set GLASSDOOR_BASE to run live endpoint tests")


def call(path, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=240)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def status(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=240).status_code


def test_company_lookup():
    assert 9079 in [c["id"] for c in call("/glassdoor/companies/autocomplete", query="google")["companies"]]
    body = call("/glassdoor/companies/search", query="bank", location="New York", min_rating=4)
    assert body["count"] > 100 and body["companies"][0]["ratings"]["overall"] >= 4
    assert call("/glassdoor/companies/search", job_title="nurse", page=2)["current_page"] == 2


def test_company_details():
    body = call("/glassdoor/companies/details", company="1651")
    assert body["name"] == "Microsoft" and body["ceo"]["name"] and body["competitors"]
    assert call("/glassdoor/companies/details", company="https://www.glassdoor.co.uk/Reviews/Google-Reviews-E9079.htm")["id"] == 9079
    assert call("/glassdoor/companies/details", company="Netflix")["id"] == 11891
    body = call("/glassdoor/companies/locations", company="1651")
    assert body["offices_count"] > 10 and body["offices"][0]["city"]
    assert status("/glassdoor/companies/details", company="99999999") == 404
    assert status("/glassdoor/companies/details", company="https://www.linkedin.com/company/google") == 400


def test_company_reviews_and_ratings():
    body = call("/glassdoor/companies/reviews", company="9079")
    assert body["count"] > 10000 and body["reviews"][0]["pros"] and body["next"]
    body = call("/glassdoor/companies/reviews", company="Amazon", rating=1, employment_status="regular,contract",
                current_employees_only="true", page=2)
    assert all(r["rating"] == 1 for r in body["reviews"])
    assert call("/glassdoor/companies/reviews", company="9079", query="parking")["count"] > 0
    body = call("/glassdoor/companies/ratings", company="9079")
    assert body["ratings"]["overall"] and body["distribution"]["overall"]["5"] and body["industry_benchmark"]


def test_company_interviews():
    body = call("/glassdoor/companies/interviews", company="Apple", sort="popular")
    assert body["stats"]["average_difficulty"] and body["interviews"][0]["process"]
    body = call("/glassdoor/companies/interviews", company="9079", outcome="accepted_offer", experience="positive")
    assert all(i["outcome"] == "accept_offer" for i in body["interviews"])


def test_company_pay_and_perks():
    body = call("/glassdoor/companies/salaries", company="9079")
    assert body["salaries"][0]["total_pay"]["p50"] and body["salaries"][0]["currency"] == "USD"
    assert call("/glassdoor/companies/salaries", company="9079", job_title="software engineer",
                location="New York", sort="highest_pay")["salaries"]
    body = call("/glassdoor/companies/benefits", company="9079", country="GB")
    assert body["country"] == "GB" and body["categories"]
    assert call("/glassdoor/companies/photos", company="9079", page=2)["photos"][0]["image"]


def test_company_jobs_compare_posts():
    body = call("/glassdoor/companies/jobs", company="9079", page=3)
    assert body["current_page"] == 3 and len(body["jobs"]) == 30 and body["jobs"][0]["company"]["id"] == 9079
    body = call("/glassdoor/companies/compare", companies="Google,Microsoft,1138", job_title="Software Engineer")
    assert len(body["companies"]) == 3 and body["salary_comparison"][0]["companies"]
    assert call("/glassdoor/companies/community-posts", company="9079", limit=5)["posts"]


def test_salaries():
    body = call("/glassdoor/salaries/estimate", job_title="Data Scientist", location="Seattle",
                years_of_experience="4_to_6", industry="Internet & Web Services")
    assert body["total_pay"]["p50"] and body["location"]["name"] == "Seattle, WA"
    assert call("/glassdoor/salaries/by-company", job_title="Software Engineer", location="Austin")["salaries"]
    body = call("/glassdoor/salaries/reports", job_title="Software Engineer", company="Google", page=2)
    assert body["reports"][0]["base_pay"] and body["reports"][0]["total_pay"]


def test_jobs():
    body = call("/glassdoor/jobs/search", query="data analyst", location="Chicago")
    assert body["count"] > 30 and body["jobs"][0]["link"]
    body = call("/glassdoor/jobs/search", query="nurse", easy_apply_only="true", seniority="entry_level",
                min_salary=60000)
    assert all(j["is_easy_apply"] for j in body["jobs"])
    assert call("/glassdoor/jobs/search", query="software engineer", page=8)["current_page"] == 8
    job = call("/glassdoor/jobs/details", job=body["jobs"][0]["link"])
    assert job["description"] and job["company"]


def test_reference():
    assert call("/glassdoor/job-titles/autocomplete", query="product man")["job_titles"][0]["id"]
    assert call("/glassdoor/locations/autocomplete", query="london", type="city")["locations"][0]["country_code"] == "GB"
    assert len(call("/glassdoor/industries")["sectors"]) > 20


def test_community():
    assert call("/glassdoor/community/bowls/details", bowl="https://www.glassdoor.com/Community/technology")["name"]
    assert call("/glassdoor/community/bowls/related", bowl="technology")["bowls"]
    posts = call("/glassdoor/community/bowls/posts", bowl="technology", sort="top", limit=5)["posts"]
    assert len(posts) == 5
    post = call("/glassdoor/community/posts/details", post=posts[0]["link"])
    assert post["text"] and post["bowl"]["handle"] == "technology"
    assert call("/glassdoor/community/posts/comments", post=post["id"])["comments"]
