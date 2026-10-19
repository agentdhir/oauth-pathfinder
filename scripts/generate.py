"""Generate guides from the command line: python scripts/generate.py Notion "Google Gmail" linkedin.com"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.research import generate_guide
from app.main import GUIDES, REVIEWS

for q in sys.argv[1:]:
    t = time.time()
    print(f"\n=== {q}")
    try:
        g = generate_guide(q, emit=lambda k, m: print(f"  [{k}] {m}"))
    except Exception as e:
        print(f"  FAILED: {e}")
        continue
    if (REVIEWS / f"{g.slug}.json").exists():
        print(f"  NOTE: reviews/{g.slug}.json now refers to an older version; re-check it and update guide_generated_at")
    (GUIDES / f"{g.slug}.json").write_text(g.model_dump_json(indent=2), encoding="utf-8")
    s = g.evidence_stats
    print(f"  -> guides/{g.slug}.json  {g.difficulty} | setup {g.setup_time} | wait {g.approval_wait} | "
          f"quotes {s['quotes_verified']}/{s['quotes']} | {time.time() - t:.0f}s via {g.model}")
