A simple communication flow would be:

1. Candidate logs into your main Node/React website and completes KYC.
2. Your backend creates/assigns a unique `userId` and stores the KYC status.
3. Candidate clicks **Give AI Interview**.
4. Your backend generates a short-lived signed interview token containing:

```json
{
  "userId": "user_123",
  "employerId": "employer_456",
  "interviewId": "interview_789",
  "expiresAt": 1234567890
}
```

5. Redirect the candidate to the AI interview platform:

```text
https://ai-interview-platform.com/start?token=SIGNED_TOKEN
```

6. The AI platform validates the token, loads the interview, records the camera/audio, asks questions, evaluates answers, and generates a score.
7. After completion, the AI platform sends the result to your main application through a secure backend webhook:

```http
POST https://your-main-app.com/api/interviews/webhook
```

Including:

```json
{
  "interviewId": "interview_789",
  "userId": "user_123",
  "score": 82,
  "recordingUrl": "https://storage.../recording.mp4",
  "evaluation": {},
  "completedAt": "2026-10-15T12:00:00Z"
}
```

8. Your main application stores the score and recording reference, then displays it in:

- Employer dashboard
- Candidate dashboard
- Admin/interview reports

Recommended communication:

```text
Node/React Website
        ↓ signed token
AI Interview Platform
        ↓ secure webhook/API
Node Backend
        ↓
Employer Dashboard + Candidate Dashboard
```

Use a shared `interviewId`, backend-to-backend API calls, signed tokens, HTTPS, and cloud storage such as S3 for recordings. The browser should never directly send sensitive evaluation data to the employer account.