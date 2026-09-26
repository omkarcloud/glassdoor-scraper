"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. A company can be a name, a Glassdoor company ID or any
Glassdoor company link.
"""
import json
import os

from glassdoor import companies, jobs, refs

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # 10 reviews a page, newest first, with every Glassdoor filter available
    save("reviews_google.json", companies.reviews(refs.resolve_company("Google")))

    # the full company profile: CEO, ratings, size, revenue, awards, competitors
    save("company_google.json", companies.details(refs.resolve_company("Google")))

    # 30 jobs a page with salary estimates
    save("jobs_software_engineer_sf.json", jobs.search(query="software engineer",
                                                       location=refs.resolve_location("San Francisco")))
