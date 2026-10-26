"""The 56 quiz categories, in the required display order."""
import re

CATEGORY_NAMES = [
    "History", "Math", "Science", "Space (Astronomy)", "Kannada", "English",
    "Social Science", "Software", "Hardware", "Artificial Intelligence (AI)",
    "Machine Learning (ML)", "General Knowledge (GK)", "Aptitude", "Web Development",
    "Puzzles", "Chess", "Cricket", "Health & Human Body", "Olympics", "Formula",
    "IPL", "Operating Systems", "Python", "Java", "Algorithms & Data Structures",
    "Computer Basics", "Animals", "Birds", "Plants", "General Trivia",
    "Oceans & Marine Life", "Mountains & Rivers (India Only)", "Travel & Tourism",
    "Countries & Capitals", "Board Games", "Number Puzzles", "Languages",
    "Famous People", "Mobile & Apps", "Brain Teasers", "Mental Math", "Cinema",
    "Photography", "UI/UX Design", "HTML", "CSS", "Scientists", "Law & Constitution",
    "Indian History", "World History", "Environment", "Technology",
    "Logical Reasoning", "Funny Questions", "Crazy Facts", "Trick Questions",
]
assert len(CATEGORY_NAMES) == 56 and len(set(CATEGORY_NAMES)) == 56

KANNADA = "Kannada"

# Extra guidance for the AI prompt where the name alone is ambiguous.
CATEGORY_GUIDANCE = {
    "Formula": "Formula 1 motor racing: history, rules, circuits, teams and drivers (settled historical facts only).",
    "IPL": "Indian Premier League cricket: past seasons, rules, records that are settled history.",
    "Mountains & Rivers (India Only)": "Mountains, ranges, rivers, lakes and dams located in India only.",
    "Space (Astronomy)": "Astronomy and space exploration.",
    "Funny Questions": "Light-hearted wordplay or humorous questions that still have exactly one clearly correct answer.",
    "Crazy Facts": "Surprising but well-established, verifiable facts.",
    "Trick Questions": "Riddle-style questions with a clever but unambiguous answer.",
    "Brain Teasers": "Logic and lateral-thinking teasers with one unambiguous answer.",
    "Law & Constitution": "The Constitution of India and basic legal concepts.",
    "Indian History": "History of the Indian subcontinent.",
    "General Trivia": "Mixed everyday trivia.",
    "Languages": "World languages, scripts, linguistics and Indian languages.",
}


def slugify(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def language_for(name: str) -> str:
    return "kn" if name == KANNADA else "en"
