from pydantic import BaseModel, Field


class GitHubAnalysisRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=1,
        max_length=39,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37})$",
        description="GitHub username to analyze.",
    )


class GitHubRepositoryAnalysisRequest(BaseModel):
    owner: str = Field(
        ...,
        min_length=1,
        max_length=39,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37})$",
    )
    repository: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
