from pydantic import BaseModel, Field


class DecompositionTask(BaseModel):
    title: str
    description: str
    estimated_days: int = Field(ge=1, le=10)
    priority: str = Field(pattern=r"^p[012]$", default="p1")
    dependencies: list[str] = Field(default_factory=list)


class DecompositionEpic(BaseModel):
    title: str
    tasks: list[DecompositionTask]


class DecompositionResult(BaseModel):
    epics: list[DecompositionEpic]


class ClarifyingQuestion(BaseModel):
    question: str
    why: str


class ClarifyingQuestionsResult(BaseModel):
    questions: list[ClarifyingQuestion] = Field(max_length=3)
