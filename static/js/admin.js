const form = document.getElementById("jobForm");
const message = document.getElementById("adminMessage");
const editor = document.getElementById("questionEditor");
const questionList = document.getElementById("questionList");
const activeJobLabel = document.getElementById("activeJobLabel");
let activeJobId = "";
let activeLanguage = "en";
let activeLanguages = ["en"];
let activeSource = "";
let activeCount = 8;
let activeTypes = ["description", "short_answer", "multiple_choice"];
let activeJobName = "Interview role";
let currentQuestions = [];

form.addEventListener("submit", async event => {
  event.preventDefault();
  const data = new FormData(form);
  activeJobId = String(data.get("job_id")).trim();
  activeSource = String(data.get("job_description")).trim();
  activeJobName = String(data.get("job_name")).trim();
  activeLanguages = String(data.get("languages")).split(",").map(item => item.trim().toLowerCase()).filter(Boolean);
  activeLanguage = activeLanguages[0] || "en";
  activeCount = Number(data.get("question_count")) || 8;
  activeTypes = data.get("include_mcq") ? ["description", "short_answer", "multiple_choice"] : ["description", "short_answer"];
  try {
    const response = await fetch("/api/admin/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      job_id: activeJobId, job_name: data.get("job_name"), employer_id: data.get("employer_id"), job_description: activeSource,
      duration_seconds: Number(data.get("duration_minutes")) * 60, languages: String(data.get("languages")).split(",").map(item => item.trim()).filter(Boolean)
      , attempt_mode: data.get("attempt_mode"), show_results_to_candidate: data.get("show_results_to_candidate") === "on"
    }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not create job.");
    await generateQuestions();
  } catch (error) { showMessage(error.message); }
});

document.getElementById("generateAgainBtn").addEventListener("click", generateQuestions);
document.getElementById("saveQuestionsBtn").addEventListener("click", saveQuestions);
document.getElementById("deleteQuestionsBtn").addEventListener("click", deleteQuestions);
document.getElementById("addQuestionBtn").addEventListener("click", () => {
  currentQuestions = readEditorQuestions();
  currentQuestions.push({ question_type: "description", question_text: "", expected_answer: "", options: [] });
  renderQuestions(currentQuestions);
  editor.classList.remove("hidden");
});

async function generateQuestions() {
  if (!activeJobId) return;
  showMessage("Generating questions from the JD/test brief...");
  try {
    const response = await fetch(`/api/admin/jobs/${encodeURIComponent(activeJobId)}/generate-questions`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: activeLanguage, languages: activeLanguages, count: activeCount, question_types: activeTypes, job_description: activeSource })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Question generation failed.");
    renderQuestions(result.questions || []);
    editor.classList.remove("hidden");
    activeJobLabel.textContent = `${activeJobId} · ${activeLanguage} · Review every question and expected answer before saving.`;
  showMessage(`Questions generated in ${activeLanguage}. Copies were prepared for: ${result.translated_languages?.join(", ") || activeLanguages.join(", ")}. Edit the source questions and save to refresh all translations.`);
  } catch (error) { showMessage(error.message); }
}

function renderQuestions(questions) {
  currentQuestions = questions;
  questionList.innerHTML = questions.map((question, index) => `<article class="question-editor" data-index="${index}">
    <div class="question-editor-heading"><strong>Question ${index + 1}</strong><div><select class="question-type"><option value="description" ${question.question_type === "description" ? "selected" : ""}>Description</option><option value="short_answer" ${question.question_type === "short_answer" ? "selected" : ""}>Short answer</option><option value="multiple_choice" ${question.question_type === "multiple_choice" ? "selected" : ""}>Multiple choice</option></select><button class="secondary assist-question-btn" type="button">Help me with AI</button></div></div>
    <label>Question<textarea class="question-text" rows="3"></textarea></label>
    <label>Expected answer / evaluation rubric<textarea class="expected-answer" rows="3"></textarea></label>
    <label>Options (only for multiple choice, comma separated)<input class="question-options" placeholder="Option A, Option B, Option C, Option D"></label>
  </article>`).join("");
  questionList.querySelectorAll(".question-editor").forEach((card, index) => {
    card.querySelector(".question-text").value = questions[index].question_text || "";
    card.querySelector(".expected-answer").value = questions[index].expected_answer || "";
    card.querySelector(".question-options").value = (questions[index].options || []).join(", ");
    card.querySelector(".assist-question-btn").addEventListener("click", () => assistQuestion(card));
  });
}

async function assistQuestion(card) {
  const button = card.querySelector(".assist-question-btn");
  button.disabled = true;
  button.textContent = "Thinking...";
  try {
    const response = await fetch("/api/admin/questions/assist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      job_name: activeJobName, source_text: activeSource, language: activeLanguage,
      question_type: card.querySelector(".question-type").value,
      draft_question: card.querySelector(".question-text").value,
      draft_expected_answer: card.querySelector(".expected-answer").value
    }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "AI assistance failed.");
    card.querySelector(".question-text").value = result.question_text || "";
    card.querySelector(".expected-answer").value = result.expected_answer || "";
    card.querySelector(".question-options").value = (result.options || []).join(", ");
    showMessage("AI suggestion applied. Review it before saving.");
  } catch (error) { showMessage(error.message); }
  finally { button.disabled = false; button.textContent = "Help me with AI"; }
}

async function saveQuestions() {
  const questions = readEditorQuestions();
  if (!questions.length) return showMessage("Add at least one question.");
  if (questions.some(item => !item.question_text)) return showMessage("Every question must have question text.");
  const response = await fetch(`/api/admin/jobs/${encodeURIComponent(activeJobId)}/questions`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language: activeLanguage, languages: activeLanguages, questions }) });
  const result = await response.json();
  if (!response.ok) return showMessage(result.error || "Questions could not be saved.");
  showMessage(`Question bank saved and translated for: ${activeLanguages.join(", ")}.`);
  setTimeout(() => window.location.reload(), 700);
}

async function deleteQuestions() {
  if (!activeJobId || !window.confirm(`Delete all ${activeLanguage} questions for ${activeJobId}? This cannot be undone.`)) return;
  const response = await fetch(`/api/admin/jobs/${encodeURIComponent(activeJobId)}/questions?language=${encodeURIComponent(activeLanguage)}`, { method: "DELETE" });
  const result = await response.json();
  if (!response.ok) return showMessage(result.error || "Question bank could not be deleted.");
  questionList.innerHTML = "";
  currentQuestions = [];
  showMessage(`${result.deleted} questions deleted. Add questions manually or generate a new draft.`);
}

function readEditorQuestions() {
  return [...questionList.querySelectorAll(".question-editor")].map(card => ({
    question_type: card.querySelector(".question-type").value,
    question_text: card.querySelector(".question-text").value.trim(),
    expected_answer: card.querySelector(".expected-answer").value.trim(),
    options: card.querySelector(".question-options").value.split(",").map(item => item.trim()).filter(Boolean)
  }));
}

document.querySelectorAll("[data-job-id]").forEach(button => button.addEventListener("click", async () => {
  const url = `${window.location.origin}/interview/${encodeURIComponent(button.dataset.jobId)}/onboarding`;
  await navigator.clipboard.writeText(url);
  showMessage(`Candidate link copied for ${button.dataset.jobName}.`);
}));

document.querySelectorAll("[data-edit-job]").forEach(button => button.addEventListener("click", async () => {
  activeJobId = button.dataset.editJob;
  activeJobName = button.dataset.jobName;
  activeSource = button.dataset.jobSource;
  activeLanguage = button.dataset.jobLanguage || "en";
  activeLanguages = activeLanguage.split(",").map(item => item.trim()).filter(Boolean);
  const response = await fetch(`/api/admin/jobs/${encodeURIComponent(activeJobId)}/questions?language=${encodeURIComponent(activeLanguage)}`);
  const result = await response.json();
  if (!response.ok) return showMessage(result.error || "Questions could not be loaded.");
  renderQuestions(result.questions || []);
  activeJobLabel.textContent = `${activeJobId} · ${activeLanguage} · Edit and save the question bank.`;
  editor.classList.remove("hidden");
  editor.scrollIntoView({ behavior: "smooth", block: "start" });
}));

function showMessage(text) { message.textContent = text; message.classList.remove("hidden"); }
