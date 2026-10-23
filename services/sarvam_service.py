import os
from pathlib import Path

import requests


class SarvamError(RuntimeError):
    def __init__(self, message, status_code=502, code="sarvam_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def speech_to_text(audio_file, language):
    _require_sarvam_config("SARVAM_STT_URL")
    url = os.getenv("SARVAM_STT_URL")
    model = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
    language_code = get_language_code(language)

    filename = getattr(audio_file, "filename", "") or "answer.wav"
    content_type = getattr(audio_file, "mimetype", "") or _guess_audio_type(filename)

    files = {
        "file": (
            Path(filename).name,
            audio_file.stream if hasattr(audio_file, "stream") else audio_file,
            content_type,
        )
    }
    data = {
        "model": model,
        "mode": "transcribe",
        "language_code": language_code,
    }

    try:
        response = requests.post(
            url,
            headers=_subscription_headers(),
            data=data,
            files=files,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise SarvamError(f"Could not connect to Sarvam STT: {exc}") from exc

    _raise_for_sarvam_error(response)
    payload = response.json()

    return {
        "transcript": payload.get("transcript", "").strip(),
        "language_code": payload.get("language_code"),
        "request_id": payload.get("request_id"),
    }


def text_to_speech(text, language, speaker=None):
    _require_sarvam_config("SARVAM_TTS_URL")
    url = os.getenv("SARVAM_TTS_URL")
    payload = {
        "text": text,
        "target_language_code": get_language_code(language),
        "model": os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
        "speaker": speaker or os.getenv("SARVAM_TTS_SPEAKER", "shubh"),
    }

    try:
        response = requests.post(
            url,
            headers={**_subscription_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise SarvamError(f"Could not connect to Sarvam TTS: {exc}") from exc

    _raise_for_sarvam_error(response)
    data = response.json()
    audios = data.get("audios") or []

    return {
        "audio_base64": "".join(audios),
        "audio_format": "wav",
        "request_id": data.get("request_id"),
    }


def generate_ai_question_voice(question, language):
    return text_to_speech(question, language)


def get_language_code(language):
    normalized = str(language or "en").strip().lower()
    configured = os.getenv(f"SARVAM_LANG_{normalized.upper()}", "").strip()
    if configured:
        return configured
    if normalized == "hi":
        return os.getenv("SARVAM_LANG_HI", "hi-IN")
    return os.getenv("SARVAM_LANG_EN", "en-IN")


def _require_sarvam_config(endpoint_var):
    missing = [
        name
        for name in ("SARVAM_API_KEY", endpoint_var)
        if not os.getenv(name)
    ]
    if missing:
        raise SarvamError(
            f"Missing Sarvam environment variables: {', '.join(missing)}",
            status_code=500,
            code="sarvam_config_missing",
        )


def _subscription_headers():
    return {"api-subscription-key": os.getenv("SARVAM_API_KEY", "")}


def _raise_for_sarvam_error(response):
    if response.ok:
        return

    message = response.text
    try:
        payload = response.json()
        error = payload.get("error") or payload
        if isinstance(error, dict):
            message = error.get("message") or str(error)
        else:
            message = str(error)
    except ValueError:
        pass

    code = "sarvam_error"
    if response.status_code == 402:
        code = "sarvam_no_credits"
    elif response.status_code == 403:
        code = "sarvam_invalid_key"
    elif response.status_code == 429:
        code = "sarvam_rate_limited"

    raise SarvamError(
        f"Sarvam API error {response.status_code}: {message}",
        status_code=response.status_code,
        code=code,
    )


def _guess_audio_type(filename):
    extension = Path(filename).suffix.lower()
    if extension == ".wav":
        return "audio/wav"
    if extension == ".mp3":
        return "audio/mpeg"
    if extension == ".ogg":
        return "audio/ogg"
    if extension == ".flac":
        return "audio/flac"
    if extension == ".aac":
        return "audio/aac"
    return "audio/wav"
