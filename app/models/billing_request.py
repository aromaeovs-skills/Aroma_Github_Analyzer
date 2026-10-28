from pydantic import BaseModel


class SubscriptionCancellationRequest(BaseModel):
    cancel_at_cycle_end: bool = True
