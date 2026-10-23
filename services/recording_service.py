import os
import shutil
import subprocess
from pathlib import Path
from werkzeug.utils import secure_filename


class RecordingConversionError(RuntimeError):
    pass


def save_uploaded_recording(uploaded_file, session_code, upload_dir):
    upload_dir = Path(upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    original_name = secure_filename(uploaded_file.filename or "interview.webm")
    extension = Path(original_name).suffix or ".webm"
    filename = f"{secure_filename(session_code).lower()}{extension}"
    destination = upload_dir / filename
    uploaded_file.save(destination)

    return str(destination.relative_to(Path.cwd()))


def convert_recording_to_mp4(source_path):
    source = Path(source_path).resolve()
    if not source.exists() or not source.is_file():
        raise RecordingConversionError("Uploaded recording could not be found for MP4 conversion.")

    configured_binary = os.getenv("FFMPEG_BINARY", "ffmpeg").strip() or "ffmpeg"
    ffmpeg_binary = shutil.which(configured_binary)
    if not ffmpeg_binary:
        raise RecordingConversionError(
            "MP4 conversion is unavailable because FFmpeg is not installed or FFMPEG_BINARY is invalid."
        )

    destination = source.with_suffix(".mp4")
    temporary_destination = destination.with_name(f"{destination.stem}.converting.mp4")
    temporary_destination.unlink(missing_ok=True)

    command = [
        ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-c:v",
        "libx264",
        "-preset",
        os.getenv("FFMPEG_PRESET", "veryfast"),
        "-crf",
        os.getenv("FFMPEG_CRF", "23"),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(temporary_destination),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "600")),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        temporary_destination.unlink(missing_ok=True)
        raise RecordingConversionError(f"MP4 conversion could not be completed: {exc}") from exc

    if result.returncode != 0 or not temporary_destination.exists() or temporary_destination.stat().st_size == 0:
        temporary_destination.unlink(missing_ok=True)
        detail = (result.stderr or "Unknown FFmpeg error").strip()[-800:]
        raise RecordingConversionError(f"MP4 conversion failed: {detail}")

    temporary_destination.replace(destination)
    if source != destination:
        source.unlink(missing_ok=True)
    return destination
