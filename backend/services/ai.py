import json
import logging

from google import genai
from google.genai import types

from models.decomposition import (
    ClarifyingQuestionsResult,
    DecompositionEpic,
    DecompositionResult,
    EpicSkeleton,
    EpicTasksResult,
    PlanSkeleton,
    ProjectContext,
)

logger = logging.getLogger(__name__)

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
      "dependencies": ["Other ticket title"]
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
    if not parts:
        return ""
    return "\n\nStructured context from PM:\n" + "\n".join(parts)


async def generate_questions(content: str, project_context: ProjectContext, gemini_key: str) -> ClarifyingQuestionsResult:
    client = genai.Client(api_key=gemini_key)
    prompt = QUESTIONS_PROMPT + "\n\nPRD Content:\n" + content + _build_structured_context(project_context)
    response = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    data = json.loads(response.text)
    return ClarifyingQuestionsResult(**data)


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
) -> PlanSkeleton:
    prompt = SKELETON_PROMPT + _build_prd_context(content, project_context, answers)
    response = await client.aio.models.generate_content(
        model=DECOMPOSITION_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
            max_output_tokens=4096,
        ),
    )
    return PlanSkeleton(**json.loads(response.text))


async def _generate_epic_tasks(
    content: str,
    project_context: ProjectContext,
    answers: dict[str, str] | None,
    epic: EpicSkeleton,
    all_epics: list[EpicSkeleton],
    prior_context: list[dict],
    client: genai.Client,
) -> list:
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
    return result.tasks


async def decompose_prd(
    content: str,
    project_context: ProjectContext,
    answers: dict[str, str] | None,
    gemini_key: str,
) -> DecompositionResult:
    client = genai.Client(api_key=gemini_key)

    skeleton = await _generate_skeleton(content, project_context, answers, client)

    epics: list[DecompositionEpic] = []
    context: list[dict] = []

    for epic_skel in skeleton.epics:
        tasks = await _generate_epic_tasks(content, project_context, answers, epic_skel, skeleton.epics, context, client)
        epics.append(DecompositionEpic(title=epic_skel.title, tasks=tasks))
        context.append({"epic": epic_skel.title, "tasks": [t.title for t in tasks]})

    return DecompositionResult(summary=skeleton.summary, epics=epics)


async def generate_embedding(text: str, gemini_key: str) -> list[float]:
    client = genai.Client(api_key=gemini_key)
    response = await client.aio.models.embed_content(
        model="gemini-embedding-2",
        contents=text,
    )
    return response.embeddings[0].values
