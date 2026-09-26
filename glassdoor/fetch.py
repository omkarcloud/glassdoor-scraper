"""Glassdoor transport: warmed curl_cffi (Chrome TLS) sessions on direct
egress, with a headful patchright in-page fetch as the last resort.

Surfaces (all logged-out, validated 2026-09-26; every POST carries
`gd-csrf-token: 1`):

  graph(query, variables)   POST /graph — Apollo GraphQL, the main surface.
                            Introspection is off and every error is masked
                            as "Server error", so queries only use field
                            names proven live (glassdoor/queries.py,
                            glassdoor/graphql/*).
  bff(path, args)           POST /bff/company-compare/<name>,
                            /job-search-next/bff/<name> and (salary reports
                            only) /bff/employer-profile-mono/<name>: the
                            Next.js backends-for-frontends, JSON body = the
                            args the page's SWR hook sends.
  get_json(path, params)    GET /autocomplete/* (employers, jobTitle, location).

Cloudflare Bot Management fronts the site, with per-path rules that drift
(observed 2026-09-26 from the GKE egress vs the office IP):
  * a session with no Glassdoor cookies is challenged (403, header
    cf-mitigated: challenge, title "Security | Glassdoor") on /graph and
    the employer-profile BFF; job search and the autocompletes may pass;
  * one warm-up GET sets gdId / asst (and gdsid for page loads). Which one
    passes changes over the day, so WARM_PATHS are tried in order
    (/autocomplete/jobTitle passed 10/10 from GKE in the afternoon, the
    job-search redirect only in the morning);
  * warmed, /graph, /bff/company-compare/* and /job-search-next/bff/* pass
    from GKE; /bff/employer-profile-mono/* is challenged there even with
    every cookie (it passes from the office IP) — so everything that has a
    /graph root uses it, and only salary reports still need that backend;
  * a warmed session keeps passing until Cloudflare's rate rule answers
    429 after a few hundred rapid calls from one IP.
So calls share a small pool of warmed sessions; a session is retired on its
first 401 / 403 / 429 or after config.GLASSDOOR_REQUESTS_PER_SESSION calls,
and a call is retried on freshly warmed sessions up to
config.GLASSDOOR_MAX_ATTEMPTS times (with a longer pause after a 429). When
every attempt was challenged, one headful patchright Chrome loads the
job-search page (Cloudflare's JS challenge runs and clears) and repeats the
call as an in-page fetch; that browser stays open for
config.GLASSDOOR_BROWSER_IDLE_SECONDS, and the challenged backend goes
straight to the browser for CURL_BLOCKED_TTL.

Residential exits are worse than datacenter egress here (residential
us/gb/ca/de: 6/6 challenged on the warm-up), so config.GLASSDOOR_PROXY_COUNTRIES
is empty by default.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  GlassdoorUpstreamError  transport failure / 5xx / unexpected body — retryable
  GlassdoorBlocked        Cloudflare challenge / 401 / 429 everywhere — retryable
  GlassdoorBadRequest     upstream 400 (params it rejects)            — never retried
  GlassdoorNotFound       the entity does not exist                  — never retried
"""
import json
import os
import random
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.glassdoor.com"
IMPERSONATE = "chrome"
TIMEOUT = (10, 40)          # (connect, read)

NAV_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9", "sec-fetch-dest": "document", "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none", "sec-fetch-user": "?1", "upgrade-insecure-requests": "1",
}
API_HEADERS = {
    "accept": "*/*", "accept-language": "en-US,en;q=0.9", "content-type": "application/json",
    "gd-csrf-token": "1", "origin": SITE, "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}
GET_JSON_HEADERS = {
    "accept": "application/json", "accept-language": "en-US,en;q=0.9", "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
}
# Common one-word searches: the warm-up URL varies so every session does not
# open with the same request.
WARM_KEYWORDS = ("nurse", "driver", "engineer", "analyst", "teacher", "manager", "sales",
                 "accountant", "designer", "developer", "cashier", "pharmacist")
# Warm-up candidates, tried in order until one sets a Glassdoor cookie.
# Cloudflare's per-path rules drift: on 2026-09-26 the GKE egress passed the
# job-search redirect in the morning and only the /autocomplete/jobTitle GET
# by the afternoon (the others answered 403 there), while the office IP
# passed all of them.
WARM_PATHS = (("/autocomplete/jobTitle?term={kw}", "json"),
              ("/Job/jobs.htm?sc.keyword={kw}", "page"),
              ("/autocomplete/employers?term={kw}", "json"),
              ("/Community/index.htm", "page"))
WARM_COOKIES = ("gdsid", "gdId")
CHALLENGE_MARKERS = ("<title>Security | Glassdoor", "cf-mitigated", "Just a moment", "challenge-platform")
BLOCK_STATUSES = (401, 403, 429)
BROWSER_WARM_URL = SITE + "/Job/jobs.htm?sc.keyword=software%20engineer"
BROWSER_SETTLE_TIMEOUT = 30
RATE_LIMIT_BACKOFF = 2.0    # seconds x attempt after a 429
CURL_BLOCKED_TTL = 600      # a backend challenged on every curl attempt goes straight to the browser this long


class GlassdoorUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected body — retryable."""


class GlassdoorBlocked(GlassdoorUpstreamError, Blocked):
    """Cloudflare challenge (403), bot check (401) or rate limit (429)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class GlassdoorBadRequest(BadRequest):
    """Glassdoor answered 400 to params it does not accept."""


class GlassdoorNotFound(NotFound):
    """The company / job / post does not exist — never retried."""


def dump_debug(name, text):
    """Write a raw response to $GLASSDOOR_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("GLASSDOOR_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text if isinstance(text, str) else json.dumps(text))
        except OSError:
            pass


# ---- warmed sessions ------------------------------------------------------------------
# A curl_cffi Session is not thread-safe, so a session is checked OUT for the
# duration of one call and returned afterwards; idle sessions wait in `_idle`.

class _Session:
    __slots__ = ("sess", "used", "proxy")

    def __init__(self, sess, proxy):
        self.sess = sess
        self.proxy = proxy
        self.used = 0

    def close(self):
        try:
            self.sess.close()
        except Exception:
            pass


_idle = []
_idle_lock = threading.Lock()


def _budget():
    return max(1, int(config.GLASSDOOR_REQUESTS_PER_SESSION))


def _warm():
    """A new session whose warm-up request set the Glassdoor cookies (the
    first of WARM_PATHS that passes)."""
    from curl_cffi import requests as curl_requests
    proxy = config.glassdoor_proxy()
    sess = curl_requests.Session(impersonate=IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    statuses = []
    for path, kind in WARM_PATHS:
        url = SITE + path.format(kw=random.choice(WARM_KEYWORDS))
        headers = NAV_HEADERS if kind == "page" else {**GET_JSON_HEADERS, "referer": SITE + "/Job/index.htm"}
        try:
            resp = sess.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=False)
        except Exception as e:
            statuses.append(f"{type(e).__name__}")
            continue
        statuses.append(str(resp.status_code))
        if any(sess.cookies.get(name) for name in WARM_COOKIES):
            return _Session(sess, proxy)
    sess.close()
    if any(s.isdigit() and int(s) in BLOCK_STATUSES for s in statuses):
        raise GlassdoorBlocked(f"every warm-up was challenged ({', '.join(statuses)})", status=403)
    raise GlassdoorUpstreamError(f"no warm-up set session cookies ({', '.join(statuses)})")


def _checkout(fresh=False):
    if not fresh:
        with _idle_lock:
            if _idle:
                return _idle.pop()
    return _warm()


def _checkin(session):
    session.used += 1
    if session.used >= _budget():
        session.close()
        return
    with _idle_lock:
        _idle.append(session)


def reset_sessions():
    """Drop every idle session (tests, or after a burst of blocks)."""
    with _idle_lock:
        sessions, _idle[:] = list(_idle), []
    for session in sessions:
        session.close()


# ---- classification ---------------------------------------------------------------------

def _is_challenge(status, text, headers):
    if (headers or {}).get("cf-mitigated"):
        return True
    return status in BLOCK_STATUSES and any(m in (text or "")[:4000] for m in CHALLENGE_MARKERS)


def classify(status, text, headers, label):
    """Raise the failure a response represents, or return its text."""
    text = text or ""
    if status in BLOCK_STATUSES or _is_challenge(status, text, headers):
        dump_debug("blocked", text[:5000])
        raise GlassdoorBlocked(f"HTTP {status} on {label}", status=status)
    if status == 404:
        raise GlassdoorNotFound(f"glassdoor has nothing for {label}")
    if status == 400:
        dump_debug("bad_request", text[:5000])
        raise GlassdoorBadRequest(f"glassdoor rejected {label}")
    if status in (301, 302, 303, 307, 308):
        raise GlassdoorUpstreamError(f"unexpected redirect on {label}")
    if status != 200:
        raise GlassdoorUpstreamError(f"HTTP {status} on {label}")
    return text


def _parse_json(text, label):
    try:
        return json.loads(text) if text.strip() else None
    except ValueError:
        dump_debug("non_json", text)
        if any(m in text[:4000] for m in CHALLENGE_MARKERS):
            raise GlassdoorBlocked(f"challenge page on {label}")
        raise GlassdoorUpstreamError(f"non-JSON body on {label}")


# ---- browser fallback ---------------------------------------------------------------------

class _Browser:
    """One headful patchright Chrome, opened on demand, reused while busy
    and closed after config.GLASSDOOR_BROWSER_IDLE_SECONDS unused."""

    def __init__(self):
        self.lock = threading.Lock()
        self.driver = None
        self.last_used = 0.0
        self.closer = None

    def _open(self):
        from chrome_manager import create_scope
        from patchright_driver import PatchrightDriver
        with create_scope():
            driver = PatchrightDriver(proxy_url=config.glassdoor_proxy(), headless=False)
        try:
            driver.nav(BROWSER_WARM_URL, mode="blocked", challenge_markers=("Just a moment", "Security | Glassdoor"))
            deadline = time.monotonic() + BROWSER_SETTLE_TIMEOUT
            while time.monotonic() < deadline:
                names = {c.get("name") for c in driver.cookies()}
                if all(name in names for name in WARM_COOKIES):
                    break
                time.sleep(1.0)
            else:
                raise GlassdoorBlocked("browser never cleared the Cloudflare challenge")
        except Exception:
            driver.close()
            raise
        return driver

    def _close_if_idle(self):
        while True:
            time.sleep(30)
            with self.lock:
                if self.driver is None:
                    self.closer = None
                    return
                if time.time() - self.last_used > config.GLASSDOOR_BROWSER_IDLE_SECONDS:
                    self._drop()
                    self.closer = None
                    return

    def _drop(self):
        if self.driver is not None:
            try:
                self.driver.close()
            except Exception:
                pass
        self.driver = None

    def request(self, method, path_and_query, headers, body, label):
        """In-page fetch of a same-origin path. The page may sit on a local
        TLD (page GETs are GeoIP-redirected: glassdoor.co.in from India), and
        a cross-origin POST to www.glassdoor.com would fail CORS, so the call
        goes to the page's own origin."""
        from urllib.parse import urlsplit
        from patchright_driver import _FETCH_JS, FETCH_TIMEOUT_MS
        with self.lock:
            if self.driver is None:
                self.driver = self._open()
            if self.closer is None:
                self.closer = threading.Thread(target=self._close_if_idle, daemon=True)
                self.closer.start()
            self.last_used = time.time()
            try:
                parts = urlsplit(self.driver.current_url or "")
                origin = f"{parts.scheme}://{parts.netloc}" if parts.netloc else SITE
                res = self.driver.call(lambda page: page.evaluate(_FETCH_JS, {
                    "url": origin + path_and_query, "method": method, "headers": headers, "body": body,
                    "referrer": origin + "/Job/index.htm", "timeoutMs": FETCH_TIMEOUT_MS}))
            except Exception:
                self._drop()
                raise
        if not res or (not res.get("status") and res.get("error")):
            raise GlassdoorUpstreamError(f"browser fetch failed on {label}: {(res or {}).get('error')}")
        status = int(res.get("status") or 0)
        text = res.get("body") or ""
        if status in BLOCK_STATUSES:
            with self.lock:
                self._drop()
        return classify(status, text, res.get("headers") or {}, label)


_browser = _Browser()


# ---- requests -------------------------------------------------------------------------------
# Cloudflare's rules are per path: from the GKE egress every
# /bff/employer-profile-mono/* call is challenged while /graph passes. A
# backend that just failed every curl attempt is remembered for
# CURL_BLOCKED_TTL so the next calls skip the doomed attempts.

_curl_blocked = {}
_curl_blocked_lock = threading.Lock()


def _backend(path):
    """'/bff/employer-profile-mono/recent-salaries' -> '/bff/employer-profile-mono'."""
    parts = [p for p in path.split("?")[0].split("/") if p]
    return "/" + "/".join(parts[:2]) if parts[:1] == ["bff"] else "/" + (parts[0] if parts else "")


def _curl_is_blocked(path):
    with _curl_blocked_lock:
        until = _curl_blocked.get(_backend(path), 0)
    return until > time.monotonic()


def _mark_curl_blocked(path):
    with _curl_blocked_lock:
        _curl_blocked[_backend(path)] = time.monotonic() + CURL_BLOCKED_TTL


def _request(method, path, *, params=None, body=None, headers=None, label=None):
    """One call through the session pool (retries on fresh sessions, then the
    browser) -> response text."""
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    path_and_query = path + (("?" + urlencode(query)) if query else "")
    url = SITE + path_and_query
    label = label or path
    data = json.dumps(body, separators=(",", ":")) if body is not None else None
    last = None
    blocked_only = True
    attempts = max(1, int(config.GLASSDOOR_MAX_ATTEMPTS))
    if config.GLASSDOOR_BROWSER_FALLBACK and _curl_is_blocked(path):
        attempts = 0
        last = GlassdoorBlocked(f"{_backend(path)} is challenged for curl; using the browser", status=403)
    for attempt in range(1, attempts + 1):
        session = None
        rate_limited = False
        try:
            session = _checkout(fresh=attempt > 1)
            resp = session.sess.request(method, url, headers=headers, data=data,
                                        timeout=TIMEOUT, allow_redirects=False)
            text = classify(resp.status_code, resp.text, resp.headers, label)
            _checkin(session)
            return text
        except GlassdoorBlocked as e:
            last = e
            rate_limited = e.status == 429
            if session is not None:
                session.close()
        except (GlassdoorNotFound, GlassdoorBadRequest):
            if session is not None:
                _checkin(session)
            raise
        except GlassdoorUpstreamError as e:
            last, blocked_only = e, False
            if session is not None:
                session.close()
        except Exception as e:
            last, blocked_only = GlassdoorUpstreamError(f"request failed on {label}: {type(e).__name__}: {e}"), False
            if session is not None:
                session.close()
        print(f"glassdoor: attempt {attempt}/{attempts} on {label} failed: {last}")
        if attempt < attempts:
            # a 429 is Cloudflare's per-IP rate rule: a fresh session on the
            # same egress only helps after a pause
            time.sleep(RATE_LIMIT_BACKOFF * attempt if rate_limited else 0.4 * attempt)
    if blocked_only and config.GLASSDOOR_BROWSER_FALLBACK:
        if attempts:
            print(f"glassdoor: every curl attempt on {label} was challenged; trying the browser")
            if getattr(last, "status", None) != 429:
                _mark_curl_blocked(path)
        try:
            return _browser.request(method, path_and_query, {k: v for k, v in (headers or {}).items()
                                                  if k not in ("origin", "referer") and not k.startswith("sec-")},
                                    data, label)
        except (GlassdoorNotFound, GlassdoorBadRequest):
            raise
        except Exception as e:
            print(f"glassdoor: browser fallback failed on {label}: {type(e).__name__}: {e}")
            raise GlassdoorBlocked(f"{label}: challenged on {attempts} sessions and in a browser") from e
    raise last


def _api_headers(referer):
    return {**API_HEADERS, "referer": SITE + (referer or "/")}


def post_json(path, body, referer=None, label=None, extra_headers=None):
    """POST a JSON body -> parsed JSON."""
    headers = _api_headers(referer)
    if extra_headers:
        headers.update(extra_headers)
    label = label or path
    return _parse_json(_request("POST", path, body=body, headers=headers, label=label), label)


def get_json(path, params=None, referer="/Job/index.htm", label=None):
    """GET a JSON endpoint (/autocomplete/*) -> parsed JSON."""
    label = label or path
    headers = {**GET_JSON_HEADERS, "referer": SITE + referer}
    return _parse_json(_request("GET", path, params=params, headers=headers, label=label), label)


def _raise_graph_errors(payload, label, data_key):
    """GraphQL / BFF bodies carry {data, errors}. A null result with errors
    is a failure; errors next to usable data are ignored (partial data)."""
    if not isinstance(payload, dict):
        raise GlassdoorUpstreamError(f"unexpected body on {label}")
    data = payload.get("data")
    errors = payload.get("errors") or []
    result = data.get(data_key) if isinstance(data, dict) and data_key else data
    if result is None and errors:
        messages = "; ".join(str((e or {}).get("message") or e) for e in errors)[:300]
        details = json.dumps(errors)[:600]
        dump_debug("graph_error", details)
        if "Incorrect input data" in details or '"status": 400' in details:
            raise GlassdoorBadRequest(f"glassdoor rejected the {label} input")
        raise GlassdoorUpstreamError(f"{label}: {messages}")
    return data if isinstance(data, dict) else {}


def graph(query, variables=None, label="graph", client="reviews", data_key=None, referer="/Job/index.htm"):
    """POST /graph (one operation) -> the `data` object. `data_key` names the
    root field whose null-with-errors means failure."""
    body = [{"operationName": None, "variables": variables or {}, "query": query}]
    payload = post_json("/graph", body, referer=referer, label=label,
                        extra_headers={"apollographql-client-name": client, "apollographql-client-version": "1.0"})
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return _raise_graph_errors(payload, label, data_key)


def bff(path, args, label=None, data_key=None, referer="/Job/index.htm"):
    """POST a /bff/... backend -> its `data` object."""
    label = label or path.rsplit("/", 1)[-1]
    payload = post_json(path, args, referer=referer, label=label)
    return _raise_graph_errors(payload, label, data_key)


# ---- memo + fan-out -------------------------------------------------------------------------
# Resolutions (company name -> id, job title -> id, place -> location) and
# pagination cursors are reused across calls.

_memo = OrderedDict()
_memo_lock = threading.Lock()
MEMO_TTL = 3600
MEMO_MAX = 2048


def memoized(key, fn, ttl=MEMO_TTL):
    now = time.monotonic()
    with _memo_lock:
        hit = _memo.get(key)
        if hit and now - hit[0] < ttl:
            _memo.move_to_end(key)
            return hit[1]
    value = fn()
    with _memo_lock:
        _memo[key] = (now, value)
        _memo.move_to_end(key)
        while len(_memo) > MEMO_MAX:
            _memo.popitem(last=False)
    return value


def memo_get(key):
    with _memo_lock:
        hit = _memo.get(key)
        return hit[1] if hit else None


def memo_put(key, value):
    with _memo_lock:
        _memo[key] = (time.monotonic(), value)
        _memo.move_to_end(key)
        while len(_memo) > MEMO_MAX:
            _memo.popitem(last=False)


def run_parallel(fns, workers):
    """Run zero-arg callables in parallel; results align with `fns`. Each
    result is ("ok", value) or ("error", exception)."""
    def guard(fn):
        try:
            return ("ok", fn())
        except Exception as e:
            return ("error", e)
    if not fns:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(fns)))) as ex:
        return list(ex.map(guard, fns))


if __name__ == "__main__":
    # Smoke test: python glassdoor/fetch.py [employer id]
    eid = int(sys.argv[1]) if len(sys.argv) > 1 else 9079
    print(graph("query Q($id: Int!) { employer(id: $id) { id shortName } }", {"id": eid}, data_key="employer"))
