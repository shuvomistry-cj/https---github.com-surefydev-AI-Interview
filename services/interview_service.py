DEFAULT_QUESTIONS = [
    "Tell us about your experience that is most relevant to this role.",
    "Describe a challenging problem you solved and the approach you took.",
    "How do you prioritize quality, deadlines, and collaboration?",
    "What would you focus on during your first 30 days in this role?",
]

DEFAULT_GREETINGS = {
    "hi": "Namaste. This is your AI interviewer. Please answer each question naturally. Let us begin.",
    "te": "Namaskaram. This is your AI interviewer. Please answer each question naturally. Let us begin.",
}

DEFAULT_CLOSINGS = {
    "hi": "Dhanyavaad. Aapka interview complete ho gaya hai.",
    "te": "Dhanyavadalu. Mee interview poorthayindi.",
}


def get_questions(language):
    return DEFAULT_QUESTIONS


def get_greeting(language):
    return DEFAULT_GREETINGS.get(language, "Welcome. I am your AI interviewer. Please answer each question naturally. Let us begin.")


def get_closing(language):
    return DEFAULT_CLOSINGS.get(language, "Thank you. Your interview is complete and your result is being prepared.")
