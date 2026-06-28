from pydantic import BaseModel, Field


class DecompositionTask(BaseModel):
    title: str
    description: str
    motivation: str
    deliverables: list[str] = Field(default_factory=list)
    important_notes: list[str] = Field(default_factory=list)
    estimated_days: int = Field(ge=1, le=10)
    priority: str = Field(pattern=r"^p[012]$", default="p1")
    dependencies: list[str] = Field(default_factory=list)


class DecompositionEpic(BaseModel):
    title: str
    tasks: list[DecompositionTask]


class DecompositionResult(BaseModel):
    summary: str
    epics: list[DecompositionEpic]


class EpicSkeleton(BaseModel):
    title: str
    scope: str


class PlanSkeleton(BaseModel):
    summary: str
    epics: list[EpicSkeleton]


class EpicTasksResult(BaseModel):
    tasks: list[DecompositionTask]


class ClarifyingQuestion(BaseModel):
    question: str
    why: str


class ClarifyingQuestionsResult(BaseModel):
    questions: list[ClarifyingQuestion] = Field(max_length=3)
