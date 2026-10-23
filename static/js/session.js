const localVideo = document.getElementById("localVideo");
const questionOverlay = document.getElementById("questionOverlay");
const questionOverlayLabel = document.getElementById("questionOverlayLabel");
const questionOverlayText = document.getElementById("questionOverlayText");
const permissionOverlay = document.getElementById("permissionOverlay");
const permissionText = document.getElementById("permissionText");
const permissionBtn = document.getElementById("permissionBtn");
const micBtn = document.getElementById("micBtn");
const cameraBtn = document.getElementById("cameraBtn");
const startBtn = document.getElementById("startBtn");
const endBtn = document.getElementById("endBtn");
const languageSelect = document.getElementById("languageSelect");
const timerEl = document.getElementById("timer");
const statusPill = document.getElementById("statusPill");
const chatLog = document.getElementById("chatLog");
const answerBox = document.getElementById("answerBox");
const questionOptions = document.getElementById("questionOptions");
const manualAnswer = document.getElementById("manualAnswer");
const submitAnswerBtn = document.getElementById("submitAnswerBtn");
const recordAnswerBtn = document.getElementById("recordAnswerBtn");
const transcribeAnswerBtn = document.getElementById("transcribeAnswerBtn");
const copyLinkBtn = document.getElementById("copyLinkBtn");
const shareLink = document.getElementById("shareLink");
const copyCodeBtn = document.getElementById("copyCodeBtn");
const sessionCodeInput = document.getElementById("sessionCodeInput");
const recordingBanner = document.getElementById("recordingBanner");
const recordingTitle = document.getElementById("recordingTitle");
const recordingText = document.getElementById("recordingText");
const postSessionBox = document.getElementById("postSessionBox");
const postSessionText = document.getElementById("postSessionText");
const saveSessionBtn = document.getElementById("saveSessionBtn");
const startAgainBtn = document.getElementById("startAgainBtn");
const previewActions = document.getElementById("previewActions");
const previewRecordingBtn = document.getElementById("previewRecordingBtn");
const downloadRecordingBtn = document.getElementById("downloadRecordingBtn");
const shareRecordingBtn = document.getElementById("shareRecordingBtn");
const videoEditingBox = document.getElementById("videoEditingBox");
const evaluationBox = document.getElementById("evaluationBox");
const evaluationScore = document.getElementById("evaluationScore");
const evaluationTag = document.getElementById("evaluationTag");
const evaluationSummary = document.getElementById("evaluationSummary");
const videoEditingStatus = document.getElementById("videoEditingStatus");
const videoEditingMessage = document.getElementById("videoEditingMessage");
const retryVideoEditingBtn = document.getElementById("retryVideoEditingBtn");
const editedVideoActions = document.getElementById("editedVideoActions");
const previewEditedVideoBtn = document.getElementById("previewEditedVideoBtn");
const downloadEditedVideoBtn = document.getElementById("downloadEditedVideoBtn");
const shareEditedVideoBtn = document.getElementById("shareEditedVideoBtn");
const faceWarning = document.getElementById("faceWarning");
const faceGuide = document.getElementById("faceGuide");

let mediaStream = null;
let sessionRecorder = null;
let sessionChunks = [];
let finalSessionBlob = null;
let recordingStartedAt = null;
let questions = window.INTERVIEW_QUESTIONS || [];
let questionMeta = window.INTERVIEW_QUESTION_META || [];
let greeting = window.INTERVIEW_GREETING || "";
let closing = window.INTERVIEW_CLOSING || "";
let currentQuestionIndex = -1;
let currentQuestion = "";
let sessionActive = false;
let sessionFinished = false;
let timerInterval = null;
let elapsedSeconds = 0;
let questionAudio = null;
let answerRecorder = null;
let answerRecording = null;
let pendingTranscripts = [];
let pendingFinishMessage = "";
let permissionMessageShown = false;
let permissionRetrying = false;
let voiceMonitor = null;
let recordingAudioContext = null;
let recordingDestination = null;
let recordingMicSource = null;
let recordingStream = null;
let faceMonitor = null;
let faceMonitorStopped = false;
let faceChecking = false;
let faceWarningShownAt = 0;
let lastFaceBox = null;
let lastFaceBoxAt = 0;
let stableFaceFrames = 0;
let videoEditingPoll = null;
let currentQuestionMeta = null;

const ANSWER_PAUSE_TO_TRANSCRIBE_MS = 1700;
const ANSWER_MAX_RECORDING_MS = 24000;
const ANSWER_MIN_AUDIO_SECONDS = 0.8;
const RECORDING_CHUNK_SIZE = 4 * 1024 * 1024;

permissionBtn.addEventListener("click", handlePermissionButton);
micBtn.addEventListener("click", toggleMic);
cameraBtn.addEventListener("click", toggleCamera);
startBtn.addEventListener("click", startSession);
endBtn.addEventListener("click", () => finishSession("Session ended. Nothing has been saved yet."));
submitAnswerBtn.addEventListener("click", submitAnswer);
recordAnswerBtn.addEventListener("click", startAnswerRecording);
transcribeAnswerBtn.addEventListener("click", stopAndTranscribeAnswer);
copyLinkBtn.addEventListener("click", copySessionLink);
copyCodeBtn.addEventListener("click", copySessionCode);
saveSessionBtn.addEventListener("click", saveSession);
retryVideoEditingBtn.addEventListener("click", retryVideoEditing);
startAgainBtn.addEventListener("click", () => {
  fetch(`/api/sessions/${window.SESSION_CODE}/end`, { method: "POST" }).finally(() => {
    window.location.href = "/";
  });
});

setAnswerControls(false, false);
setRecordingBanner(false);

if (window.SESSION_STATUS === "saved" || window.RECORDING_URL) {
  setupSavedSessionView();
} else {
  addMessage("ai", "Voice assistant is ready. Allow camera and mic, then start the session.");
  checkExistingMediaPermission();
}

async function handlePermissionButton() {
  if (permissionBtn.dataset.action === "reload") {
    window.location.reload();
    return;
  }
  await requestMedia();
}

async function requestMedia() {
  if (permissionRetrying) return;
  permissionRetrying = true;
  permissionBtn.disabled = true;

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });
    localVideo.srcObject = mediaStream;
    permissionOverlay.classList.add("hidden");
    setStatus("ready");
    permissionMessageShown = false;
    startFaceMonitor();
  } catch (error) {
    await showPermissionProblem(error);
  } finally {
    permissionRetrying = false;
    permissionBtn.disabled = false;
  }
}

async function checkExistingMediaPermission() {
  const states = await getPermissionStates();
  if (states.camera === "granted" && states.microphone === "granted") {
    await requestMedia();
    return;
  }

  if (states.camera === "denied" || states.microphone === "denied") {
    setPermissionOverlay(
      "Camera or microphone is blocked. Open the lock icon, allow both permissions, then reload this page.",
      "Reload Page",
      "reload"
    );
  }
}

async function getPermissionStates() {
  const result = { camera: "unknown", microphone: "unknown" };
  if (!navigator.permissions?.query) return result;

  try {
    result.camera = (await navigator.permissions.query({ name: "camera" })).state;
  } catch (error) {
    result.camera = "unknown";
  }

  try {
    result.microphone = (await navigator.permissions.query({ name: "microphone" })).state;
  } catch (error) {
    result.microphone = "unknown";
  }

  return result;
}

async function showPermissionProblem(error) {
  const states = await getPermissionStates();
  const message = permissionHelpMessage(error, states);
  setPermissionOverlay(message, "Reload Page", "reload");

  if (!permissionMessageShown) {
    addMessage("ai", message);
    permissionMessageShown = true;
  }
}

function permissionHelpMessage(error, states) {
  if (states.camera === "granted" && states.microphone === "granted") {
    return "Chrome has permission now, but this page must be reloaded before the camera and mic can start.";
  }
  if (states.camera === "denied" || states.microphone === "denied") {
    return "Camera or microphone is blocked. Open the lock icon, allow both permissions, then reload this page.";
  }
  if (error?.name === "NotFoundError" || error?.name === "DevicesNotFoundError") {
    return "No camera or microphone was found. Connect a device, then reload this page.";
  }
  if (error?.name === "NotReadableError" || error?.name === "TrackStartError") {
    return "Camera or microphone is already being used by another app. Close that app, then reload this page.";
  }
  return "Chrome could not start camera and microphone. Allow both permissions from the lock icon, then reload this page.";
}

function setPermissionOverlay(message, buttonText, action) {
  permissionOverlay.classList.remove("hidden");
  permissionText.textContent = message;
  permissionBtn.textContent = buttonText;
  permissionBtn.dataset.action = action;
}

function toggleMic() {
  if (!mediaStream) return;
  const audioTrack = mediaStream.getAudioTracks()[0];
  if (!audioTrack) return;
  audioTrack.enabled = !audioTrack.enabled;
  micBtn.textContent = audioTrack.enabled ? "Mic On" : "Mic Off";
  micBtn.classList.toggle("off", !audioTrack.enabled);
}

function toggleCamera() {
  if (!mediaStream) return;
  const videoTrack = mediaStream.getVideoTracks()[0];
  if (!videoTrack) return;
  videoTrack.enabled = !videoTrack.enabled;
  cameraBtn.textContent = videoTrack.enabled ? "Camera On" : "Camera Off";
  cameraBtn.classList.toggle("off", !videoTrack.enabled);
  if (!videoTrack.enabled) {
    showFaceWarning("Camera is off. Turn it on before continuing.");
  }
}

async function startSession() {
  if (!mediaStream) {
    await requestMedia();
  }
  if (!mediaStream) return;

  const response = await fetch(`/api/sessions/${window.SESSION_CODE}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language: languageSelect.value })
  });

  if (!response.ok) {
    addMessage("ai", "Could not start the session. Please refresh and try again.");
    return;
  }

  const data = await response.json();
  questions = data.questions || questions;
  questionMeta = data.question_meta || questionMeta;
  if (data.duration_seconds) window.INTERVIEW_DURATION_SECONDS = data.duration_seconds;
  greeting = data.greeting || greeting;
  sessionActive = true;
  sessionFinished = false;
  pendingTranscripts = [];
  finalSessionBlob = null;
  currentQuestionIndex = -1;
  startBtn.disabled = true;
  endBtn.disabled = false;
  languageSelect.disabled = true;
  postSessionBox.classList.add("hidden");
  setStatus("active");
  startSessionRecording();
  startTimer();

  addMessage("ai", greeting);
  showQuestionOverlay(greeting, "Welcome");
  await playQuestionWithVoice(greeting, askNextQuestion);
}

function startSessionRecording() {
  sessionChunks = [];
  recordingStartedAt = Date.now();
  recordingStream = createSessionRecordingStream();
  const options = {
    videoBitsPerSecond: 1200000,
    audioBitsPerSecond: 96000
  };
  if (MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")) {
    options.mimeType = "video/webm;codecs=vp9,opus";
  } else if (MediaRecorder.isTypeSupported("video/webm")) {
    options.mimeType = "video/webm";
  }

  sessionRecorder = new MediaRecorder(recordingStream || mediaStream, options);
  sessionRecorder.ondataavailable = event => {
    if (event.data && event.data.size > 0) {
      sessionChunks.push(event.data);
    }
  };
  sessionRecorder.onstop = prepareSessionRecording;
  sessionRecorder.start(1000);
}

function startTimer() {
  elapsedSeconds = 0;
  updateTimer();
  timerInterval = window.setInterval(() => {
    elapsedSeconds += 1;
    updateTimer();
    if (elapsedSeconds >= Number(window.INTERVIEW_DURATION_SECONDS || 900)) {
      finishSession("Interview duration reached. We are completing your interview.");
    }
  }, 1000);
}

function updateTimer() {
  const minutes = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
  const seconds = String(elapsedSeconds % 60).padStart(2, "0");
  timerEl.textContent = `${minutes}:${seconds}`;
}

async function askNextQuestion(preface = "") {
  if (!sessionActive) return;
  currentQuestionIndex += 1;

  if (currentQuestionIndex >= questions.length) {
    completeInterview(preface);
    return;
  }

  currentQuestion = questions[currentQuestionIndex];
  currentQuestionMeta = questionMeta[currentQuestionIndex] || { question_type: "description", options: [] };
  answerBox.classList.add("hidden");
  const displayedText = preface
    ? `${preface} ${currentQuestionIndex + 1}. ${currentQuestion}`
    : `${currentQuestionIndex + 1}. ${currentQuestion}`;
  const spokenText = preface ? `${preface} ${currentQuestion}` : currentQuestion;
  addMessage("ai", displayedText);
  showQuestionOverlay(displayedText, `Question ${currentQuestionIndex + 1} of ${questions.length}`);
  const answerHandler = currentQuestionMeta.question_type === "multiple_choice" && (currentQuestionMeta.options || []).length
    ? showMultipleChoice
    : startAnswerRecording;
  await playQuestionWithVoice(spokenText, answerHandler);
}

function showMultipleChoice() {
  answerBox.classList.remove("hidden");
  manualAnswer.value = "";
  manualAnswer.classList.add("hidden");
  document.querySelector('label[for="manualAnswer"]')?.classList.add("hidden");
  questionOptions.innerHTML = "";
  questionOptions.classList.remove("hidden");
  setStatus("awaiting-choice");
  setAnswerControls(false, false);
  (currentQuestionMeta.options || []).forEach(option => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary option-button";
    button.textContent = option;
    button.addEventListener("click", async () => {
      manualAnswer.value = option;
      await submitAnswer();
    });
    questionOptions.appendChild(button);
  });
}

async function completeInterview(preface = "") {
  const finalText = preface ? `${preface} ${closing}` : closing;
  addMessage("ai", finalText);
  showQuestionOverlay(finalText, "Interview complete");
  await playQuestionWithVoice(finalText, () => {
    finishSession("Interview completed. Nothing has been saved yet.");
  });
}

async function playQuestionWithVoice(text, onDone) {
  setStatus("asking");
  setAnswerControls(false, false);
  setRecordingBanner(true, "Asking", "Listen to the question. Your answer will start after playback.");

  try {
    const response = await fetch(`/api/sessions/${window.SESSION_CODE}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language: languageSelect.value })
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new VoiceClientError("Voice playback failed.", payload.error_code);
    }

    questionAudio = new Audio(`data:audio/wav;base64,${payload.audio_base64}`);
    connectAssistantAudioToRecording(questionAudio);
    questionAudio.onended = () => onDone();
    questionAudio.onerror = () => onDone();
    if (recordingAudioContext?.state === "suspended") {
      await recordingAudioContext.resume();
    }
    await questionAudio.play();
  } catch (error) {
    showVoiceError(error, "voice");
    onDone();
  }
}

async function startAnswerRecording() {
  if (!sessionActive || !mediaStream) return;
  if (answerRecorder?.isRecording) {
    await answerRecorder.stop();
  }

  answerBox.classList.remove("hidden");
  questionOptions.classList.add("hidden");
  manualAnswer.classList.remove("hidden");
  document.querySelector('label[for="manualAnswer"]')?.classList.remove("hidden");
  manualAnswer.value = "";
  manualAnswer.placeholder = "Listening... speak your answer naturally.";
  setStatus("listening");
  setAnswerControls(true, false);
  setRecordingBanner(true, "Listening", "Speak naturally. I will wait through short pauses.");

  try {
    answerRecorder = await createWavRecorder(mediaStream);
    answerRecorder.start();
    startVoiceMonitor();
  } catch (error) {
    addMessage("ai", "Could not start answer recording. Type your answer and click Continue.");
    setRecordingBanner(false);
    setAnswerControls(false, true);
  }
}

async function stopAndTranscribeAnswer() {
  if (!answerRecorder?.isRecording) {
    manualAnswer.focus();
    return;
  }

  stopVoiceMonitor();
  setStatus("transcribing");
  setRecordingBanner(true, "Processing", "Processing your voice...");
  setAnswerControls(false, false);
  manualAnswer.placeholder = "Processing your voice...";

  try {
    answerRecording = await answerRecorder.stop();
    if (!answerRecording.blob.size || answerRecording.duration < ANSWER_MIN_AUDIO_SECONDS) {
      await repeatCurrentQuestion("I could not understand your answer. Please answer again.");
      return;
    }

    const formData = new FormData();
    formData.append("audio", answerRecording.blob, "answer.wav");
    formData.append("language", languageSelect.value);

    const response = await fetch(`/api/sessions/${window.SESSION_CODE}/stt`, {
      method: "POST",
      body: formData
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new VoiceClientError("Voice processing failed.", payload.error_code);
    }

    manualAnswer.value = payload.transcript || "";
    manualAnswer.placeholder = "Review or edit the transcript, then continue.";
    setStatus("review");
    setRecordingBanner(false);
    setAnswerControls(false, true);

    if (manualAnswer.value.trim()) {
      window.setTimeout(submitAnswer, 80);
    } else {
      await repeatCurrentQuestion("I could not understand your answer. Please answer again.");
    }
  } catch (error) {
    addMessage("ai", error.message || "I could not identify the answer. Please record again or type it manually.");
    setStatus("review");
    setRecordingBanner(false);
    setAnswerControls(false, true);
  }
}

async function repeatCurrentQuestion(reason) {
  if (!sessionActive || !currentQuestion) return;
  const repeatText = `${reason} ${currentQuestion}`;
  manualAnswer.value = "";
  answerBox.classList.add("hidden");
  setAnswerControls(false, false);
  setRecordingBanner(false);
  addMessage("ai", repeatText);
  await playQuestionWithVoice(repeatText, startAnswerRecording);
}

async function submitAnswer() {
  if (answerRecorder?.isRecording) {
    await stopAndTranscribeAnswer();
    return;
  }

  const answer = manualAnswer.value.trim();
  if (!answer) {
    manualAnswer.focus();
    return;
  }

  const wasFollowUp = Boolean(currentQuestionMeta?.is_follow_up);
  addMessage("user", answer);
  pendingTranscripts.push({
    question_number: currentQuestionIndex + 1,
    question_text: currentQuestion,
    answer_text: answer
  });
  answerBox.classList.add("hidden");
  questionOptions.classList.add("hidden");
  manualAnswer.classList.remove("hidden");
  document.querySelector('label[for="manualAnswer"]')?.classList.remove("hidden");
  setAnswerControls(false, false);

  // Give the adaptive interviewer one chance to clarify each configured question.
  // Follow-up answers always move on, preventing an endless clarification loop.
  if (!wasFollowUp) {
    const adaptive = await getAdaptiveTurn(currentQuestion, answer);
    if (adaptive?.follow_up && adaptive.follow_up_question) {
      currentQuestion = adaptive.follow_up_question;
      currentQuestionMeta = { question_type: "description", options: [], is_follow_up: true };
      answerBox.classList.add("hidden");
      questionOptions.classList.add("hidden");
      const followUpText = `Follow-up: ${adaptive.follow_up_question}`;
      addMessage("ai", followUpText);
      showQuestionOverlay(followUpText, "Follow-up question");
      await playQuestionWithVoice(adaptive.follow_up_question, startAnswerRecording);
      return;
    }
    const acknowledgement = adaptive?.acknowledgement || await getAnswerAcknowledgement(answer);
    await askNextQuestion(acknowledgement);
    return;
  }

  const acknowledgement = await getAnswerAcknowledgement(answer);
  await askNextQuestion(acknowledgement);
}

async function getAdaptiveTurn(question, answer) {
  try {
    const response = await fetch(`/api/sessions/${window.SESSION_CODE}/adaptive-turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        answer,
        language: languageSelect.value
      })
    });
    const result = await response.json();
    if (response.ok) return result;
  } catch (error) {
    // A failed adaptive request must never stop the interview.
  }
  return null;
}

async function getAnswerAcknowledgement(answer) {
  try {
    const response = await fetch(`/api/sessions/${window.SESSION_CODE}/acknowledgement`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer, language: languageSelect.value })
    });
    const result = await response.json();
    if (response.ok && result.text) return result.text;
  } catch (error) {
    // The interview should continue even if the acknowledgement request fails.
  }
  return answer.trim().split(/\s+/).length <= 2
    ? "That is okay. Let us move to the next question."
    : "Thank you, that gives me useful context. Let us continue.";
}

async function finishSession(message) {
  if (!sessionActive) return;
  sessionActive = false;
  sessionFinished = true;
  pendingFinishMessage = message;
  startBtn.disabled = true;
  endBtn.disabled = true;
  answerBox.classList.add("hidden");
  setRecordingBanner(false);
  stopFaceMonitor();
  setStatus("ending");
  addMessage("ai", message);

  if (timerInterval) {
    window.clearInterval(timerInterval);
    timerInterval = null;
  }
  if (questionAudio) {
    questionAudio.pause();
    questionAudio = null;
  }
  if (answerRecorder?.isRecording) {
    stopVoiceMonitor();
    await answerRecorder.stop();
  }

  if (sessionRecorder && sessionRecorder.state !== "inactive") {
    sessionRecorder.stop();
  } else {
    showPostSessionOptions();
  }
}

function prepareSessionRecording() {
  finalSessionBlob = new Blob(sessionChunks, { type: "video/webm" });
  stopSessionRecordingAudio();
  showPostSessionOptions();
}

function showPostSessionOptions() {
  setStatus("complete");
  postSessionText.textContent = `${pendingFinishMessage} Save this session or start again.`;
  postSessionBox.classList.remove("hidden");
}

function showQuestionOverlay(text, label = "AI Interviewer") {
  if (!questionOverlay || !questionOverlayText) return;
  questionOverlayLabel.textContent = label;
  questionOverlayText.textContent = text;
  questionOverlay.classList.remove("hidden");
}

async function saveSession() {
  saveSessionBtn.disabled = true;
  startAgainBtn.disabled = true;
  setStatus("saving");
  addMessage("ai", "Saving session recording and transcript...");

  try {
    for (const transcript of pendingTranscripts) {
      const transcriptResponse = await fetch(`/api/sessions/${window.SESSION_CODE}/transcripts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(transcript)
      });
      if (!transcriptResponse.ok) {
        const transcriptPayload = await readJsonResponse(transcriptResponse);
        throw new Error(transcriptPayload.error || "Transcript save failed.");
      }
    }

    if (!finalSessionBlob?.size) {
      throw new Error("Recording is not ready yet. Please wait a moment and try again.");
    }

    const duration = recordingStartedAt ? (Date.now() - recordingStartedAt) / 1000 : elapsedSeconds;
    await uploadSessionRecording(finalSessionBlob, duration);

    const saveResponse = await fetch(`/api/sessions/${window.SESSION_CODE}/save`, { method: "POST" });
    const savePayload = await readJsonResponse(saveResponse);
    if (!saveResponse.ok) {
      throw new Error(savePayload.error || "Save failed.");
    }
    if (!savePayload.recording_url) {
      throw new Error("Recording was not saved. Please try Save Session again.");
    }

    setStatus("saved");
    addMessage("ai", "Session saved.");
    renderEvaluation(savePayload.evaluation);
    postSessionText.textContent = "Session saved. You can preview, download, copy the code, or start a new session.";
    showPreviewActions(savePayload.recording_url);
    renderVideoEditing(savePayload.video_editing);
    saveSessionBtn.textContent = "Saved";
    startAgainBtn.disabled = false;
  } catch (error) {
    setStatus("save failed");
    addMessage("ai", error.message || "Could not save the session. Please try Save Session again.");
    postSessionText.textContent = "Could not save the recording. Please try Save Session again.";
    saveSessionBtn.disabled = false;
    startAgainBtn.disabled = false;
  }
}

function renderEvaluation(evaluation) {
  if (!evaluation || evaluation.score === undefined || !evaluationBox) return;
  evaluationScore.textContent = evaluation.score;
  evaluationTag.textContent = evaluation.tag || "Evaluated";
  evaluationSummary.textContent = evaluation.summary || "Your interview has been evaluated against the job requirements.";
  evaluationBox.classList.remove("hidden");
}

async function uploadSessionRecording(blob, duration) {
  const totalChunks = Math.ceil(blob.size / RECORDING_CHUNK_SIZE);
  const uploadId = `${window.SESSION_CODE}-${Date.now()}-${Math.random().toString(36).slice(2)}`;

  for (let index = 0; index < totalChunks; index += 1) {
    const start = index * RECORDING_CHUNK_SIZE;
    const end = Math.min(start + RECORDING_CHUNK_SIZE, blob.size);
    const formData = new FormData();
    formData.append("upload_id", uploadId);
    formData.append("chunk_index", String(index));
    formData.append("total_chunks", String(totalChunks));
    formData.append("duration", String(duration));
    formData.append("chunk", blob.slice(start, end), `${window.SESSION_CODE}.part`);

    setStatus(`uploading ${index + 1}/${totalChunks}`);
    postSessionText.textContent = index === totalChunks - 1
      ? "Uploading final part and converting the recording to MP4..."
      : `Uploading recording ${index + 1} of ${totalChunks}...`;

    const response = await fetch(`/api/sessions/${window.SESSION_CODE}/recording-chunk`, {
      method: "POST",
      body: formData
    });
    const payload = await readJsonResponse(response);

    if (!response.ok) {
      throw new Error(payload.error || "Recording upload failed.");
    }
    if (index === totalChunks - 1 && !payload.complete) {
      throw new Error("Recording upload did not finish.");
    }
  }
}

async function readJsonResponse(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}

function startVoiceMonitor() {
  stopVoiceMonitor();
  const audioTrack = mediaStream.getAudioTracks()[0];
  if (!audioTrack?.enabled) {
    addMessage("ai", "Your microphone is muted. Turn Mic On and answer again.");
    return;
  }

  const Context = window.AudioContext || window.webkitAudioContext;
  const context = new Context();
  const source = context.createMediaStreamSource(mediaStream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0.65;
  const data = new Uint8Array(analyser.fftSize);
  const startedAt = Date.now();
  const calibrationUntil = startedAt + 700;
  let speechStarted = false;
  let lastSpeechAt = 0;
  let noiseFloor = 0.012;
  let quietFrames = 0;
  let speechFrames = 0;
  source.connect(analyser);

  const tick = () => {
    if (!answerRecorder?.isRecording) return;
    analyser.getByteTimeDomainData(data);
    const volume = rms(data);
    const now = Date.now();
    const threshold = Math.max(0.028, noiseFloor + 0.018, noiseFloor * 2.35);

    if (!speechStarted) {
      if (now < calibrationUntil || volume <= threshold) {
        noiseFloor = noiseFloor * 0.94 + volume * 0.06;
      }
      if (now < calibrationUntil) {
        recordingText.textContent = "Listening for your voice...";
      } else if (volume > threshold) {
        speechFrames += 1;
        if (speechFrames >= 4) {
          speechStarted = true;
          lastSpeechAt = now;
          quietFrames = 0;
          recordingText.textContent = "I can hear you. Keep going.";
        }
      } else {
        speechFrames = 0;
        recordingText.textContent = "Speak naturally. I will stop after a short pause.";
      }
    } else if (volume > threshold) {
      lastSpeechAt = now;
      quietFrames = 0;
      recordingText.textContent = "I can hear you. Keep going.";
    } else {
      quietFrames += 1;
      const pauseMs = now - lastSpeechAt;
      recordingText.textContent = pauseMs > 700
        ? "Your answer seems complete. Processing..."
        : "Listening for your pause...";
    }

    if (
      speechStarted &&
      quietFrames > 8 &&
      now - lastSpeechAt > ANSWER_PAUSE_TO_TRANSCRIBE_MS &&
      now - startedAt > 1200
    ) {
      stopAndTranscribeAnswer();
      return;
    }

    if (now - startedAt > ANSWER_MAX_RECORDING_MS) {
      recordingText.textContent = "I have enough to process now.";
      stopAndTranscribeAnswer();
      return;
    }

    voiceMonitor.frame = window.requestAnimationFrame(tick);
  };

  voiceMonitor = { context, source, analyser, frame: window.requestAnimationFrame(tick) };
}

function setupSavedSessionView() {
  stopFaceMonitor();
  permissionOverlay.classList.add("hidden");
  localVideo.controls = true;
  localVideo.muted = false;
  if (window.RECORDING_URL) {
    localVideo.src = window.RECORDING_URL;
  }

  startBtn.disabled = true;
  endBtn.disabled = true;
  languageSelect.disabled = true;
  setStatus("saved");

  const transcripts = window.SAVED_TRANSCRIPTS || [];
  if (transcripts.length) {
    transcripts.forEach(item => {
      addMessage("ai", `${item.question_number}. ${item.question_text}`);
      addMessage("user", item.answer_text);
    });
  } else {
    addMessage("ai", "Saved session loaded. The transcript is not available yet.");
  }

  postSessionText.textContent = "Saved session loaded. You can preview, download, or copy the session code.";
  postSessionBox.classList.remove("hidden");
  saveSessionBtn.disabled = true;
  saveSessionBtn.textContent = "Saved";
  startAgainBtn.disabled = false;
  showPreviewActions(window.RECORDING_URL);
  renderEvaluation(window.INITIAL_EVALUATION);
  if (window.INITIAL_VIDEO_EDITING) {
    renderVideoEditing(window.INITIAL_VIDEO_EDITING);
  } else {
    refreshVideoEditingStatus();
  }
}

function showPreviewActions(recordingUrl) {
  if (!recordingUrl) return;
  previewRecordingBtn.href = recordingUrl;
  downloadRecordingBtn.href = recordingUrl;
  downloadRecordingBtn.setAttribute("download", `${window.SESSION_CODE}.mp4`);
  shareRecordingBtn.dataset.shareUrl = recordingUrl;
  previewActions.classList.remove("hidden");
}

async function refreshVideoEditingStatus() {
  try {
    const response = await fetch(`/api/sessions/${window.SESSION_CODE}/video-editing`);
    const payload = await readJsonResponse(response);
    if (response.ok) renderVideoEditing(payload.video_editing);
  } catch (error) {
    // The saved recording remains available even if status polling is temporarily unavailable.
  }
}

async function retryVideoEditing() {
  retryVideoEditingBtn.disabled = true;
  videoEditingMessage.textContent = "Submitting the recording again...";
  try {
    const response = await fetch(`/api/sessions/${window.SESSION_CODE}/video-editing/retry`, {
      method: "POST"
    });
    const payload = await readJsonResponse(response);
    if (!response.ok) throw new Error(payload.error || "Could not retry video editing.");
    renderVideoEditing(payload.video_editing);
  } catch (error) {
    videoEditingMessage.textContent = error.message;
    retryVideoEditingBtn.disabled = false;
  }
}

function renderVideoEditing(job) {
  if (!job || job.status === "disabled" || job.status === "not_submitted") {
    videoEditingBox.classList.add("hidden");
    stopVideoEditingPolling();
    return;
  }

  const status = job.status || "not_submitted";
  videoEditingBox.classList.remove("hidden");
  videoEditingStatus.textContent = status.replaceAll("_", " ");
  videoEditingStatus.className = `editing-status-pill status-${status}`;
  retryVideoEditingBtn.classList.toggle("hidden", status !== "failed");
  retryVideoEditingBtn.disabled = false;
  editedVideoActions.classList.add("hidden");

  const messages = {
    pending: "The recording is waiting to be submitted to the editing workflow.",
    submitted: "The recording and interview details were sent to n8n.",
    processing: "The AI workflow is editing the recording now.",
    completed: "Your social-ready edited video is available.",
    failed: job.error_message || "The editing workflow failed. Your original recording is still safe."
  };
  videoEditingMessage.textContent = messages[status] || "Checking the editing workflow...";

  if (status === "completed" && job.edited_video_url) {
    previewEditedVideoBtn.href = job.edited_video_url;
    downloadEditedVideoBtn.href = job.edited_video_url;
    downloadEditedVideoBtn.setAttribute("download", `${window.SESSION_CODE}-edited.mp4`);
    shareEditedVideoBtn.dataset.shareUrl = job.edited_video_url;
    editedVideoActions.classList.remove("hidden");
  }

  if (["pending", "submitted", "processing"].includes(status)) {
    startVideoEditingPolling();
  } else {
    stopVideoEditingPolling();
  }
}

function startVideoEditingPolling() {
  if (videoEditingPoll) return;
  videoEditingPoll = window.setInterval(refreshVideoEditingStatus, 10000);
}

function stopVideoEditingPolling() {
  if (!videoEditingPoll) return;
  window.clearInterval(videoEditingPoll);
  videoEditingPoll = null;
}

function stopVoiceMonitor() {
  if (!voiceMonitor) return;
  window.cancelAnimationFrame(voiceMonitor.frame);
  voiceMonitor.source.disconnect();
  voiceMonitor.context.close();
  voiceMonitor = null;
}

function createSessionRecordingStream() {
  try {
    const Context = window.AudioContext || window.webkitAudioContext;
    recordingAudioContext = new Context();
    recordingDestination = recordingAudioContext.createMediaStreamDestination();
    recordingMicSource = recordingAudioContext.createMediaStreamSource(mediaStream);
    recordingMicSource.connect(recordingDestination);

    const stream = new MediaStream();
    mediaStream.getVideoTracks().forEach(track => stream.addTrack(track));
    recordingDestination.stream.getAudioTracks().forEach(track => stream.addTrack(track));
    return stream;
  } catch (error) {
    recordingAudioContext = null;
    recordingDestination = null;
    recordingMicSource = null;
    return null;
  }
}

function connectAssistantAudioToRecording(audio) {
  if (!recordingAudioContext || !recordingDestination) return;

  try {
    const source = recordingAudioContext.createMediaElementSource(audio);
    source.connect(recordingDestination);
    source.connect(recordingAudioContext.destination);
  } catch (error) {
    // If the browser refuses graph routing, the assistant still plays normally.
  }
}

function stopSessionRecordingAudio() {
  if (recordingStream) {
    recordingStream.getAudioTracks().forEach(track => track.stop());
    recordingStream = null;
  }
  if (recordingMicSource) {
    recordingMicSource.disconnect();
    recordingMicSource = null;
  }
  if (recordingAudioContext) {
    recordingAudioContext.close();
    recordingAudioContext = null;
  }
  recordingDestination = null;
}

function startFaceMonitor() {
  stopFaceMonitor();
  if (window.FaceDetection) {
    startMediaPipeFaceMonitor();
    return;
  }
  if ("FaceDetector" in window) {
    startNativeFaceMonitor();
    return;
  }
  if (faceGuide) {
    faceGuide.classList.remove("hidden");
  }
}

function startMediaPipeFaceMonitor() {
  let detector = null;
  try {
    detector = new window.FaceDetection({
      locateFile: file => `https://cdn.jsdelivr.net/npm/@mediapipe/face_detection/${file}`
    });
    detector.setOptions({
      model: "short",
      minDetectionConfidence: 0.55
    });
    detector.onResults(results => {
      const detections = results.detections || [];
      handleFaceDetections(detections.map(mediaPipeDetectionBox));
      faceChecking = false;
    });
  } catch (error) {
    startNativeFaceMonitor();
    return;
  }

  faceMonitorStopped = false;
  const checkFace = async () => {
    if (faceMonitorStopped || !mediaStream || sessionFinished || !localVideo.srcObject) return;

    if (!isCameraTrackOn()) {
      showFaceWarning("Camera is off. Turn it on before continuing.");
      faceMonitor = window.setTimeout(checkFace, 1200);
      return;
    }

    if (localVideo.readyState >= 2 && !faceChecking) {
      try {
        faceChecking = true;
        await detector.send({ image: localVideo });
      } catch (error) {
        faceChecking = false;
        startNativeFaceMonitor();
        return;
      }
    }

    faceMonitor = window.setTimeout(checkFace, 1200);
  };

  faceMonitor = window.setTimeout(checkFace, 1000);
}

function startNativeFaceMonitor() {
  let detector = null;
  try {
    detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 1 });
  } catch (error) {
    return;
  }

  faceMonitorStopped = false;
  const checkFace = async () => {
    if (faceMonitorStopped || !mediaStream || sessionFinished || !localVideo.srcObject) return;

    if (!isCameraTrackOn()) {
      showFaceWarning("Camera is off. Turn it on before continuing.");
      faceMonitor = window.setTimeout(checkFace, 1500);
      return;
    }

    if (localVideo.readyState >= 2) {
      try {
        const faces = await detector.detect(localVideo);
        handleFaceDetections(faces.map(nativeDetectionBox));
      } catch (error) {
        stopFaceMonitor();
        return;
      }
    }

    faceMonitor = window.setTimeout(checkFace, 1500);
  };

  faceMonitor = window.setTimeout(checkFace, 1500);
}

function stopFaceMonitor() {
  faceMonitorStopped = true;
  faceChecking = false;
  lastFaceBox = null;
  lastFaceBoxAt = 0;
  stableFaceFrames = 0;
  if (faceMonitor) {
    window.clearTimeout(faceMonitor);
    faceMonitor = null;
  }
  hideFaceWarning();
}

function handleFaceDetections(boxes) {
  if (!boxes.length) {
    lastFaceBox = null;
    lastFaceBoxAt = 0;
    stableFaceFrames = 0;
    setFaceState("bad", "Please come back into the frame.");
    return;
  }

  const motion = getFaceMotion(boxes[0]);
  setFaceState("good", "Face in frame");

  if (motion.fast) {
    showFaceStatus("Hold steady for a clear recording.", "warn");
  }
}

function mediaPipeDetectionBox(detection) {
  const relativeBox = detection?.locationData?.relativeBoundingBox || {};
  return {
    x: clamp01(relativeBox.xMin || 0),
    y: clamp01(relativeBox.yMin || 0),
    width: clamp01(relativeBox.width || 0),
    height: clamp01(relativeBox.height || 0)
  };
}

function nativeDetectionBox(face) {
  const box = face.boundingBox || {};
  const videoWidth = localVideo.videoWidth || 1;
  const videoHeight = localVideo.videoHeight || 1;
  return {
    x: clamp01((box.x || 0) / videoWidth),
    y: clamp01((box.y || 0) / videoHeight),
    width: clamp01((box.width || 0) / videoWidth),
    height: clamp01((box.height || 0) / videoHeight)
  };
}

function isCameraTrackOn() {
  const videoTrack = mediaStream?.getVideoTracks()[0];
  return Boolean(videoTrack?.enabled);
}

function setFaceState(state, message) {
  if (faceGuide) {
    faceGuide.classList.toggle("face-guide-good", state === "good");
    faceGuide.classList.toggle("face-guide-warn", false);
    faceGuide.classList.toggle("face-guide-bad", state === "bad");
  }

  if (state === "good") {
    showFaceStatus(message, "good");
    return;
  }

  stableFaceFrames = 0;
  showFaceStatus(message, state);
}

function showFaceStatus(message, state) {
  if (!faceWarning) return;
  faceWarning.textContent = message;
  faceWarning.classList.toggle("face-warning-good", state === "good");
  faceWarning.classList.toggle("face-warning-warn", state === "warn");
  faceWarning.classList.toggle("face-warning-bad", state === "bad");
  faceWarning.classList.remove("hidden");
  faceWarningShownAt = Date.now();
}

function showFaceWarning(message) {
  setFaceState("bad", message);
}

function clamp01(value) {
  return Math.max(0, Math.min(1, Number(value) || 0));
}

function hideFaceWarning() {
  if (!faceWarning) return;
  if (Date.now() - faceWarningShownAt < 1000) return;
  faceWarning.classList.add("hidden");
}

function getFaceMotion(box) {
  const now = Date.now();
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;
  let fast = false;

  if (lastFaceBox && lastFaceBoxAt) {
    const elapsed = Math.max(1, now - lastFaceBoxAt);
    const lastCenterX = lastFaceBox.x + lastFaceBox.width / 2;
    const lastCenterY = lastFaceBox.y + lastFaceBox.height / 2;
    const centerMove = Math.hypot(centerX - lastCenterX, centerY - lastCenterY);
    const sizeMove = Math.abs(box.width - lastFaceBox.width) + Math.abs(box.height - lastFaceBox.height);
    const movementPerSecond = ((centerMove * 1.6) + sizeMove) / (elapsed / 1000);
    fast = movementPerSecond > 0.36;
  }

  lastFaceBox = box;
  lastFaceBoxAt = now;
  if (fast) stableFaceFrames = 0;

  return { fast };
}

function rms(data) {
  let sum = 0;
  for (let index = 0; index < data.length; index += 1) {
    const value = (data[index] - 128) / 128;
    sum += value * value;
  }
  return Math.sqrt(sum / data.length);
}

async function createWavRecorder(stream) {
  const audioContext = createAudioContext();
  const source = audioContext.createMediaStreamSource(stream);
  const processor = audioContext.createScriptProcessor(4096, 1, 1);
  const silentOutput = audioContext.createGain();
  const chunks = [];

  silentOutput.gain.value = 0;
  processor.onaudioprocess = event => {
    chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  };

  return {
    isRecording: false,
    start() {
      this.isRecording = true;
      source.connect(processor);
      processor.connect(silentOutput);
      silentOutput.connect(audioContext.destination);
    },
    async stop() {
      this.isRecording = false;
      processor.disconnect();
      silentOutput.disconnect();
      source.disconnect();
      await audioContext.close();
      const samples = mergeFloat32(chunks);
      return {
        blob: encodeWav(samples, audioContext.sampleRate),
        duration: samples.length / audioContext.sampleRate
      };
    }
  };
}

function createAudioContext() {
  const Context = window.AudioContext || window.webkitAudioContext;
  try {
    return new Context({ sampleRate: 16000 });
  } catch (error) {
    return new Context();
  }
}

function mergeFloat32(chunks) {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const result = new Float32Array(length);
  let offset = 0;
  chunks.forEach(chunk => {
    result.set(chunk, offset);
    offset += chunk.length;
  });
  return result;
}

function encodeWav(samples, sampleRate) {
  const bytesPerSample = 2;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * bytesPerSample, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true);
  view.setUint16(32, bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, samples.length * bytesPerSample, true);

  let offset = 44;
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }

  return new Blob([view], { type: "audio/wav" });
}

function writeString(view, offset, text) {
  for (let index = 0; index < text.length; index += 1) {
    view.setUint8(offset + index, text.charCodeAt(index));
  }
}

function setAnswerControls(isRecording, canSave) {
  recordAnswerBtn.disabled = isRecording;
  transcribeAnswerBtn.disabled = !isRecording;
  submitAnswerBtn.disabled = !canSave;
}

function setRecordingBanner(visible, title = "", text = "") {
  recordingBanner.classList.toggle("hidden", !visible);
  if (title) recordingTitle.textContent = title;
  if (text) recordingText.textContent = text;
}

class VoiceClientError extends Error {
  constructor(message, code) {
    super(message);
    this.code = code;
  }
}

function showVoiceError(error, feature) {
  addMessage("ai", error.message || `Voice ${feature} failed.`);
  if (error.code === "sarvam_no_credits") {
    addMessage("ai", "The voice service is connected, but the account has no credits. Add credits, restart the server, then start a new session.");
    return;
  }
  if (error.code === "sarvam_invalid_key") {
    addMessage("ai", "The voice service rejected the API key. Create a fresh key, put it in .env, restart the server, then try again.");
    return;
  }
  if (error.code === "sarvam_config_missing") {
    addMessage("ai", "Voice settings are missing in .env. Add the API key and endpoints, restart the server, then try again.");
    return;
  }
  addMessage("ai", "You can record again or type the answer manually while voice processing is unavailable.");
}

function addMessage(role, text) {
  const message = document.createElement("div");
  message.className = `message ${role}`;
  message.innerHTML = `<span class="role">${role === "ai" ? "AI Assistant" : "You"}</span><p></p>`;
  message.querySelector("p").textContent = text;
  chatLog.appendChild(message);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setStatus(status) {
  statusPill.textContent = status;
}

async function copySessionLink() {
  await copyText(shareLink.value, copyLinkBtn, "Copied");
}

async function copySessionCode() {
  await copyText(sessionCodeInput.value, copyCodeBtn, "Copied");
}

async function copyText(value, button, copiedText) {
  try {
    await navigator.clipboard.writeText(value);
    const original = button.textContent;
    button.textContent = copiedText;
    window.setTimeout(() => {
      button.textContent = original;
    }, 1200);
  } catch (error) {
    sessionCodeInput.select();
  }
}

