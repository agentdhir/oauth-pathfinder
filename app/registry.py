"""Known providers, so the agent doesn't spend an LLM call working out where the official docs live.
data/providers.json is hand-seeded; apps the agent resolves itself are remembered in cache/providers_learned.json."""
import json, re
from pathlib import Path
from .storage import CACHE_DIR

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "providers.json"
LEARNED = CACHE_DIR / "providers_learned.json"


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _load() -> dict:
    out = {}
    for f, src in ((SEED, "registry"), (LEARNED, "learned")):
        if f.exists():
            for e in json.loads(f.read_text(encoding="utf-8")):
                e["source"] = src
                for alias in [e["app_name"], *e.get("aliases", [])]:
                    out.setdefault(_key(alias), e)
    return out


def lookup(name: str, domain: str | None = None) -> dict | None:
    reg = _load()
    if e := reg.get(_key(name)):
        return e
    if domain:
        site = ".".join(domain.lower().split(".")[-2:])
        for e in reg.values():
            if site in e["official_domains"]:
                return e
    return None


def remember(query: str, app_name: str, provider: str, official_domains: list[str], docs_hosts: list[str]):
    """Save an LLM resolution so the next lookup of this app is free."""
    if not official_domains:
        return
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(LEARNED.read_text(encoding="utf-8")) if LEARNED.exists() else []
    if any(_key(e["app_name"]) == _key(app_name) for e in data):
        return
    data.append({"app_name": app_name, "aliases": [query] if _key(query) != _key(app_name) else [], "provider": provider,
                 "official_domains": official_domains, "docs_hosts": docs_hosts})
    LEARNED.write_text(json.dumps(data, indent=1), encoding="utf-8")
