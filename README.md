# OAuth Pathfinder

**Look up an app → get a shareable guide to creating your own OAuth app with that provider and getting it approved.**
Each guide gives a difficulty rating, the hands-on time and the approval wait separately, prerequisites, ordered steps marked *agent can do* or *you*, the nuances and blockers to expect, and a clear account of what's sourced, what was tested, and what's still uncertain.
If the app isn't in the library, an agent researches it live (≈1–2 min) and publishes a guide at a share link.

- Live: `<deploy URL>`
- Demo guides: GitHub, HubSpot, Slack, Notion, Gmail, LinkedIn. Each has a different kind of setup challenge, from instant self-serve to partner-gated.
- Verification log: [VERIFICATION.md](VERIFICATION.md)

## The problem, as I understand it

An agent builder can prototype on a platform's **managed OAuth app**. Composio's docs say most popular toolkits ship with one. Before launch, they usually need **their own OAuth app** with the provider. Reasons:
- their name on the consent screen instead of "Composio";
- scopes beyond the platform defaults;
- a dedicated rate-limit quota;
- for some toolkits, no managed app exists at all.

Creating the app is usually the easy part. What hurts is everything around it, and it differs wildly by provider:

| Pattern | Example | What actually costs time |
|---|---|---|
| Self-serve, no review | GitHub | ~15 minutes |
| Self-serve + distribution switch | Slack, Notion | Enabling public distribution; optional directory/marketplace review |
| Verification by scope | Google (Gmail) | Brand verification; sensitive scopes need review; restricted scopes need a security assessment |
| Partner-gated | LinkedIn | The API you need may require an application you may not get |

Developers can't tell which of these they're in until they're halfway through. Composio's existing setup pages (composio.dev/auth) cover *how to create credentials*. They don't cover difficulty, timelines, review triggers or blockers. **That gap is this project's scope.**

## Key decisions

1. **Answer the questions a developer actually has, in this order.** First: how hard is this, how long is the hands-on work, how long is the wait, and do I need review? Then the steps. The verdict strip shows hands-on time and approval wait separately, because "30 minutes of work and 3 weeks of waiting" calls for a different plan than "3 hours of work".
2. **"What will your agent do?" comes before the steps.** Difficulty often depends on the capability, not the app. Slack: posting is self-serve, but unlisted apps get 1 request/min on reading message history, so a reader agent effectively needs Marketplace approval. LinkedIn: sign-in and posting as the member are open, while nearly everything else is a partner program. Gmail: sensitive vs restricted scopes mean days vs weeks. Each guide has a capability → scopes → access table (self-serve / review / partner), and the overall rating is for the most common agent use case.
3. **Evidence is checked by code, not by the LLM.** Every requirement, step, nuance and blocker must carry a short verbatim quote from a fetched page. The server checks each quote against the page text by string matching, ignoring whitespace, with a near-verbatim fallback, and labels each claim:
   - *verified*: every quote it cites was found in the source;
   - *partial*: some of its quotes were found;
   - *unsupported*: none were found.

   Every quote is one click from its source.
4. **Timelines get special treatment.** Approval wait is the number developers care about most, and the one docs state least often. The guide shows whether the timeline is *quoted from a source* or *an estimate*.
5. **Official docs first, forums labelled.** The agent works out the provider's official domains, so "Gmail" resolves to google.com and SDK mirrors don't count. Forum posts (e.g. devforum.zoom.us) are labelled *community, anecdotal*. They're often the only place real approval wait times are reported, so they're kept, but the guide must say "(reported by developers on the forum)". At most 2 community and 2 third-party pages are read.
6. **The agent does what an agent practically can, and says where you take over.**
   - **Searches and reads:** it searches, picks official docs, and follows links into review, scopes and publishing pages.
   - **Gap-filling:** every guide must answer the same 7 questions: review process, review timeline, distribution, scopes, token lifetime, rate limits, user caps. Code checks which ones the official pages already answer, and the agent searches only for the rest. Each guide shows the coverage.
   - **Live probes:** it calls the documented authorize endpoint with a dummy client_id and the token endpoint with dummy credentials. This confirms the endpoints are real and behave like OAuth, for example `invalid_client`.
   - **Where it stops:** it doesn't create accounts, accept terms, or pass identity or business verification. Every step is labelled *agent* or *you*.
7. **Shareable by default.** Each guide has a stable URL with link previews, plus a Markdown export for tickets and docs. A progress checklist is saved in the browser.
8. **Composio does the OAuth plumbing, so the guide doesn't teach it.** Generated steps cover only the provider side: create the app, configure it, get approved, distribute. A fixed "Plug it into Composio" section (callback URL, Auth Config, `ac_` ID, test) replaces the usual "build the authorize URL / exchange the code" steps. A "Do you need your own OAuth app yet?" panel shows whether Composio already has a managed app, when `COMPOSIO_API_KEY` is set.
9. **Use code wherever the work is the same every time, and the LLM only for judgement.** Reviewing the pipeline for repeated work moved four things from the LLM to code:
   - a provider registry (≈45 popular apps, plus every app the agent resolves itself is remembered);
   - the gap checklist;
   - the fixed Composio section;
   - quote checks and endpoint probes.

   A guide for a known app costs **one** LLM call, and an unknown app costs two (down from three). That matters on a free tier of 20 requests per model per day.

## How it works

```
query ─► web search (DuckDuckGo)
      ─► official domains: provider registry, else Gemini Flash-Lite (result remembered)            [0–1 LLM call]
      ─► read ≤9 pages, official first, follow review/scope/publish links (httpx; r.jina.ai reader for JS-rendered docs)
      ─► checklist (code): which of 7 standard questions are unanswered? search + read ≤3 more pages
      ─► write guide (strongest Gemini Flash model with quota left; structured JSON output)       [1 LLM call]
      ─► verify quotes against page text (code) ─► probe authorize/token endpoints ─► save JSON ─► /g/<slug>
```

Progress streams to the browser over Server-Sent Events. Each guide stores the agent's trace (searches, reads, skips, decisions). Human verification lives separately in `reviews/<slug>.json` (see [reviews/README.md](reviews/README.md)), so regenerating a guide never erases it.

## Run locally

```bash
python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add GEMINI_API_KEY (free: https://aistudio.google.com/apikey)
python scripts/list_models.py              # optional: see which models your key can use
uvicorn app.main:app --reload              # http://127.0.0.1:8000
python scripts/generate.py Asana "Microsoft Outlook"   # optional: batch-generate guides
python scripts/reverify.py                 # re-check every saved quote against its source (no LLM)
```

### Deploy on Vercel (free Hobby plan)

1. Import the GitHub repo in Vercel. FastAPI is detected from `requirements.txt`, and the entrypoint is `app/main.py`. `vercel.json` sets a 300 s max duration, which a live generation needs.
2. Add environment variables: `GEMINI_API_KEY` (required), plus `GEMINI_MODELS` and `GEMINI_LIGHT_MODELS` from `.env.example`.
3. Optional but recommended: **Storage → Upstash Redis** (free) in the Vercel dashboard. It sets `KV_REST_API_URL` / `KV_REST_API_TOKEN`. Without it, live-generated guides live only in the function's `/tmp` and their share links can break when the instance is recycled. Curated guides are always fine.

## Limitations

- **Free-tier quotas.** The Gemini free tier allows 20 requests/day per model, and the stronger models are often "busy". Each guide uses 1 strong-model call (plus 1 Flash-Lite call for apps outside the registry), with fallback across models. If only Flash-Lite is available, the guide still generates but carries a **"Draft quality"** banner: in my tests Flash-Lite quoted correctly but misjudged which steps are required. Live generation on the public link is rationed (4 per visitor per hour, 30 per day) so the quota lasts. Heavy use needs a paid key.
- **Docs ≠ reality.** The guide is only as good as the public docs. Review timelines are rarely documented, and actual reviewer behaviour (rejection reasons, back-and-forth) mostly isn't in docs. The human-tested notes in VERIFICATION.md partly cover this.
- **Quote matching proves a quote exists, not that the claim follows from it.** A real quote can still be over-generalised. Spot-checks are in VERIFICATION.md.
- **Search quality.** DuckDuckGo results vary, and some docs are JS-rendered or block bots. The reader fallback helps but isn't perfect.
- **Storage.** Curated guides and human reviews are JSON files in the repo. Live-generated guides go to Redis when configured, otherwise to temporary storage. The page cache and learned-provider list are temporary on Vercel, which only costs a little speed.
- **No login automation.** The agent never signs into developer consoles. That is deliberate (credentials, ToS), and those steps are marked *you*.
