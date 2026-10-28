from typing import List

from pydantic import BaseModel, Field


class GitHubRepositoryInsight(BaseModel):
    name: str
    description: str | None = None
    language: str | None = None
    stars: int = 0
    forks: int = 0
    has_readme: bool | None = None


class GitHubAnalysisResponse(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    repository_score: int = Field(..., ge=0, le=100)
    documentation_score: int = Field(..., ge=0, le=100)
    activity_score: int = Field(..., ge=0, le=100)
    diversity_score: int = Field(..., ge=0, le=100)

    summary: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    detected_skills: List[str] = Field(default_factory=list)
    top_projects: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    repositories: List[GitHubRepositoryInsight] = Field(default_factory=list)
    repository_reviews: List[dict] = Field(default_factory=list)
