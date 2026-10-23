import os

import requests


class N8NIntegrationError(RuntimeError):
    pass


def video_editing_enabled():
    return os.getenv("N8N_VIDEO_EDITING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def submit_video_editing_job(payload):
    webhook_url = os.getenv("N8N_VIDEO_EDITING_WEBHOOK_URL", "").strip()
    secret = os.getenv("N8N_VIDEO_EDITING_SECRET", "").strip()
    if not webhook_url or not secret:
        raise N8NIntegrationError(
            "n8n video editing is enabled, but its webhook URL or secret is missing."
        )

    try:
        response = requests.post(
            webhook_url,
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
                "X-90-Surefy-Event-Id": payload["event_id"],
            },
            json=payload,
            timeout=float(os.getenv("N8N_WEBHOOK_TIMEOUT_SECONDS", "10")),
        )
    except requests.RequestException as exc:
        raise N8NIntegrationError(f"Could not reach the n8n video-editing webhook: {exc}") from exc

    if not response.ok:
        detail = (response.text or "No response body").strip()[-800:]
        raise N8NIntegrationError(
            f"n8n rejected the video-editing job with HTTP {response.status_code}: {detail}"
        )

    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}

    return {
        "external_job_id": str(
            data.get("job_id")
            or data.get("execution_id")
            or data.get("id")
            or ""
        ).strip()
        or None,
        "response": data,
    }
