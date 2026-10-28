from typing import List

from pydantic import BaseModel, Field


class RepositoryMetrics(BaseModel):
    total_files: int = 0
    source_files: int = 0
    sampled_lines: int = 0

    has_readme: bool = False
    has_tests: bool = False
    has_docker: bool = False
    has_ci: bool = False
    has_license: bool = False

    detected_frameworks: List[str] = Field(default_factory=list)
    dependency_files: List[str] = Field(default_factory=list)
    important_files: List[str] = Field(default_factory=list)


class RepositoryCodeAnalysis(BaseModel):
    repository_name: str
    code_quality_score: int = Field(..., ge=0, le=100)
    architecture_score: int = Field(..., ge=0, le=100)
    readability_score: int = Field(..., ge=0, le=100)
    maintainability_score: int = Field(..., ge=0, le=100)
    testing_score: int = Field(..., ge=0, le=100)
    documentation_score: int = Field(..., ge=0, le=100)
    complexity_score: int = Field(..., ge=0, le=100)

    developer_level: str
    project_difficulty: str
    summary: str
    strengths: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    detected_skills: List[str] = Field(default_factory=list)
    engineering_practices: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)

    metrics: RepositoryMetrics
