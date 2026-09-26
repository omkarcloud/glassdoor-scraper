"""Cache TTL per /glassdoor/* endpoint (cache.py, keyed on the validated
params — marshmallow fills the defaults, so an omitted param and its
default share a row).

Company profiles, ratings and salary aggregates move slowly; review,
interview and community lists gain entries daily; job listings churn
within hours; reference lists barely change."""
from datetime import timedelta

# --- companies ------------------------------------------------------------------
AUTOCOMPLETE_CACHE = timedelta(days=7)
COMPANY_SEARCH_CACHE = timedelta(days=3)
COMPANY_CACHE = timedelta(days=3)
RATINGS_CACHE = timedelta(days=2)
REVIEWS_CACHE = timedelta(hours=12)
INTERVIEWS_CACHE = timedelta(hours=12)
COMPANY_SALARIES_CACHE = timedelta(days=3)
BENEFITS_CACHE = timedelta(days=7)
PHOTOS_CACHE = timedelta(days=7)
LOCATIONS_CACHE = timedelta(days=7)
COMPANY_JOBS_CACHE = timedelta(hours=3)
COMPARE_CACHE = timedelta(days=2)
COMMUNITY_POSTS_CACHE = timedelta(hours=6)

# --- salaries ---------------------------------------------------------------------
SALARY_ESTIMATE_CACHE = timedelta(days=7)
SALARY_BY_COMPANY_CACHE = timedelta(days=3)
SALARY_REPORTS_CACHE = timedelta(hours=12)

# --- jobs ---------------------------------------------------------------------------
JOB_SEARCH_CACHE = timedelta(hours=1)
JOB_DETAILS_CACHE = timedelta(hours=6)

# --- reference ------------------------------------------------------------------------
REFERENCE_CACHE = timedelta(days=14)

# --- community --------------------------------------------------------------------------
BOWL_CACHE = timedelta(days=1)
BOWL_POSTS_CACHE = timedelta(hours=2)
POST_CACHE = timedelta(hours=2)
