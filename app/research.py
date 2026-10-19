"""Research agent.

  1. search      broad web search for the app's OAuth / app-review docs
  2. resolve     LLM identifies the provider's official domains (so "Gmail" -> google.com, SDK mirrors aren't "official")
  3. read        official pages first, following promising same-site links (oauth / review / publish / scopes ...)
  4. extract     LLM writes a structured guide where every claim must carry a verbatim quote from a source
  5. gap-fill    agent searches the official docs for what it couldn't verify, reads more, rewrites the guide
  6. verify      every quote is checked against the fetched page text (string match, not LLM judgement)
  7. probe       live, non-destructive requests to the documented authorize / token endpoints
"""
import heapq, os, re, threading, time
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from . import registry
from .composio import managed_status
from .fetch import fetch_page, web_search, is_public_url, UA
from .models import Guide, GuideDraft, Item, Step, Blocker, Capability, Evidence, Source, Probe

load_dotenv()
MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", "gemini-3.6-flash,gemini-3.5-flash").split(",") if m.strip()]
LIGHT_MODELS = [m.strip() for m in os.getenv("GEMINI_LIGHT_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",") if m.strip()]
MAX_PAGES, GAP_PAGES = 9, 3
LINK_WEIGHTS = {"oauth": 5, "authoriz": 4, "app-review": 5, "review": 4, "publish": 4, "verification": 4, "verify": 3,
                "distribut": 4, "marketplace": 3, "listing": 2, "scope": 3, "permission": 2, "redirect": 3, "auth": 2,
                "regist": 3, "creat": 3, "new-app": 3, "set-up": 2, "setup": 2, "getting-started": 2, "quickstart": 2, "production": 3, "go-live": 4,
                "approval": 4, "requirements": 3, "getting-access": 5, "access": 2, "partner": 2, "limits": 2, "rate-limit": 1, "security": 2, "consent": 3, "public": 2}
LINK_PENALTY = ("blog", "pricing", "changelog", "community", "careers", "template", "customers", "press", "events",
                "/reference/", "release-notes", "/legal", "status.", "/blob/", "@latest/", "/enterprise-server", "/api/article/", "/fr/", "/de/", "/ja/", "/es/", "/pt", "/ko/", "/zh")
NOISE = ("youtube.com", "reddit.com", "medium.com", "stackoverflow.com", "quora.com", "linkedin.com/pulse", "dev.to",
         "npmjs.com", "pypi.org", "hexdocs.pm", "pkg.go.dev", "rubygems.org", "facebook.com/groups", "x.com/", "twitter.com/")
COMMUNITY_HOSTS = {"forum", "forums", "community", "devforum", "discuss", "discussions", "devcommunity", "answers", "groups"}
QUOTE_MAP = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " ", "​": ""}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "app"


def _norm(s: str) -> str:
    for a, b in QUOTE_MAP.items():
        s = s.replace(a, b)
    s = re.sub(r"[`*_#>\[\]]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _name_from_input(q: str) -> tuple[str, str | None]:
    q = q.strip()
    if "." in q and " " not in q:
        host = urlparse(q if "://" in q else "https://" + q).hostname or q
        host = host.removeprefix("www.")
        return host.split(".")[0].capitalize(), host
    return q, None


def _site(host: str) -> str:
    """Registrable domain, roughly: developers.notion.com -> notion.com, api.example.co.uk -> example.co.uk."""
    parts = (host or "").lower().split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _link_score(url: str) -> int:
    u = url.lower()
    if any(p in u for p in LINK_PENALTY):
        return -10
    return sum(w for k, w in LINK_WEIGHTS.items() if k in u)


# ---------------------------------------------------------------- LLM
_exhausted: dict[str, float] = {}  # model -> time its quota resets (free tier: ~20 requests/day/model)
_ctx = threading.local()  # per-generation deadline (serverless functions are killed at ~300s)
BUDGET = int(os.getenv("GEN_BUDGET_SECONDS", "230"))


def llm(prompt: str, schema, emit, label: str, light: bool = False):
    """Light calls (resolve) use Flash-Lite models; the guide itself uses the strongest model with quota left."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    last = None
    deadline = getattr(_ctx, "deadline", None)
    models = LIGHT_MODELS + MODELS if light else MODELS + LIGHT_MODELS
    for model in [m for m in dict.fromkeys(models) if _exhausted.get(m, 0) < time.time()]:
        if deadline and model not in LIGHT_MODELS and time.time() > deadline - 75:
            emit("skip", f"Running out of time; skipping {model} for a faster model")
            continue
        tries = 2 if (light or model in LIGHT_MODELS) else 3  # strong models are often briefly "busy": wait a bit longer
        if deadline and time.time() > deadline - 120:
            tries = 1
        for attempt in range(tries):
            try:
                emit("think", f"{label} with {model}" + (" (retry)" if attempt else ""))
                resp = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json",
                                                       response_schema=schema, temperature=0.2))
                return schema.model_validate_json(resp.text), model
            except Exception as e:
                last, msg = e, str(e)
                if "404" in msg or "NOT_FOUND" in msg:
                    _exhausted[model] = time.time() + 86400
                    break
                if any(x in msg for x in ("429", "RESOURCE_EXHAUSTED")):
                    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", msg)
                    wait = (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))) if m else 60
                    _exhausted[model] = time.time() + wait
                    emit("skip", f"{model} out of free quota" + (" for today" if wait > 3600 else f" for {wait:.0f}s") + ", trying next model")
                    break
                if any(x in msg for x in ("503", "UNAVAILABLE", "overloaded", "500", "INTERNAL")):
                    emit("skip", f"{model} busy")
                    time.sleep(2 if tries == 2 else 6 * (attempt + 1))
                    continue
                if type(e).__name__ == "ValidationError":
                    continue
                break
    raise RuntimeError(f"All Gemini models failed: {str(last)[:200]}")


class Resolution(BaseModel):
    app_name: str = Field(description="Canonical product name, e.g. 'Gmail' or 'HubSpot'")
    provider: str = Field(description="Company whose OAuth app the developer must create, e.g. 'Google' for Gmail")
    official_domains: list[str] = Field(description="Registrable domains owned by the provider that host its developer docs, e.g. ['google.com'] or ['notion.com','notion.so']")
    docs_hosts: list[str] = Field(description="Hostnames of official developer docs seen in the results, e.g. ['developers.google.com']")
    supports_oauth: bool = Field(description="Whether the results indicate a third-party OAuth 2.0 flow exists for this app")


def known_provider(query: str) -> Resolution | None:
    name, domain = _name_from_input(query)
    if e := registry.lookup(name, domain):
        return Resolution(app_name=e["app_name"], provider=e["provider"], official_domains=e["official_domains"],
                          docs_hosts=e.get("docs_hosts", []), supports_oauth=True)
    return None


def resolve(query: str, results: list[dict], emit) -> Resolution:
    lines = "\n".join(f"- {r['title']} <{r['url']}>" for r in results[:25])
    prompt = (f'A developer typed "{query}". Using these web search results, identify the app and the provider\'s OFFICIAL '
              f"developer documentation domains. Third-party blogs, SDK mirrors and integration platforms are NOT official.\n\n{lines}")
    try:
        r, _ = llm(prompt, Resolution, emit, "Identifying the official developer docs", light=True)
        r.official_domains = [_site(d.removeprefix("https://").split("/")[0]) for d in r.official_domains if d]
        registry.remember(query, r.app_name, r.provider, r.official_domains, r.docs_hosts)  # next time: no LLM call
        return r
    except Exception:
        name, domain = _name_from_input(query)
        hosts = [urlparse(x["url"]).hostname or "" for x in results]
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        doms = list(dict.fromkeys(_site(h) for h in hosts if key and key in h.replace("-", "")))
        if domain:
            doms.insert(0, _site(domain))
        return Resolution(app_name=name, provider=name, official_domains=doms[:3], docs_hosts=[], supports_oauth=True)


# ---------------------------------------------------------------- reading
class Reader:
    def __init__(self, official: list[str], emit, app_name: str = ""):
        self.official, self.emit = set(official), emit
        self.key = re.sub(r"[^a-z0-9]", "", app_name.lower())
        self.pages: list[dict] = []
        self.seen: set[str] = set()
        self.queue: list[tuple] = []  # (-priority, n, url)
        self.n = 0
        self.counts = {"official": 0, "community": 0, "third-party": 0}
        self.fingerprints: list[set[str]] = []

    def kind(self, url: str) -> str:
        """official docs > community forum (anecdotal, but where real approval waits get reported) > third-party."""
        host = (urlparse(url).hostname or "").lower()
        if host.split(".")[0] in COMMUNITY_HOSTS or "community" in host:
            return "community"
        return "official" if _site(host) in self.official else "third-party"

    def is_official(self, url: str) -> bool:
        return self.kind(url) == "official"

    def push(self, url: str, bonus: int = 0, title: str = ""):
        url = url.split("#")[0].rstrip("/")
        if url in self.seen or any(n in url for n in NOISE) or not url.startswith("http"):
            return
        kind = self.kind(url)
        if kind != "official" and self.key and self.key not in re.sub(r"[^a-z0-9]", "", (url + title).lower()):
            return  # not official and not even about this app
        # official pages always outrank the rest; keywords order pages within each group
        pri = _link_score(url) + bonus + {"official": 100, "community": 40, "third-party": 0}[kind]
        self.n += 1
        heapq.heappush(self.queue, (-pri, self.n, url))

    def read(self, budget: int):
        target = len(self.pages) + budget
        while self.queue and len(self.pages) < target:
            neg, _, url = heapq.heappop(self.queue)
            if url in self.seen or -neg < 0:
                continue
            self.seen.add(url)
            kind = self.kind(url)
            if kind != "official" and self.counts[kind] >= 2:
                continue  # community / third-party pages fill gaps but are weaker evidence
            self.emit("read", url)
            p = fetch_page(url)
            if not p or len(p["text"]) < 800:
                self.emit("skip", f"Unreadable or too short: {url}")
                continue
            self.seen.add(p["url"].split("#")[0].rstrip("/"))
            words = re.findall(r"[a-z0-9]+", p["text"].lower())[:600]
            shingles = {" ".join(words[i:i + 6]) for i in range(max(1, len(words) - 5))}
            if any(len(shingles & s) / max(1, len(shingles | s)) > 0.6 for s in self.fingerprints):
                self.emit("skip", f"Duplicate of a page already read (another version/mirror): {url}")
                continue
            self.fingerprints.append(shingles)
            p["id"], p["kind"], p["official"] = len(self.pages) + 1, kind, kind == "official"
            self.counts[kind] += 1
            self.pages.append(p)
            if kind == "official":  # follow promising same-site links
                host = urlparse(p["url"]).hostname
                for l in p["links"]:
                    if urlparse(l).hostname == host and _link_score(l) >= 4:
                        self.push(l, bonus=-2)


# ---------------------------------------------------------------- coverage checklist (code, no LLM)
# The questions every guide must answer. Checking whether the official pages already cover them is plain regex;
# only the uncovered ones trigger extra searches. This replaced an LLM "draft to find gaps" call per guide.
CHECKLIST = [
    ("review process", r"app review|review process|submit\w* (your |the )?app|for review|verification process|approv(al|ed) by",
     "app review approval process"),
    ("review timeline", r"\d+\s*(?:-|to|–)\s*\d+\s*(?:business )?(?:days|weeks)|(?:several|few) (?:business )?(?:days|weeks)|turnaround",
     "review how long business days"),
    ("distribution to other users", r"distribut|public (?:app|integration|connection)|multi-?tenant|other (?:workspaces|organizations|accounts)|any workspace|publish",
     "distribute app other workspaces public"),
    ("scopes", r"\bscopes?\b|permissions", "OAuth scopes permissions list"),
    ("token lifetime", r"refresh token|expires? (?:in|after)|expiration|lifetime", "access token expiration refresh token"),
    ("rate limits", r"rate limit", "API rate limits apps"),
    ("user caps / test users", r"test users?|user cap|up to \d[\d,]* (?:users|installs|accounts|workspaces)|unverified app|development mode|sandbox",
     "test users limit development mode unverified app"),
]


def coverage(pages: list[dict]) -> list[tuple[str, str]]:
    """Return (topic, search terms) for checklist questions no official page touches."""
    text = " ".join(p["text"].lower() for p in pages if p.get("official"))
    return [(topic, terms) for topic, pattern, terms in CHECKLIST if not re.search(pattern, text)]


# ---------------------------------------------------------------- extraction
PROMPT = """You are a meticulous developer-relations researcher. A developer building an AI agent wants their end users to connect "{app}" (OAuth provider: {provider}).
Before launch they must create their OWN OAuth app with the provider and may need it approved. Using ONLY the numbered sources below, write a setup-and-approval guide.

Rules:
- Every requirement, step, nuance and blocker needs evidence: source_id plus a SHORT VERBATIM quote (one sentence or phrase, <=240 chars) copied exactly from that source. If you cannot quote it, leave evidence empty and, if it matters, also list it under `unverified`.
- Never invent URLs, endpoints, limits, timelines or fees. Do not fill gaps from memory.
- Time: `setup_time` = hands-on effort; `approval_wait` = calendar time waiting on the provider ("None" if no review applies). Put every quote that states a duration in `timing_evidence`. If no source states the review duration, write approval_wait as "Not documented" or a clearly-labelled estimate like "~1-2 weeks (estimate)", and add the question to `unverified`.
- Be honest about difficulty: separate self-serve setup from approval / verification / partner gating, and say exactly what triggers review (scopes, number of users, publishing to a marketplace, distribution to other workspaces/tenants).
- Difficulty, setup_time, approval_wait and approval_required describe the REQUIRED path only. Optional extras (marketplace/directory listings, verified-publisher badges) go in steps with required=false and must not raise the difficulty.
- BUT access often depends on what the agent does. Fill `capabilities` with 3-6 rows (read data, write/send, admin/org-level, etc.) showing which scopes or API products each needs and whether they are self-serve, need review, or need partner approval. Include rate-limit or listing caveats that make an "optional" step effectively necessary for that capability. Rate overall difficulty for the most common agent use case and mention in difficulty_reason if other capabilities are harder.
- Include REQUIRED distribution switches (e.g. making an app public / multi-tenant / "activate distribution") as steps; without them other users or workspaces cannot install the app.
- Actor per step: `agent` only if it can be done by an API, CLI or script; anything needing a human login, identity/business verification, payment, legal acceptance or a console form is `developer`.
- Cover the PROVIDER-SIDE path, in order: developer account -> create the OAuth app -> configure redirect URI and scopes -> test with your own account -> anything needed before other users/companies can connect (review, verification, publishing, distribution settings) -> production. Typically 5-10 concrete steps (what to click, what to enter).
- Do NOT write steps for implementing the OAuth flow itself (building the authorize URL, exchanging the code, refreshing or storing tokens): the developer's agent platform (e.g. Composio) does that, and the guide adds those platform steps separately.
- Nuances: redirect-URI rules, scope quirks, token lifetime/refresh, test-user or install caps, per-workspace/tenant installs, rate limits. Blockers: realistic failure/rejection causes with a concrete workaround.
- Prefer OFFICIAL sources. A claim backed only by a THIRD-PARTY source must say "(per a third-party guide)"; one backed only by a COMMUNITY forum post must say "(reported by developers on the forum)". Forum posts are useful for real-world review times but are anecdotal. Ignore sources not about {app}.
- `unverified`: specific questions a developer would ask that the sources leave open (e.g. "How long Notion's review takes").

Sources:
{sources}
"""


def extract(res: Resolution, pages: list[dict], emit, label: str, light: bool = False) -> tuple[GuideDraft, str]:
    label = {"official": "OFFICIAL", "community": "COMMUNITY FORUM", "third-party": "THIRD-PARTY"}
    blocks = "\n\n".join(f"[S{p['id']}] ({label[p.get('kind', 'official')]}) {p['title']} <{p['url']}>\n{p['text']}"
                         for p in pages)
    return llm(PROMPT.format(app=res.app_name, provider=res.provider, sources=blocks), GuideDraft, emit, label, light)


# ---------------------------------------------------------------- evidence
def quote_in(quote: str, page_norm: str) -> bool:
    """Is the quote really in the page? Whitespace-insensitive exact match per '...'-separated fragment
    (HTML-to-text adds spaces around inline tags), else >=90% of the quote's 6-word chunks appear verbatim."""
    q = _norm(quote).strip(" .\"'…")
    if len(q) < 12:
        return False
    flat = re.sub(r"\s+", "", page_norm)
    parts = [x for x in re.split(r"\s*(?:\.\.\.|…)\s*", q) if len(x) >= 8]
    if parts and all(re.sub(r"\s+", "", x).strip(".") in flat for x in parts):
        return True
    words = re.findall(r"[a-z0-9]+", q)
    if len(words) < 8:
        return False
    page_words = " " + " ".join(re.findall(r"[a-z0-9]+", page_norm)) + " "
    chunks = [" " + " ".join(words[i:i + 6]) + " " for i in range(len(words) - 5)]
    return sum(c in page_words for c in chunks) / len(chunks) >= 0.9


def verifier(pages: list[dict]):
    by_id = {p["id"]: p for p in pages}
    norm = {i: _norm(p["text"]) for i, p in by_id.items()}
    stats = {"claims": 0, "verified": 0, "partial": 0, "unsupported": 0, "quotes": 0, "quotes_verified": 0}

    def build(evs) -> tuple[list[Evidence], str]:
        out = []
        for e in evs:
            p = by_id.get(e.source_id)
            if not p or not e.quote.strip():
                continue
            ok = quote_in(e.quote, norm[e.source_id])
            stats["quotes"] += 1
            stats["quotes_verified"] += ok
            out.append(Evidence(source_id=e.source_id, url=p["url"], quote=e.quote.strip(), verified=ok))
        good = sum(x.verified for x in out)
        conf = "verified" if good and good == len(out) else "partial" if good else "unsupported"
        stats["claims"] += 1
        stats[conf] += 1
        return out, conf
    return build, stats


def probe(d: GuideDraft, emit) -> list[Probe]:
    """Non-destructive live checks with a dummy client_id: do the documented endpoints exist and behave like OAuth?"""
    results = []
    with httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": UA}) as c:
        if d.authorization_url.startswith("https://") and is_public_url(d.authorization_url):
            emit("probe", f"GET {d.authorization_url} with a dummy client_id")
            try:
                r = c.get(d.authorization_url, params={"client_id": "pathfinder-probe", "response_type": "code",
                                                       "redirect_uri": "https://example.com/callback", "state": "probe"})
                loc = r.headers.get("location", "")
                results.append(Probe(name="Authorization endpoint responds", url=d.authorization_url,
                                     result=f"HTTP {r.status_code}" + (f" → redirects to {loc[:140]}" if loc else ""),
                                     ok=r.status_code < 500 and r.status_code != 404))
            except Exception as e:
                results.append(Probe(name="Authorization endpoint responds", url=d.authorization_url, result=f"error: {type(e).__name__}", ok=False))
        if d.token_url.startswith("https://") and is_public_url(d.token_url):
            emit("probe", f"POST {d.token_url} with dummy credentials")
            try:
                r = c.post(d.token_url, data={"grant_type": "authorization_code", "code": "probe", "client_id": "pathfinder-probe",
                                              "client_secret": "probe", "redirect_uri": "https://example.com/callback"})
                body = re.sub(r"\s+", " ", r.text[:180])
                # some providers (e.g. Slack) answer 200 with {"ok":false,"error":...}; an OAuth-style error body counts
                oauth_error = bool(re.search(r"invalid_(client|grant|code|request)|\"error\"", r.text[:2000]))
                results.append(Probe(name="Token endpoint rejects dummy credentials", url=d.token_url,
                                     result=f"HTTP {r.status_code}: {body}", ok=r.status_code in (400, 401, 403) or oauth_error))
            except Exception as e:
                results.append(Probe(name="Token endpoint rejects dummy credentials", url=d.token_url, result=f"error: {type(e).__name__}", ok=False))
    return results


# ---------------------------------------------------------------- orchestration
def generate_guide(query: str, emit=lambda k, m: None) -> Guide:
    trace, outer, t0 = [], emit, time.time()
    _ctx.deadline = t0 + BUDGET

    def emit(kind, msg):
        trace.append({"t": round(time.time() - t0, 1), "kind": kind, "msg": msg})
        outer(kind, msg)

    name, domain = _name_from_input(query)
    emit("plan", f"Researching {name}" + (f" ({domain})" if domain else ""))

    results, seen = [], set()
    for q in [f"{name} OAuth app create developer docs", f"{name} register new OAuth application client ID client secret",
              f"{name} OAuth app review verification publish approval",
              f"{name} API rate limits for third-party apps"] + \
             ([f"site:{_site(domain)} OAuth"] if domain else []):
        emit("search", q)
        for r in web_search(q, n=8):
            if r["url"] not in seen:
                seen.add(r["url"]); results.append(r)

    if res := known_provider(query):
        emit("plan", f"{res.app_name} is in the provider registry, so no LLM lookup is needed")
    else:
        res = resolve(query, results, emit)
    emit("plan", f"{res.app_name}: OAuth provider {res.provider}; official docs on {', '.join(res.official_domains) or 'unknown'}")
    reader = Reader(res.official_domains, emit, res.app_name)
    for r in results:
        reader.push(r["url"], title=r.get("title", ""))
    for host in (res.docs_hosts or [])[:1]:  # targeted search inside the official docs
        q = f"site:{host} OAuth app review OR publish OR verification OR scopes"
        emit("search", q)
        for r in web_search(q, n=6):
            reader.push(r["url"], bonus=2, title=r.get("title", ""))

    reader.read(MAX_PAGES)
    if len(reader.pages) < 2:
        raise RuntimeError(f"Could only read {len(reader.pages)} documentation page(s) for '{query}'. Try the app's website URL.")
    # gap-fill (code, no LLM): which standard questions do the official pages not cover yet? search for those only
    missing = coverage(reader.pages)
    if missing and (res.docs_hosts or res.official_domains):
        emit("gap", "Checklist: official pages don't cover " + ", ".join(t for t, _ in missing) + " yet; searching for them")
        site = (res.docs_hosts or res.official_domains)[0]
        before = len(reader.pages)
        for topic, terms in missing[:4]:
            q = f"site:{site} {res.app_name} {terms}"
            emit("search", q)
            for r in web_search(q, n=4):
                reader.push(r["url"], bonus=3, title=r.get("title", ""))
        reader.read(GAP_PAGES)
        still = coverage(reader.pages)
        emit("gap", f"Read {len(reader.pages) - before} more pages; "
             + ("all checklist topics now covered" if not still else "still not covered: " + ", ".join(t for t, _ in still)))
    else:
        emit("gap", "Checklist: official pages cover every standard question")
    checklist = [{"topic": t, "covered": t not in {m for m, _ in coverage(reader.pages)}} for t, _, _ in CHECKLIST]

    # the one LLM call that writes the guide (strongest model with quota left)
    draft, model = extract(res, reader.pages, emit, f"Writing guide from {len(reader.pages)} pages")

    emit("verify", "Checking every quote against the fetched page text")
    build, stats = verifier(reader.pages)

    def items(xs):
        out = []
        for x in xs:
            ev, c = build(x.evidence)
            out.append(Item(text=x.text, evidence=ev, confidence=c))
        return out

    steps = []
    for s in draft.steps:
        ev, c = build(s.evidence)
        steps.append(Step(title=s.title, text=s.detail, url=s.url if s.url.startswith("https://") else "",
                          actor=s.actor, required=s.required, evidence=ev, confidence=c))
    blockers = []
    for b in draft.blockers:
        ev, c = build(b.evidence)
        blockers.append(Blocker(issue=b.issue, why_it_happens=b.why_it_happens, workaround=b.workaround, evidence=ev, confidence=c))
    reqs, nuances = items(draft.requirements), items(draft.nuances)
    caps = []
    for c in draft.capabilities:
        ev, conf = build(c.evidence)
        caps.append(Capability(capability=c.capability, scopes=c.scopes, access=c.access, what_it_takes=c.what_it_takes,
                               evidence=ev, confidence=conf))
    tev, tconf = build(draft.timing_evidence)
    timing = Item(text=f"Setup {draft.setup_time}; approval wait {draft.approval_wait}", evidence=tev, confidence=tconf)
    emit("verify", f"{stats['quotes_verified']}/{stats['quotes']} quotes found verbatim in sources; "
                   f"timeline is {'sourced' if tconf != 'unsupported' else 'an estimate (no source states it)'}")

    probes = probe(draft, emit)
    composio = managed_status(res.app_name)
    if composio:
        emit("probe", f"Composio toolkit '{composio['toolkit']}': managed app {'available' if composio['managed'] else 'not found'}")
    app_name = draft.app_name or res.app_name
    return Guide(
        slug=slugify(app_name), app_name=app_name, website=draft.website,
        category=draft.category, summary=draft.summary, difficulty=draft.difficulty,
        difficulty_reason=draft.difficulty_reason, setup_time=draft.setup_time, approval_wait=draft.approval_wait,
        approval_required=draft.approval_required, approval_details=draft.approval_details,
        authorization_url=draft.authorization_url, token_url=draft.token_url,
        developer_console_url=draft.developer_console_url, uses_pkce=draft.uses_pkce,
        capabilities=caps, requirements=reqs, steps=steps, nuances=nuances, blockers=blockers,
        agent_can_do=draft.agent_can_do, developer_must_do=draft.developer_must_do, unverified=draft.unverified,
        sources=[Source(id=p["id"], url=p["url"], title=p["title"] or p["url"], fetched_via=p["via"], chars=len(p["text"]),
                        official=p["official"], kind=p.get("kind", "official")) for p in reader.pages],
        probes=probes, composio=composio, evidence_stats=stats, timing=timing, trace=trace, checklist=checklist,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), model=model,
        model_tier="fallback" if model in LIGHT_MODELS and model not in MODELS else "strong")
