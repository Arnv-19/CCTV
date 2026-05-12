from __future__ import annotations

from pathlib import Path

from app.services.whatsapp_service import get_whatsapp_settings, upload_media, _raise_for_response, _graph_url
import requests


def send_snapshot_image(
    snapshot_path: str,
    *,
    recipient_number: str | None = None,
    caption: str | None = None,
) -> dict:
    path = Path(snapshot_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

    settings = get_whatsapp_settings(recipient_number)
    media_id = upload_media(settings, path)
    payload = {
        "messaging_product": "whatsapp",
        "to": settings.recipient_number,
        "type": "image",
        "image": {"id": media_id},
    }
    if caption:
        payload["image"]["caption"] = caption

    response = requests.post(
        _graph_url(settings, "messages"),
        headers={
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    _raise_for_response(response, "image send")
    return {"file": str(path), "media_id": media_id, "response": response.json()}


def send_snapshot_best_effort(snapshot_path: str | None, caption: str) -> dict | None:
    if not snapshot_path:
        return None
    try:
        return send_snapshot_image(snapshot_path, caption=caption)
    except Exception as exc:
        print(f"[WhatsApp] Snapshot send failed: {exc}")
        return None

