import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.database.github_repository import (
    AnalysisStorageUnavailable,
    GitHubRepository,
)
from app.models.github_request import (
    GitHubAnalysisRequest,
    GitHubRepositoryAnalysisRequest,
)
from app.services.auth import (
    Member,
    get_current_member,
    is_premium_member,
    require_premium_member,
)
from app.services.github.github_service import GitHubService
from app.services.usage import (
    MonthlyLimitExceeded,
    UsageRepository,
    UsageStorageUnavailable,
)

logger = logging.getLogger(__name__)
router = APIRouter()
github_service = GitHubService()
github_repository = GitHubRepository()
usage_repository = UsageRepository()


def _raise_analysis_error(exc: RuntimeError) -> None:
    message = str(exc)
    if "rate limit exceeded" in message.lower():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message,
        ) from exc
    if "No AI providers are configured" in message or "All configured AI providers failed" in message:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=message,
        ) from exc
    logger.exception("GitHub analysis provider failed")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="An upstream GitHub or AI provider failed while analyzing the request.",
    ) from exc


def _save_analysis(member: Member, analysis_type: str, target: dict, data: dict) -> str:
    document = {
        "user_id": member.user_id,
        "membership_plan": member.plan,
        "analysis_type": analysis_type,
        "target": target,
        **data,
    }
    return github_repository.save(document)


@router.post("/repository/analyze", status_code=status.HTTP_201_CREATED)
def analyze_repository(
    request: GitHubRepositoryAnalysisRequest,
    member: Member = Depends(get_current_member),
):
    usage = None
    if not is_premium_member(member):
        try:
            usage = usage_repository.consume_repository_analysis(member.user_id)
        except MonthlyLimitExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Monthly repository analysis limit reached.",
                    "used": exc.used,
                    "limit": exc.limit,
                    "period": exc.period,
                },
            ) from exc
        except UsageStorageUnavailable as exc:
            logger.error("Repository analysis quota storage is unavailable: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Usage storage is unavailable; repository analysis cannot safely proceed.",
            ) from exc

    try:
        analysis = github_service.analyze_repository(request.owner, request.repository)
        analysis_data = analysis.model_dump()
        analysis_id = _save_analysis(
            member,
            "repository",
            {"owner": request.owner, "repository": request.repository},
            analysis_data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AnalysisStorageUnavailable as exc:
        logger.error("Analysis result storage is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis result storage is unavailable.",
        ) from exc
    except RuntimeError as exc:
        _raise_analysis_error(exc)

    return {
        "success": True,
        "analysis_id": analysis_id,
        "usage": usage,
        "data": analysis_data,
    }


@router.post("/account/analyze", status_code=status.HTTP_201_CREATED)
@router.post("/analyze", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def analyze_github_account(
    request: GitHubAnalysisRequest,
    member: Member = Depends(require_premium_member),
):
    try:
        analysis = github_service.analyze(request.username)
        analysis_data = analysis.model_dump()
        analysis_id = _save_analysis(
            member,
            "account",
            {"username": request.username},
            analysis_data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AnalysisStorageUnavailable as exc:
        logger.error("Analysis result storage is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis result storage is unavailable.",
        ) from exc
    except RuntimeError as exc:
        _raise_analysis_error(exc)

    return {"success": True, "analysis_id": analysis_id, "data": analysis_data}


@router.get("/usage")
def get_usage(member: Member = Depends(get_current_member)):
    if is_premium_member(member):
        return {"success": True, "plan": member.plan, "used": None, "limit": None}
    try:
        usage = usage_repository.get_repository_usage(member.user_id)
    except UsageStorageUnavailable as exc:
        logger.error("Repository analysis quota storage is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage storage is unavailable.",
        ) from exc
    return {"success": True, "plan": member.plan, **usage}


@router.get("/latest")
@router.get("/latest/{student_id}", include_in_schema=False)
def get_latest_github_analysis(
    student_id: str | None = None,
    member: Member = Depends(get_current_member),
):
    if student_id is not None and student_id != member.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    try:
        analysis = github_repository.get_latest_by_user(member.user_id)
    except AnalysisStorageUnavailable as exc:
        logger.error("Analysis result storage is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis result storage is unavailable.",
        ) from exc
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No GitHub analysis found.",
        )
    return {"success": True, "data": analysis}


@router.get("/history")
@router.get("/history/{student_id}", include_in_schema=False)
def get_github_history(
    student_id: str | None = None,
    member: Member = Depends(get_current_member),
):
    if student_id is not None and student_id != member.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    try:
        history = github_repository.get_history_by_user(member.user_id)
    except AnalysisStorageUnavailable as exc:
        logger.error("Analysis result storage is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis result storage is unavailable.",
        ) from exc
    return {"success": True, "count": len(history), "data": history}


@router.get("/{analysis_id}")
def get_github_analysis_by_id(
    analysis_id: str,
    member: Member = Depends(get_current_member),
):
    try:
        analysis = github_repository.get_by_id_for_user(analysis_id, member.user_id)
    except AnalysisStorageUnavailable as exc:
        logger.error("Analysis result storage is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis result storage is unavailable.",
        ) from exc
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub analysis not found.",
        )
    return {"success": True, "data": analysis}
