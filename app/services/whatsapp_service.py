from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()


class WhatsAppConfigError(RuntimeError):
    pass


@dataclass
class WhatsAppSettings:
    access_token: str
    phone_number_id: str
    recipient_number: str
    api_version: str = "v25.0"


def get_whatsapp_settings(recipient_number: str | None = None) -> WhatsAppSettings:
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    default_recipient = os.getenv("WHATSAPP_TO_NUMBER", "").strip()
    api_version = os.getenv("WHATSAPP_API_VERSION", "v25.0").strip() or "v25.0"
    to_number = (recipient_number or default_recipient).strip()

    missing = [
        name for name, value in (
            ("WHATSAPP_ACCESS_TOKEN", access_token),
            ("WHATSAPP_PHONE_NUMBER_ID", phone_number_id),
            ("WHATSAPP_TO_NUMBER", to_number),
        ) if not value
    ]
    if missing:
        raise WhatsAppConfigError(
            "Missing WhatsApp configuration: " + ", ".join(missing)
        )

    return WhatsAppSettings(
        access_token=access_token,
        phone_number_id=phone_number_id,
        recipient_number=to_number,
        api_version=api_version,
    )


def _graph_url(settings: WhatsAppSettings, path: str) -> str:
    return f"https://graph.facebook.com/{settings.api_version}/{settings.phone_number_id}/{path.lstrip('/')}"


def upload_media(settings: WhatsAppSettings, file_path: str | Path) -> str:
    file_path = Path(file_path)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    with file_path.open("rb") as file_handle:
        response = requests.post(
            _graph_url(settings, "media"),
            headers={"Authorization": f"Bearer {settings.access_token}"},
            data={
                "messaging_product": "whatsapp",
                "type": mime_type,
            },
            files={
                "file": (file_path.name, file_handle, mime_type),
            },
            timeout=60,
        )
    _raise_for_response(response, "media upload")
    payload = response.json()
    media_id = payload.get("id")
    if not media_id:
        raise RuntimeError(f"WhatsApp media upload returned no media id: {payload}")
    return str(media_id)


def send_document_message(
    settings: WhatsAppSettings,
    *,
    media_id: str,
    filename: str,
    caption: str | None = None,
):
    payload = {
        "messaging_product": "whatsapp",
        "to": settings.recipient_number,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
        },
    }
    if caption:
        payload["document"]["caption"] = caption

    response = requests.post(
        _graph_url(settings, "messages"),
        headers={
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    _raise_for_response(response, "document send")
    return response.json()


def send_documents(
    file_paths: list[str | Path],
    *,
    recipient_number: str | None = None,
    caption_prefix: str | None = None,
    caption_text: str | None = None,
    filename_stem: str | None = None,
) -> list[dict]:
    settings = get_whatsapp_settings(recipient_number)
    responses = []
    for file_path in file_paths:
        path = Path(file_path)
        media_id = upload_media(settings, path)
        filename = f"{filename_stem}{path.suffix}" if filename_stem else path.name
        if caption_text is not None:
            caption = caption_text
        elif caption_prefix:
            caption = f"{caption_prefix}: {path.name}"
        else:
            caption = path.name
        responses.append(
            {
                "file": filename,
                "media_id": media_id,
                "response": send_document_message(
                    settings,
                    media_id=media_id,
                    filename=filename,
                    caption=caption,
                ),
            }
        )
    return responses


def _raise_for_response(response: requests.Response, action: str) -> None:
    if response.ok:
        return
    try:
        detail = response.json()
    except Exception:
        detail = response.text
    raise RuntimeError(f"WhatsApp {action} failed ({response.status_code}): {detail}")
