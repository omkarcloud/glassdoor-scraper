"""Configuration for the Glassdoor Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT             port the API listens on (default 8000)
    GLASSDOOR_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                     (default: none — direct). Glassdoor answers direct
                     requests fine at normal volume; set it only if you start
                     seeing HTTP 429 (rate limited) at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy: a request that is blocked or fails is retried on a freshly
# warmed session this many times.
MAX_RETRIES = 4

GLASSDOOR_PROXY = os.environ.get("GLASSDOOR_PROXY") or None

# Names the glassdoor/ package reads.
GLASSDOOR_MAX_ATTEMPTS = MAX_RETRIES
GLASSDOOR_REQUESTS_PER_SESSION = 40   # a warmed session is replaced after this many requests
GLASSDOOR_COMPARE_WORKERS = 4         # parallel lookups in /companies/compare
GLASSDOOR_PROXY_COUNTRIES = ()
# The browser fallback needs Chrome + patchright; this kit is plain HTTP.
GLASSDOOR_BROWSER_FALLBACK = False
GLASSDOOR_BROWSER_IDLE_SECONDS = 300


def glassdoor_proxy():
    return os.environ.get("GLASSDOOR_PROXY") or None
