import os
import hmac
import hashlib
import json
import random
import re
import shutil
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, send_file, session as flask_session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import load_env

load_env()

from database.models import (
    create_interview_job,
    create_job_session,
    create_video_edit_job,
    end_session,
    get_latest_recording_for_session,
    get_recording_by_id,
    get_recordings_for_session,
    get_session_by_code,
    get_transcripts_for_session,
    get_latest_video_edit_job_for_session,
    get_interview_job,
    update_interview_job_result_visibility,
    get_interview_questions,
    get_latest_candidate_attempt,
    get_attempt_files,
    get_job_interview_stats,
    list_interview_jobs,
    get_video_edit_job_by_event_id,
    init_db,
    mark_session_saved,
    save_recording,
    save_transcript,
    save_interview_evaluation,
    save_interview_evaluation_error,
    replace_interview_questions,
    delete_interview_questions,
    delete_candidate_attempt,
    start_session,
    update_video_edit_job,
    update_session_webhook_status,
)
from services.interview_service import get_closing
from services.interview_service import get_questions
from services.interview_service import get_greeting
from services.recording_service import (
    RecordingConversionError,
    convert_recording_to_mp4,
    save_uploaded_recording,
)
from services.sarvam_service import SarvamError, speech_to_text, text_to_speech
from services.interview_platform_service import (
    InterviewPlatformError,
    create_interview_token,
    evaluate_interview,
    generate_job_questions,
    translate_job_questions,
    assist_question,
    adapt_interview_turn,
    send_result_webhook,
    verify_interview_token,
)
from services.n8n_service import (
    N8NIntegrationError,
    submit_video_editing_job,
    video_editing_enabled,
)


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads" / "recordings"
CHUNK_TEMP_DIR = BASE_DIR / "uploads" / "recording_chunks"
EDITED_UPLOAD_DIR = BASE_DIR / "uploads" / "edited_recordings"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CHUNK_TEMP_DIR.mkdir(parents=True, exist_ok=True)
EDITED_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "local-dev-secret")
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "1024")) * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

init_db()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not flask_session.get("admin_authenticated"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        expected = os.getenv("ADMIN_PASSWORD", "admin123")
        if hmac.compare_digest(password, expected):
            flask_session["admin_authenticated"] = True
            return redirect(request.args.get("next") or url_for("admin_dashboard"))
        return render_template("admin_login.html", error="Invalid admin password."), 401
    return render_template("admin_login.html")


@app.post("/admin/logout")
def admin_logout():
    flask_session.pop("admin_authenticated", None)
    return redirect(url_for("admin_login"))


@app.get("/admin")
@admin_required
def admin_dashboard():
    jobs = []
    for job in list_interview_jobs():
        item = dict(job)
        item["languages"] = _json_list(job.get("languages_json"))
        display_language = item["languages"][0] if item["languages"] else "en"
        item["questions"] = get_interview_questions(job["job_id"], display_language)
        item["stats"] = get_job_interview_stats(job["job_id"])["summary"]
        jobs.append(item)
    return render_template("admin.html", jobs=jobs, default_password=os.getenv("ADMIN_PASSWORD", "admin123"))


@app.get("/admin/jobs/<job_id>/candidates")
@admin_required
def admin_job_candidates(job_id):
    job = get_interview_job(job_id)
    if not job:
        return render_template("not_found.html", session_code=job_id), 404
    results = get_job_interview_stats(job_id)
    candidates = []
    for candidate in results["candidates"]:
        item = dict(candidate)
        item["evaluation"] = json.loads(item.get("evaluation_json") or "null")
        item["recording_url"] = url_for("recording_by_id", recording_id=item["recording_id"]) if item.get("recording_id") else None
        candidates.append(item)
    return render_template("admin_job_candidates.html", job=job, summary=results["summary"], candidates=candidates)


@app.post("/api/admin/jobs/<job_id>/result-visibility")
@admin_required
def api_admin_result_visibility(job_id):
    if not get_interview_job(job_id):
        return jsonify({"error": "Job not found."}), 404
    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get("show_results_to_candidate"))
    job = update_interview_job_result_visibility(job_id, enabled)
    return jsonify({
        "show_results_to_candidate": bool(job.get("show_results_to_candidate")),
    })


@app.post("/api/admin/sessions/<session_code>/evaluate")
@admin_required
def api_admin_evaluate_session(session_code):
    session = get_session_by_code(session_code)
    if not session or not session.get("job_id"):
        return jsonify({"error": "Interview session not found."}), 404
    recording = get_latest_recording_for_session(session["id"])
    transcripts = get_transcripts_for_session(session["id"])
    if not recording:
        return jsonify({"error": "This candidate has no uploaded recording."}), 400
    if not transcripts:
        return jsonify({"error": "This candidate has no saved answers to evaluate."}), 400
    job = get_interview_job(session["job_id"])
    questions = get_interview_questions(session["job_id"], session.get("language") or "en")
    if not questions:
        return jsonify({"error": "No question bank exists for the candidate's interview language."}), 400
    try:
        evaluation = evaluate_interview(
            job["job_name"], questions, transcripts, session.get("language") or "en"
        )
        saved = save_interview_evaluation(
            session_code,
            evaluation["score"],
            evaluation["tag"],
            evaluation,
            "pending",
        )
        webhook_status = "pending"
        webhook_error = ""
        try:
            webhook_status = send_result_webhook(
                _build_interview_result_payload(saved, job, recording, evaluation, transcripts)
            )
        except Exception as exc:
            webhook_status = "failed"
            webhook_error = str(exc)
        saved = update_session_webhook_status(session_code, webhook_status)
        return jsonify({
            "evaluation": evaluation,
            "webhook_status": webhook_status,
            "webhook_error": webhook_error,
            "session": saved,
        })
    except InterviewPlatformError as exc:
        save_interview_evaluation_error(session_code, str(exc))
        return jsonify({"error": str(exc), "evaluation_status": "failed"}), 502


@app.post("/api/admin/jobs")
@admin_required
def api_admin_create_job():
    payload = request.get_json(silent=True) or {}
    job_id = re.sub(r"[^A-Za-z0-9_-]", "-", str(payload.get("job_id") or "").strip()).strip("-")
    job_name = str(payload.get("job_name") or "").strip()
    description = str(payload.get("job_description") or "").strip()
    employer_id = str(payload.get("employer_id") or "").strip()
    try:
        duration = max(60, min(7200, int(payload.get("duration_seconds") or 900)))
    except (TypeError, ValueError):
        return jsonify({"error": "Duration must be a number of seconds."}), 400
    languages = _normalise_languages(payload.get("languages", ["en"]))
    attempt_mode = str(payload.get("attempt_mode") or "single").strip().lower()
    show_results_to_candidate = bool(payload.get("show_results_to_candidate"))
    if attempt_mode not in {"single", "multi"}:
        return jsonify({"error": "attempt_mode must be single or multi."}), 400
    if not job_id or not job_name:
        return jsonify({"error": "job_id and job_name are required."}), 400
    if get_interview_job(job_id):
        return jsonify({"error": "That Job ID already exists."}), 409
    job = create_interview_job(
        job_id, job_name, description, employer_id, duration, languages or ["en"],
        attempt_mode, show_results_to_candidate,
    )
    questions = payload.get("questions") or []
    if questions:
        replace_interview_questions(job_id, _normalise_questions(questions, languages[0] if languages else "en"))
    return jsonify({"job": job, "questions": get_interview_questions(job_id)}), 201


@app.post("/api/admin/jobs/<job_id>/generate-questions")
@admin_required
def api_admin_generate_questions(job_id):
    job = get_interview_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    payload = request.get_json(silent=True) or {}
    language = str(payload.get("language") or "en").strip()
    languages = _normalise_languages(_json_list(job.get("languages_json")) or payload.get("languages") or [language])
    try:
        count = max(1, min(30, int(payload.get("count") or 8)))
        questions = generate_job_questions(
            job["job_name"],
            str(payload.get("job_description") or job["job_description"]),
            language,
            count=count,
            question_types=payload.get("question_types"),
        )
        translated_banks = {language: _normalise_questions(questions, language)}
        for target_language in languages:
            if target_language == language:
                continue
            translated_banks[target_language] = _normalise_questions(
                translate_job_questions(job["job_name"], questions, language, target_language),
                target_language,
            )
    except (TypeError, ValueError, InterviewPlatformError) as exc:
        return jsonify({"error": str(exc)}), 502
    for bank_language, bank in translated_banks.items():
        replace_interview_questions(job_id, bank, bank_language)
    return jsonify({"questions": questions, "translated_languages": list(translated_banks)})


@app.put("/api/admin/jobs/<job_id>/questions")
@admin_required
def api_admin_save_questions(job_id):
    job = get_interview_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    payload = request.get_json(silent=True) or {}
    source_language = str(payload.get("language") or "en").strip()
    languages = _normalise_languages(_json_list(job.get("languages_json")) or payload.get("languages") or [source_language])
    questions = _normalise_questions(payload.get("questions") or [], source_language)
    if not questions:
        return jsonify({"error": "At least one valid question is required."}), 400
    translated_banks = {source_language: questions}
    try:
        for target_language in languages:
            if target_language == source_language:
                continue
            translated_banks[target_language] = _normalise_questions(
                translate_job_questions(job["job_name"], questions, source_language, target_language),
                target_language,
            )
    except InterviewPlatformError as exc:
        return jsonify({"error": str(exc)}), 502
    for language, bank in translated_banks.items():
        replace_interview_questions(job_id, bank, language)
    return jsonify({"questions": questions, "translated_languages": list(translated_banks)})


@app.get("/api/admin/jobs/<job_id>/questions")
@admin_required
def api_admin_get_questions(job_id):
    if not get_interview_job(job_id):
        return jsonify({"error": "Job not found."}), 404
    return jsonify({"questions": get_interview_questions(job_id, request.args.get("language", "en"))})


@app.delete("/api/admin/jobs/<job_id>/questions")
@admin_required
def api_admin_delete_questions(job_id):
    if not get_interview_job(job_id):
        return jsonify({"error": "Job not found."}), 404
    language = request.args.get("language", "").strip() or None
    deleted = delete_interview_questions(job_id, language)
    return jsonify({"deleted": deleted, "language": language})


@app.post("/api/admin/questions/assist")
@admin_required
def api_admin_assist_question():
    payload = request.get_json(silent=True) or {}
    question_type = str(payload.get("question_type") or "description")
    if question_type not in {"description", "short_answer", "multiple_choice"}:
        return jsonify({"error": "Invalid question type."}), 400
    try:
        result = assist_question(
            str(payload.get("job_name") or "Interview role"),
            str(payload.get("source_text") or ""),
            str(payload.get("language") or "en"),
            question_type,
            str(payload.get("draft_question") or ""),
            str(payload.get("draft_expected_answer") or ""),
        )
    except InterviewPlatformError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@app.get("/interview/<job_id>/onboarding")
def interview_onboarding(job_id):
    job = get_interview_job(job_id)
    if not job or job.get("status") != "active":
        return render_template("not_found.html", session_code=job_id), 404
    token = request.args.get("token", "").strip()
    token_data = verify_interview_token(token, job_id) if token else {}
    if token and not token_data:
        return render_template("not_found.html", session_code="Invalid or expired interview link"), 401
    configured_languages = _normalise_languages(_json_list(job.get("languages_json")))
    available_languages = [
        language for language in configured_languages
        if get_interview_questions(job_id, language)
    ]
    return render_template(
        "interview_onboarding.html",
        job=job,
        token=token,
        token_data=token_data,
        local_user_id=request.args.get("user_id", "").strip(),
        candidate_name=request.args.get("name", "").strip(),
        candidate_email=request.args.get("email", "").strip().lower(),
        selected_language=request.args.get("language", "").strip(),
        languages=available_languages or configured_languages,
        error=None if available_languages else "The administrator has not generated questions for this job yet.",
    )


@app.post("/interview/lookup")
def candidate_lookup():
    job_id = str(request.form.get("job_id") or "").strip()
    job = get_interview_job(job_id)
    if not job or job.get("status") != "active":
        return render_template("index.html", error="Job ID not found or no longer active."), 404
    return redirect(url_for("interview_onboarding", job_id=job_id, user_id=request.form.get("user_id", "").strip()))


@app.post("/api/interviews/launch")
def api_launch_interview():
    launch_secret = os.getenv("INTERVIEW_LAUNCH_SECRET", "").strip()
    supplied_secret = request.headers.get("X-Interview-Launch-Key", "")
    if not launch_secret or not hmac.compare_digest(supplied_secret, launch_secret):
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    job_id = str(payload.get("job_id") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()
    employer_id = str(payload.get("employer_id") or "").strip()
    interview_id = str(payload.get("interview_id") or uuid.uuid4().hex).strip()
    job = get_interview_job(job_id)
    if not job or not user_id:
        return jsonify({"error": "job_id and user_id are required, and the job must exist."}), 400
    token = create_interview_token(user_id, employer_id, interview_id, job_id, int(job["duration_seconds"]))
    return jsonify({
        "job_id": job_id,
        "interview_id": interview_id,
        "launch_url": f"{_base_url()}{url_for('interview_onboarding', job_id=job_id)}?token={token}",
        "expires_in_seconds": int(job["duration_seconds"]),
    })


@app.post("/interview/<job_id>/onboarding")
def begin_job_interview(job_id):
    job = get_interview_job(job_id)
    if not job:
        return render_template("not_found.html", session_code=job_id), 404
    token = request.form.get("token", "").strip()
    token_data = verify_interview_token(token, job_id) if token else None
    if token and not token_data:
        return render_template("not_found.html", session_code="Invalid or expired interview link"), 401
    language = request.form.get("language", "en").strip()
    supplied_user_id = request.form.get("user_id", "").strip()
    full_name = request.form.get("full_name", "").strip()
    email_address = request.form.get("email_address", "").strip().lower()
    languages = _normalise_languages(_json_list(job.get("languages_json")))
    available_languages = [
        value for value in languages
        if get_interview_questions(job_id, value)
    ]
    if language not in available_languages:
        return render_template(
            "interview_onboarding.html",
            job=job,
            token=token,
            token_data=token_data or {},
            local_user_id=request.form.get("user_id", "").strip(),
            candidate_name=full_name,
            candidate_email=email_address,
            selected_language=language,
            languages=available_languages or languages,
            error="Questions are not available in the selected language yet. Please ask the administrator to regenerate this job's question bank.",
        ), 409
    if (token_data or {}).get("userId"):
        user_id = token_data["userId"]
    elif supplied_user_id:
        user_id = supplied_user_id
    else:
        # Local/manual launches need a stable identity so different candidates do not
        # all become the same blank/default candidate. Production launches should use
        # the userId from the signed Node/React token.
        if not email_address:
            return render_template(
                "interview_onboarding.html",
                job=job,
                token=token,
                token_data=token_data or {},
                local_user_id=supplied_user_id,
                candidate_name=full_name,
                candidate_email=email_address,
                selected_language=language,
                languages=available_languages or languages,
                error="Enter your email address or use a candidate-specific interview link before starting.",
            ), 400
        identity_source = email_address
        user_id = "local-" + hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:24]
    employer_id = (token_data or {}).get("employerId") or job.get("employer_id")
    interview_id = (token_data or {}).get("interviewId") or f"{job_id}-{uuid.uuid4().hex[:12]}"
    previous_attempt = get_latest_candidate_attempt(job_id, user_id)
    if previous_attempt and job.get("attempt_mode", "single") == "single":
        return render_template(
            "interview_onboarding.html",
            job=job,
            token=token,
            token_data=token_data or {},
            local_user_id=user_id,
            candidate_name=full_name,
            candidate_email=email_address,
            selected_language=language,
            languages=languages,
            error="You have already completed or started this interview. Please contact the administrator if you need it reopened.",
        ), 409
    if previous_attempt:
        _remove_candidate_attempt(job_id, user_id)
    token = token or create_interview_token(user_id, employer_id, interview_id, job_id, int(job["duration_seconds"]))
    interview = create_job_session(
        job_id, _base_url(), user_id, employer_id, token, interview_id, language,
        full_name, email_address,
    )
    return redirect(url_for("session_room", session_code=interview["session_code"]))


@app.post("/api/admin/jobs/<job_id>/candidates/<applicant_user_id>/reopen")
@admin_required
def api_admin_reopen_candidate(job_id, applicant_user_id):
    if not get_interview_job(job_id):
        return jsonify({"error": "Job not found."}), 404
    removed = _remove_candidate_attempt(job_id, applicant_user_id)
    if not removed:
        return jsonify({"error": "No existing attempt found for this candidate."}), 404
    return jsonify({"reopened": True, "deleted_session_code": removed["session_code"]})


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/session/<session_code>/my-sessions")
def my_sessions(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return render_template("not_found.html", session_code=session_code), 404

    recordings = get_recordings_for_session(session["id"])
    return render_template(
        "my_sessions.html",
        session=session,
        recordings=recordings,
    )


@app.post("/sessions")
def new_session():
    return render_template("index.html", error="Legacy session creation has been removed. Enter a Job ID to start an interview."), 410


@app.post("/join")
def join_session():
    raw_value = request.form.get("session_link", "").strip()
    session_code = _extract_session_code(raw_value)

    if not session_code:
        return render_template("index.html", error="Please enter a session link or code."), 400

    session = get_session_by_code(session_code)
    if not session:
        return render_template("index.html", error="Session not found. Check the code and try again."), 404

    return redirect(url_for("session_room", session_code=session_code))


@app.get("/session/<session_code>")
def session_room(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return render_template("not_found.html", session_code=session_code), 404

    session = dict(session)
    if not session.get("job_id"):
        return render_template("not_found.html", session_code="This legacy session is no longer part of the AI interview platform."), 410
    session["session_link"] = f"{_base_url()}/session/{session_code}"
    transcripts = get_transcripts_for_session(session["id"])
    recording = get_latest_recording_for_session(session["id"])
    recording_url = None
    if recording:
        recording_url = url_for("recording_file", session_code=session_code)
    editing_job = get_latest_video_edit_job_for_session(session["id"])
    job = get_interview_job(session.get("job_id"))

    job_questions = get_interview_questions(session.get("job_id"), session.get("language") or "en") if session.get("job_id") else []
    if job_questions:
        job_questions = random.sample(job_questions, len(job_questions))
    if not job_questions:
        return render_template(
            "not_found.html",
            session_code="This interview does not have a question bank for the selected language.",
        ), 409
    question_texts = [item["question_text"] for item in job_questions]
    return render_template(
        "session.html",
        session=session,
        questions=question_texts,
        question_meta=job_questions,
        job=job,
        greeting=get_greeting(session["language"]),
        closing=get_closing(session["language"]),
        transcripts=transcripts,
        recording=recording,
        recording_url=recording_url,
        sarvam_config={
            "en": os.getenv("SARVAM_LANG_EN", "en-IN"),
            "hi": os.getenv("SARVAM_LANG_HI", "hi-IN"),
        },
        prepared_script=json.loads(session.get("prepared_script") or "[]"),
        evaluation=(json.loads(session.get("evaluation_json") or "null") if job and job.get("show_results_to_candidate") else None),
        editing_job=_public_video_edit_job(editing_job),
    )


@app.post("/api/sessions/<session_code>/start")
def api_start_session(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    payload = request.get_json(silent=True) or {}
    language = payload.get("language") or session["language"]
    updated = start_session(session_code, language)
    configured_questions = get_interview_questions(updated.get("job_id"), language) if updated.get("job_id") else []
    if configured_questions:
        configured_questions = random.sample(configured_questions, len(configured_questions))
    if not configured_questions:
        return jsonify({
            "error": "This interview does not have a question bank for the selected language. Please contact the administrator."
        }), 409
    question_texts = [item["question_text"] for item in configured_questions]
    return jsonify({
        "session": updated,
        "questions": question_texts,
        "question_meta": configured_questions,
        "duration_seconds": updated.get("duration_seconds") or 900,
        "greeting": get_greeting(language),
        "closing": get_closing(language),
    })


@app.post("/api/sessions/<session_code>/transcripts")
def api_save_transcript(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    payload = request.get_json(silent=True) or {}
    required = ["question_number", "question_text", "answer_text"]
    if any(payload.get(field) in (None, "") for field in required):
        return jsonify({"error": "Missing transcript fields"}), 400

    transcript = save_transcript(
        session_id=session["id"],
        question_number=int(payload["question_number"]),
        question_text=str(payload["question_text"]),
        answer_text=str(payload["answer_text"]),
    )
    return jsonify({"transcript": transcript})


@app.post("/api/sessions/<session_code>/acknowledgement")
def api_candidate_acknowledgement(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    payload = request.get_json(silent=True) or {}
    answer = str(payload.get("answer") or "").strip()
    language = str(payload.get("language") or session.get("language") or "en").lower()
    return jsonify(_candidate_acknowledgement(answer, language))


@app.post("/api/sessions/<session_code>/adaptive-turn")
def api_adaptive_turn(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    payload = request.get_json(silent=True) or {}
    current_question = str(payload.get("question") or "").strip()
    answer = str(payload.get("answer") or "").strip()
    if not current_question or not answer:
        return jsonify({"follow_up": False, **_candidate_acknowledgement(answer, session.get("language") or "en")})
    job = get_interview_job(session.get("job_id")) if session.get("job_id") else None
    result = adapt_interview_turn(
        job.get("job_name") if job else "Interview",
        session.get("language") or "en",
        current_question,
        answer,
    )
    return jsonify(result)


@app.post("/api/sessions/<session_code>/tts")
def api_sarvam_tts(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    language = payload.get("language") or session["language"]
    voice_role = payload.get("voice_role", "ravi")
    if not text:
        return jsonify({"error": "Text is required"}), 400

    try:
        ravi_speaker = os.getenv(
            "SARVAM_TTS_RAVI_SPEAKER",
            os.getenv("SARVAM_TTS_SPEAKER", "shubh"),
        )
        if voice_role == "founder":
            speaker = (
                os.getenv("SARVAM_TTS_FEMALE_SPEAKER", "priya")
                if session.get("gender") == "female"
                else os.getenv("SARVAM_TTS_MALE_SPEAKER", "ratan")
            )
            if speaker == ravi_speaker:
                speaker = "ishita" if session.get("gender") == "female" else "ratan"
                if speaker == ravi_speaker:
                    speaker = "aditya"
        else:
            speaker = ravi_speaker
        audio = text_to_speech(text, language, speaker=speaker)
    except SarvamError as exc:
        return jsonify({"error": str(exc), "error_code": exc.code}), exc.status_code

    return jsonify(audio)


@app.post("/api/sessions/<session_code>/stt")
def api_sarvam_stt(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    audio = request.files.get("audio")
    if not audio:
        return jsonify({"error": "No answer audio uploaded"}), 400

    language = request.form.get("language") or session["language"]

    try:
        result = speech_to_text(audio, language)
    except SarvamError as exc:
        return jsonify({"error": str(exc), "error_code": exc.code}), exc.status_code

    return jsonify(result)


@app.post("/api/sessions/<session_code>/recording")
def api_upload_recording(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    recording = request.files.get("recording")
    if not recording:
        return jsonify({"error": "No recording file uploaded"}), 400

    duration = float(request.form.get("duration") or 0)
    recorded_at = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    recording_id = f"{session['id']}_{session_code}_{recorded_at}"
    uploaded_path = BASE_DIR / save_uploaded_recording(recording, recording_id, UPLOAD_DIR)
    try:
        converted_path = convert_recording_to_mp4(uploaded_path)
    except RecordingConversionError as exc:
        uploaded_path.unlink(missing_ok=True)
        return jsonify({"error": str(exc), "error_code": "mp4_conversion_failed"}), 500
    file_path = str(converted_path.relative_to(BASE_DIR))
    saved = save_recording(session["id"], file_path, duration)
    return jsonify({"recording": saved})


@app.post("/api/sessions/<session_code>/recording-chunk")
def api_upload_recording_chunk(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    chunk = request.files.get("chunk")
    if not chunk:
        return jsonify({"error": "No recording chunk uploaded"}), 400

    try:
        upload_id = _safe_upload_id(request.form.get("upload_id", ""))
        chunk_index = int(request.form.get("chunk_index", ""))
        total_chunks = int(request.form.get("total_chunks", ""))
        duration = float(request.form.get("duration") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid recording chunk metadata"}), 400

    if not upload_id or chunk_index < 0 or total_chunks < 1 or chunk_index >= total_chunks:
        return jsonify({"error": "Invalid recording chunk metadata"}), 400

    chunk_dir = _recording_chunk_dir(session["id"], upload_id)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk.save(chunk_dir / f"{chunk_index:06d}.part")

    if chunk_index != total_chunks - 1:
        return jsonify({
            "complete": False,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
        })

    missing = [
        index
        for index in range(total_chunks)
        if not (chunk_dir / f"{index:06d}.part").exists()
    ]
    if missing:
        return jsonify({"error": "Recording upload is missing chunks", "missing": missing}), 400

    recorded_at = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    recording_id = f"{session['id']}_{session_code}_{recorded_at}"
    destination = UPLOAD_DIR / f"{recording_id.lower()}.webm"
    with destination.open("wb") as output:
        for index in range(total_chunks):
            with (chunk_dir / f"{index:06d}.part").open("rb") as source:
                shutil.copyfileobj(source, output)

    try:
        converted_path = convert_recording_to_mp4(destination)
    except RecordingConversionError as exc:
        destination.unlink(missing_ok=True)
        shutil.rmtree(chunk_dir, ignore_errors=True)
        return jsonify({"error": str(exc), "error_code": "mp4_conversion_failed"}), 500

    shutil.rmtree(chunk_dir, ignore_errors=True)
    file_path = str(converted_path.relative_to(BASE_DIR))
    saved = save_recording(session["id"], file_path, duration)
    return jsonify({"complete": True, "recording": saved})


@app.post("/api/sessions/<session_code>/save")
def api_save_session(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    recording = get_latest_recording_for_session(session["id"])
    if not recording:
        return jsonify({"error": "Recording must be uploaded before saving the session"}), 400

    saved = mark_session_saved(session_code)
    evaluation = None
    show_results_to_candidate = False
    webhook_status = "pending"
    if saved.get("job_id"):
        job = get_interview_job(saved["job_id"])
        show_results_to_candidate = bool(job and job.get("show_results_to_candidate"))
        questions = get_interview_questions(saved["job_id"], saved.get("language") or "en")
        transcripts = get_transcripts_for_session(saved["id"])
        try:
            evaluation = evaluate_interview(job["job_name"], questions, transcripts, saved.get("language") or "en")
            saved = save_interview_evaluation(
                session_code,
                evaluation["score"],
                evaluation["tag"],
                evaluation,
                "pending",
            )
            webhook_payload = _build_interview_result_payload(saved, job, recording, evaluation, transcripts)
            try:
                webhook_status = send_result_webhook(webhook_payload)
            except InterviewPlatformError as exc:
                app.logger.warning("Interview webhook failed for %s: %s", session_code, exc)
                webhook_status = "failed"
            saved = update_session_webhook_status(session_code, webhook_status)
        except InterviewPlatformError as exc:
            app.logger.warning("Interview evaluation failed for %s: %s", session_code, exc)
            save_interview_evaluation_error(session_code, str(exc))
            webhook_status = "evaluation_failed"
    try:
        editing_job = _queue_video_editing_job(saved, recording)
    except Exception as exc:
        app.logger.exception("Video-editing submission failed after session %s was saved", session_code)
        editing_job = {
            "status": "failed",
            "error_message": f"The session was saved, but video editing could not be queued: {exc}",
        }
    return jsonify({
        "session": saved,
        "recording_url": url_for("recording_file", session_code=session_code) if saved.get("recording_path") else None,
        "my_sessions_url": url_for("my_sessions", session_code=session_code),
        "video_editing": _public_video_edit_job(editing_job),
        "evaluation": evaluation if show_results_to_candidate else None,
        "webhook_status": webhook_status,
    })


@app.get("/api/sessions/<session_code>/video-editing")
def api_video_editing_status(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    job = get_latest_video_edit_job_for_session(session["id"])
    if not job:
        status = "disabled" if not video_editing_enabled() else "not_submitted"
        return jsonify({"video_editing": {"status": status}})
    return jsonify({"video_editing": _public_video_edit_job(job)})


@app.post("/api/sessions/<session_code>/video-editing/retry")
def api_retry_video_editing(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    if not video_editing_enabled():
        return jsonify({"error": "Automated video editing is not enabled."}), 503

    recording = get_latest_recording_for_session(session["id"])
    if not recording:
        return jsonify({"error": "No saved recording is available for editing."}), 400
    latest_job = get_latest_video_edit_job_for_session(session["id"])
    if latest_job and latest_job["status"] in {"pending", "submitted", "processing"}:
        return jsonify({"video_editing": _public_video_edit_job(latest_job)})
    if latest_job and latest_job["status"] == "completed":
        return jsonify({"video_editing": _public_video_edit_job(latest_job)})

    try:
        job = _queue_video_editing_job(
            session,
            recording,
            attempt_count=(latest_job.get("attempt_count", 0) + 1) if latest_job else 1,
        )
    except Exception as exc:
        app.logger.exception("Video-editing retry failed for session %s", session_code)
        return jsonify({"error": str(exc)}), 502
    return jsonify({"video_editing": _public_video_edit_job(job)})


@app.get("/api/integrations/n8n/recordings/<int:recording_id>")
def n8n_recording_download(recording_id):
    if not _n8n_request_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    recording = get_recording_by_id(recording_id)
    if not recording:
        return jsonify({"error": "Recording not found"}), 404
    recording_path = (BASE_DIR / recording["file_path"]).resolve()
    if UPLOAD_DIR.resolve() not in recording_path.parents or not recording_path.exists():
        return jsonify({"error": "Recording file not found"}), 404
    if recording_path.suffix.lower() != ".mp4":
        return jsonify({"error": "Only MP4 recordings can be sent for editing"}), 409
    return send_file(
        recording_path,
        mimetype="video/mp4",
        as_attachment=True,
        download_name=f"{recording['session_code']}.mp4",
    )


@app.post("/api/integrations/n8n/video-editing/callback")
def n8n_video_editing_callback():
    if not _n8n_request_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    event_id = str(payload.get("event_id") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    if not event_id or status not in {"processing", "completed", "failed"}:
        return jsonify({"error": "event_id and a valid status are required"}), 400
    job = get_video_edit_job_by_event_id(event_id)
    if not job:
        return jsonify({"error": "Video-editing job not found"}), 404

    edited_video_url = str(payload.get("edited_video_url") or "").strip() or None
    thumbnail_url = str(payload.get("thumbnail_url") or "").strip() or None
    if edited_video_url and not _valid_http_url(edited_video_url):
        return jsonify({"error": "edited_video_url must use http or https"}), 400
    if thumbnail_url and not _valid_http_url(thumbnail_url):
        return jsonify({"error": "thumbnail_url must use http or https"}), 400
    if status == "completed" and not edited_video_url and not job.get("edited_file_path"):
        return jsonify({"error": "A completed job requires edited_video_url or an uploaded edited file"}), 400

    updated = update_video_edit_job(
        event_id,
        status=status,
        external_job_id=str(payload.get("external_job_id") or job.get("external_job_id") or "").strip() or None,
        edited_video_url=edited_video_url or job.get("edited_video_url"),
        edited_duration=_optional_float(payload.get("edited_duration_seconds")),
        thumbnail_url=thumbnail_url or job.get("thumbnail_url"),
        error_message=str(payload.get("error") or "").strip() or None,
        completed_at=_utc_now() if status in {"completed", "failed"} else None,
    )
    return jsonify({"video_editing": _public_video_edit_job(updated)})


@app.post("/api/integrations/n8n/video-editing/upload")
def n8n_video_editing_upload():
    if not _n8n_request_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    event_id = str(request.form.get("event_id") or "").strip()
    video = request.files.get("video")
    job = get_video_edit_job_by_event_id(event_id) if event_id else None
    if not job:
        return jsonify({"error": "Video-editing job not found"}), 404
    if not video:
        return jsonify({"error": "An edited MP4 file is required in the video field"}), 400

    destination = (EDITED_UPLOAD_DIR / f"{event_id}.mp4").resolve()
    if destination.parent != EDITED_UPLOAD_DIR.resolve():
        return jsonify({"error": "Invalid event ID"}), 400
    temporary = destination.with_name(f"{destination.stem}.uploading.mp4")
    video.save(temporary)
    try:
        with temporary.open("rb") as uploaded:
            header = uploaded.read(12)
        if len(header) < 8 or header[4:8] != b"ftyp":
            return jsonify({"error": "The uploaded file is not a valid MP4 container"}), 400
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)

    edited_url = f"{_base_url()}{url_for('edited_recording_file', event_id=event_id)}"
    updated = update_video_edit_job(
        event_id,
        status="completed",
        edited_file_path=str(destination.relative_to(BASE_DIR)),
        edited_video_url=edited_url,
        edited_duration=_optional_float(request.form.get("edited_duration_seconds")),
        error_message=None,
        completed_at=_utc_now(),
    )
    return jsonify({"video_editing": _public_video_edit_job(updated)}), 201


@app.get("/edited-recordings/<event_id>")
def edited_recording_file(event_id):
    job = get_video_edit_job_by_event_id(event_id)
    if not job or not job.get("edited_file_path"):
        return jsonify({"error": "Edited recording not found"}), 404
    edited_path = (BASE_DIR / job["edited_file_path"]).resolve()
    if EDITED_UPLOAD_DIR.resolve() not in edited_path.parents or not edited_path.exists():
        return jsonify({"error": "Edited recording file missing"}), 404
    return send_file(
        edited_path,
        mimetype="video/mp4",
        as_attachment=request.args.get("download") == "1",
        download_name=f"edited-{event_id}.mp4",
    )


def _queue_video_editing_job(session, recording, attempt_count=1):
    if not video_editing_enabled():
        return {
            "status": "disabled",
            "error_message": None,
        }

    existing_job = get_latest_video_edit_job_for_session(session["id"])
    if (
        existing_job
        and existing_job.get("recording_id") == recording["id"]
        and existing_job.get("status") in {"pending", "submitted", "processing", "completed"}
    ):
        return existing_job

    event_id = str(uuid.uuid4())
    job = create_video_edit_job(
        session_id=session["id"],
        recording_id=recording["id"],
        event_id=event_id,
        attempt_count=attempt_count,
    )
    payload = _build_video_editing_payload(session, recording, job)
    try:
        result = submit_video_editing_job(payload)
        return update_video_edit_job(
            event_id,
            status="submitted",
            external_job_id=result.get("external_job_id"),
            submitted_at=_utc_now(),
            error_message=None,
        )
    except N8NIntegrationError as exc:
        app.logger.warning("n8n video-editing submission failed for %s: %s", event_id, exc)
        return update_video_edit_job(
            event_id,
            status="failed",
            error_message=str(exc),
            completed_at=_utc_now(),
        )


def _build_video_editing_payload(session, recording, job):
    transcripts = get_transcripts_for_session(session["id"])
    raw_answers = _json_list(session.get("preparation_answers"))
    prepared_script = _json_list(session.get("prepared_script"))
    base_url = _base_url()
    return {
        "schema_version": "1.0",
        "event_type": "session.saved",
        "event_id": job["event_id"],
        "created_at": _utc_now(),
        "session": {
            "id": session["id"],
            "code": session["session_code"],
            "language": session.get("language") or "en",
            "recorded_duration_seconds": recording.get("duration") or 0,
            "target_duration_seconds": 90,
            "attempt_number": job.get("attempt_count") or 1,
        },
        "founder": {
            "name": session.get("founder_name") or "",
            "company_name": session.get("startup_name") or "",
            "designation": session.get("designation") or "",
            "gender": session.get("gender") or "",
            "email": session.get("email_address") or "",
            "contact_number": session.get("contact_number") or "",
        },
        "interview": {
            "questions": get_questions("en"),
            "founder_preparation_answers": raw_answers,
            "prepared_script": prepared_script,
            "actual_transcript": [
                {
                    "question_number": item["question_number"],
                    "question": item["question_text"],
                    "answer": item["answer_text"],
                }
                for item in transcripts
            ],
        },
        "assets": {
            "raw_video": {
                "url": f"{base_url}{url_for('n8n_recording_download', recording_id=recording['id'])}",
                "filename": f"{session['session_code']}.mp4",
                "mime_type": "video/mp4",
                "authentication": "Use the same Authorization Bearer secret as the webhook",
            }
        },
        "callbacks": {
            "status_url": f"{base_url}{url_for('n8n_video_editing_callback')}",
            "edited_video_upload_url": f"{base_url}{url_for('n8n_video_editing_upload')}",
            "authentication": "Use the same Authorization Bearer secret as the webhook",
        },
    }


def _public_video_edit_job(job):
    if not job:
        return None
    return {
        "event_id": job.get("event_id"),
        "external_job_id": job.get("external_job_id"),
        "status": job.get("status") or "not_submitted",
        "attempt_count": job.get("attempt_count"),
        "submitted_at": job.get("submitted_at"),
        "completed_at": job.get("completed_at"),
        "edited_video_url": job.get("edited_video_url"),
        "edited_duration_seconds": job.get("edited_duration"),
        "thumbnail_url": job.get("thumbnail_url"),
        "error_message": job.get("error_message"),
    }


def _n8n_request_authorized():
    secret = os.getenv("N8N_VIDEO_EDITING_SECRET", "").strip()
    provided = request.headers.get("Authorization", "")
    return bool(secret) and hmac.compare_digest(provided, f"Bearer {secret}")


def _normalise_questions(items, language="en"):
    valid_types = {"multiple_choice", "short_answer", "description"}
    normalised = []
    for item in items:
        if isinstance(item, str):
            item = {"question_text": item}
        if not isinstance(item, dict):
            continue
        text = str(item.get("question_text") or item.get("question") or "").strip()
        if not text:
            continue
        question_type = str(item.get("question_type") or "description").strip()
        if question_type not in valid_types:
            question_type = "description"
        options = item.get("options") if isinstance(item.get("options"), list) else []
        normalised.append({
            "language": str(item.get("language") or language).strip(),
            "question_type": question_type,
            "question_text": text,
            "expected_answer": str(item.get("expected_answer") or "").strip(),
            "options": [str(option).strip() for option in options if str(option).strip()][:6],
        })
    return normalised


def _normalise_languages(items):
    languages = []
    for value in items:
        language = str(value or "").strip().lower()
        if language and language not in languages:
            languages.append(language)
    return languages or ["en"]


def _remove_candidate_attempt(job_id, applicant_user_id):
    attempt = get_latest_candidate_attempt(job_id, applicant_user_id)
    if not attempt:
        return None
    files = get_attempt_files(attempt["id"])
    deleted = delete_candidate_attempt(job_id, applicant_user_id)
    for relative_path in files:
        path = (BASE_DIR / relative_path).resolve()
        if UPLOAD_DIR.resolve() in path.parents or EDITED_UPLOAD_DIR.resolve() in path.parents:
            path.unlink(missing_ok=True)
    return deleted


def _candidate_acknowledgement(answer, language):
    # Keep Unicode letters so Hindi, Telugu, and other supported languages are
    # counted as real answers instead of becoming an empty string.
    lowered = re.sub(r"[^\w\s']", "", answer.lower(), flags=re.UNICODE).strip()
    uncertain_phrases = (
        "i dont know", "i don't know", "i do not know", "not sure", "no idea", "cant answer", "can't answer",
        "unable to answer", "skip", "pass", "nothing to say", "i have no idea",
    )
    is_uncertain = not lowered or len(lowered.split()) <= 2 or any(phrase in lowered for phrase in uncertain_phrases)
    if is_uncertain:
        messages = {
            "hi": "Koi baat nahi. Chaliye agle sawaal par chalte hain.",
            "te": "Parvaledu. Taruvata prashnaku veldam.",
            "en": "That is okay. Let us move to the next question.",
        }
        return {"category": "uncertain", "text": messages.get(language, messages["en"])}
    messages = {
        "hi": "Dhanyavaad, isse mujhe aapka perspective samajhne mein madad mili.",
        "te": "Dhanyavadalu, mee samadhanam valla mee perspective ardham ayyindi.",
        "en": "Thank you, that gives me useful context. Let us continue.",
    }
    return {"category": "answered", "text": messages.get(language, messages["en"])}


def _build_interview_result_payload(session, job, recording, evaluation, transcripts):
    return {
        "schema_version": "1.0",
        "event_type": "interview.completed",
        "created_at": _utc_now(),
        "interviewId": session.get("interview_id") or session.get("session_code"),
        "jobId": session.get("job_id"),
        "userId": session.get("applicant_user_id"),
        "employerId": session.get("employer_id") or job.get("employer_id"),
        "score": evaluation.get("score"),
        "tag": evaluation.get("tag"),
        "evaluation": evaluation,
        "recordingUrl": f"{_base_url()}{url_for('recording_file', session_code=session['session_code'])}",
        "transcript": [
            {"questionNumber": item["question_number"], "question": item["question_text"], "answer": item["answer_text"]}
            for item in transcripts
        ],
    }


def _json_list(raw_value):
    if not raw_value:
        return []
    try:
        value = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _valid_http_url(value):
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _optional_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@app.post("/api/sessions/<session_code>/end")
def api_end_session(session_code):
    session = get_session_by_code(session_code)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    ended = end_session(session_code)
    return jsonify({"session": ended})


@app.get("/recordings/<session_code>")
def recording_file(session_code):
    session = get_session_by_code(session_code)
    if not session or not session.get("recording_path"):
        return jsonify({"error": "Recording not found"}), 404

    recording_path = (BASE_DIR / session["recording_path"]).resolve()
    recordings_root = UPLOAD_DIR.resolve()
    if recordings_root not in recording_path.parents:
        return jsonify({"error": "Invalid recording path"}), 400
    if not recording_path.exists():
        return jsonify({"error": "Recording file missing"}), 404

    return send_file(recording_path, mimetype=_recording_mimetype(recording_path), as_attachment=False)


@app.get("/recordings/<int:recording_id>/view")
def recording_by_id(recording_id):
    return _send_recording_by_id(recording_id, as_attachment=False)


@app.get("/recordings/<int:recording_id>/download")
def download_recording_by_id(recording_id):
    return _send_recording_by_id(recording_id, as_attachment=True)


def _extract_session_code(value):
    if not value:
        return ""

    parsed = urlparse(value)
    if parsed.path:
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return parts[-1]

    return value.strip().split("/")[-1]


def _base_url():
    configured = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    current = request.host_url.rstrip("/")
    if configured and "127.0.0.1" not in configured and "localhost" not in configured:
        return configured
    return current


def _safe_upload_id(value):
    safe_value = "".join(
        character
        for character in value.strip()
        if character.isalnum() or character in {"-", "_"}
    )
    return safe_value[:80]


def _recording_chunk_dir(session_id, upload_id):
    chunk_dir = (CHUNK_TEMP_DIR / f"{session_id}_{upload_id}").resolve()
    chunks_root = CHUNK_TEMP_DIR.resolve()
    if chunk_dir.parent != chunks_root:
        raise ValueError("Invalid recording chunk path")
    return chunk_dir


def _send_recording_by_id(recording_id, as_attachment=False):
    recording = get_recording_by_id(recording_id)
    if not recording:
        return jsonify({"error": "Recording not found"}), 404

    recording_path = (BASE_DIR / recording["file_path"]).resolve()
    recordings_root = UPLOAD_DIR.resolve()
    if recordings_root not in recording_path.parents:
        return jsonify({"error": "Invalid recording path"}), 400
    if not recording_path.exists():
        return jsonify({"error": "Recording file missing"}), 404

    extension = recording_path.suffix.lower() or ".mp4"
    filename = f"{recording['session_code']}_{recording['id']}{extension}"
    return send_file(
        recording_path,
        mimetype=_recording_mimetype(recording_path),
        as_attachment=as_attachment,
        download_name=filename,
    )


def _recording_mimetype(recording_path):
    return "video/mp4" if Path(recording_path).suffix.lower() == ".mp4" else "video/webm"


@app.context_processor
def inject_now():
    return {"current_year": datetime.now().year}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
