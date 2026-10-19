# Verification log

How I checked the guidance, what the checks caught, what changed because of them, and what is still uncertain.
Dates are when the check was done (2026-10-19 unless noted).

## Three layers of checking

| Layer | Runs on | What it proves | What it can't prove |
|---|---|---|---|
| **1. Quote matching** (code) | Every claim in every guide | The cited sentence really exists in the cited official page | That the claim correctly *follows* from the sentence |
| **2. Live endpoint probes** (code) | Every guide with documented endpoints | The authorize / token URLs exist and behave like OAuth (redirect to consent, reject dummy credentials) | Anything about review or approval |
| **3. Human spot-checks and setup attempts** | A sample of claims, plus hands-on attempts | Judgement: is the rating right, is a step really required, does the console match the docs? | Doesn't scale; only covers what I sampled |

Layer 3 exists because layers 1–2 *passed* guides that were still wrong. The examples are below.

## What the checks caught, and what I changed

| # | What happened | How it was caught | Change |
|---|---|---|---|
| 1 | The first GitHub guide rated GitHub **moderate** because of *Marketplace publisher verification*, and had no "register an OAuth app" step. A plain GitHub OAuth app needs no review. | Human read of the guide | The difficulty rating now covers only the **required** path. Optional steps (marketplace listings, badges) are badged *Optional* and can't raise the rating. |
| 2 | That GitHub run's "12 sources" were ~4 documents read several times: the enterprise-cloud version, the raw GitHub markdown, and an API mirror. | Inspecting the source list | Near-duplicate pages are removed by text similarity, and mirror URL patterns rank lower. "Creating an OAuth app" is now read. |
| 3 | Quote matching under-reported: 5/12 quotes "not found" for Notion, although most were real. Converting HTML to text inserts spaces around bold and code tags. | Reading the failed quotes against page text | Matching now ignores whitespace, with a near-verbatim fallback (≥90% of 6-word chunks match). Notion went from 5/12 to 10/12 and Gmail from 13/23 to 22/23. |
| 4 | The remaining failures were real paraphrases. Gmail: "Google's OAuth policies require separate projects…" vs the heading "Use separate projects for testing and production". Notion: rows of a parameter table merged into one "quote". | Same | Kept as **not found verbatim**, shown in red with the source link. The claim may be right, but it isn't a quote. |
| 5 | A Flash-Lite guide marked Slack's **"Activate Public Distribution"** as *optional* (it's what lets other workspaces install the app). It also rated Slack **hard / up to 10 weeks**, based on the *optional* Marketplace review. All 13 of its quotes were real. | Human read | Guides record which model wrote them. Fallback-model guides carry a **"Draft quality"** banner. The final pass uses the strongest available model. Demo guides get a human review. |
| 6 | Google pages appeared as sources in the LinkedIn and Notion guides. They ranked high on review/verification keywords. | Inspecting source lists | Official-docs pages always rank above third-party ones, and third-party pages must mention the app. |
| 7 | The Slack token-endpoint probe was flagged ⚠️. Slack answers **HTTP 200** with `{"ok":false,"error":"invalid_code"}` rather than 4xx. | Reviewing probe output | A probe now passes on an OAuth-style error body as well as on a 4xx status. |

## Independent spot-checks against official docs

| App | Claim | Result | Source |
|---|---|---|---|
| Google | Sensitive-scope verification "typically takes 3-5 business days" | ✅ Confirmed | [sensitive-scope-verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification) |
| Google | Restricted scopes "can potentially take several weeks"; brand verification "typically takes 2-3 business days" if branding changed | ✅ Confirmed | [restricted-scope-verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) |
| Google | Restricted scopes accessed via a third-party server need a security assessment by a Google-empanelled assessor (CASA), repeated "at least every 12 months" | ✅ Confirmed | same |
| Google | Cost of that security assessment | ❔ **Not documented** on Google's pages. Any figure would be hearsay. | — |
| Google | Apps in "Testing" status get refresh tokens "expiring in 7 days" (unless only name/email/profile scopes) | ✅ Confirmed. This matters for agents: a testing-mode Gmail agent silently loses access after a week. | [oauth2 overview](https://developers.google.com/identity/protocols/oauth2) |
| Google | Exact user cap for unverified / testing apps | ❔ The docs say a cap exists but don't state the number on the pages checked. | — |
| Notion | "The Authorization URL field populates after a public connection is submitted for review" | ⚠️ **Ambiguous.** The docs never say what this review is, who does it, or how long it takes. Basic OAuth otherwise looks self-serve. → hands-on test below | [authorization](https://developers.notion.com/guides/get-started/authorization) |
| Slack | Marketplace listing is optional | ⚠️ **True on paper, misleading for agents.** Since 2025-05-29, commercially distributed apps *not* approved for the Marketplace get `conversations.history` / `conversations.replies` cut to **1 request/minute, 15 objects**. An agent that reads messages effectively needs Marketplace approval. | [changelog](https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps/), [clarification](https://docs.slack.dev/changelog/2025/06/03/rate-limits-clarity/) |
| Slack | When existing installs became subject to the new limits | ❔ **Slack's own pages disagree:** 2025-06-30 (EN changelog), 2025-09-02 (JA FAQ), 2026-03-03 (current method reference). | [conversations.history](https://docs.slack.dev/reference/methods/conversations.history/) |
| LinkedIn | Fallback guide rated LinkedIn **easy** | ❌ **Only true for sign-in and posting as the member.** "Open permissions" are only `profile`, `email`, `w_member_social`. Docs: "Most permissions and partner programs require explicit approval from LinkedIn." Advertising, Sales Navigator and Talent APIs are partner programs; Compliance is closed. | [getting-access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access) |
| Composio | Redirect URI to register with the provider: `https://backend.composio.dev/api/v3/toolkits/auth/callback` | ✅ Confirmed (Composio's Notion setup guide) | [composio.dev/auth/notion](https://composio.dev/auth/notion) |
| Composio | Managed apps show "Composio" on the consent screen, share rate-limit quota across Composio users, enforce a 15-minute minimum polling interval | ✅ Confirmed. This is *why* developers need their own app in production. | [Managed vs custom auth](https://docs.composio.dev/docs/authentication/custom-app-vs-managed-app) |

These findings shaped the product: the **"What will your agent do? Access depends on it"** table exists because the Slack and LinkedIn answers depend on the capability, not on the app.

## Hands-on setup attempts

> _To be filled in from real attempts (free accounts, no secrets recorded)._

| App | What I did | Time | Matched the guide? | Surprises |
|---|---|---|---|---|
| GitHub | Register a new OAuth app with the Composio callback URL | | | |
| Notion | Create a public connection; does the authorization URL appear without "review"? | | | |
| Google | Create project → OAuth consent screen (External) → add a Gmail scope | | | |

## Still uncertain

- **Review timelines** are documented by Google (sensitive and restricted scopes) and Slack (Marketplace, "up to 10 weeks"). For most other providers they are not documented, and the guides say "Not documented" or label the number an estimate.
- **Reviewer behaviour** (common rejection reasons, back-and-forth) isn't in the docs. Some guides' blockers are inferred from requirements rather than observed.
- **Docs drift.** Slack's conflicting dates show official docs can disagree with each other. Each guide records its generation date and sources, and can be regenerated.
