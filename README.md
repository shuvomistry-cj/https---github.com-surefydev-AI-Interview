# AI Interview Platform

This application provides job-specific AI interviews for candidates. Administrators create a job, paste a job description or test brief, generate questions with Groq, edit the questions and expected-answer rubrics, and publish a candidate interview link.

## Run locally

```powershell
cd "C:\Users\user\Documents\AI Interview Module"
.\.venv\Scripts\Activate.ps1
python database\init_db.py
python -m flask --app app run --host 127.0.0.1 --port 1234
```

Open `http://127.0.0.1:1234/admin` for administration. The default local admin password is `admin123`; set `ADMIN_PASSWORD` before deployment.

## Main flow

1. Admin creates a Job ID and pastes a JD, test brief, or question requirements.
2. Groq generates a draft question bank.
3. Admin edits question text, type, options, and expected-answer rubric, then saves it.
4. The Node/React application launches `/api/interviews/launch` for the matching Job ID.
5. Candidate completes onboarding, selects a supported language, records the interview, and receives an evaluation score.
6. The completed result and recording URL are delivered to `INTERVIEW_RESULT_WEBHOOK_URL`.

## Required environment

Configure PostgreSQL, Sarvam voice settings, Groq settings, and the interview secrets in `.env`. `GROQ_MODEL` should use an active model such as `openai/gpt-oss-120b`.
