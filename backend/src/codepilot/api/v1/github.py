"""GitHub webhook HTTP boundary."""

from fastapi import APIRouter, Request

from codepilot.core.errors import ApplicationError
from codepilot.github.contracts import WebhookProcessingResult
from codepilot.github.webhooks import GitHubWebhookService, InvalidWebhookSignatureError

router = APIRouter(prefix="/github", tags=["github"])


@router.post("/webhook", response_model=WebhookProcessingResult)
async def github_webhook(request: Request) -> WebhookProcessingResult:
    service = getattr(request.app.state, "github_webhook_service", None)
    if not isinstance(service, GitHubWebhookService):
        raise ApplicationError(
            "github_not_configured",
            "GitHub integration is not configured.",
            status_code=503,
        )
    try:
        return await service.handle(
            event_name=request.headers.get("X-GitHub-Event", ""),
            delivery_id=request.headers.get("X-GitHub-Delivery", ""),
            signature=request.headers.get("X-Hub-Signature-256", ""),
            body=await request.body(),
        )
    except InvalidWebhookSignatureError as error:
        raise ApplicationError(
            "invalid_github_signature",
            "GitHub webhook signature is invalid.",
            status_code=401,
        ) from error
