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


# Display emoji for each category (used on the Profile page).
CATEGORY_EMOJI = {
    "History": "\U0001F3DB\uFE0F", "Math": "\u2797", "Science": "\U0001F52C", "Space (Astronomy)": "\U0001F680",
    "Kannada": "\U0001F5E3\uFE0F", "English": "\U0001F520", "Social Science": "\U0001F30D", "Software": "\U0001F4BB",
    "Hardware": "\U0001F5A5\uFE0F", "Artificial Intelligence (AI)": "\U0001F916", "Machine Learning (ML)": "\U0001F4C8",
    "General Knowledge (GK)": "\U0001F4A1", "Aptitude": "\U0001F4D0", "Web Development": "\U0001F578\uFE0F",
    "Puzzles": "\U0001F9E9", "Chess": "\u265F\uFE0F", "Cricket": "\U0001F3CF", "Health & Human Body": "\U0001FAC0",
    "Olympics": "\U0001F947", "Formula": "\U0001F3CE\uFE0F", "IPL": "\U0001F3C6", "Operating Systems": "\U0001FA9F",
    "Python": "\U0001F40D", "Java": "\u2615", "Algorithms & Data Structures": "\u2699\uFE0F",
    "Computer Basics": "\u2328\uFE0F", "Animals": "\U0001F43E", "Birds": "\U0001F426", "Plants": "\U0001F331",
    "General Trivia": "\u2753", "Oceans & Marine Life": "\U0001F40B", "Mountains & Rivers (India Only)": "\U0001F3D4\uFE0F",
    "Travel & Tourism": "\u2708\uFE0F", "Countries & Capitals": "\U0001F5FA\uFE0F", "Board Games": "\U0001F3B2",
    "Number Puzzles": "\U0001F522", "Languages": "\U0001F4AC", "Famous People": "\U0001F31F", "Mobile & Apps": "\U0001F4F1",
    "Brain Teasers": "\U0001F9E0", "Mental Math": "\U0001F9EE", "Cinema": "\U0001F3AC", "Photography": "\U0001F4F7",
    "UI/UX Design": "\U0001F3A8", "HTML": "\U0001F4C4", "CSS": "\U0001F58C\uFE0F", "Scientists": "\U0001F469\u200D\U0001F52C",
    "Law & Constitution": "\u2696\uFE0F", "Indian History": "\U0001F3EF", "World History": "\U0001F3FA",
    "Environment": "\U0001F333", "Technology": "\U0001F6E0\uFE0F", "Logical Reasoning": "\U0001F50D",
    "Funny Questions": "\U0001F602", "Crazy Facts": "\U0001F92F", "Trick Questions": "\U0001F3AD",
}
assert set(CATEGORY_EMOJI) == set(CATEGORY_NAMES)
