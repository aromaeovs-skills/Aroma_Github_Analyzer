import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.database.billing_repository import BillingRepository, BillingStorageUnavailable
from app.models.billing_request import SubscriptionCancellationRequest
from app.services.auth import Member, get_current_member
from app.services.razorpay import (
    BillingConfigurationError,
    BillingProviderError,
    RazorpayService,
)

logger = logging.getLogger(__name__)
billing_router = APIRouter(prefix="/billing")
webhook_router = APIRouter()
billing_repository = BillingRepository()
razorpay_service = RazorpayService(billing_repository)
MAX_WEBHOOK_BODY_BYTES = 1_000_000


@billing_router.post("/subscription", status_code=status.HTTP_201_CREATED)
def create_subscription(member: Member = Depends(get_current_member)):
    try:
        data = razorpay_service.create_subscription(member.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except BillingConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BillingStorageUnavailable as exc:
        logger.error("Billing storage unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription storage is unavailable.",
        ) from exc
    except BillingProviderError as exc:
        logger.error("Razorpay subscription creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The payment provider could not create the subscription.",
        ) from exc
    return {"success": True, "data": data}


@billing_router.get("/subscription")
def get_subscription(member: Member = Depends(get_current_member)):
    try:
        subscription = billing_repository.get_latest_subscription(member.user_id)
    except BillingStorageUnavailable as exc:
        logger.error("Billing storage unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription status is unavailable.",
        ) from exc
    if subscription is None:
        return {"success": True, "data": None}
    return {"success": True, "data": subscription}


@billing_router.post("/subscription/cancel")
def cancel_subscription(
    request: SubscriptionCancellationRequest,
    member: Member = Depends(get_current_member),
):
    try:
        data = razorpay_service.cancel_subscription(
            member.user_id,
            request.cancel_at_cycle_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except BillingConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BillingStorageUnavailable as exc:
        logger.error("Billing storage unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription storage is unavailable.",
        ) from exc
    except BillingProviderError as exc:
        logger.error("Razorpay cancellation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The payment provider could not cancel the subscription.",
        ) from exc
    return {"success": True, "data": data}


@webhook_router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
    event_id: str | None = Header(default=None, alias="X-Razorpay-Event-Id"),
):
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Razorpay webhook signature.",
        )
    content_length = request.headers.get("content-length")
    if content_length:
        if not content_length.isdigit() or int(content_length) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Webhook payload is too large.",
            )
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Webhook payload is too large.",
        )
    try:
        processed = razorpay_service.process_webhook(body, signature, event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BillingConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay webhook verification is not configured.",
        ) from exc
    except BillingStorageUnavailable as exc:
        logger.error("Billing webhook could not be persisted: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription status could not be updated.",
        ) from exc
    return {"success": True, "processed": processed}
