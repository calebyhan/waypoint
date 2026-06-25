import json
import logging

from google import genai
from google.genai import types

from models.decomposition import (
    ClarifyingQuestionsResult,
    DecompositionResult,
)

logger = logging.getLogger(__name__)

QUESTIONS_PROMPT = """You are an AI project planning assistant. A project manager has provided a PRD (Product Requirements Document) or project description. Your job is to ask up to 3 clarifying questions that will help you produce a better task breakdown.

Focus on:
- Deadline / timeline constraints
- Team size and composition
- Tech stack or existing infrastructure

Only ask questions whose answers would meaningfully change the task decomposition. If the document is clear enough, return fewer questions or none.

Respond with JSON matching this schema:
{
  "questions": [
    {"question": "...", "why": "..."}
  ]
}

PRD Content:
"""

DECOMPOSITION_PROMPT = """You are an AI project planning assistant. Decompose the following PRD into epics and PR-sized tasks (1-2 days of work each).

Rules:
- Each epic groups related tasks under a feature area
- Each task should be completable in a single PR (1-2 days)
- Assign priorities: p0 (launch blocker), p1 (important), p2 (nice to have)
- List dependencies as titles of other tasks this one depends on
- Be specific and actionable — avoid vague tasks like "set up infrastructure"

Respond with JSON matching this schema:
{
  "epics": [
    {
      "title": "Epic Name",
      "tasks": [
        {
          "title": "Task title",
          "description": "What to implement",
          "estimated_days": 2,
          "priority": "p0",
          "dependencies": ["Other task title"]
        }
      ]
    }
  ]
}
"""


async def generate_questions(content: str, gemini_key: str) -> ClarifyingQuestionsResult:
    client = genai.Client(api_key=gemini_key)
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=QUESTIONS_PROMPT + content,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    data = json.loads(response.text)
    return ClarifyingQuestionsResult(**data)


async def decompose_prd(
    content: str,
    answers: dict[str, str] | None,
    gemini_key: str,
) -> DecompositionResult:
    prompt = DECOMPOSITION_PROMPT + f"\n\nPRD Content:\n{content}"
    if answers:
        prompt += "\n\nAdditional context from PM:\n"
        for question, answer in answers.items():
            prompt += f"Q: {question}\nA: {answer}\n"

    client = genai.Client(api_key=gemini_key)
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
        ),
    )
    data = json.loads(response.text)
    return DecompositionResult(**data)


async def generate_embedding(text: str, gemini_key: str) -> list[float]:
    client = genai.Client(api_key=gemini_key)
    response = await client.aio.models.embed_content(
        model="gemini-embedding-exp-03-07",
        contents=text,
    )
    return response.embeddings[0].values
