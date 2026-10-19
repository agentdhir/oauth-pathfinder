"""Re-check every quote in saved guides against their source pages (no LLM calls).
Usage: python scripts/reverify.py notion gmail   (or no args for all guides)"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.fetch import fetch_page
from app.research import _norm, quote_in
from app.main import GUIDES

slugs = sys.argv[1:] or [p.stem for p in GUIDES.glob("*.json")]
for slug in slugs:
    path = GUIDES / f"{slug}.json"
    g = json.loads(path.read_text(encoding="utf-8"))
    norm = {}
    for s in g["sources"]:
        p = fetch_page(s["url"])
        norm[s["id"]] = _norm(p["text"]) if p else ""
    stats = {"claims": 0, "verified": 0, "partial": 0, "unsupported": 0, "quotes": 0, "quotes_verified": 0}
    failed = []
    for sec in ("capabilities", "requirements", "steps", "nuances", "blockers"):
        for it in g.get(sec, []):
            for e in it["evidence"]:
                e["verified"] = quote_in(e["quote"], norm.get(e["source_id"], ""))
                stats["quotes"] += 1
                stats["quotes_verified"] += e["verified"]
                if not e["verified"]:
                    failed.append((e["source_id"], e["quote"][:150]))
            good = sum(e["verified"] for e in it["evidence"])
            it["confidence"] = "verified" if good and good == len(it["evidence"]) else "partial" if good else "unsupported"
            stats["claims"] += 1
            stats[it["confidence"]] += 1
    if g.get("timing"):  # timeline evidence is reported separately, not counted in claim stats
        t = g["timing"]
        for e in t["evidence"]:
            e["verified"] = quote_in(e["quote"], norm.get(e["source_id"], ""))
        good = sum(e["verified"] for e in t["evidence"])
        t["confidence"] = "verified" if good and good == len(t["evidence"]) else "partial" if good else "unsupported"
    g["evidence_stats"] = stats
    path.write_text(json.dumps(g, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{slug}: {stats['quotes_verified']}/{stats['quotes']} quotes verified")
    for sid, q in failed:
        print(f"   not found in S{sid}: {q!r}")
