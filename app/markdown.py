"""Render a guide as portable Markdown (paste into a ticket, Notion page, or PR)."""

CONF = {"verified": "✅ quote-verified", "partial": "⚠️ partly verified", "unsupported": "❔ unsourced"}


def _cite(ev: list[dict]) -> str:
    ids = sorted({e["source_id"] for e in ev})
    return " " + "".join(f"[S{i}]" for i in ids) if ids else ""


def to_markdown(g: dict) -> str:
    L = [f"# {g['app_name']}: OAuth app setup & approval guide", "",
         f"> {g['summary']}", "",
         f"| Difficulty | Hands-on setup | Approval wait | Review required |",
         f"|---|---|---|---|",
         f"| **{g['difficulty'].title()}** | {g['setup_time']} | {g['approval_wait']} | {'Yes' if g['approval_required'] else 'No'} |", "",
         f"**Why:** {g['difficulty_reason']}", ""]
    if g.get("timing"):
        L += ["_Timeline: " + ("quoted from source" + _cite(g["timing"]["evidence"]) if g["timing"]["confidence"] != "unsupported"
                               else "estimate. No source states it.") + "_", ""]
    if g.get("approval_details"):
        L += ["## Approval / review", g["approval_details"], ""]
    if g.get("review"):
        r = g["review"]
        L += ["## Human review", f"Reviewed {r.get('date', '')}: {r.get('summary', '')}", ""]
        for c in r.get("corrections", []):
            L.append(f"- **Correction:** {c}")
        L.append("")
    if g.get("capabilities"):
        L += ["## What will your agent do? Access depends on it", "", "| Capability | Scopes / product | Access | What it takes |", "|---|---|---|---|"]
        L += [f"| {c['capability']} | `{c['scopes']}` | **{c['access']}** | {c['what_it_takes']}{_cite(c['evidence'])} |" for c in g["capabilities"]]
        L.append("")
    L += ["## Before you start"]
    for it in g["requirements"]:
        L.append(f"- {it['text']}{_cite(it['evidence'])} _{CONF[it['confidence']]}_")
    L += ["", "## Steps"]
    for i, s in enumerate(g["steps"], 1):
        who = {"agent": "🤖 agent", "developer": "🧑 you", "either": "🤖/🧑 either"}[s["actor"]]
        if s.get("required") is False:
            who += ", optional"
        link = f" ([open]({s['url']}))" if s.get("url") else ""
        L.append(f"{i}. **{s['title']}** ({who}){link}: {s['text']}{_cite(s['evidence'])}")
    L += ["", "## Plug it into Composio",
          "1. Register redirect URI `https://backend.composio.dev/api/v3/toolkits/auth/callback` in the provider app (exact match, HTTPS, no trailing slash).",
          f"2. Composio dashboard → Auth Configs → {g['app_name']} toolkit → OAuth2 → enable \"Use your own developer authentication\" → paste Client ID and Client Secret.",
          "3. Pass the Auth Config ID (`ac_...`) to your session for this toolkit.",
          "4. Connect a test account via Connect Link / Playground; confirm your app's name on the consent screen.",
          "", "## Nuances & gotchas"]
    for it in g["nuances"]:
        L.append(f"- {it['text']}{_cite(it['evidence'])}")
    L += ["", "## If you get blocked"]
    for b in g["blockers"]:
        L.append(f"- **{b['issue']}**: {b['why_it_happens']} → _Workaround:_ {b['workaround']}{_cite(b['evidence'])}")
    L += ["", "## Who does what", "**An agent can:**"] + [f"- {x}" for x in g["agent_can_do"]]
    L += ["", "**You need to:**"] + [f"- {x}" for x in g["developer_must_do"]]
    L += ["", "## What we could not verify"] + [f"- {x}" for x in g["unverified"] or ["Nothing flagged."]]
    if g.get("probes"):
        L += ["", "## Live checks"] + [f"- {'✅' if p['ok'] else '⚠️'} {p['name']}: `{p['url']}` → {p['result']}" for p in g["probes"]]
    s = g.get("evidence_stats", {})
    L += ["", "## Sources",
          f"_{s.get('quotes_verified', 0)}/{s.get('quotes', 0)} cited quotes were found verbatim in the fetched pages. "
          f"Generated {g['generated_at']} by {g['model']}._", ""]
    L += [f"- [S{x['id']}] [{x['title']}]({x['url']})" for x in g["sources"]]
    return "\n".join(L) + "\n"
