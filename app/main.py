"""Web server: guide library, live generation (SSE), share links, markdown export."""
import html, json, os, queue, threading, time
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .models import Guide
from .research import generate_guide, slugify, _name_from_input
from . import storage
from .markdown import to_markdown

ROOT = Path(__file__).resolve().parent.parent
GUIDES = ROOT / "guides"      # curated guides, committed to the repo (read-only on Vercel)
REVIEWS = ROOT / "reviews"    # human verification notes, committed
STATIC = ROOT / "static"
OVERRIDABLE = ("difficulty", "difficulty_reason", "setup_time", "approval_wait", "approval_required", "approval_details")
GEN_LOCK = threading.Semaphore(int(os.getenv("MAX_CONCURRENT_GENERATIONS", "2")))
# Free-tier LLM quota is small (~20 requests/day/model), so live generation on the public link is rationed.
PER_IP_PER_HOUR = int(os.getenv("PER_IP_PER_HOUR", "4"))
DAILY_CAP = int(os.getenv("DAILY_GENERATION_CAP", "30"))
_gen_log: list[tuple[float, str]] = []  # in-memory fallback when Redis isn't configured

app = FastAPI(title="OAuth Pathfinder")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _allow(ip: str) -> str | None:
    day_msg = "Today's live-generation budget is used up (free-tier LLM quota). Browse the library, or try again tomorrow."
    ip_msg = f"You've generated {PER_IP_PER_HOUR} guides in the last hour. Please try again a bit later."
    now = time.time()
    if storage.using_redis():  # shared across serverless instances
        if (storage.count(f"rl:day:{int(now // 86400)}", 86400) or 0) > DAILY_CAP:
            return day_msg
        if (storage.count(f"rl:ip:{ip}:{int(now // 3600)}", 3600) or 0) > PER_IP_PER_HOUR:
            return ip_msg
        return None
    _gen_log[:] = [(t, i) for t, i in _gen_log if now - t < 86400]
    if len(_gen_log) >= DAILY_CAP:
        return day_msg
    if sum(1 for t, i in _gen_log if i == ip and now - t < 3600) >= PER_IP_PER_HOUR:
        return ip_msg
    _gen_log.append((now, ip))
    return None


def load(slug: str) -> dict | None:
    slug = slugify(slug)
    p = GUIDES / f"{slug}.json"
    g = json.loads(p.read_text(encoding="utf-8")) if p.exists() else storage.load_generated(slug)
    return apply_review(g) if g else None


def apply_review(g: dict) -> dict:
    """Human verification lives in reviews/<slug>.json, separate from agent output, so regenerating a guide
    never erases it. A review may correct headline fields; the agent's original values are kept for display."""
    p = REVIEWS / f"{g['slug']}.json"
    if not p.exists():
        return g
    r = json.loads(p.read_text(encoding="utf-8"))
    r["stale"] = r.get("guide_generated_at") not in (None, g["generated_at"])  # guide was regenerated after review
    overrides = {k: v for k, v in r.get("overrides", {}).items() if k in OVERRIDABLE}
    if overrides and not r["stale"]:
        r["agent_said"] = {k: g.get(k) for k in overrides}
        g.update(overrides)
    g["review"] = r
    return g


def all_guides() -> list[dict]:
    seen, out = set(), []
    curated = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(GUIDES.glob("*.json"))]
    for g in curated + storage.list_generated():
        if g["slug"] in seen:
            continue
        seen.add(g["slug"])
        g = apply_review(g)
        out.append({k: g.get(k) for k in ("slug", "app_name", "category", "difficulty", "setup_time", "approval_wait",
                                          "approval_required", "generated_at", "website", "model_tier")}
                   | {"reviewed": bool(g.get("review")) and not g["review"]["stale"], "stats": g.get("evidence_stats")})
    return out


def find_existing(q: str) -> dict | None:
    name, domain = _name_from_input(q)
    if g := load(name):
        return g
    for g in all_guides():
        if domain and g.get("website") and domain in g["website"]:
            return load(g["slug"])
        if g["app_name"].lower() == name.lower():
            return load(g["slug"])
    return None


@app.get("/api/guides")
def api_list():
    return all_guides()


@app.get("/api/guides/{slug}")
def api_get(slug: str):
    g = load(slug)
    if not g:
        raise HTTPException(404, "No guide yet")
    return g


@app.get("/api/generate")
def api_generate(request: Request, q: str = Query(..., min_length=2, max_length=120), force: bool = False):
    q = q.strip()
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()

    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    def stream():
        if not force and (g := find_existing(q)):
            yield sse("done", {"slug": g["slug"], "cached": True})
            return
        if not os.getenv("GEMINI_API_KEY"):
            yield sse("fail", {"message": "Server has no GEMINI_API_KEY configured."})
            return
        if refusal := _allow(ip):
            yield sse("fail", {"message": refusal})
            return
        if not GEN_LOCK.acquire(timeout=1):
            yield sse("fail", {"message": "The agent is busy with other guides; try again in a minute."})
            return
        events: queue.Queue = queue.Queue()
        result: dict = {}

        def run():
            try:
                g: Guide = generate_guide(q, emit=lambda k, m: events.put(("progress", {"kind": k, "msg": m})))
                if (REVIEWS / f"{g.slug}.json").exists():  # never overwrite a human-reviewed guide from the public UI
                    g.slug = g.slug + "-live"
                storage.save_generated(g.slug, g.model_dump_json(indent=2))
                result["slug"] = g.slug
            except Exception as e:
                result["error"] = str(e)[:400]
            finally:
                events.put(None)
                GEN_LOCK.release()

        threading.Thread(target=run, daemon=True).start()
        while True:
            try:
                item = events.get(timeout=15)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if item is None:
                break
            yield sse(*item)
        if "slug" in result:
            yield sse("done", {"slug": result["slug"], "cached": False})
        else:
            yield sse("fail", {"message": result.get("error", "unknown error")})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/g/{slug}.md", response_class=PlainTextResponse)
def guide_md(slug: str):
    g = load(slug)
    if not g:
        raise HTTPException(404)
    return to_markdown(g)


@app.get("/g/{slug}", response_class=HTMLResponse)
def guide_page(slug: str):
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    if g := load(slug):  # server-side title/description so shared links preview well
        title = html.escape(f"{g['app_name']} OAuth setup guide · OAuth Pathfinder")
        desc = html.escape(f"{g['difficulty'].title()} · setup {g['setup_time']} · approval wait {g['approval_wait']}. {g['summary']}"[:280])
        page = page.replace("<title>OAuth Pathfinder</title>",
                            f'<title>{title}</title><meta name="description" content="{desc}">'
                            f'<meta property="og:title" content="{title}"><meta property="og:description" content="{desc}">')
    return page


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC / "index.html")
