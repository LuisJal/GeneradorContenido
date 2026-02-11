"""FastAPI webhook handler for Telegram callback queries."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.integrations.telegram_client import TelegramApprovalClient
from app.models.content import ContentItem, ContentStatus
from app.utils.logging_config import get_logger

logger = get_logger("webhooks")

router = APIRouter(prefix="")


def _get_telegram_client() -> TelegramApprovalClient:
    """Build a :class:`TelegramApprovalClient` from application settings."""
    return TelegramApprovalClient(settings.telegram_bot_token)


# ------------------------------------------------------------------
# Telegram webhook
# ------------------------------------------------------------------


@router.post("/webhooks/telegram")
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Receive Telegram updates (callback queries from approval keyboard).

    Expected callback_data formats:
        - ``approve:<content_id>``
        - ``reject:<content_id>``
        - ``edit:<content_id>``
    """
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        logger.warning("Received invalid JSON payload on Telegram webhook")
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

    callback_query = payload.get("callback_query")
    if callback_query is None:
        # Not a callback_query update -- acknowledge and ignore.
        logger.debug("Telegram update without callback_query, ignoring")
        return JSONResponse({"ok": True})

    data: Optional[str] = callback_query.get("data")
    if not data or ":" not in data:
        logger.warning("callback_query with unexpected data: %s", data)
        return JSONResponse({"ok": True})

    action, _, raw_id = data.partition(":")
    try:
        content_id = int(raw_id)
    except (ValueError, TypeError):
        logger.warning("Invalid content_id in callback_data: %s", data)
        return JSONResponse({"ok": True})

    # Resolve caller information
    from_user = callback_query.get("from", {})
    username = from_user.get("username") or from_user.get("first_name", "unknown")

    # Resolve the chat where the message lives
    message = callback_query.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    message_id: Optional[int] = message.get("message_id")

    if not chat_id:
        logger.warning("Could not determine chat_id from callback_query")
        return JSONResponse({"ok": True})

    # Fetch the content item ------------------------------------------------
    content_item: Optional[ContentItem] = db.execute(
        select(ContentItem).where(ContentItem.id == content_id)
    ).scalar_one_or_none()

    if content_item is None:
        logger.warning("ContentItem %d not found for callback", content_id)
        return JSONResponse({"ok": True})

    client = _get_telegram_client()

    # ------------------------------------------------------------------
    # Handle actions
    # ------------------------------------------------------------------

    if action == "approve":
        content_item.status = ContentStatus.APPROVED.value
        content_item.approval_status = "approved"
        content_item.approved_at = datetime.utcnow()
        content_item.approved_by = username
        db.commit()

        # Remove inline keyboard
        if message_id:
            try:
                await client.update_message(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"Aprobado por @{username}",
                )
            except Exception:
                logger.exception("Failed to update message after approval")

        await client.send_notification(
            chat_id=chat_id,
            text=f"Contenido #{content_id} aprobado por @{username}.",
        )
        logger.info("Content %d approved by %s", content_id, username)

    elif action == "reject":
        content_item.status = ContentStatus.REJECTED.value
        content_item.approval_status = "rejected"
        db.commit()

        # Remove inline keyboard
        if message_id:
            try:
                await client.update_message(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"Rechazado por @{username}",
                )
            except Exception:
                logger.exception("Failed to update message after rejection")

        await client.send_notification(
            chat_id=chat_id,
            text=f"Contenido #{content_id} rechazado por @{username}.",
        )
        logger.info("Content %d rejected by %s", content_id, username)

    elif action == "edit":
        await client.send_notification(
            chat_id=chat_id,
            text=(
                f"Modo edicion para contenido #{content_id}.\n\n"
                "Usa los siguientes comandos para editar las descripciones:\n"
                "  /edit_ig <nueva descripcion> - Instagram\n"
                "  /edit_yt <nueva descripcion> - YouTube\n"
                "  /edit_tt <nueva descripcion> - TikTok\n\n"
                "Cuando termines, envia /done para aprobar con los cambios."
            ),
        )
        logger.info("Content %d entering edit mode, requested by %s", content_id, username)
        # TODO: Implement stateful edit-message handling (track which
        # content_id is being edited per chat, handle /edit_* and /done
        # commands in a follow-up update handler).

    else:
        logger.warning("Unknown action '%s' in callback_data", action)

    return JSONResponse({"ok": True})
