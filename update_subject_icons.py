import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tutorconnect.db")

ICONS = {
    "Mathematics": "bi-calculator",
    "English Language": "bi-book",
    "Further Mathematics": "bi-plus-slash-minus",
    "Physics": "bi-lightning-charge",
    "Chemistry": "bi-droplet-half",
    "Biology": "bi-bug",
    "Computer Science": "bi-laptop",
    "Data Analysis": "bi-bar-chart-line",
    "Web Development": "bi-globe",
    "Economics": "bi-graph-up-arrow",
    "Accounting": "bi-receipt",
    "Financial Accounting": "bi-cash-stack",
    "Business Studies": "bi-briefcase",
    "Government": "bi-bank",
    "Literature in English": "bi-pen",
    "Christian Religious Studies": "bi-journal-bookmark",
    "Geography": "bi-geo-alt",
    "History": "bi-hourglass-split",
    "French": "bi-translate",
    "Yoruba": "bi-chat-dots",
    "Igbo": "bi-chat-dots",
    "Hausa": "bi-chat-dots",
    "Music": "bi-music-note-beamed",
    "Fine Art": "bi-palette",
    "Agricultural Science": "bi-flower1",
    "Civic Education": "bi-people",
    "Phonics & Reading": "bi-alphabet",
    "Verbal & Quantitative Reasoning": "bi-lightbulb",
    "IELTS Preparation": "bi-airplane",
    "JAMB / UTME Coaching": "bi-bullseye",
    "WAEC & NECO Prep": "bi-pencil-square",
    "Public Speaking": "bi-mic",
}

if not os.path.exists(DB_PATH):
    raise SystemExit("Database file not found: " + DB_PATH)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
changed = 0
for name, icon in ICONS.items():
    cur.execute("UPDATE subjects SET icon = ? WHERE name = ?", (icon, name))
    changed += cur.rowcount
conn.commit()
conn.close()
print("Subjects updated:", changed, "of", len(ICONS))
