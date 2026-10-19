"""Guide schema. `*Draft` types are what the LLM fills in; the server then verifies
evidence quotes against the fetched page text and produces the final `Guide`."""
from typing import Literal
from pydantic import BaseModel, Field

Difficulty = Literal["instant", "easy", "moderate", "hard", "gated"]
Actor = Literal["agent", "developer", "either"]


class EvidenceDraft(BaseModel):
    source_id: int = Field(description="Number N of the [S N] source block the quote comes from")
    quote: str = Field(description="Short VERBATIM excerpt (<=240 chars) copied from that source")


class ItemDraft(BaseModel):
    text: str
    evidence: list[EvidenceDraft]


class StepDraft(BaseModel):
    title: str
    detail: str = Field(description="Concrete instructions: what to click/fill/enter, exact values where known")
    url: str = Field(description="Deep link for this step, or empty string")
    actor: Actor = Field(description="agent = an AI agent/script can do it via API/CLI; developer = needs a human (login, KYC, payment, form review); either")
    required: bool = Field(description="false for optional steps that are not needed for other users to connect, e.g. marketplace/directory listing, publisher badges")
    evidence: list[EvidenceDraft]


class BlockerDraft(BaseModel):
    issue: str
    why_it_happens: str
    workaround: str
    evidence: list[EvidenceDraft]


Access = Literal["self-serve", "review required", "partner / approval", "unclear"]


class CapabilityDraft(BaseModel):
    capability: str = Field(description="What an AI agent would do, in plain words, e.g. 'Read channel messages', 'Send email', 'Post to a company page'")
    scopes: str = Field(description="Scopes / permissions / API product needed, as named by the provider")
    access: Access = Field(description="What it takes to use this for OTHER users in production")
    what_it_takes: str = Field(description="One sentence: review, verification, partner application, rate-limit caveat, etc.")
    evidence: list[EvidenceDraft]


class GuideDraft(BaseModel):
    app_name: str
    website: str
    category: str = Field(description="e.g. Productivity, CRM, Dev tools, Social")
    summary: str = Field(description="2-3 sentences: what the developer must do to ship OAuth for this app")
    difficulty: Difficulty = Field(description="Rate ONLY the REQUIRED path for users outside your own org/workspace to connect in production (ignore optional marketplace listings). instant=self-serve, no review, minutes; easy=self-serve, <1h, maybe a distribution toggle; moderate=self-serve but extra verification/config, hours-days, or review only for some scopes; hard=provider review/verification required for typical scopes, days-weeks; gated=partner program or approval you may not get")
    difficulty_reason: str
    setup_time: str = Field(description="Hands-on time, e.g. '15-30 minutes'")
    approval_wait: str = Field(description="Wait for provider approval, e.g. 'None', '1-3 business days', 'Several weeks'. Say 'Not documented' if unknown")
    timing_evidence: list[EvidenceDraft] = Field(description="Verbatim quotes that state setup or review durations. EMPTY if setup_time/approval_wait are your own estimates")
    approval_required: bool
    approval_details: str = Field(description="What gets reviewed and what triggers review (scopes, user count, publishing). Empty string if none")
    authorization_url: str = Field(description="OAuth authorization endpoint if stated in sources, else empty")
    token_url: str = Field(description="OAuth token endpoint if stated in sources, else empty")
    developer_console_url: str = Field(description="Where the OAuth app is created, else empty")
    uses_pkce: bool
    capabilities: list[CapabilityDraft] = Field(description="3-6 rows mapping typical agent capabilities to the scopes/products and access level each needs. Difficulty often depends on this.")
    requirements: list[ItemDraft] = Field(description="Prerequisites: account type, paid plan, business verification, domain, privacy policy URL, etc.")
    steps: list[StepDraft]
    nuances: list[ItemDraft] = Field(description="Gotchas: redirect URI rules, scope quirks, token expiry/refresh, rate limits, test-user caps, per-workspace installs")
    blockers: list[BlockerDraft]
    agent_can_do: list[str] = Field(description="Parts of the process an agent can do or has done for the developer")
    developer_must_do: list[str] = Field(description="Parts needing a human")
    unverified: list[str] = Field(description="Important things the sources did NOT confirm. Be honest and specific.")


class Evidence(BaseModel):
    source_id: int
    url: str
    quote: str
    verified: bool  # quote found in the fetched page text


class Item(BaseModel):
    text: str
    evidence: list[Evidence] = []
    confidence: Literal["verified", "partial", "unsupported"] = "unsupported"


class Step(Item):
    title: str = ""
    url: str = ""
    actor: Actor = "developer"
    required: bool = True


class Blocker(BaseModel):
    issue: str
    why_it_happens: str
    workaround: str
    evidence: list[Evidence] = []
    confidence: Literal["verified", "partial", "unsupported"] = "unsupported"


class Capability(BaseModel):
    capability: str
    scopes: str
    access: Access
    what_it_takes: str
    evidence: list[Evidence] = []
    confidence: Literal["verified", "partial", "unsupported"] = "unsupported"


class Source(BaseModel):
    id: int
    url: str
    title: str
    fetched_via: str  # direct | reader
    chars: int
    official: bool = True
    kind: Literal["official", "community", "third-party"] = "official"


class Probe(BaseModel):
    name: str
    url: str
    result: str
    ok: bool


class Guide(BaseModel):
    slug: str
    app_name: str
    website: str
    category: str
    summary: str
    difficulty: Difficulty
    difficulty_reason: str
    setup_time: str
    approval_wait: str
    approval_required: bool
    approval_details: str
    authorization_url: str
    token_url: str
    developer_console_url: str
    uses_pkce: bool
    capabilities: list[Capability] = []
    requirements: list[Item]
    steps: list[Step]
    nuances: list[Item]
    blockers: list[Blocker]
    agent_can_do: list[str]
    developer_must_do: list[str]
    unverified: list[str]
    sources: list[Source]
    probes: list[Probe]
    evidence_stats: dict
    generated_at: str
    model: str
    model_tier: Literal["strong", "fallback"] = "strong"  # fallback = written by a Flash-Lite model because stronger ones were unavailable
    timing: Item | None = None  # evidence for setup_time / approval_wait; "unsupported" means it's an estimate
    trace: list[dict] = []  # what the agent searched, read, skipped and decided
    checklist: list[dict] = []  # standard questions and whether the official sources cover them
    composio: dict | None = None  # managed-app status from Composio's toolkit API, when a key is configured
    review: dict | None = None  # human verification notes (curated guides): date, summary, checked[], corrections[]
