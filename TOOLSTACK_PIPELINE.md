# ToolStack — AI Tool Discovery Pipeline
> Automatically discovers freshly launched, undiscovered AI tools and generates ready-to-record YouTube scripts before anyone else covers them.

---

## Table of Contents

- [Architecture](#architecture)
- [Setup](#setup)
- [Project Structure](#project-structure)
- [Configuration — `.env`](#configuration--env)
- [Models — `models.py`](#models--modelspy)
- [Connectors](#connectors)
  - [Hacker News](#hacker-news--connectorshackernewspy)
  - [Reddit](#reddit--connectorsredditpy)
  - [GitHub](#github--connectorsgithubpy)
  - [Product Hunt](#product-hunt--connectorsproducthuntpy)
- [Filters — Gap Check](#filters--gap-check--filtersgap_checkpy)
- [Scoring](#scoring--scorerscorerpy)
- [Queue Manager](#queue-manager--queuemanagerpy)
- [Script Generator](#script-generator--utilsscript_generatorpy)
- [Orchestrator — `main.py`](#orchestrator--mainpy)
- [Requirements](#requirements--requirementstxt)
- [CLI Reference](#cli-reference)
- [Scoring Weights](#scoring-weights)
- [YouTube API Quota](#youtube-api-quota)
- [Running on a Schedule](#running-on-a-schedule)

---

## Architecture

```
main.py                  ← Orchestrator + CLI
├── connectors/
│   ├── hackernews.py    ← Show HN posts (no auth needed)
│   ├── reddit.py        ← r/SideProject, r/indiehackers, etc.
│   ├── github.py        ← Low-star AI repos via GitHub REST API
│   └── producthunt.py   ← New launches via GraphQL API
│
├── filters/
│   └── gap_check.py     ← YouTube API: video count + max views per tool
│
├── scoring/
│   └── scorer.py        ← 0–100 score across 5 signals
│
├── queue/
│   └── manager.py       ← SQLite persistence + queue state machine
│
└── utils/
    └── script_generator.py  ← Fetches landing page + calls Claude API
```

**Pipeline flow:**

```
Discover → Pre-filter → YouTube gap check → Score → Queue → Generate script
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Fill in your keys
```

| Key | Where to get it | Cost |
|-----|----------------|------|
| `YOUTUBE_API_KEY` | [console.cloud.google.com](https://console.cloud.google.com) → APIs → YouTube Data v3 | Free (10k units/day) |
| `REDDIT_CLIENT_ID` / `SECRET` | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → create app | Free |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Pay per use |
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) → classic token | Free |
| `PRODUCT_HUNT_TOKEN` | [api.producthunt.com/v2/oauth/applications](https://api.producthunt.com/v2/oauth/applications) | Free |

> YouTube and Reddit are highest priority. GitHub and Product Hunt improve coverage but are optional.

### 3. Run

```bash
python main.py run          # Full discovery cycle
python main.py queue        # Show queued tools
python main.py stats        # Pipeline stats
python main.py script <url> # Generate script for a queued tool
python main.py schedule     # Auto-run every 6 hours
```

---

## Project Structure

Create this folder layout before running:

```
toolstack/
├── connectors/
│   ├── __init__.py
│   ├── hackernews.py
│   ├── reddit.py
│   ├── github.py
│   └── producthunt.py
├── filters/
│   ├── __init__.py
│   └── gap_check.py
├── scoring/
│   ├── __init__.py
│   └── scorer.py
├── queue/
│   ├── __init__.py
│   └── manager.py
├── utils/
│   ├── __init__.py
│   └── script_generator.py
├── scripts/              ← Generated scripts saved here
├── config.py
├── models.py
├── main.py
├── requirements.txt
└── .env
```

---

## Configuration — `.env`

Create a `.env` file in the project root:

```ini
# ── Reddit ────────────────────────────────────────────────────────────────────
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=toolstack-scraper/1.0

# ── YouTube Data API v3 ───────────────────────────────────────────────────────
# Free tier: 10,000 units/day. A search costs 100 units → 100 searches/day free.
YOUTUBE_API_KEY=your_youtube_api_key

# ── GitHub (optional — raises rate limit from 60 to 5000 req/hr) ─────────────
GITHUB_TOKEN=your_github_token

# ── Product Hunt ─────────────────────────────────────────────────────────────
PRODUCT_HUNT_TOKEN=your_ph_token

# ── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=your_anthropic_key

# ── Pipeline thresholds ───────────────────────────────────────────────────────
FRESHNESS_DAYS=7
MAX_YT_VIEWS=5000
MAX_YT_VIDEOS=3
MIN_SCORE_THRESHOLD=40
DB_PATH=toolstack.db
```

---

## `config.py`

```python
"""
config.py — Central config. All env vars live here.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────────────────────────
REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = os.getenv("REDDIT_USER_AGENT", "toolstack-scraper/1.0")

YOUTUBE_API_KEY      = os.getenv("YOUTUBE_API_KEY", "")
GITHUB_TOKEN         = os.getenv("GITHUB_TOKEN", "")
PRODUCT_HUNT_TOKEN   = os.getenv("PRODUCT_HUNT_TOKEN", "")

# ── Pipeline thresholds ───────────────────────────────────────────────────────
FRESHNESS_DAYS       = int(os.getenv("FRESHNESS_DAYS", "7"))
MAX_YT_VIEWS         = int(os.getenv("MAX_YT_VIEWS", "5000"))
MAX_YT_VIDEOS        = int(os.getenv("MAX_YT_VIDEOS", "3"))
MIN_SCORE_THRESHOLD  = int(os.getenv("MIN_SCORE_THRESHOLD", "40"))
DB_PATH              = os.getenv("DB_PATH", "toolstack.db")
```

---

## Models — `models.py`

Single source of truth for what a "tool candidate" looks like across the pipeline.

```python
"""
models.py — Data model for a discovered tool candidate.
Every connector returns a list of ToolCandidate objects.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ToolCandidate:
    # ── Identity ──────────────────────────────────────────────────────────────
    name: str                          # Tool name as found in source
    url: str                           # Primary URL (landing page or repo)
    source: str                        # "hackernews" | "reddit" | "github" | "producthunt"
    source_url: str                    # Link to the original post/listing

    # ── Metadata ──────────────────────────────────────────────────────────────
    description: str = ""
    found_at: datetime = field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None

    # ── Social signals ────────────────────────────────────────────────────────
    upvotes: int = 0
    comments: int = 0
    stars: int = 0                     # GitHub stars

    # ── Gap check results ─────────────────────────────────────────────────────
    yt_video_count: int = -1           # -1 = not checked yet
    yt_max_views: int = -1
    yt_gap_passed: Optional[bool] = None

    # ── Scoring ───────────────────────────────────────────────────────────────
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)

    # ── Queue state ───────────────────────────────────────────────────────────
    queued: bool = False
    script_generated: bool = False
    skipped: bool = False
    skip_reason: str = ""

    def age_hours(self) -> float:
        """Hours since the source post was published."""
        if self.published_at is None:
            return 999.0
        return (datetime.utcnow() - self.published_at).total_seconds() / 3600

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "source": self.source,
            "source_url": self.source_url,
            "description": self.description,
            "found_at": self.found_at.isoformat(),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "upvotes": self.upvotes,
            "comments": self.comments,
            "stars": self.stars,
            "yt_video_count": self.yt_video_count,
            "yt_max_views": self.yt_max_views,
            "yt_gap_passed": self.yt_gap_passed,
            "score": self.score,
            "score_breakdown": self.score_breakdown,
            "queued": self.queued,
            "script_generated": self.script_generated,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }
```

---

## Connectors

### Hacker News — `connectors/hackernews.py`

Targets "Show HN" posts via Algolia's free HN API. No API key required.

```python
"""
connectors/hackernews.py

Pulls "Show HN" posts via Algolia's free HN API. No auth required.
Targets: Show HN posts, under 72 hours old, < 80 points, AI keywords.

Algolia HN docs: https://hn.algolia.com/api
"""
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from toolstack.models import ToolCandidate
from toolstack.config import FRESHNESS_DAYS

BASE_URL = "https://hn.algolia.com/api/v1/search"

AI_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "agent", "automation",
    "ml", "voice", "chatbot", "copilot", "generative", "openai",
    "model", "inference", "embedding", "rag", "multimodal",
]

MAX_POINTS_FOR_OBSCURE = 150


def _extract_url(hit: dict) -> str:
    return hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"


def _parse_date(ts: Optional[int]) -> Optional[datetime]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


def _is_ai_related(title: str, text: str) -> bool:
    combined = (title + " " + text).lower()
    return any(kw in combined for kw in AI_KEYWORDS)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_page(params: dict) -> dict:
    with httpx.Client(timeout=15) as client:
        r = client.get(BASE_URL, params=params)
        r.raise_for_status()
        return r.json()


def fetch(max_results: int = 50) -> list[ToolCandidate]:
    """Return ToolCandidate objects for Show HN AI tool posts."""
    cutoff = datetime.utcnow() - timedelta(days=FRESHNESS_DAYS)
    cutoff_ts = int(cutoff.timestamp())

    params = {
        "query": "Show HN",
        "tags": "show_hn",
        "numericFilters": f"created_at_i>{cutoff_ts},points<{MAX_POINTS_FOR_OBSCURE}",
        "hitsPerPage": min(max_results, 100),
    }

    data = _fetch_page(params)
    hits = data.get("hits", [])

    candidates: list[ToolCandidate] = []
    seen_urls: set[str] = set()

    for hit in hits:
        title = hit.get("title", "")
        text = hit.get("story_text") or ""
        url = _extract_url(hit)

        if not _is_ai_related(title, text):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        name = title.replace("Show HN:", "").replace("Show HN -", "").strip()
        for sep in [" – ", " - ", " (", " |"]:
            if sep in name:
                name = name.split(sep)[0].strip()

        candidates.append(
            ToolCandidate(
                name=name,
                url=url,
                source="hackernews",
                source_url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                description=text[:300].strip() if text else title,
                published_at=_parse_date(hit.get("created_at_i")),
                upvotes=hit.get("points", 0),
                comments=hit.get("num_comments", 0),
            )
        )

    return candidates
```

---

### Reddit — `connectors/reddit.py`

Watches key subreddits on the `new` feed — not `hot`. Hot already has upvotes.

```python
"""
connectors/reddit.py

Watches subreddits where founders post their tools before they blow up.
Uses the "new" feed — hot means it's already discovered.

Subreddits:
  r/SideProject, r/indiehackers, r/MachineLearning,
  r/singularity, r/ChatGPT, r/LocalLLaMA, r/OpenAI, r/artificial
"""
import re
import praw
from datetime import datetime, timedelta
from typing import Optional

from toolstack.models import ToolCandidate
from toolstack.config import (
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
    REDDIT_USER_AGENT, FRESHNESS_DAYS,
)

SUBREDDITS = [
    "SideProject", "indiehackers", "MachineLearning",
    "singularity", "ChatGPT", "LocalLLaMA", "OpenAI", "artificial",
]

LAUNCH_SIGNALS = [
    "i built", "i made", "we built", "we launched", "launch",
    "introducing", "show hn", "just released", "open source",
    "free tool", "check out", "built a", "made a",
]

AI_KEYWORDS = [
    "ai", "llm", "gpt", "agent", "automation", "ml", "voice",
    "chatbot", "copilot", "generative", "model", "inference",
    "embedding", "rag", "multimodal", "claude", "gemini",
]

PRODUCT_URL_PATTERNS = [
    r"github\.com", r"\.ai/", r"\.io/", r"\.app/",
    r"\.dev/", r"huggingface\.co", r"replicate\.com",
]


def _is_launch_post(title: str, selftext: str) -> bool:
    combined = (title + " " + selftext[:500]).lower()
    return any(sig in combined for sig in LAUNCH_SIGNALS)


def _is_ai_related(title: str, selftext: str) -> bool:
    combined = (title + " " + selftext[:500]).lower()
    return any(kw in combined for kw in AI_KEYWORDS)


def _extract_product_url(submission) -> Optional[str]:
    if not submission.is_self:
        url = submission.url
        if any(re.search(p, url) for p in PRODUCT_URL_PATTERNS):
            return url
    urls = re.findall(r'https?://[^\s\)\]]+', submission.selftext or "")
    for url in urls:
        if any(re.search(p, url) for p in PRODUCT_URL_PATTERNS):
            return url
    return f"https://reddit.com{submission.permalink}"


def _parse_name(title: str) -> str:
    title = re.sub(
        r'^(i built|i made|we built|we launched|introducing|built a|made a)\s*:?\s*',
        '', title, flags=re.IGNORECASE
    ).strip()
    for sep in [" – ", " - ", ": ", " (", " |"]:
        if sep in title:
            return title.split(sep)[0].strip()
    words = title.split()
    return " ".join(words[:5]) if len(words) > 5 else title


def fetch(max_per_sub: int = 30) -> list[ToolCandidate]:
    """Return ToolCandidate objects from Reddit new feeds."""
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        print("[reddit] ⚠ No credentials — skipping Reddit connector.")
        return []

    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    cutoff = datetime.utcnow() - timedelta(days=FRESHNESS_DAYS)
    candidates: list[ToolCandidate] = []
    seen_urls: set[str] = set()

    for sub_name in SUBREDDITS:
        try:
            subreddit = reddit.subreddit(sub_name)
            for post in subreddit.new(limit=max_per_sub):
                created = datetime.utcfromtimestamp(post.created_utc)
                if created < cutoff:
                    continue
                title = post.title or ""
                selftext = post.selftext or ""
                if not _is_ai_related(title, selftext):
                    continue
                if not _is_launch_post(title, selftext):
                    continue
                url = _extract_product_url(post)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                candidates.append(
                    ToolCandidate(
                        name=_parse_name(title),
                        url=url,
                        source="reddit",
                        source_url=f"https://reddit.com{post.permalink}",
                        description=(selftext[:300] or title).strip(),
                        published_at=created,
                        upvotes=post.score,
                        comments=post.num_comments,
                    )
                )
        except Exception as e:
            print(f"[reddit] ⚠ Error on r/{sub_name}: {e}")
            continue

    return candidates
```

---

### GitHub — `connectors/github.py`

Finds freshly created AI repos with low stars — highest credibility signal because the tool actually has working code.

```python
"""
connectors/github.py

Searches GitHub for freshly created AI repos with LOW stars.
A repo with 12 stars and an "ai-tools" topic is more valuable than
one with 3000 stars — that one's already discovered.

Rate limits: 10 req/min unauthenticated, 30/min with token.
"""
import httpx
from datetime import datetime, timedelta
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from toolstack.models import ToolCandidate
from toolstack.config import GITHUB_TOKEN, FRESHNESS_DAYS

SEARCH_URL = "https://api.github.com/search/repositories"

TOPICS = [
    "llm", "ai-tools", "ai-agent", "large-language-model",
    "generative-ai", "openai", "langchain", "rag", "voice-ai",
]

MAX_STARS = 100
MIN_STARS = 2


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=5, max=30))
def _search(query: str) -> list[dict]:
    params = {"q": query, "sort": "updated", "order": "desc", "per_page": 30}
    with httpx.Client(timeout=20, headers=_headers()) as client:
        r = client.get(SEARCH_URL, params=params)
        if r.status_code == 403:
            print("[github] ⚠ Rate limited")
            return []
        r.raise_for_status()
        return r.json().get("items", [])


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def _tool_name_from_repo(repo: dict) -> str:
    name = repo.get("name", "").replace("-", " ").replace("_", " ")
    return name.title()


def fetch(max_results: int = 60) -> list[ToolCandidate]:
    """Search GitHub for freshly created low-star AI repos."""
    cutoff = (datetime.utcnow() - timedelta(days=FRESHNESS_DAYS)).strftime("%Y-%m-%d")
    candidates: list[ToolCandidate] = []
    seen_urls: set[str] = set()

    for topic in TOPICS:
        query = (
            f"topic:{topic} "
            f"stars:{MIN_STARS}..{MAX_STARS} "
            f"pushed:>{cutoff} "
            f"fork:false"
        )
        try:
            items = _search(query)
        except Exception as e:
            print(f"[github] ⚠ Error on topic={topic}: {e}")
            continue

        for repo in items:
            html_url = repo.get("html_url", "")
            if not html_url or html_url in seen_urls:
                continue
            seen_urls.add(html_url)
            if repo.get("archived"):
                continue
            description = repo.get("description") or ""
            if not description:
                continue
            homepage = repo.get("homepage") or html_url
            candidates.append(
                ToolCandidate(
                    name=_tool_name_from_repo(repo),
                    url=homepage,
                    source="github",
                    source_url=html_url,
                    description=description[:300],
                    published_at=_parse_date(repo.get("created_at")),
                    stars=repo.get("stargazers_count", 0),
                )
            )

        if len(candidates) >= max_results:
            break

    return candidates[:max_results]
```

---

### Product Hunt — `connectors/producthunt.py`

Queries the PH GraphQL API for recently launched tools with low vote counts.

```python
"""
connectors/producthunt.py

Queries Product Hunt's GraphQL API for recently launched low-vote tools.
High vote count = already getting press = too late for us.

PH GraphQL playground: https://api.producthunt.com/v2/docs
"""
import httpx
from datetime import datetime, timedelta
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from toolstack.models import ToolCandidate
from toolstack.config import PRODUCT_HUNT_TOKEN, FRESHNESS_DAYS

GQL_URL = "https://api.producthunt.com/v2/api/graphql"
MAX_VOTES = 200

GQL_QUERY = """
query GetPosts($after: String, $postedAfter: DateTime) {
  posts(
    order: NEWEST
    after: $after
    postedAfter: $postedAfter
    topic: "artificial-intelligence"
  ) {
    edges {
      node {
        id name tagline url votesCount commentsCount createdAt website
        topics { edges { node { name } } }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {PRODUCT_HUNT_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=20))
def _gql(variables: dict) -> dict:
    with httpx.Client(timeout=20) as client:
        r = client.post(
            GQL_URL,
            json={"query": GQL_QUERY, "variables": variables},
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)
    except ValueError:
        return None


def fetch(max_results: int = 50) -> list[ToolCandidate]:
    """Return ToolCandidate objects from Product Hunt new launches."""
    if not PRODUCT_HUNT_TOKEN:
        print("[producthunt] ⚠ No token — skipping.")
        return []

    cutoff = (datetime.utcnow() - timedelta(days=FRESHNESS_DAYS)).strftime(
        "%Y-%m-%dT00:00:00+00:00"
    )

    candidates: list[ToolCandidate] = []
    seen_ids: set[str] = set()
    cursor: Optional[str] = None

    while len(candidates) < max_results:
        variables = {"postedAfter": cutoff}
        if cursor:
            variables["after"] = cursor

        try:
            data = _gql(variables)
        except Exception as e:
            print(f"[producthunt] ⚠ GraphQL error: {e}")
            break

        posts = data.get("data", {}).get("posts", {})
        edges = posts.get("edges", [])

        for edge in edges:
            node = edge.get("node", {})
            pid = node.get("id", "")
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            if node.get("votesCount", 0) > MAX_VOTES:
                continue

            topic_edges = node.get("topics", {}).get("edges", [])
            topic_names = [t["node"]["name"] for t in topic_edges]
            url = node.get("website") or node.get("url", "")
            if not url:
                continue

            description = node.get("tagline", "")
            if topic_names:
                description += f" | Topics: {', '.join(topic_names[:3])}"

            candidates.append(
                ToolCandidate(
                    name=node.get("name", "Unknown"),
                    url=url,
                    source="producthunt",
                    source_url=node.get("url", ""),
                    description=description[:300],
                    published_at=_parse_date(node.get("createdAt")),
                    upvotes=node.get("votesCount", 0),
                    comments=node.get("commentsCount", 0),
                )
            )

        page_info = posts.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return candidates[:max_results]
```

---

## Filters — Gap Check — `filters/gap_check.py`

The most critical filter in the pipeline. Uses YouTube Data API v3.

> **Quota note:** Each gap check costs ~200 units (100 search + 100 stats).
> Free tier = 10,000 units/day → **50 gap checks/day for free.**

```python
"""
filters/gap_check.py

For each tool candidate, searches YouTube and checks:
  1. How many videos exist about it?
  2. What is the max view count of those videos?

If either threshold is exceeded, the tool is disqualified.

YouTube Data API v3:
  - Search:  100 units per call
  - Videos:  1 unit per call
  - Free:    10,000 units/day → ~50 gap checks/day
"""
import httpx
import time
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from toolstack.models import ToolCandidate
from toolstack.config import YOUTUBE_API_KEY, MAX_YT_VIEWS, MAX_YT_VIDEOS

YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
REQUEST_DELAY = 0.5


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
def _yt_search(query: str, max_results: int = 10) -> list[dict]:
    if not YOUTUBE_API_KEY:
        return []
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "order": "viewCount",
        "key": YOUTUBE_API_KEY,
    }
    with httpx.Client(timeout=15) as client:
        r = client.get(YT_SEARCH_URL, params=params)
        r.raise_for_status()
        return r.json().get("items", [])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
def _yt_video_stats(video_ids: list[str]) -> dict[str, int]:
    if not video_ids or not YOUTUBE_API_KEY:
        return {}
    params = {
        "part": "statistics",
        "id": ",".join(video_ids[:50]),
        "key": YOUTUBE_API_KEY,
    }
    with httpx.Client(timeout=15) as client:
        r = client.get(YT_VIDEOS_URL, params=params)
        r.raise_for_status()
    result = {}
    for item in r.json().get("items", []):
        vid_id = item["id"]
        result[vid_id] = int(item.get("statistics", {}).get("viewCount", 0))
    return result


def _build_query(candidate: ToolCandidate) -> str:
    name = candidate.name.strip()
    generic_risk = len(name.split()) <= 1
    return f"{name} AI tool" if generic_risk else name


def check(candidate: ToolCandidate) -> ToolCandidate:
    """Run the YouTube gap check on a single candidate. Mutates in place."""
    if not YOUTUBE_API_KEY:
        candidate.yt_video_count = 0
        candidate.yt_max_views = 0
        candidate.yt_gap_passed = True
        return candidate

    query = _build_query(candidate)

    try:
        items = _yt_search(query, max_results=10)
        time.sleep(REQUEST_DELAY)

        video_ids = [
            item["id"]["videoId"]
            for item in items
            if item.get("id", {}).get("kind") == "youtube#video"
        ]

        if not video_ids:
            candidate.yt_video_count = 0
            candidate.yt_max_views = 0
            candidate.yt_gap_passed = True
            return candidate

        stats = _yt_video_stats(video_ids)
        time.sleep(REQUEST_DELAY)

        candidate.yt_video_count = len(video_ids)
        candidate.yt_max_views = max(stats.values()) if stats else 0
        candidate.yt_gap_passed = (
            candidate.yt_video_count <= MAX_YT_VIDEOS
            and candidate.yt_max_views <= MAX_YT_VIEWS
        )

    except Exception as e:
        print(f"[gap_check] ⚠ Error checking '{candidate.name}': {e}")
        candidate.yt_video_count = -1
        candidate.yt_max_views = -1
        candidate.yt_gap_passed = None

    return candidate


def check_batch(
    candidates: list[ToolCandidate],
    skip_already_checked: bool = True,
) -> list[ToolCandidate]:
    """Run gap check on a list. Skips already-checked candidates."""
    needs_check = [
        c for c in candidates
        if not (skip_already_checked and c.yt_gap_passed is not None)
    ]
    print(f"[gap_check] Checking {len(needs_check)} candidates against YouTube...")
    for i, candidate in enumerate(needs_check):
        print(f"  [{i+1}/{len(needs_check)}] {candidate.name}")
        check(candidate)
        passed = "✓" if candidate.yt_gap_passed else "✗"
        print(f"    {passed} videos={candidate.yt_video_count} max_views={candidate.yt_max_views:,}")
    return candidates
```

---

## Scoring — `scoring/scorer.py`

Scores each candidate 0–100 on opportunity value, not tool quality.

```python
"""
scoring/scorer.py

Scores candidates 0–100 on how good a YouTube opportunity they represent.

Breakdown (100 pts total):
  YouTube gap        30 pts   Fewer existing videos = bigger opportunity
  Freshness          25 pts   Newer = first-mover advantage
  Social velocity    20 pts   Comments > upvotes as engagement signal
  Source credibility 15 pts   GitHub > PH > HN > Reddit
  Description quality 10 pts  Needs enough info to script well
"""
import math
from toolstack.models import ToolCandidate

W_FRESHNESS   = 25
W_YT_GAP      = 30
W_VELOCITY    = 20
W_SOURCE      = 15
W_DESCRIPTION = 10

FRESHNESS_HALF_LIFE_HOURS = 48.0

SOURCE_SCORES = {
    "github":      1.0,
    "hackernews":  0.85,
    "producthunt": 0.75,
    "reddit":      0.60,
}


def _score_freshness(candidate: ToolCandidate) -> float:
    age_h = candidate.age_hours()
    decay = math.exp(-age_h / FRESHNESS_HALF_LIFE_HOURS)
    return round(W_FRESHNESS * decay, 2)


def _score_yt_gap(candidate: ToolCandidate) -> float:
    if candidate.yt_gap_passed is None:
        return W_YT_GAP * 0.5
    if not candidate.yt_gap_passed:
        return 0.0

    vid_count = candidate.yt_video_count
    max_views = candidate.yt_max_views

    if vid_count == 0:      video_factor = 1.0
    elif vid_count == 1:    video_factor = 0.85
    elif vid_count == 2:    video_factor = 0.65
    else:                   video_factor = 0.40

    if max_views == 0:      view_factor = 1.0
    elif max_views < 500:   view_factor = 0.95
    elif max_views < 2000:  view_factor = 0.75
    else:                   view_factor = 0.50

    return round(W_YT_GAP * video_factor * view_factor, 2)


def _score_velocity(candidate: ToolCandidate) -> float:
    if candidate.source == "github":
        stars = candidate.stars
        if stars == 0:      return W_VELOCITY * 0.2
        elif stars < 5:     return W_VELOCITY * 0.5
        elif stars < 20:    return W_VELOCITY * 0.8
        elif stars < 50:    return W_VELOCITY * 1.0
        else:               return W_VELOCITY * 0.7

    upvotes  = max(candidate.upvotes, 1)
    comments = candidate.comments
    ratio = comments / upvotes
    ratio_factor = min(ratio / 0.3, 1.0)

    if comments >= 20:      comment_bonus = 1.0
    elif comments >= 10:    comment_bonus = 0.85
    elif comments >= 5:     comment_bonus = 0.65
    elif comments >= 2:     comment_bonus = 0.45
    else:                   comment_bonus = 0.20

    combined = (ratio_factor * 0.6 + comment_bonus * 0.4)
    return round(W_VELOCITY * combined, 2)


def _score_source(candidate: ToolCandidate) -> float:
    factor = SOURCE_SCORES.get(candidate.source, 0.5)
    return round(W_SOURCE * factor, 2)


def _score_description(candidate: ToolCandidate) -> float:
    desc = candidate.description.strip()
    if not desc:                return 0.0
    length = len(desc)
    if length >= 150:           return float(W_DESCRIPTION)
    elif length >= 80:          return W_DESCRIPTION * 0.75
    elif length >= 30:          return W_DESCRIPTION * 0.50
    else:                       return W_DESCRIPTION * 0.25


def score(candidate: ToolCandidate) -> ToolCandidate:
    """Score a single candidate. Mutates in place and returns it."""
    breakdown = {
        "freshness":   _score_freshness(candidate),
        "yt_gap":      _score_yt_gap(candidate),
        "velocity":    _score_velocity(candidate),
        "source":      _score_source(candidate),
        "description": _score_description(candidate),
    }
    candidate.score = round(sum(breakdown.values()), 2)
    candidate.score_breakdown = breakdown
    return candidate


def score_batch(candidates: list[ToolCandidate]) -> list[ToolCandidate]:
    """Score and sort by score descending."""
    for c in candidates:
        score(c)
    return sorted(candidates, key=lambda c: c.score, reverse=True)
```

---

## Queue Manager — `queue/manager.py`

SQLite-backed queue. Persists everything across runs.

```python
"""
queue/manager.py

SQLite queue for tool candidates.

Tables:
  candidates   — All tools seen, with full metadata + state
  run_log      — Log of each pipeline run
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from toolstack.models import ToolCandidate
from toolstack.config import DB_PATH, MIN_SCORE_THRESHOLD

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    url               TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_url        TEXT,
    description       TEXT,
    found_at          TEXT,
    published_at      TEXT,
    upvotes           INTEGER DEFAULT 0,
    comments          INTEGER DEFAULT 0,
    stars             INTEGER DEFAULT 0,
    yt_video_count    INTEGER DEFAULT -1,
    yt_max_views      INTEGER DEFAULT -1,
    yt_gap_passed     INTEGER,
    score             REAL DEFAULT 0,
    score_breakdown   TEXT,
    queued            INTEGER DEFAULT 0,
    script_generated  INTEGER DEFAULT 0,
    skipped           INTEGER DEFAULT 0,
    skip_reason       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS run_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at        TEXT NOT NULL,
    found         INTEGER DEFAULT 0,
    gap_checked   INTEGER DEFAULT 0,
    queued        INTEGER DEFAULT 0,
    skipped       INTEGER DEFAULT 0,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_score   ON candidates(score DESC);
CREATE INDEX IF NOT EXISTS idx_queued  ON candidates(queued, script_generated);
CREATE INDEX IF NOT EXISTS idx_source  ON candidates(source);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript(SCHEMA)
    print(f"[queue] Database ready at {Path(DB_PATH).resolve()}")


def upsert(candidate: ToolCandidate):
    d = candidate.to_dict()
    with _conn() as conn:
        conn.execute("""
            INSERT INTO candidates (
                url, name, source, source_url, description,
                found_at, published_at, upvotes, comments, stars,
                yt_video_count, yt_max_views, yt_gap_passed,
                score, score_breakdown, queued, script_generated,
                skipped, skip_reason
            ) VALUES (
                :url, :name, :source, :source_url, :description,
                :found_at, :published_at, :upvotes, :comments, :stars,
                :yt_video_count, :yt_max_views, :yt_gap_passed,
                :score, :score_breakdown, :queued, :script_generated,
                :skipped, :skip_reason
            )
            ON CONFLICT(url) DO UPDATE SET
                score           = excluded.score,
                score_breakdown = excluded.score_breakdown,
                yt_video_count  = excluded.yt_video_count,
                yt_max_views    = excluded.yt_max_views,
                yt_gap_passed   = excluded.yt_gap_passed
        """, {
            **d,
            "yt_gap_passed": (
                None if d["yt_gap_passed"] is None else int(d["yt_gap_passed"])
            ),
            "score_breakdown": json.dumps(d["score_breakdown"]),
        })


def mark_queued(url: str):
    with _conn() as conn:
        conn.execute("UPDATE candidates SET queued=1 WHERE url=?", (url,))


def mark_script_generated(url: str):
    with _conn() as conn:
        conn.execute("UPDATE candidates SET script_generated=1 WHERE url=?", (url,))


def mark_skipped(url: str, reason: str):
    with _conn() as conn:
        conn.execute(
            "UPDATE candidates SET skipped=1, skip_reason=? WHERE url=?",
            (reason, url),
        )


def log_run(found: int, gap_checked: int, queued: int, skipped: int, notes: str = ""):
    with _conn() as conn:
        conn.execute(
            "INSERT INTO run_log (ran_at, found, gap_checked, queued, skipped, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), found, gap_checked, queued, skipped, notes),
        )


def already_seen(url: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM candidates WHERE url=?", (url,)).fetchone()
    return row is not None


def get_queue(limit: int = 20) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT * FROM candidates
            WHERE queued=1 AND script_generated=0 AND skipped=0
            ORDER BY score DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _conn() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        queued   = conn.execute("SELECT COUNT(*) FROM candidates WHERE queued=1").fetchone()[0]
        scripted = conn.execute("SELECT COUNT(*) FROM candidates WHERE script_generated=1").fetchone()[0]
        skipped  = conn.execute("SELECT COUNT(*) FROM candidates WHERE skipped=1").fetchone()[0]
        runs     = conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
    return {
        "total_seen": total, "queued": queued,
        "scripted": scripted, "skipped": skipped, "pipeline_runs": runs,
    }


def get_ready_for_queue(min_score: float = MIN_SCORE_THRESHOLD, limit: int = 10) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT * FROM candidates
            WHERE yt_gap_passed=1 AND score >= ? AND queued=0 AND skipped=0
            ORDER BY score DESC LIMIT ?
        """, (min_score, limit)).fetchall()
    return [dict(r) for r in rows]
```

---

## Script Generator — `utils/script_generator.py`

Fetches the tool's actual landing page, then calls Claude to generate a ready-to-record script with `[CHECK]` flags on unverifiable claims.

```python
"""
utils/script_generator.py

Generates a ready-to-record YouTube script for a queued tool.

Accuracy layer:
  1. Fetches the tool's actual landing page before generating
  2. Passes raw copy to Claude as ground truth
  3. Claude flags unverifiable claims with [CHECK]
  4. You review [CHECK] markers before recording

Output: .txt script file + .meta.json sidecar with title/tag/thumbnail metadata
"""
import httpx
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from toolstack.models import ToolCandidate

OUTPUT_DIR = Path("scripts")
OUTPUT_DIR.mkdir(exist_ok=True)

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-opus-4-6"

# ── Personality system prompt — tune this to define your channel voice ────────
PERSONALITY_SYSTEM_PROMPT = """
You are the scriptwriter for a YouTube channel called ToolStack that reviews
newly launched, obscure AI tools before anyone else covers them.

CHANNEL VOICE: The "Skeptical Builder"
  - You sound like a senior developer who has seen a thousand demos and
    knows which ones actually work vs. which ones are marketing fluff.
  - You are curious and fair, but you always ask: "who actually uses this?"
  - Plain English. No buzzwords unless you are calling them out.
  - Always find one genuinely impressive thing about every tool.
  - Always give an honest verdict on pricing — never hide bad news.
  - Light sarcasm is fine. Heavy negativity is not.
  - Speak in second person: "you can do X", "if you are a Y person".

SCRIPT STRUCTURE (do not change the section labels):
  [HOOK]           0–8s      Bold claim or the most surprising capability
  [CONTEXT]        8–30s     What problem was this built to solve?
  [DEMO_NARRATION] 30s–3min  Walk through actual usage, step by step
  [HONEST_TAKE]    3–4min    Who is this actually for? What is missing?
  [VERDICT]        4–4:20    One sentence summary. Score out of 10 optional.
  [CTA]            4:20–4:30 "Subscribe for more tools before they blow up."

ACCURACY RULES:
  - Facts from the landing page copy = state confidently
  - Anything you are inferring = add [CHECK] after it
  - Never invent pricing. If not in the copy, say "check their site"
  - Never say a tool "uses GPT-4" unless explicitly stated

OUTPUT FORMAT:
  Script text only, with the section labels above.
  After the script, a JSON block inside ```json ``` markers containing:
    title_options: [3 YouTube title options]
    thumbnail_hook: Short text under 6 words for the thumbnail
    tags: [8–12 YouTube tags]
    description_first_line: First line of the video description under 100 chars
"""


def _fetch_landing_page(url: str) -> str:
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            r = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ToolStack/1.0)"},
            )
            r.raise_for_status()
            text = r.text
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:3000]
    except Exception as e:
        print(f"[script_generator] ⚠ Could not fetch {url}: {e}")
        return ""


def _build_user_prompt(candidate: ToolCandidate, landing_page_text: str) -> str:
    return f"""
Write a YouTube script for this AI tool:

TOOL NAME: {candidate.name}
URL: {candidate.url}
SOURCE: {candidate.source} ({candidate.source_url})
DESCRIPTION: {candidate.description}
SOCIAL SIGNALS: {candidate.upvotes} upvotes, {candidate.comments} comments, {candidate.stars} stars

LANDING PAGE COPY (verified source — treat as ground truth):
{landing_page_text if landing_page_text else "[Could not fetch landing page — mark any specific claims with [CHECK]]"}

Write the full script. Use [CHECK] for any claim not confirmed by the landing page copy.
""".strip()


def generate_script(candidate: ToolCandidate, api_key: str) -> Optional[Path]:
    """Generate a script. Returns path to saved .txt file, or None on failure."""
    print(f"[script_generator] Fetching landing page for {candidate.name}...")
    landing_page = _fetch_landing_page(candidate.url)

    user_prompt = _build_user_prompt(candidate, landing_page)

    print(f"[script_generator] Generating script for {candidate.name}...")
    try:
        with httpx.Client(timeout=90) as client:
            r = client.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 2000,
                    "system": PERSONALITY_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            r.raise_for_status()
            response = r.json()
    except Exception as e:
        print(f"[script_generator] ✗ API error: {e}")
        return None

    raw_text = response["content"][0]["text"]

    safe_name  = re.sub(r'[^\w\-]', '_', candidate.name.lower())[:40]
    timestamp  = datetime.utcnow().strftime("%Y%m%d_%H%M")
    script_path = OUTPUT_DIR / f"{timestamp}_{safe_name}.txt"
    script_path.write_text(raw_text, encoding="utf-8")
    print(f"[script_generator] ✓ Script saved: {script_path}")

    json_match = re.search(r'```json\s*(.*?)```', raw_text, re.DOTALL)
    if json_match:
        try:
            meta = json.loads(json_match.group(1))
            meta.update({
                "tool_name": candidate.name, "tool_url": candidate.url,
                "source": candidate.source, "score": candidate.score,
                "generated_at": datetime.utcnow().isoformat(),
            })
            meta_path = script_path.with_suffix(".meta.json")
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            print(f"[script_generator] ✓ Metadata saved: {meta_path}")
        except json.JSONDecodeError:
            print("[script_generator] ⚠ Could not parse metadata JSON")

    return script_path
```

---

## Orchestrator — `main.py`

```python
"""
main.py — ToolStack Pipeline Orchestrator

Usage:
    python main.py run               # One full discovery cycle
    python main.py queue             # Show what is in the queue
    python main.py stats             # Pipeline stats
    python main.py script <url>      # Generate script for a specific tool
    python main.py schedule          # Run automatically every 6 hours
"""
import os
import sys
import time
import schedule
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from toolstack.config import MIN_SCORE_THRESHOLD
from toolstack.models import ToolCandidate
from toolstack.connectors import hackernews, reddit, github, producthunt
from toolstack.filters import gap_check
from toolstack.scoring import scorer
from toolstack.queue import manager
from toolstack.utils import script_generator

console = Console()


def step_discover() -> list[ToolCandidate]:
    console.print("\n[bold cyan]Step 1 — Discovery[/bold cyan]")
    all_candidates: list[ToolCandidate] = []

    sources = [
        ("Hacker News",  hackernews.fetch,  {"max_results": 50}),
        ("Reddit",       reddit.fetch,       {"max_per_sub": 25}),
        ("GitHub",       github.fetch,       {"max_results": 60}),
        ("Product Hunt", producthunt.fetch,  {"max_results": 40}),
    ]

    for name, fn, kwargs in sources:
        try:
            results = fn(**kwargs)
            console.print(f"  {name}: [green]{len(results)} candidates[/green]")
            all_candidates.extend(results)
        except Exception as e:
            console.print(f"  {name}: [red]Error — {e}[/red]")

    seen: set[str] = set()
    unique = []
    for c in all_candidates:
        if c.url not in seen:
            seen.add(c.url)
            unique.append(c)

    console.print(f"\n  Total unique: [bold]{len(unique)}[/bold]")
    return unique


def step_pre_filter(candidates: list[ToolCandidate]) -> list[ToolCandidate]:
    console.print("\n[bold cyan]Step 2 — Pre-filter[/bold cyan]")
    filtered = []
    for c in candidates:
        if manager.already_seen(c.url):
            continue
        if not c.description.strip():
            c.skipped = True; c.skip_reason = "no description"
            manager.upsert(c); manager.mark_skipped(c.url, c.skip_reason)
            continue
        if len(c.name.strip()) < 3:
            c.skipped = True; c.skip_reason = "name too short"
            manager.upsert(c); manager.mark_skipped(c.url, c.skip_reason)
            continue
        filtered.append(c)
    console.print(f"  After pre-filter: [bold]{len(filtered)}[/bold] new candidates")
    return filtered


def step_gap_check(candidates: list[ToolCandidate]) -> list[ToolCandidate]:
    console.print("\n[bold cyan]Step 3 — YouTube gap check[/bold cyan]")
    if not candidates:
        console.print("  Nothing to check.")
        return []
    gap_check.check_batch(candidates)
    passed = [c for c in candidates if c.yt_gap_passed]
    failed = [c for c in candidates if c.yt_gap_passed is False]
    for c in failed:
        c.skipped = True
        c.skip_reason = f"yt_gap: {c.yt_video_count} videos, max {c.yt_max_views:,} views"
    console.print(f"  Passed: [green]{len(passed)}[/green]  Failed: [red]{len(failed)}[/red]")
    return candidates


def step_score_and_queue(candidates: list[ToolCandidate]) -> list[ToolCandidate]:
    console.print("\n[bold cyan]Step 4 — Scoring & queueing[/bold cyan]")
    scorer.score_batch(candidates)
    queued_count = 0
    for c in candidates:
        manager.upsert(c)
        if c.skipped:
            manager.mark_skipped(c.url, c.skip_reason)
            continue
        if c.yt_gap_passed and c.score >= MIN_SCORE_THRESHOLD:
            c.queued = True
            manager.mark_queued(c.url)
            queued_count += 1
        else:
            c.skipped = True
            c.skip_reason = f"score too low ({c.score:.1f} < {MIN_SCORE_THRESHOLD})"
            manager.mark_skipped(c.url, c.skip_reason)
    console.print(f"  Queued this run: [bold green]{queued_count}[/bold green]")
    return candidates


def show_queue():
    items = manager.get_queue(limit=20)
    if not items:
        console.print("[yellow]Queue is empty.[/yellow]")
        return
    t = Table(title="Script Queue", box=box.SIMPLE_HEAD, show_lines=False)
    t.add_column("Score", style="bold green", width=7)
    t.add_column("Name", width=28)
    t.add_column("Source", width=12)
    t.add_column("YT vids", width=8)
    t.add_column("URL", style="dim", overflow="fold", width=35)
    for item in items:
        t.add_row(str(item["score"]), item["name"], item["source"],
                  str(item["yt_video_count"]), item["url"])
    console.print(t)


def show_stats():
    stats = manager.get_stats()
    console.print(Panel(
        f"Total seen:     [bold]{stats['total_seen']}[/bold]\n"
        f"Queued:         [bold green]{stats['queued']}[/bold green]\n"
        f"Scripted:       [bold blue]{stats['scripted']}[/bold blue]\n"
        f"Skipped:        [bold red]{stats['skipped']}[/bold red]\n"
        f"Pipeline runs:  [bold]{stats['pipeline_runs']}[/bold]",
        title="Pipeline Stats", expand=False,
    ))


def run_pipeline():
    start = datetime.utcnow()
    console.print(Panel(
        f"[bold]ToolStack Discovery Pipeline[/bold]\n"
        f"Started at {start.strftime('%Y-%m-%d %H:%M UTC')}",
        style="cyan",
    ))
    manager.init_db()
    candidates = step_discover()
    candidates = step_pre_filter(candidates)
    candidates = step_gap_check(candidates)
    candidates = step_score_and_queue(candidates)
    queued  = sum(1 for c in candidates if c.queued)
    skipped = sum(1 for c in candidates if c.skipped)
    manager.log_run(
        found=len(candidates), gap_checked=len([c for c in candidates if c.yt_gap_passed is not None]),
        queued=queued, skipped=skipped,
    )
    elapsed = (datetime.utcnow() - start).seconds
    console.print(f"\n[bold green]✓ Done in {elapsed}s[/bold green] — {queued} queued, {skipped} skipped\n")
    show_queue()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "run":
        run_pipeline()

    elif cmd == "queue":
        manager.init_db(); show_queue()

    elif cmd == "stats":
        manager.init_db(); show_stats()

    elif cmd == "script":
        if len(sys.argv) < 3:
            console.print("[red]Usage: python main.py script <tool_url>[/red]")
            sys.exit(1)
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            console.print("[red]ANTHROPIC_API_KEY not set in .env[/red]")
            sys.exit(1)
        manager.init_db()
        url = sys.argv[2]
        items = manager.get_queue(limit=100)
        match = next((i for i in items if i["url"] == url), None)
        if not match:
            console.print(f"[red]URL not found in queue: {url}[/red]")
            sys.exit(1)
        candidate = ToolCandidate(
            name=match["name"], url=match["url"], source=match["source"],
            source_url=match["source_url"] or "", description=match["description"] or "",
            score=match["score"],
        )
        path = script_generator.generate_script(candidate, api_key)
        if path:
            manager.mark_script_generated(url)
            console.print(f"[green]Script ready: {path}[/green]")

    elif cmd == "schedule":
        console.print("[cyan]Running on schedule — every 6 hours[/cyan]")
        schedule.every(6).hours.do(run_pipeline)
        run_pipeline()
        while True:
            schedule.run_pending()
            time.sleep(60)

    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        console.print("Usage: python main.py [run|queue|stats|script <url>|schedule]")
```

---

## Requirements — `requirements.txt`

```text
httpx>=0.27.0
praw>=7.7.1
python-dotenv>=1.0.0
rich>=13.7.0
schedule>=1.2.0
aiosqlite>=0.20.0
tenacity>=8.2.0
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `python main.py run` | Full discovery cycle — scrape, filter, score, queue |
| `python main.py queue` | Display current queue sorted by score |
| `python main.py stats` | Pipeline summary stats |
| `python main.py script <url>` | Generate script for a specific queued tool URL |
| `python main.py schedule` | Auto-run every 6 hours (for VPS deployment) |

---

## Scoring Weights

Tune these in `scoring/scorer.py` after your first week of data:

| Signal | Points | Logic |
|--------|--------|-------|
| YouTube gap | 30 | 0 videos = full 30 pts. Decays per video found. |
| Freshness | 25 | Exponential decay with 48hr half-life |
| Social velocity | 20 | Comment/upvote ratio + absolute comment count |
| Source credibility | 15 | GitHub 1.0 → HN 0.85 → PH 0.75 → Reddit 0.60 |
| Description quality | 10 | Length proxy for "scriptable" information |

**Tightening the "undiscovered" definition** — edit `.env`:

```ini
MAX_YT_VIDEOS=1      # Skip if ANY video exists
MAX_YT_VIEWS=1000    # Skip if any video has 1k+ views
FRESHNESS_DAYS=3     # Only tools from the past 3 days
```

---

## YouTube API Quota

| Operation | Cost | Free daily limit |
|-----------|------|-----------------|
| Search | 100 units | 100 searches |
| Video stats | 1 unit per video | ~10,000 |
| **Gap check (both)** | **~200 units** | **~50 gap checks** |

The pipeline pre-filters aggressively before hitting YouTube, so 20–40 checks per run is typical. Running every 6 hours = 80–160 checks/day — just above free tier. Either run twice daily or enable billing ($0.005 per 100 units beyond free).

---

## Running on a Schedule

For a $5/mo VPS (Hetzner CX11 or DigitalOcean Droplet):

```bash
# Clone your project
git clone <your-repo> toolstack
cd toolstack
pip install -r requirements.txt
cp .env.example .env  # fill in keys

# Run with tmux
tmux new -s toolstack
python main.py schedule

# Ctrl+B, D to detach — pipeline runs every 6 hours
```

Or as a systemd service for reliability:

```ini
# /etc/systemd/system/toolstack.service
[Unit]
Description=ToolStack Discovery Pipeline
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/toolstack
ExecStart=/usr/bin/python3 main.py schedule
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable toolstack
sudo systemctl start toolstack
sudo journalctl -u toolstack -f   # Watch logs
```
