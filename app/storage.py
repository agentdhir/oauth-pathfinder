"""Where live-generated guides and counters live.

Curated guides are committed in guides/. Guides generated on the live site go to Redis (Upstash REST API,
e.g. added via the Vercel Marketplace) so share links survive serverless restarts. Locally, or without Redis,
they are plain files. On Vercel the project directory is read-only, so local files go under /tmp."""
import json, os
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path("/tmp/oauth-pathfinder") if os.getenv("VERCEL") else ROOT
GENERATED = DATA_DIR / "guides"
CACHE_DIR = DATA_DIR / "cache"

_URL = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
_TOKEN = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")


def redis(*cmd):
    """One Redis command over Upstash's REST API; None if Redis isn't configured or fails."""
    if not (_URL and _TOKEN):
        return None
    try:
        r = httpx.post(_URL, headers={"Authorization": f"Bearer {_TOKEN}"}, json=[str(c) for c in cmd], timeout=10)
        return r.json().get("result")
    except Exception:
        return None


def using_redis() -> bool:
    return bool(_URL and _TOKEN)


def save_generated(slug: str, guide_json: str):
    if using_redis():
        redis("SET", f"guide:{slug}", guide_json)
        redis("SADD", "guides", slug)
        return
    GENERATED.mkdir(parents=True, exist_ok=True)
    (GENERATED / f"{slug}.json").write_text(guide_json, encoding="utf-8")


def load_generated(slug: str) -> dict | None:
    if using_redis():
        raw = redis("GET", f"guide:{slug}")
        return json.loads(raw) if raw else None
    p = GENERATED / f"{slug}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def list_generated() -> list[dict]:
    if using_redis():
        slugs = redis("SMEMBERS", "guides") or []
        raws = redis("MGET", *[f"guide:{s}" for s in slugs]) if slugs else []
        return [json.loads(r) for r in raws or [] if r]
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(GENERATED.glob("*.json"))] if GENERATED.exists() else []


def count(key: str, ttl: int) -> int | None:
    """Increment a counter that expires after ttl seconds; None if Redis isn't configured."""
    n = redis("INCR", key)
    if n == 1:
        redis("EXPIRE", key, ttl)
    return n
