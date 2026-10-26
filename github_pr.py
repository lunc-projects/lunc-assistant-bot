"""GitHub pull-request data for the LUNC Assistant Bot (2026-10-25).

Read-only, unauthenticated GitHub REST API calls (public repos only).
Unauthenticated rate limit is 60 requests/hour per source IP — the
poller dedupes repos across groups and caches per-repo state so a cycle
costs only a handful of calls per watched repo.

Everything network-shaped goes through gh_get(), which tests replace
with a fake. The diff logic (diff_events) is pure: fetched JSON in,
(events, new_state) out, so the poller is unit-testable end to end.
"""
import os, re, time, datetime
import httpx

GH_API = "https://api.github.com"
UA_HEADERS = {"User-Agent": "LUNC-Assistant-Bot", "Accept": "application/vnd.github+json"}

# Repos a group follows when it turns /pralerts on with none configured.
DEFAULT_REPOS = ["terra-classic-io/website", "classic-terra/core"]

REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$")
PR_URL_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/(\d+)")
PULL_NUM_RE = re.compile(r"/pull/(\d+)")


class GhError(Exception):
    """A GitHub fetch failed. status is the HTTP status (0 = network)."""
    def __init__(self, status, message=""):
        super().__init__(message or f"GitHub HTTP {status}")
        self.status = status


def is_rate_limited(err):
    return isinstance(err, GhError) and err.status in (403, 429)


async def gh_get(path, client=None):
    """GET api.github.com<path> -> parsed JSON. Raises GhError."""
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=20, headers=UA_HEADERS,
                                   proxy=os.getenv("OUTBOUND_PROXY") or None)
    try:
        r = await client.get(f"{GH_API}{path}")
        if r.status_code != 200:
            raise GhError(r.status_code, f"GET {path} -> {r.status_code}")
        return r.json()
    except GhError:
        raise
    except Exception as e:
        raise GhError(0, str(e))
    finally:
        if own:
            await client.aclose()


def valid_repo(s):
    return bool(s and REPO_RE.match(s.strip()))


def parse_pr_args(args, watched_repos):
    """Resolve /pr arguments to (repo, number, error).

    Forms: /pr <owner/repo> <number> · /pr <full PR URL> ·
    /pr <number> (only when the chat watches exactly one repo).
    """
    args = [a for a in (args or []) if a]
    if not args:
        return None, None, "Usage: /pr <owner/repo> <number> — or /pr <PR link>, or just /pr <number> if this chat watches one repo."
    joined = " ".join(args)
    m = PR_URL_RE.search(joined)
    if m:
        return m.group(1), int(m.group(2)), None
    if len(args) >= 2 and valid_repo(args[0]):
        try:
            return args[0], int(args[1]), None
        except ValueError:
            return None, None, f"'{args[1]}' isn't a PR number."
    if len(args) == 1:
        if valid_repo(args[0]):
            return None, None, "Add the PR number too: /pr " + args[0] + " <number>"
        try:
            num = int(args[0])
        except ValueError:
            return None, None, "Usage: /pr <owner/repo> <number> — or /pr <PR link>."
        watched = list(watched_repos or [])
        if len(watched) == 1:
            return watched[0], num, None
        if not watched:
            return None, None, "This chat isn't watching any repo yet — give me one: /pr <owner/repo> <number>."
        return None, None, "This chat watches more than one repo — name one: /pr <owner/repo> <number>."
    return None, None, "Usage: /pr <owner/repo> <number> — or /pr <PR link>."


def excerpt(text, limit=300):
    """One-line, tag-free excerpt of a GitHub body/comment."""
    if not text:
        return ""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", str(text))       # ![img](url)
    t = re.sub(r"<[^>]+>", "", t)                              # <img ...> etc.
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[:limit].rstrip() + "…"
    return t


def _iso_to_epoch(s):
    try:
        return int(datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def pr_state_label(pr):
    if pr.get("merged_at") or pr.get("merged"):
        return "✅ Merged"
    if pr.get("state") == "closed":
        return "❌ Closed"
    if pr.get("draft"):
        return "📝 Open (draft)"
    return "🟢 Open"


async def fetch_pr_detail(repo, number, fetch=None):
    """(pr_dict, latest_comment_dict_or_None) for /pr. Raises GhError."""
    fetch = fetch or gh_get
    pr = await fetch(f"/repos/{repo}/pulls/{number}")
    latest = None
    try:
        comments = await fetch(f"/repos/{repo}/issues/{number}/comments?per_page=30&sort=created&direction=desc")
        if comments:
            latest = comments[0]
    except GhError:
        latest = None  # detail matters more than the comment garnish
    return pr, latest


def format_pr_detail(repo, pr, latest_comment=None):
    n = pr.get("number")
    lines = [f"🔀 PR #{n} — {repo}",
             pr.get("title", ""),
             f"State: {pr_state_label(pr)} · by {(pr.get('user') or {}).get('login', '?')}"]
    if pr.get("additions") is not None:
        lines.append(f"Files: {pr.get('changed_files', 0)} changed · +{pr.get('additions', 0)} −{pr.get('deletions', 0)}")
    lines.append(f"Created: {str(pr.get('created_at', ''))[:10]} · Updated: {str(pr.get('updated_at', ''))[:16].replace('T', ' ')} UTC")
    body = excerpt(pr.get("body"), 300)
    if body:
        lines.append("")
        lines.append(body)
    if latest_comment:
        who = (latest_comment.get("user") or {}).get("login", "?")
        cbody = excerpt(latest_comment.get("body"), 200)
        if cbody:
            lines.append("")
            lines.append(f"💬 Latest comment — {who}:")
            lines.append(f"> {cbody}")
    lines.append(pr.get("html_url", f"https://github.com/{repo}/pull/{n}"))
    return "\n".join(lines)


# ------------------------- notification events -------------------------

def format_event(ev):
    """One notification message, shaped like Steve's example:
    💬 <actor> commented on PR #<n> — <repo> / <title> / > <excerpt> / <url>"""
    repo, n = ev["repo"], ev["number"]
    kind = ev["kind"]
    if kind == "comment":
        head = f"💬 {ev['actor']} commented on PR #{n} — {repo}"
    elif kind == "review":
        head = f"👀 {ev['actor']} reviewed PR #{n} — {repo}"
        state = {"APPROVED": "approved ✅", "CHANGES_REQUESTED": "requested changes 🔁",
                 "COMMENTED": "commented", "DISMISSED": "dismissed"}.get(ev.get("review_state", ""), "")
        if state:
            head += f" ({state})"
    elif kind == "opened":
        head = f"🆕 {ev['actor']} opened PR #{n} — {repo}"
    elif kind == "ready":
        head = f"👀 PR #{n} is ready for review — {repo}"
    elif kind == "merged":
        head = f"✅ PR #{n} merged — {repo}"
    elif kind == "closed":
        head = f"❌ PR #{n} closed — {repo}"
    else:
        head = f"🔀 PR #{n} — {repo}"
    lines = [head]
    if ev.get("title"):
        lines.append(ev["title"])
    body = excerpt(ev.get("body"), 200)
    if body:
        lines.append(f"> {body}")
    if ev.get("url"):
        lines.append(ev["url"])
    return "\n".join(lines)


def _pr_snapshot(pr, prev=None):
    snap = {"state": pr.get("state"), "merged": bool(pr.get("merged_at") or pr.get("merged")),
            "draft": bool(pr.get("draft")), "updated_at": pr.get("updated_at", ""),
            "title": pr.get("title", ""), "reviews_last_id": (prev or {}).get("reviews_last_id", 0)}
    return snap


def init_state(prs, last_comment_id=0, last_review_comment_id=0, now_ts=None):
    """Snapshot a repo WITHOUT emitting history (cursor init, no backfill)."""
    return {"init_ts": int(now_ts if now_ts is not None else time.time()),
            "last_comment_id": int(last_comment_id or 0),
            "last_review_comment_id": int(last_review_comment_id or 0),
            "prs": {str(pr["number"]): _pr_snapshot(pr) for pr in prs}}


def diff_events(repo, state, prs, comments, review_comments, reviews_by_pr,
                skip_logins=()):
    """Pure diff: (events, new_state). All lists are raw GitHub JSON dicts;
    comments/review_comments ascending by id, reviews_by_pr {number: [reviews]}.
    skip_logins: actors to never notify about (the bot's own identity)."""
    skip = {s.lower() for s in (skip_logins or ())}
    old_prs = state.get("prs", {})
    new_prs = dict(old_prs)
    events = []

    def actor_of(item):
        return ((item.get("user") or {}).get("login")) or "?"

    # --- PR state changes + opened/ready ---
    for pr in prs:
        num = str(pr["number"])
        prev = old_prs.get(num)
        new_prs[num] = _pr_snapshot(pr, prev)
        if prev is None:
            # Brand-new to our snapshot: only news if it appeared after we
            # started watching (older PRs entering the page aren't events).
            if _iso_to_epoch(pr.get("created_at")) >= state.get("init_ts", 0) - 300:
                events.append({"kind": "opened", "repo": repo, "number": pr["number"],
                               "title": pr.get("title", ""), "actor": actor_of(pr),
                               "body": pr.get("body"), "url": pr.get("html_url"),
                               "ts": _iso_to_epoch(pr.get("created_at"))})
            continue
        was, now = prev.get("state"), pr.get("state")
        if was == "open" and now == "closed":
            merged = bool(pr.get("merged_at") or pr.get("merged"))
            events.append({"kind": "merged" if merged else "closed", "repo": repo,
                           "number": pr["number"], "title": pr.get("title", ""),
                           "actor": actor_of(pr), "body": "",
                           "url": pr.get("html_url"),
                           "ts": _iso_to_epoch(pr.get("updated_at"))})
        elif was == "open" and now == "open" and prev.get("draft") and not pr.get("draft"):
            events.append({"kind": "ready", "repo": repo, "number": pr["number"],
                           "title": pr.get("title", ""), "actor": actor_of(pr),
                           "body": "", "url": pr.get("html_url"),
                           "ts": _iso_to_epoch(pr.get("updated_at"))})

    def title_for(num):
        s = new_prs.get(str(num)) or old_prs.get(str(num)) or {}
        return s.get("title", "")

    # --- issue comments that are on PRs (html_url contains /pull/) ---
    last_cid = state.get("last_comment_id", 0)
    max_cid = last_cid
    for c in comments or []:
        cid = c.get("id", 0)
        max_cid = max(max_cid, cid)
        if cid <= last_cid:
            continue
        url = c.get("html_url", "")
        m = PULL_NUM_RE.search(url)
        if not m:
            continue  # a plain issue comment, not a PR comment
        if actor_of(c).lower() in skip:
            continue
        num = int(m.group(1))
        events.append({"kind": "comment", "repo": repo, "number": num,
                       "title": title_for(num), "actor": actor_of(c),
                       "body": c.get("body"), "url": url,
                       "ts": _iso_to_epoch(c.get("created_at"))})

    # --- inline review comments (pulls/comments are PR-only) ---
    last_rid = state.get("last_review_comment_id", 0)
    max_rid = last_rid
    for c in review_comments or []:
        cid = c.get("id", 0)
        max_rid = max(max_rid, cid)
        if cid <= last_rid:
            continue
        if actor_of(c).lower() in skip:
            continue
        m = re.search(r"/pulls/(\d+)$", c.get("pull_request_url", ""))
        if not m:
            continue
        num = int(m.group(1))
        events.append({"kind": "comment", "repo": repo, "number": num,
                       "title": title_for(num), "actor": actor_of(c),
                       "body": c.get("body"), "url": c.get("html_url"),
                       "ts": _iso_to_epoch(c.get("created_at"))})

    # --- submitted reviews (only approvals / change requests / bodies) ---
    for num_s, reviews in (reviews_by_pr or {}).items():
        snap = new_prs.get(str(num_s))
        if snap is None:
            continue
        last_rev = snap.get("reviews_last_id", 0)
        max_rev = last_rev
        for rv in reviews or []:
            rid = rv.get("id", 0)
            max_rev = max(max_rev, rid)
            if rid <= last_rev:
                continue
            if actor_of(rv).lower() in skip:
                continue
            rstate = rv.get("state", "")
            if rstate not in ("APPROVED", "CHANGES_REQUESTED") and not excerpt(rv.get("body"), 10):
                continue  # silent review shells ride along with their comments
            events.append({"kind": "review", "repo": repo, "number": int(num_s),
                           "title": title_for(num_s), "actor": actor_of(rv),
                           "review_state": rstate, "body": rv.get("body"),
                           "url": rv.get("html_url"),
                           "ts": _iso_to_epoch(rv.get("submitted_at"))})
        snap["reviews_last_id"] = max_rev

    events.sort(key=lambda e: e.get("ts", 0))
    new_state = {"init_ts": state.get("init_ts", 0),
                 "last_comment_id": max_cid,
                 "last_review_comment_id": max_rid,
                 "prs": new_prs}
    return events, new_state


async def poll_repo(repo, state, fetch=None, skip_logins=(), now_ts=None):
    """One poll of one repo -> (events, new_state). Raises GhError.

    state None -> initialize cursors at 'now' and return no events, so a
    freshly watched repo never dumps its history into the group."""
    fetch = fetch or gh_get
    if state is None:
        prs = await fetch(f"/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100")
        latest_c = await fetch(f"/repos/{repo}/issues/comments?per_page=1&sort=created&direction=desc")
        latest_rc = await fetch(f"/repos/{repo}/pulls/comments?per_page=1&sort=created&direction=desc")
        return [], init_state(prs,
                              latest_c[0]["id"] if latest_c else 0,
                              latest_rc[0]["id"] if latest_rc else 0,
                              now_ts=now_ts)
    prs = await fetch(f"/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=50")
    old_prs = state.get("prs", {})
    changed = [pr for pr in prs
               if str(pr["number"]) in old_prs
               and old_prs[str(pr["number"])].get("updated_at") != pr.get("updated_at")
               and pr.get("state") == "open"][:10]
    reviews_by_pr = {}
    for pr in changed:
        try:
            reviews_by_pr[str(pr["number"])] = await fetch(
                f"/repos/{repo}/pulls/{pr['number']}/reviews?per_page=30")
        except GhError:
            pass  # one PR's reviews failing must not sink the whole cycle
    comments = await fetch(f"/repos/{repo}/issues/comments?per_page=100&sort=created&direction=desc")
    review_comments = await fetch(f"/repos/{repo}/pulls/comments?per_page=50&sort=created&direction=desc")
    return diff_events(repo, state, prs, list(reversed(comments)),
                       list(reversed(review_comments)), reviews_by_pr,
                       skip_logins=skip_logins)
