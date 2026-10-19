"""Dry-run the research agent's discovery + reading for a list of apps (one cheap LLM call each, no guide written).
Usage: python scripts/discovery_check.py Zoom calendly.com Xero"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.fetch import web_search
from app.research import Reader, resolve, _name_from_input, _site, MAX_PAGES

for q in sys.argv[1:]:
    t = time.time()
    name, domain = _name_from_input(q)
    results, seen = [], set()
    for s in [f"{name} OAuth app create developer docs", f"{name} register new OAuth application client ID client secret",
              f"{name} OAuth app review verification publish approval", f"{name} API rate limits for third-party apps"] + \
             ([f"site:{_site(domain)} OAuth"] if domain else []):
        for r in web_search(s, n=8):
            if r["url"] not in seen:
                seen.add(r["url"]); results.append(r)
    res = resolve(q, results, lambda k, m: None)
    rd = Reader(res.official_domains, lambda k, m: None, res.app_name)
    for r in results:
        rd.push(r["url"], title=r.get("title", ""))
    rd.read(MAX_PAGES)
    off = sum(p["official"] for p in rd.pages)
    print(f"\n=== {q} -> {res.app_name} (provider {res.provider}; official {res.official_domains}; oauth={res.supports_oauth}) "
          f"{len(rd.pages)} pages, {off} official, {time.time() - t:.0f}s")
    for p in rd.pages:
        print(f"   {'OFF' if p['official'] else '3rd'} {p['via'][:3]} {len(p['text']):>6}  {p['url'][:110]}")
