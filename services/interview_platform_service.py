import base64
import hashlib
import hmac
import json
import os
import time

import requests


class InterviewPlatformError(RuntimeError):
    pass


def create_interview_token(user_id, employer_id, interview_id, job_id, ttl_seconds=900):
    payload = {
        "userId": user_id,
        "employerId": employer_id,
        "interviewId": interview_id,
        "jobId": job_id,
        "expiresAt": int(time.time()) + ttl_seconds,
    }
    encoded = _encode(payload)
    return f"{encoded}.{_signature(encoded)}"


def verify_interview_token(token, expected_job_id=None):
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _signature(encoded)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if int(payload.get("expiresAt", 0)) < int(time.time()):
            return None
        if expected_job_id and payload.get("jobId") != expected_job_id:
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def generate_job_questions(job_name, job_description, language, count=8, question_types=None):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise InterviewPlatformError("GROQ_API_KEY is not configured.")
    question_types = question_types or ["description", "short_answer", "multiple_choice"]
    prompt = f"""
Create {count} unique interview questions for the job below.
Job title: {job_name}
Job description:
{job_description}
Language: {language}
Allowed types: {', '.join(question_types)}

Return only JSON in this shape:
{{"questions":[{{"question_type":"description|short_answer|multiple_choice","question_text":"...","expected_answer":"...","options":["..."]}}]}}
Rules: cover the job requirements, avoid duplicates, keep questions practical, and make expected_answer a concise rubric.
For multiple_choice return exactly four options and make expected_answer the correct option text.
""".strip()
    try:
        response = requests.post(
            os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You are an expert technical interviewer. Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=90,
        )
        response.raise_for_status()
        value = json.loads(response.json()["choices"][0]["message"]["content"])
        questions = value.get("questions")
    except requests.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise InterviewPlatformError(f"Question generation failed: {detail}") from exc
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        raise InterviewPlatformError(f"Question generation failed: {exc}") from exc
    if not isinstance(questions, list) or not questions:
        raise InterviewPlatformError("Groq returned no questions.")
    return [
        {
            "language": language,
            "question_type": item.get("question_type", "description"),
            "question_text": str(item.get("question_text", "")).strip(),
            "expected_answer": str(item.get("expected_answer", "")).strip(),
            "options": item.get("options") if isinstance(item.get("options"), list) else [],
        }
        for item in questions
        if str(item.get("question_text", "")).strip()
    ][:count]


def translate_job_questions(job_name, questions, source_language, target_language):
    """Translate a reviewed question bank while preserving types and scoring meaning."""
    if source_language == target_language:
        return [dict(item, language=target_language) for item in questions]
    # Smaller batches are more reliable for long question banks and keep the
    # translated JSON within the model response limit.
    if len(questions) > 4:
        translated = []
        for start in range(0, len(questions), 4):
            translated.extend(
                translate_job_questions(
                    job_name,
                    questions[start:start + 4],
                    source_language,
                    target_language,
                )
            )
        return translated
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise InterviewPlatformError("GROQ_API_KEY is not configured.")
    prompt = f"""
Translate this interview question bank from {source_language} to {target_language} for the job '{job_name}'.
Translate question_text, expected_answer, and every multiple-choice option naturally and completely.
Keep question_type and question order unchanged. Expected answers are evaluation rubrics, so preserve their meaning.
Return only JSON in this shape: {{"questions":[{{"question_type":"description|short_answer|multiple_choice","question_text":"...","expected_answer":"...","options":["..."]}}]}}
Source question bank:
{json.dumps(questions, ensure_ascii=False)}
""".strip()
    try:
        request_json = {
            "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a precise multilingual interview translator. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        }
        response = None
        for attempt in range(3):
            response = requests.post(
                os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=request_json,
                timeout=90,
            )
            if response.status_code != 429 or attempt == 2:
                break
            retry_after = response.headers.get("retry-after", "5")
            try:
                delay = max(1, min(30, int(float(retry_after))))
            except ValueError:
                delay = 5
            time.sleep(delay)
        response.raise_for_status()
        value = json.loads(response.json()["choices"][0]["message"]["content"])
        translated = value.get("questions")
    except requests.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise InterviewPlatformError(f"Question translation failed: {detail}") from exc
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        raise InterviewPlatformError(f"Question translation failed: {exc}") from exc
    if not isinstance(translated, list) or len(translated) != len(questions):
        raise InterviewPlatformError("AI returned an incomplete translated question bank.")
    return [
        {
            "language": target_language,
            "question_type": item.get("question_type", source.get("question_type", "description")),
            "question_text": str(item.get("question_text", "")).strip(),
            "expected_answer": str(item.get("expected_answer", "")).strip(),
            "options": item.get("options") if isinstance(item.get("options"), list) else [],
        }
        for source, item in zip(questions, translated)
    ]


def assist_question(job_name, source_text, language, question_type, draft_question="", draft_expected_answer=""):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise InterviewPlatformError("GROQ_API_KEY is not configured.")
    prompt = f"""
You are helping an administrator prepare one job interview question.
Job: {job_name}
Job description or test brief: {source_text}
Language: {language}
Question type: {question_type}
Draft question: {draft_question}
Draft expected answer/rubric: {draft_expected_answer}

Improve the draft if present, or create a suitable question if it is empty.
Return only JSON: {{"question_text":"...","expected_answer":"...","options":[]}}.
For multiple_choice, provide exactly four options and make expected_answer the correct option text.
The expected answer must be a fair evaluation rubric, accepting relevant paraphrases.
""".strip()
    try:
        response = requests.post(
            os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                "temperature": 0.45,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You are an expert interview designer. Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=90,
        )
        response.raise_for_status()
        value = json.loads(response.json()["choices"][0]["message"]["content"])
    except requests.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise InterviewPlatformError(f"Question assistance failed: {detail}") from exc
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        raise InterviewPlatformError(f"Question assistance failed: {exc}") from exc
    question_text = str(value.get("question_text") or "").strip()
    if not question_text:
        raise InterviewPlatformError("AI returned an empty question.")
    return {
        "question_text": question_text,
        "expected_answer": str(value.get("expected_answer") or "").strip(),
        "options": value.get("options") if isinstance(value.get("options"), list) else [],
    }


def adapt_interview_turn(job_name, language, current_question, candidate_answer):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return {"follow_up": False, "acknowledgement": "Thank you, that gives me useful context. Let us continue."}
    prompt = f"""
You are conducting a professional job interview for {job_name}.
Language: {language}
Question asked: {current_question}
Candidate answer: {candidate_answer}

Decide whether the answer needs one concise follow-up to clarify a missing detail.
Use a follow-up only when the answer is incomplete, vague, contradictory, or does not answer the question.
Do not ask a follow-up for a clear, relevant answer. Never praise blindly.
Return only JSON:
{{"follow_up":true,"follow_up_question":"...","acknowledgement":"..."}}
The acknowledgement must be one natural sentence in the selected language. If the answer is uncertain,
acknowledge that neutrally and do not pretend it was a good answer.
""".strip()
    try:
        response = requests.post(
            os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                "temperature": 0.25,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You are an adaptive interviewer. Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=45,
        )
        response.raise_for_status()
        value = json.loads(response.json()["choices"][0]["message"]["content"])
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return {"follow_up": False, "acknowledgement": "Thank you, that gives me useful context. Let us continue."}
    follow_up = bool(value.get("follow_up"))
    return {
        "follow_up": follow_up,
        "follow_up_question": str(value.get("follow_up_question") or "").strip() if follow_up else "",
        "acknowledgement": str(value.get("acknowledgement") or "").strip(),
    }


def evaluate_interview(job_name, questions, transcripts, language):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise InterviewPlatformError("GROQ_API_KEY is not configured.")
    expected_by_question = {
        str(item.get("question_text") or "").strip(): str(item.get("expected_answer") or "").strip()
        for item in questions
    }
    def clip(value, limit):
        return str(value or "").strip()[:limit]

    prompt = {
        "job_name": clip(job_name, 200),
        "language": language,
        "answers": [
            {
                "question": clip(item.get("question_text"), 500),
                "expected_answer": clip(item.get("expected_answer") or expected_by_question.get(
                    str(item.get("question_text") or "").strip(), ""
                ), 600),
                "candidate_answer": clip(item.get("answer_text"), 1200),
                "type": item.get("question_type", "description"),
            }
            for item in transcripts
        ],
    }
    request_body = {
        "task": "Score the candidate from 0 to 100. Understand paraphrases and relevant answers.",
        "output": {"score": 0, "tag": "Poor|Satisfactory|Good|Well Done", "summary": "", "question_scores": []},
        "interview": prompt,
    }
    try:
        response = requests.post(
            os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                "temperature": 0.1,
                "max_tokens": 1800,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "Evaluate relevance and correctness fairly. Return strict JSON only."},
                    {"role": "user", "content": json.dumps(request_body, separators=(",", ":"), ensure_ascii=False)},
                ],
            },
            timeout=90,
        )
        response.raise_for_status()
        result = json.loads(response.json()["choices"][0]["message"]["content"])
    except requests.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        raise InterviewPlatformError(f"Interview evaluation failed: {detail}") from exc
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        raise InterviewPlatformError(f"Interview evaluation failed: {exc}") from exc
    score = max(0, min(100, int(float(result.get("score", 0)))))
    tag = result.get("tag") if result.get("tag") in {"Poor", "Satisfactory", "Good", "Well Done"} else _tag_for_score(score)
    result["score"] = score
    result["tag"] = tag
    return result


def send_result_webhook(payload):
    endpoint = os.getenv("INTERVIEW_RESULT_WEBHOOK_URL", "").strip()
    if not endpoint:
        return "disabled"
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    secret = os.getenv("INTERVIEW_WEBHOOK_SECRET", "").strip()
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest() if secret else ""
    try:
        response = requests.post(
            endpoint,
            data=body.encode(),
            headers={"Content-Type": "application/json", "X-Interview-Signature": signature},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise InterviewPlatformError(f"Result webhook failed: {exc}") from exc
    return "delivered"


def _encode(payload):
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def _signature(encoded):
    secret = os.getenv("INTERVIEW_TOKEN_SECRET", os.getenv("FLASK_SECRET_KEY", "local-dev-secret")).encode()
    return hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()


def _tag_for_score(score):
    if score < 40:
        return "Poor"
    if score < 65:
        return "Satisfactory"
    if score < 85:
        return "Good"
    return "Well Done"
