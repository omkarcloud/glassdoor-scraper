"""/glassdoor/community/* — Glassdoor Community (Fishbowl): bowls (topic
and company groups), their posts, single posts and comment threads.

Every call is the site's own Fishbowl GraphQL document (glassdoor/graphql/*)
sent to /graph. Bowl posts come as one ranked list (no cursor: the upstream
rejects every cursor form), so the route takes a `limit`; comments are
cursor-paged and walked forward like job search."""
from glassdoor import fetch
from glassdoor import parsers as P
from glassdoor import queries as Q

POST_SORTS = {"recent": "byDate", "top": "byPoints", "most_commented": "comments", "most_voted": "byVotes",
              "most_helpful": "helpful"}
COMMENT_SORTS = {"top": "POINTS", "most_liked": "LIKES", "most_replies": "REPLIES"}
COMMENTS_PER_PAGE = 20


def _graph(name, variables, label, data_key):
    return fetch.graph(Q.document(name), variables, label=label, client="fishbowl", data_key=data_key,
                       referer="/Community/index.htm")


def bowl_details(bowl):
    data = _graph("bowl_details", {"params": {"idOrHandleUrl": bowl}}, f"bowl {bowl}", "getBowlDetailsCG")
    out = P.bowl(data.get("getBowlDetailsCG"))
    if not out:
        raise fetch.GlassdoorNotFound(f"glassdoor has no community bowl '{bowl}'")
    return out


def related_bowls(bowl):
    data = _graph("related_bowls", {"params": {"idOrHandleUrl": bowl}}, f"related bowls {bowl}", "getExploreBowlsCG")
    rows = (data.get("getExploreBowlsCG") or {}).get("bowls") or []
    return {"bowls": [b for b in (P.bowl(r) for r in rows) if b]}


def bowl_posts(bowl, sort="recent", limit=20):
    data = _graph("bowl_posts", {"params": {"idOrHandleUrl": bowl}, "query": {"sort": POST_SORTS[sort], "count": limit}},
                  f"bowl posts {bowl}", "getBowlPostsCG")
    rows = (data.get("getBowlPostsCG") or {}).get("posts") or []
    # posts come without their bowl; links need the bowl's handle, not its id
    handle = fetch.memoized(("bowl_handle", bowl), lambda: bowl_details(bowl)["handle"]) if _is_id(bowl) else bowl
    return {"posts": [p for p in (P.post(r, bowl_handle=handle) for r in rows) if p]}


def post_details(post):
    data = _graph("post_details", {"params": {"idOrHandleUrl": post}}, f"post {post}", "getFishbowlPostCG")
    out = P.post(data.get("getFishbowlPostCG"))
    if not out:
        raise fetch.GlassdoorNotFound(f"glassdoor has no community post '{post}'")
    return out


def _is_id(value):
    return len(value) == 24 and all(c in "0123456789abcdef" for c in value)


def _post_id(post):
    """Comments are keyed by the post's 24-hex id; a handle is resolved once."""
    if _is_id(post):
        return post
    return fetch.memoized(("post_id", post), lambda: post_details(post)["id"])


def post_comments(post, sort="top", page=1):
    post_id = _post_id(post)
    key = ("comment_cursors", post_id, sort)
    # a copy: the memoized dict is shared with concurrent requests
    cursors = dict(fetch.memo_get(key) or {1: None})
    start = max(n for n in cursors if n <= page)
    raw = None
    for number in range(start, page + 1):
        if number not in cursors:
            raise fetch.GlassdoorNotFound(f"page {page} is past the last page of comments")
        data = _graph("post_comments", {"id": post_id, "cursor": cursors[number], "count": COMMENTS_PER_PAGE,
                                        "sortType": COMMENT_SORTS[sort]}, f"comments {post_id}", "getFishbowlPostComments")
        raw = data.get("getFishbowlPostComments") or {}
        next_cursor = (raw.get("commentsCursor") or {}).get("next")
        if next_cursor:
            cursors[number + 1] = next_cursor
        fetch.memo_put(key, cursors)
    comments = [c for c in (P.comment(r) for r in raw.get("comments") or []) if c]
    has_next = bool((raw.get("commentsCursor") or {}).get("next"))
    return {"pagination": {"page": page, "items_per_page": COMMENTS_PER_PAGE,
                           "total_pages": page + 1 if has_next else page, "total_count": None},
            "post_id": post_id, "comments": comments}
