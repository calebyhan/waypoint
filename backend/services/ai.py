import json
import logging
from collections.abc import Awaitable, Callable
from enum import Enum

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from core.config import settings
from models.decomposition import (
    ClarifyingQuestionsResult,
    DecompositionEpic,
    DecompositionResult,
    EpicSkeleton,
    EpicTasksResult,
    PlanSkeleton,
    ProjectContext,
    TeamMemberInfo,
)

logger = logging.getLogger(__name__)


class GeminiErrorKind(str, Enum):
    INVALID_KEY = "invalid_key"        # 401/403 from Gemini
    QUOTA_EXCEEDED = "quota_exceeded"  # 429 (RPD/TPM/RPM)
    TIMEOUT = "timeout"                # client-side timeout or 504
    SERVER_ERROR = "server_error"      # 5xx from Gemini
    BAD_OUTPUT = "bad_output"          # JSON parse / Pydantic validation failure
    UNKNOWN = "unknown"


class GeminiError(Exception):
    """Typed wrapper for anything that can go wrong talking to Gemini.

    `message` is always safe to show to an end user -- raw SDK exception text
    must never travel past classify_exception().
    """

    def __init__(self, kind: GeminiErrorKind, message: str, retry_after: int | None = None):
        self.kind = kind
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


def classify_exception(exc: Exception) -> GeminiError:
    """Map an exception from the google-genai SDK (or json/pydantic parsing)
    to a GeminiError with an actionable, non-leaky kind + message."""
    if isinstance(exc, GeminiError):
        return exc

    if isinstance(exc, (json.JSONDecodeError, ValidationError)):
        return GeminiError(
            GeminiErrorKind.BAD_OUTPUT,
            "The model returned output that didn't match the expected format. Please retry.",
        )

    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code in (401, 403):
            return GeminiError(
                GeminiErrorKind.INVALID_KEY,
                "Your Gemini API key was rejected. Update it in your profile settings.",
            )
        if code == 429:
            return GeminiError(
                GeminiErrorKind.QUOTA_EXCEEDED,
                "Gemini rate limit or daily quota reached for this key. Try again later.",
                retry_after=60,
            )
        if code and 500 <= code < 600:
            return GeminiError(
                GeminiErrorKind.SERVER_ERROR,
                "Gemini is temporarily unavailable. Please retry.",
            )

    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return GeminiError(GeminiErrorKind.TIMEOUT, "The request to Gemini timed out. Please retry.")

    return GeminiError(GeminiErrorKind.UNKNOWN, "AI request failed unexpectedly. Please retry.")


_RETRYABLE_KINDS = (
    GeminiErrorKind.QUOTA_EXCEEDED,
    GeminiErrorKind.SERVER_ERROR,
    GeminiErrorKind.TIMEOUT,
)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, GeminiError) and exc.kind in _RETRYABLE_KINDS


async def _with_retry(fn: Callable[[], Awaitable]):
    """Run one Gemini call with exponential backoff on 429/5xx/timeout.

    Every exception is classified into a GeminiError before the retry
    predicate sees it, so non-retryable kinds (invalid key, bad output)
    fail fast and callers only ever catch GeminiError.
    """

    async def classified():
        try:
            return await fn()
        except GeminiError:
            raise
        except Exception as exc:
            raise classify_exception(exc) from exc

    retryer = AsyncRetrying(
        stop=stop_after_attempt(settings.gemini_retry_attempts),
        wait=wait_exponential(
            multiplier=1,
            min=settings.gemini_retry_wait_min,
            max=settings.gemini_retry_wait_max,
        ),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    return await retryer(classified)


def _make_client(gemini_key: str, timeout_ms: int) -> genai.Client:
    return genai.Client(
        api_key=gemini_key,
        http_options=types.HttpOptions(timeout=timeout_ms),  # milliseconds
    )


def _usage_from_response(response) -> dict:
    meta = getattr(response, "usage_metadata", None)
    return {
        "tokens_in": getattr(meta, "prompt_token_count", 0) or 0,
        "tokens_out": getattr(meta, "candidates_token_count", 0) or 0,
    }


def _sum_usage(total: dict, part: dict) -> dict:
    return {
        "tokens_in": total["tokens_in"] + part["tokens_in"],
        "tokens_out": total["tokens_out"] + part["tokens_out"],
    }


QUESTIONS_PROMPT = """You are an AI project planning assistant. A project manager has provided a PRD (Product Requirements Document) or project description. Your job is to ask up to 3 clarifying questions that will help you produce a better task breakdown.

The PM has already provided structured context for: timeline, team size, and budget. Do NOT ask about those — focus on gaps the PRD leaves open that would meaningfully change the decomposition.

Areas to consider:
- Target users, expected scale, and performance requirements
- Integration requirements (third-party APIs, existing systems, data sources)
- Compliance, security, or regulatory constraints (HIPAA, SOC2, GDPR, etc.)
- MVP scope vs full vision — phased rollout or all-at-once?
- Success metrics and how they'll be measured
- Tech stack preferences or existing infrastructure constraints
- Deployment environment (cloud provider, on-prem, edge, etc.)
- Design or UX requirements (accessibility, branding, mobile-first, etc.)

Only ask questions whose answers would meaningfully change the task decomposition. If the document is clear enough, return fewer questions or none.

Respond with JSON matching this schema:
{
  "questions": [
    {"question": "...", "why": "..."}
  ]
}
"""

SKELETON_PROMPT = """You are an AI project planning assistant. Given a PRD, produce a high-level epic plan that covers the ENTIRE project from an empty repo to a deployed, tested product. Always assume we are starting from complete scratch — no existing codebase, no existing infrastructure, no prior code. Even if the PRD references "the current system" or "our existing X," treat those as descriptions of the target behavior, not existing code.

Walk through every phase below and produce at least one epic for each that applies:
1. Foundation / scaffolding — project setup, data models, schema/migrations, config/env vars, dependencies
2. Backend implementation — API routes, services, persistence logic, auth/security
3. Frontend implementation — app shell, components, pages, state management, API client
4. Integration / end-to-end wiring — connecting frontend to backend, error handling, the full user flow working start to finish
5. Testing — unit/integration/e2e tests, especially for security- or money-sensitive logic
6. Deployment / infra / rollout — CI/CD, hosting, monitoring, analytics for the success metrics named in the PRD

COVERAGE CHECK: list every Must Have, Should Have, Could Have, and Non-Functional Requirement bullet in the PRD to yourself. Every single one must map to at least one epic's scope. Lower-priority items must still be covered — never silently drop a requirement. If the PRD names success metrics, include an epic (or scope within an epic) for the analytics/tracking needed to measure them.

Order epics in build sequence — earlier epics are built first, later epics depend on them.

Also produce a "summary": a 3-5 sentence business justification connecting the proposed epic plan to the PRD's stated goals, personas, and success metrics. Explain WHY this plan structure serves the business objectives — do not just restate the epic titles.

Respond with JSON matching this schema:
{
  "summary": "Business justification paragraph...",
  "epics": [
    {"title": "Epic Name", "scope": "1-2 sentences: what this epic covers and what it delivers"}
  ]
}
"""

EPIC_TASKS_PROMPT = """You are an AI project planning assistant. You are expanding ONE epic from a larger project plan into PR-sized engineering tickets (1-2 days of work each).

You are building from complete scratch — no existing codebase. Every model, endpoint, component, and config file must be created from zero.

THE FULL EPIC PLAN is provided below as context. Use it to ensure technology and architecture choices are CONSISTENT across all your tickets — if the plan-level scope names a specific technology (e.g., "TimescaleDB," "Python/FastAPI," "React"), use that same technology in your deliverables. Never contradict or switch technologies that were established in other epics' scopes.

Rules:
- Each ticket should be completable in a single PR (1-2 days)
- Assign priorities: p0 (launch blocker), p1 (important), p2 (nice to have)
- Let the epic's actual scope determine the number of tickets — some epics naturally require 3 tickets, others require 8+. Do not pad to a fixed count or compress to fit one. If you only have 1-2 tickets, you have not decomposed deeply enough; if you have 10+, check whether some tickets can be merged without exceeding 2 days.
- "deliverables" must name concrete things to build: specific model/table/column names, exact endpoint paths with params, specific component or file names, specific function signatures. Never write a deliverable like "set up infrastructure" or "implement backend logic."
- "important_notes" must call out things an engineer would otherwise get wrong: explicit non-goals ("X is NOT part of this ticket"), ordering gotchas, edge cases, or constraints from the PRD.
- "motivation" is 1-2 sentences on why this ticket matters now / what it unblocks — not a restatement of the deliverables.
- Dependencies: a ticket may depend on another ticket within this epic, OR on any ticket title from the PREVIOUSLY GENERATED TICKETS list below. Do not invent dependencies on tickets that don't appear in either list. Dependency direction must reflect build order — if ticket A must exist before ticket B can be built (e.g., you need a repo before you can configure CI for it, you need a schema before you can write queries against it), then B depends on A, not the reverse.

TEAM ASSIGNMENT:
If a team roster is provided in the structured context, assign each ticket to the most appropriate team member based on their role/specialty. Match ticket focus areas to member roles:
- Frontend tickets (components, pages, UI, CSS, state management) → frontend or fullstack members
- Backend tickets (APIs, services, database, auth, migrations) → backend or fullstack members
- Infrastructure/CI/CD tickets → devops or fullstack members
- Design tickets → design members
- Testing tickets → qa or the member whose domain the tests cover
- Fullstack members can take any ticket type
Distribute work roughly evenly across the team, weighted by each member's weekly_capacity_hours. If no team roster is provided, leave "assignee" as null.

Respond with JSON matching this schema:
{
  "tasks": [
    {
      "title": "Ticket title",
      "description": "What to implement, 1-3 sentences",
      "motivation": "Why this ticket matters now / what it unblocks",
      "deliverables": ["Concrete, named thing to build", "..."],
      "important_notes": ["Non-goal, gotcha, or constraint", "..."],
      "estimated_days": 2,
      "priority": "p0",
      "dependencies": ["Other ticket title"],
      "assignee": "Team member name or null"
    }
  ]
}
"""

DECOMPOSITION_MODEL = "gemini-3.1-flash-lite"


def _build_structured_context(ctx: ProjectContext | None) -> str:
    if not ctx:
        return ""
    parts = []
    if ctx.start_date:
        parts.append(f"Start date: {ctx.start_date}")
    if ctx.timeline:
        parts.append(f"Timeline: {ctx.timeline}")
    if ctx.team_size:
        parts.append(f"Team size: {ctx.team_size}")
    if ctx.budget:
        parts.append(f"Budget: {ctx.budget}")
    if ctx.team_members:
        parts.append("Team members:")
        for m in ctx.team_members:
            parts.append(f"  - {m.name} ({m.role}, {m.weekly_capacity_hours}h/week)")
    if not parts:
        return ""
    return "\n\nStructured context from PM:\n" + "\n".join(parts)


async def generate_questions(
    content: str, project_context: ProjectContext, gemini_key: str
) -> tuple[ClarifyingQuestionsResult, dict]:
    """Returns (result, usage) where usage carries real token counts."""
    client = _make_client(gemini_key, settings.gemini_light_timeout_ms)
    prompt = QUESTIONS_PROMPT + "\n\nPRD Content:\n" + content + _build_structured_context(project_context)

    async def call():
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        data = json.loads(response.text)
        return ClarifyingQuestionsResult(**data), _usage_from_response(response)

    return await _with_retry(call)


def _build_prd_context(content: str, project_context: ProjectContext, answers: dict[str, str] | None) -> str:
    ctx = f"\n\nPRD Content:\n{content}"
    ctx += _build_structured_context(project_context)
    if answers:
        ctx += "\n\nAdditional context from PM:\n"
        for question, answer in answers.items():
            ctx += f"Q: {question}\nA: {answer}\n"
    return ctx


async def _generate_skeleton(
    content: str,
    project_context: ProjectContext,
    answers: dict[str, str] | None,
    client: genai.Client,
) -> tuple[PlanSkeleton, dict]:
    prompt = SKELETON_PROMPT + _build_prd_context(content, project_context, answers)

    async def call():
        response = await client.aio.models.generate_content(
            model=DECOMPOSITION_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )
        return PlanSkeleton(**json.loads(response.text)), _usage_from_response(response)

    return await _with_retry(call)


async def _generate_epic_tasks(
    content: str,
    project_context: ProjectContext,
    answers: dict[str, str] | None,
    epic: EpicSkeleton,
    all_epics: list[EpicSkeleton],
    prior_context: list[dict],
    client: genai.Client,
) -> tuple[list, dict]:
    prompt = EPIC_TASKS_PROMPT
    prompt += _build_prd_context(content, project_context, answers)

    prompt += "\n\nFULL EPIC PLAN (for technology/architecture consistency):\n"
    for ep in all_epics:
        marker = " <<<< EXPANDING THIS ONE" if ep.title == epic.title else ""
        prompt += f"  - {ep.title}: {ep.scope}{marker}\n"

    prompt += f"\n\nEPIC TO EXPAND:\nTitle: {epic.title}\nScope: {epic.scope}\n"

    if prior_context:
        prompt += "\nPREVIOUSLY GENERATED TICKETS (you may depend on these):\n"
        for prev in prior_context:
            prompt += f"  Epic: {prev['epic']}\n"
            for title in prev["tasks"]:
                prompt += f"    - {title}\n"

    async def call():
        response = await client.aio.models.generate_content(
            model=DECOMPOSITION_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4,
                max_output_tokens=16384,
            ),
        )
        result = EpicTasksResult(**json.loads(response.text))
        return result.tasks, _usage_from_response(response)

    return await _with_retry(call)


async def decompose_prd(
    content: str,
    project_context: ProjectContext,
    answers: dict[str, str] | None,
    gemini_key: str,
    on_epic_done: Callable[[DecompositionResult, int], None] | None = None,
) -> tuple[DecompositionResult, dict]:
    """Decompose a PRD into epics + tasks.

    Returns (result, usage) where usage sums real token counts across the
    skeleton call and every per-epic call.

    `on_epic_done(partial_result, total_epics)` is invoked after each epic's
    tasks are generated so callers can persist partial progress — a failure on
    epic N then doesn't discard the (already paid-for) epics 1..N-1.
    """
    client = _make_client(gemini_key, settings.gemini_heavy_timeout_ms)

    skeleton, usage = await _generate_skeleton(content, project_context, answers, client)

    epics: list[DecompositionEpic] = []
    context: list[dict] = []

    for epic_skel in skeleton.epics:
        tasks, epic_usage = await _generate_epic_tasks(
            content, project_context, answers, epic_skel, skeleton.epics, context, client
        )
        usage = _sum_usage(usage, epic_usage)
        epics.append(DecompositionEpic(title=epic_skel.title, tasks=tasks))
        context.append({"epic": epic_skel.title, "tasks": [t.title for t in tasks]})
        if on_epic_done is not None:
            try:
                partial = DecompositionResult(summary=skeleton.summary, epics=list(epics))
                on_epic_done(partial, len(skeleton.epics))
            except Exception:
                logger.exception("on_epic_done callback failed; continuing decomposition")

    return DecompositionResult(summary=skeleton.summary, epics=epics), usage


async def generate_embedding(text: str, gemini_key: str) -> list[float]:
    return (await generate_embeddings([text], gemini_key))[0]


async def generate_embeddings(texts: list[str], gemini_key: str) -> list[list[float]]:
    """Embed a batch of texts in a single Gemini call."""
    client = _make_client(gemini_key, settings.gemini_light_timeout_ms)

    async def call():
        response = await client.aio.models.embed_content(
            model="gemini-embedding-2",
            contents=texts,
            config={"output_dimensionality": 768},
        )
        return [e.values for e in response.embeddings]

    return await _with_retry(call)
