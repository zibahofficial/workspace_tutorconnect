"""
Database seeding.

Creates the subject vocabulary, a bootstrap administrator, a realistic set of
demo tutors (with availability), students, booking requests in every lifecycle
state, reviews and favourites — so the platform can be demonstrated the moment
it starts.  All of it is real data written through the ORM.

Idempotent: it refuses to run twice unless `force=True`.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import hash_password
from config import settings
from models import (
    DAYS_OF_WEEK,
    DAY_INDEX,
    ActivityAction,
    ActivityLog,
    Availability,
    AvailabilityException,
    BookingRequest,
    Favorite,
    Notification,
    NotificationType,
    RequestStatus,
    Review,
    StudentProfile,
    Subject,
    TeachingMode,
    TutorProfile,
    TutorStatus,
    TutorSubject,
    User,
    UserRole,
)

random.seed(20260930)

SEED_MARKER_EMAIL = "admin@example.com"

# A private, inactive Subject row acts as the "demo data installed" flag. It does
# not depend on ADMIN_EMAIL, so changing the admin address can never cause the
# seeder to run twice and duplicate bookings/reviews.
SEED_MARKER_SUBJECT = "__tutorconnect_seeded__"

UNSPLASH = "https://images.unsplash.com/{photo}?auto=format&fit=crop&w={w}&q=80"


def img(photo: str, width: int = 1200) -> str:
    return UNSPLASH.format(photo=photo, w=width)


SUBJECTS: List[Tuple[str, str, str]] = [
    ("Mathematics", "STEM", "bi-calculator"),
    ("English Language", "Languages", "bi-book"),
    ("Further Mathematics", "STEM", "bi-plus-slash-minus"),
    ("Physics", "STEM", "bi-lightning-charge"),
    ("Chemistry", "STEM", "bi-droplet-half"),
    ("Biology", "STEM", "bi-bug"),
    ("Computer Science", "Technology", "bi-laptop"),
    ("Data Analysis", "Technology", "bi-bar-chart-line"),
    ("Web Development", "Technology", "bi-globe"),
    ("Economics", "Business", "bi-graph-up-arrow"),
    ("Accounting", "Business", "bi-receipt"),
    ("Financial Accounting", "Business", "bi-cash-stack"),
    ("Business Studies", "Business", "bi-briefcase"),
    ("Government", "Humanities", "bi-bank"),
    ("Literature in English", "Humanities", "bi-pen"),
    ("Christian Religious Studies", "Humanities", "bi-journal-bookmark"),
    ("Geography", "Humanities", "bi-geo-alt"),
    ("History", "Humanities", "bi-hourglass-split"),
    ("French", "Languages", "bi-translate"),
    ("Yoruba", "Languages", "bi-chat-dots"),
    ("Igbo", "Languages", "bi-chat-dots"),
    ("Hausa", "Languages", "bi-chat-dots"),
    ("Music", "Arts", "bi-music-note-beamed"),
    ("Fine Art", "Arts", "bi-palette"),
    ("Agricultural Science", "STEM", "bi-flower1"),
    ("Civic Education", "Humanities", "bi-people"),
    ("Phonics & Reading", "Primary", "bi-alphabet"),
    ("Verbal & Quantitative Reasoning", "Primary", "bi-lightbulb"),
    ("IELTS Preparation", "Test Prep", "bi-airplane"),
    ("JAMB / UTME Coaching", "Test Prep", "bi-bullseye"),
    ("WAEC & NECO Prep", "Test Prep", "bi-pencil-square"),
    ("Public Speaking", "Life Skills", "bi-mic"),
]

TUTORS: List[Dict] = [
    dict(
        name="Chinedu Okafor", email="chinedu.okafor@example.com", password="TutorDemo123",
        headline="Mathematics & Further Mathematics Tutor (WAEC, NECO, JAMB)",
        bio=("I have spent the last eight years helping secondary-school students fall in love with "
             "Mathematics. My lessons are built around past-question drills, clear step-by-step "
             "workings and weekly progress checks so parents always know where their child stands. "
             "Over 200 students have improved by at least two grades under my coaching."),
        years=8, rate=6500, city="Yaba", state="Lagos State",
        mode=TeachingMode.HYBRID, subjects=["Mathematics", "Further Mathematics", "JAMB / UTME Coaching", "Physics"],
        quals="B.Sc. Mathematics (First Class), University of Lagos; PGDE, NCE certified",
        languages="English, Igbo, Yoruba",
        avatar="https://images.unsplash.com/photo-1531384441138-2736e62e0919?auto=format&fit=crop&w=400&h=400&q=80",
        cover="https://images.pexels.com/photos/5905923/pexels-photo-5905923.jpeg?auto=compress&cs=tinysrgb&w=900&h=420&fit=crop", verified=True, session=60,
        slots=[("Monday", "16:00", "19:00"), ("Wednesday", "16:00", "19:00"),
               ("Friday", "17:00", "20:00"), ("Saturday", "10:00", "14:00")],
    ),
    dict(
        name="Aisha Bello", email="aisha.bello@example.com", password="TutorDemo123",
        headline="Chemistry & Biology Tutor for Senior Secondary Students",
        bio=("Medicine graduate and part-time tutor in Abuja. I break down abstract chemistry "
             "concepts with practical examples, diagrams and mini-experiments you can do at home. "
             "I also prepare students for WAEC, NECO and post-UTME science papers with timed "
             "practice and detailed feedback after every session."),
        years=5, rate=5500, city="Wuse", state="FCT Abuja",
        mode=TeachingMode.HYBRID, subjects=["Chemistry", "Biology", "WAEC & NECO Prep"],
        quals="MBBS, University of Abuja; WAEC examiner (2022-2024)",
        languages="English, Hausa",
        avatar="https://images.unsplash.com/photo-1589156280159-27698a70f29e?auto=format&fit=crop&w=400&h=400&q=80",
        cover=img("photo-1532094349884-543bc11b234d"), verified=True, session=60,
        slots=[("Tuesday", "15:00", "18:00"), ("Thursday", "15:00", "18:00"),
               ("Saturday", "09:00", "13:00")],
    ),
    dict(
        name="Tunde Bakare", email="tunde.bakare@example.com", password="TutorDemo123",
        headline="Computer Science, Web Development & Data Analysis Mentor",
        bio=("Software engineer with a decade of industry experience, now teaching the next "
             "generation of Nigerian developers. My curriculum covers Python, SQL, HTML/CSS and "
             "JavaScript through real projects - you will ship a working website and a data "
             "dashboard before the eighth week. Great for students preparing for tech scholarships."),
        years=10, rate=9000, city="Ikeja", state="Lagos State",
        mode=TeachingMode.ONLINE, subjects=["Computer Science", "Web Development", "Data Analysis", "Mathematics"],
        quals="B.Eng Computer Engineering, OAU Ile-Ife; AWS Certified Developer",
        languages="English, Yoruba",
        avatar="https://images.unsplash.com/photo-1521119989659-a83eee488004?auto=format&fit=crop&w=400&h=400&q=80",
        cover=img("photo-1517694712202-14dd9538aa97"), verified=True, session=90,
        slots=[("Monday", "18:00", "21:00"), ("Wednesday", "18:00", "21:00"),
               ("Saturday", "10:00", "14:00"), ("Sunday", "16:00", "19:00")],
    ),
    dict(
        name="Ngozi Eze", email="ngozi.eze@example.com", password="TutorDemo123",
        headline="English Language, Literature & Phonics specialist",
        bio=("I teach reading, writing and spoken English to primary and junior-secondary pupils "
             "in Enugu. Sessions blend phonics drills, comprehension practice and creative writing "
             "so learners gain confidence quickly. I send parents a short voice note after every "
             "lesson summarising what was covered and what to practise at home."),
        years=6, rate=4500, city="Enugu", state="Enugu State",
        mode=TeachingMode.IN_PERSON, subjects=["English Language", "Literature in English", "Phonics & Reading"],
        quals="B.A. English & Literary Studies, UNN; Certificate in Early Years Phonics",
        languages="English, Igbo",
        avatar="https://images.unsplash.com/photo-1611432579699-484f7990b127?auto=format&fit=crop&w=400&h=400&q=80",
        cover=img("photo-1456513080510-7bf3a84b82f8"), verified=True, session=60,
        slots=[("Monday", "15:00", "18:00"), ("Tuesday", "15:00", "18:00"),
               ("Thursday", "15:00", "18:00"), ("Saturday", "09:00", "12:00")],
    ),
    dict(
        name="Ibrahim Musa", email="ibrahim.musa@example.com", password="TutorDemo123",
        headline="Physics & Mathematics Tutor (problem-solving focused)",
        bio=("Physics graduate from ABU Zaria with seven years of tutoring experience across Kano "
             "and online. I focus on exam technique: how to read a question, choose the right "
             "formula and present full working for maximum marks. My students consistently record "
             "A1-B3 in WAEC Physics."),
        years=7, rate=5000, city="Kano", state="Kano State",
        mode=TeachingMode.HYBRID, subjects=["Physics", "Mathematics", "Further Mathematics"],
        quals="B.Sc. Physics, Ahmadu Bello University; TRCN registered",
        languages="English, Hausa",
        avatar="https://images.pexels.com/photos/13801809/pexels-photo-13801809.jpeg?auto=compress&cs=tinysrgb&w=400&h=400&fit=crop",
        cover=img("photo-1636466497217-26a8cbeaf0aa"), verified=False, session=60,
        slots=[("Sunday", "14:00", "18:00"), ("Monday", "17:00", "20:00"),
               ("Wednesday", "17:00", "20:00"), ("Saturday", "08:00", "12:00")],
    ),
    dict(
        name="Folake Adeyemi", email="folake.adeyemi@example.com", password="TutorDemo123",
        headline="Economics, Financial Accounting & Commerce Tutor",
        bio=("Chartered accountant turned educator, based in Lekki, Lagos. I teach Economics and "
             "Financial Accounting with real Nigerian case studies - from Dangote's statements to "
             "CBN policy changes - so theory finally makes sense. Ideal for SS2/SS3 students and "
             "ICAN foundation candidates."),
        years=4, rate=8000, city="Lekki", state="Lagos State",
        mode=TeachingMode.ONLINE, subjects=["Economics", "Financial Accounting", "Accounting", "Business Studies"],
        quals="B.Sc. Accounting (Unilag); ICAN Associate; CFA Level I passed",
        languages="English, Yoruba",
        avatar="https://images.pexels.com/photos/5905754/pexels-photo-5905754.jpeg?auto=compress&cs=tinysrgb&w=400&h=400&fit=crop",
        cover="https://images.pexels.com/photos/12497063/pexels-photo-12497063.jpeg?auto=compress&cs=tinysrgb&w=900&h=420&fit=crop", verified=True, session=60,
        slots=[("Tuesday", "18:00", "21:00"), ("Thursday", "18:00", "21:00"),
               ("Saturday", "11:00", "14:00")],
    ),
    dict(
        name="Emeka Nwosu", email="emeka.nwosu@example.com", password="TutorDemo123",
        headline="Biology & Agricultural Science Tutor in Asaba",
        bio=("I make Biology practical. Field notes, labelled diagrams and specimen work help my "
             "students remember what they learn instead of cramming. Nine years of experience with "
             "day and boarding schools across Delta State, plus online classes for students "
             "abroad."),
        years=9, rate=4000, city="Asaba", state="Delta State",
        mode=TeachingMode.IN_PERSON, subjects=["Biology", "Agricultural Science", "Chemistry"],
        quals="B.Sc. Biology (Delta State University); NCE Biology/Chemistry",
        languages="English, Igbo",
        avatar="https://images.unsplash.com/photo-1560787313-5dff3307e257?auto=format&fit=crop&w=400&h=400&q=80",
        cover=img("photo-1530026186672-2cd00ffc50fe"), verified=False, session=60,
        slots=[("Monday", "16:00", "19:00"), ("Wednesday", "16:00", "19:00"),
               ("Saturday", "10:00", "15:00")],
    ),
    dict(
        name="Zainab Yusuf", email="zainab.yusuf@example.com", password="TutorDemo123",
        headline="Primary tutor: Phonics, Reasoning & Homework support",
        bio=("Patient, playful and structured - that is how I describe my teaching. I work with "
             "pupils from Nursery to Primary 6 in Kaduna, covering phonics, verbal and quantitative "
             "reasoning, handwriting and daily homework support. Parents receive a weekly progress "
             "sheet."),
        years=3, rate=3000, city="Kaduna", state="Kaduna State",
        mode=TeachingMode.IN_PERSON, subjects=["Phonics & Reading", "Verbal & Quantitative Reasoning", "Mathematics"],
        quals="NCE Primary Education; Montessori diploma",
        languages="English, Hausa",
        avatar="https://images.unsplash.com/photo-1523824921871-d6f1a15151f1?auto=format&fit=crop&w=400&h=400&q=80",
        cover=img("photo-1503676260728-1c00da094a0b"), verified=False, session=45,
        slots=[("Monday", "14:00", "17:00"), ("Tuesday", "14:00", "17:00"),
               ("Wednesday", "14:00", "17:00"), ("Thursday", "14:00", "17:00")],
    ),
    dict(
        name="Samuel Eze", email="samuel.eze@example.com", password="TutorDemo123",
        headline="Government, CRS & History Tutor (Port-Harcourt)",
        bio=("Twelve years preparing students for Government, Christian Religious Studies and "
             "History examinations. I use current affairs, debate formats and structured essay "
             "templates so students can answer any theory question with confidence and evidence."),
        years=12, rate=4800, city="Port Harcourt", state="Rivers State",
        mode=TeachingMode.HYBRID, subjects=["Government", "Christian Religious Studies", "History", "Civic Education"],
        quals="B.A. History & International Studies, UNIPORT; M.Ed. in progress",
        languages="English, Igbo",
        avatar="https://images.pexels.com/photos/9222199/pexels-photo-9222199.jpeg?auto=compress&cs=tinysrgb&w=400&h=400&fit=crop",
        cover="https://images.pexels.com/photos/6146981/pexels-photo-6146981.jpeg?auto=compress&cs=tinysrgb&w=900&h=420&fit=crop", verified=True, session=60,
        slots=[("Tuesday", "16:00", "19:00"), ("Friday", "16:00", "19:00"),
               ("Saturday", "09:00", "13:00")],
    ),
    dict(
        name="Grace Danjuma", email="grace.danjuma@example.com", password="TutorDemo123",
        headline="French & IELTS Preparation Coach (Jos / Online)",
        bio=("Bilingual coach with DELF B2 certification and six years of IELTS preparation "
             "experience. My students average band 7.0 after eight weeks of structured speaking, "
             "listening, reading and writing practice with mock tests marked to examiner standard."),
        years=6, rate=7000, city="Jos", state="Plateau State",
        mode=TeachingMode.ONLINE, subjects=["French", "IELTS Preparation", "English Language"],
        quals="B.A. French, University of Jos; DELF B2; TEFL certified",
        languages="English, French",
        avatar="https://images.unsplash.com/photo-1531123897727-8f129e1688ce?auto=format&fit=crop&w=400&h=400&q=80",
        cover=img("photo-1546410531-bb4caa6b424d"), verified=True, session=60,
        slots=[("Monday", "17:00", "20:00"), ("Wednesday", "17:00", "20:00"),
               ("Friday", "17:00", "20:00"), ("Sunday", "15:00", "18:00")],
    ),
    dict(
        name="Bola Ogundipe", email="bola.ogundipe@example.com", password="TutorDemo123",
        headline="Music Theory & Piano Tutor (Ibadan)",
        bio=("ABRSM Grade 8 pianist teaching theory, sight-reading and practical piano in Ibadan. "
             "Lessons are tailored to each learner - whether you are preparing for a grade exam or "
             "simply want to play your favourite songs with correct technique."),
        years=5, rate=5200, city="Ibadan", state="Oyo State",
        mode=TeachingMode.IN_PERSON, subjects=["Music", "Fine Art"],
        quals="ABRSM Grade 8 (Piano & Theory); B.A. Music, University of Ibadan",
        languages="English, Yoruba",
        avatar="https://images.pexels.com/photos/8052215/pexels-photo-8052215.jpeg?auto=compress&cs=tinysrgb&w=400&h=400&fit=crop",
        cover=img("photo-1514119412350-e174d90d280e"), verified=False, session=45,
        slots=[("Tuesday", "15:00", "18:00"), ("Thursday", "15:00", "18:00"),
               ("Saturday", "10:00", "13:00")],
    ),
    dict(
        name="Ahmed Suleiman", email="ahmed.suleiman@example.com", password="TutorDemo123",
        headline="Mathematics & Science tutor for JAMB/WAEC candidates",
        bio=("Focused exam coach in Sokoto. I run intensive small-group and one-on-one programmes "
             "for JAMB and WAEC candidates, with weekly mock exams, error logs and a personal "
             "study plan for every student. Pending final profile verification by the platform."),
        years=2, rate=3500, city="Sokoto", state="Sokoto State",
        mode=TeachingMode.HYBRID, subjects=["Mathematics", "Physics", "Chemistry", "JAMB / UTME Coaching"],
        quals="B.Sc. Mathematics Education, UDUS; awaiting TRCN certification",
        languages="English, Hausa",
        avatar="https://images.unsplash.com/photo-1519345182560-3f2917c472ef?auto=format&fit=crop&w=400&h=400&q=80",
        cover=img("photo-1427504494785-3a9ca7044f45"), verified=False, session=60,
        approval=TutorStatus.PENDING,
        slots=[("Monday", "16:00", "19:00"), ("Thursday", "16:00", "19:00")],
    ),
]

STUDENTS: List[Dict] = [
    dict(name="Chiamaka Obi", email="chiamaka@example.com", password="StudentDemo123",
         city="Surulere", state="Lagos State", level="SS3 (Senior Secondary 3)",
         goals="Score A1 in WAEC Mathematics and pass JAMB with 300+.",
         avatar="https://randomuser.me/api/portraits/women/21.jpg", budget=8000),
    dict(name="Musa Abdullahi", email="musa@example.com", password="StudentDemo123",
         city="Wuse", state="FCT Abuja", level="SS2 (Senior Secondary 2)",
         goals="Improve Chemistry and Biology grades before the promotion exam.",
         avatar="https://randomuser.me/api/portraits/men/15.jpg", budget=7000),
    dict(name="Mrs. Adaeze Nwankwo", email="adaeze@example.com", password="StudentDemo123",
         city="Enugu", state="Enugu State", level="Parent of Primary 4 pupil",
         goals="Build a strong reading foundation for my daughter.",
         guardian=True,
         avatar="https://randomuser.me/api/portraits/women/57.jpg", budget=6000),
    dict(name="Tobi Alabi", email="tobi@example.com", password="StudentDemo123",
         city="Ikeja", state="Lagos State", level="University undergraduate (200L)",
         goals="Learn Python and SQL for a data-analysis internship.",
         avatar="https://randomuser.me/api/portraits/men/36.jpg", budget=12000),
    dict(name="Halima Sani", email="halima@example.com", password="StudentDemo123",
         city="Kaduna", state="Kaduna State", level="JSS3 (Junior Secondary 3)",
         goals="Prepare for the BECE and build confidence in Mathematics.",
         avatar="https://randomuser.me/api/portraits/women/30.jpg", budget=5000),
    dict(name="Dr. Peter Okon", email="peter@example.com", password="StudentDemo123",
         city="Lekki", state="Lagos State", level="Parent of two children (JSS1 & SS1)",
         goals="Consistent after-school support in Economics and English.",
         guardian=True,
         avatar="https://randomuser.me/api/portraits/men/58.jpg", budget=15000),
]

REVIEWS_SEED: List[Dict] = [
    dict(rating=5, title="Transformed my WAEC preparation",
         comment=("Mr Okafor explains every topic from first principles and gives past questions "
                  "after each class. I moved from a C5 in mock exams to an A1 in WAEC. He also "
                  "sends my mum a progress note every week, which we really appreciate.")),
    dict(rating=5, title="Patient, structured and very effective",
         comment=("Sessions always start on time and follow a clear plan. My daughter now reads "
                  "fluently and actually enjoys her homework. Highly recommended for primary "
                  "pupils who need a gentle but firm teacher.")),
    dict(rating=4, title="Great content, would love more practice tests",
         comment=("Very strong explanations and real industry examples that made Accounting click "
                  "for me. I would have loved one extra timed practice paper each month, but "
                  "overall an excellent tutor.")),
    dict(rating=5, title="Best chemistry tutor in Abuja",
         comment=("Dr Bello makes organic chemistry feel simple. She uses everyday examples and "
                  "always checks that I truly understand before moving on. My grade went from C4 "
                  "to A1 in one term.")),
    dict(rating=4, title="Reliable and knowledgeable",
         comment=("Consistent, well-prepared lessons and very responsive on WhatsApp. My son's "
                  "Physics score improved significantly. Scheduling around exam week was a little "
                  "tight but we managed.")),
    dict(rating=5, title="From zero to building real projects",
         comment=("Tunde taught me Python, SQL and basic front-end in twelve weeks. I built a "
                  "dashboard for my final-year project and landed an internship. Worth every naira.")),
    dict(rating=3, title="Good, but sessions started late twice",
         comment=("The teaching itself is solid and my brother understands Government much better "
                  "now. However two sessions started about 20 minutes late, which shortened the "
                  "class. Communication was otherwise fine.")),
    dict(rating=5, title="IELTS band 7.5 in eight weeks",
         comment=("Grace's mock speaking tests were exactly like the real exam. Her feedback on "
                  "essays was detailed and honest. I got band 7.5 overall and 8.0 in listening.")),
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _next_weekday(from_date: date, weekday: int, min_offset: int = 1) -> date:
    """First date >= from_date + min_offset whose weekday() matches."""
    candidate = from_date + timedelta(days=min_offset)
    for _ in range(14):
        if candidate.weekday() == weekday:
            return candidate
        candidate += timedelta(days=1)
    return candidate


def _previous_weekday(from_date: date, weekday: int, min_offset: int = 7) -> date:
    candidate = from_date - timedelta(days=min_offset)
    for _ in range(14):
        if candidate.weekday() == weekday:
            return candidate
        candidate -= timedelta(days=1)
    return candidate


# --------------------------------------------------------------------------- #
# Main seeder
# --------------------------------------------------------------------------- #
def _seed_marker(db: Session) -> Optional[Subject]:
    """The private flag row that records 'demo data has been installed'."""
    return db.scalar(select(Subject).where(Subject.name == SEED_MARKER_SUBJECT))


def seed_database(db: Session, *, force: bool = False, verbose: bool = True) -> Dict[str, int]:
    """Idempotently install the subject vocabulary + demo dataset."""
    marker = _seed_marker(db)
    has_rows = (db.scalar(select(func.count(User.id))) or 0) > 0

    if (marker is not None or has_rows) and not force:
        if verbose:
            print("[seed] Database already contains data - skipping.")
        return {}

    if force and (marker is not None or has_rows):
        if verbose:
            print("[seed] force=True -> wiping existing rows first.")
        _wipe(db)

    created = {
        "subjects": 0, "admins": 0, "tutors": 0, "students": 0,
        "availability": 0, "requests": 0, "reviews": 0, "favorites": 0,
    }

    # ---- subjects --------------------------------------------------------
    subject_map: Dict[str, Subject] = {}
    for name, category, icon in SUBJECTS:
        existing = db.scalar(select(Subject).where(Subject.name == name))
        if existing is None:
            existing = Subject(name=name, category=category, icon=icon, is_active=True)
            db.add(existing)
            db.flush()
            created["subjects"] += 1
        subject_map[name] = existing

    # ---- administrators --------------------------------------------------
    admin_email = normalize(settings.admin_email) or SEED_MARKER_EMAIL
    admin_password = settings.admin_password or "AdminDemo123"
    admin = db.scalar(select(User).where(User.email == admin_email))
    if admin is None:
        admin = User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            full_name=settings.admin_name or "Platform Administrator",
            role=UserRole.ADMIN,
            is_active=True,
            avatar_url="https://randomuser.me/api/portraits/women/90.jpg",
            phone="+234 800 000 0001",
        )
        db.add(admin)
        db.flush()
        created["admins"] += 1

    # ---- tutors ----------------------------------------------------------
    tutor_profiles: Dict[str, TutorProfile] = {}
    for data in TUTORS:
        email = normalize(data["email"])
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(data["password"]),
                full_name=data["name"],
                role=UserRole.TUTOR,
                is_active=True,
                avatar_url=data["avatar"],
                phone=f"+234 80{random.randint(10000000, 99999999)}",
                last_login_at=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 6)),
            )
            db.add(user)
            db.flush()
            created["tutors"] += 1

        approval = data.get("approval", TutorStatus.APPROVED)
        profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == user.id))
        if profile is None:
            profile = TutorProfile(
                user_id=user.id,
                headline=data["headline"],
                bio=data["bio"],
                years_experience=data["years"],
                hourly_rate=data["rate"],
                session_duration_minutes=data.get("session", 60),
                city=data["city"],
                state=data["state"],
                country="Nigeria",
                teaching_mode=data["mode"],
                qualifications=data["quals"],
                languages=data["languages"],
                cover_image_url=data["cover"],
                accepts_online=data["mode"] in (TeachingMode.ONLINE, TeachingMode.HYBRID),
                accepts_in_person=data["mode"] in (TeachingMode.IN_PERSON, TeachingMode.HYBRID),
                is_visible=approval == TutorStatus.APPROVED,
                approval_status=approval,
                verified=data.get("verified", False),
            )
            db.add(profile)
            db.flush()

        for subject_name in data["subjects"]:
            subject = subject_map.get(subject_name)
            if subject is None:
                continue
            link = db.scalar(
                select(TutorSubject).where(
                    TutorSubject.tutor_profile_id == profile.id,
                    TutorSubject.subject_id == subject.id,
                )
            )
            if link is None:
                db.add(
                    TutorSubject(
                        tutor_profile_id=profile.id,
                        subject_id=subject.id,
                        proficiency="Expert" if data["years"] >= 6 else "Advanced",
                        levels="Primary, Junior Secondary, Senior Secondary",
                    )
                )

        for day, start, end in data["slots"]:
            exists = db.scalar(
                select(Availability).where(
                    Availability.tutor_profile_id == profile.id,
                    Availability.day_of_week == day,
                    Availability.start_time == _parse_time(start),
                )
            )
            if exists is None:
                db.add(
                    Availability(
                        tutor_profile_id=profile.id,
                        day_of_week=day,
                        day_index=DAY_INDEX[day],
                        start_time=_parse_time(start),
                        end_time=_parse_time(end),
                        mode=data["mode"],
                        is_active=True,
                    )
                )
                created["availability"] += 1

        tutor_profiles[data["name"]] = profile

    db.flush()

    # ---- students --------------------------------------------------------
    student_profiles: Dict[str, StudentProfile] = {}
    for data in STUDENTS:
        email = normalize(data["email"])
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(data["password"]),
                full_name=data["name"],
                role=UserRole.STUDENT,
                is_active=True,
                avatar_url=data["avatar"],
                phone=f"+234 70{random.randint(10000000, 99999999)}",
                last_login_at=datetime.now(timezone.utc) - timedelta(days=random.randint(0, 10)),
            )
            db.add(user)
            db.flush()
            created["students"] += 1

        profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
        if profile is None:
            profile = StudentProfile(
                user_id=user.id,
                education_level=data["level"],
                guardian_name=data["name"] if data.get("guardian") else None,
                city=data["city"],
                state=data["state"],
                learning_goals=data["goals"],
                preferred_mode=TeachingMode.HYBRID,
                max_budget=data["budget"],
            )
            db.add(profile)
            db.flush()
        student_profiles[data["name"]] = profile

    db.flush()

    # ---- booking requests across every status ----------------------------
    requests_created = _seed_requests(db, tutor_profiles, student_profiles, subject_map)
    created["requests"] = requests_created

    # ---- reviews on completed sessions -----------------------------------
    created["reviews"] = _seed_reviews(db)

    # ---- favourites -------------------------------------------------------
    created["favorites"] = _seed_favorites(db, student_profiles, tutor_profiles)

    # ---- activity log ------------------------------------------------------
    if not db.scalar(select(func.count(ActivityLog.id))):
        entries = [
            (ActivityAction.USER_REGISTERED, "Demo tutors and students onboarded", admin.id),
            (ActivityAction.TUTOR_APPROVED, f"{len(tutor_profiles) - 1} tutor profiles approved by admin", admin.id),
            (ActivityAction.AVAILABILITY_ADDED, f"{created['availability']} weekly availability slots published", admin.id),
            (ActivityAction.REQUEST_CREATED, f"{created['requests']} booking requests recorded", admin.id),
            (ActivityAction.REVIEW_CREATED, f"{created['reviews']} reviews published", admin.id),
        ]
        for action, description, actor in entries:
            db.add(ActivityLog(actor_user_id=actor, action=action, description=description))

    # marker row - inactive, so it never shows in search or the UI
    if _seed_marker(db) is None:
        db.add(
            Subject(name=SEED_MARKER_SUBJECT, category="system", icon=None, is_active=False)
        )
    db.flush()

    if verbose:
        print("[seed] Created: " + ", ".join(f"{k}={v}" for k, v in created.items()))
    return created


def _seed_requests(
    db: Session,
    tutor_profiles: Dict[str, TutorProfile],
    student_profiles: Dict[str, StudentProfile],
    subject_map: Dict[str, Subject],
) -> int:
    """Create requests in every lifecycle state, respecting real availability."""
    today = date.today()
    plan = [
        # (student, tutor, subject, status, when)
        ("Chiamaka Obi", "Chinedu Okafor", "Mathematics", RequestStatus.PENDING, "future"),
        ("Halima Sani", "Zainab Yusuf", "Phonics & Reading", RequestStatus.PENDING, "future"),
        ("Tobi Alabi", "Tunde Bakare", "Web Development", RequestStatus.PENDING, "future"),
        ("Mrs. Adaeze Nwankwo", "Samuel Eze", "Government", RequestStatus.PENDING, "future"),
        ("Dr. Peter Okon", "Folake Adeyemi", "Economics", RequestStatus.ACCEPTED, "future"),
        ("Musa Abdullahi", "Aisha Bello", "Chemistry", RequestStatus.ACCEPTED, "future"),
        ("Chiamaka Obi", "Grace Danjuma", "IELTS Preparation", RequestStatus.ACCEPTED, "future"),
        ("Tobi Alabi", "Chinedu Okafor", "Further Mathematics", RequestStatus.ACCEPTED, "soon"),
        ("Halima Sani", "Ibrahim Musa", "Physics", RequestStatus.COMPLETED, "past"),
        ("Chiamaka Obi", "Emeka Nwosu", "Biology", RequestStatus.COMPLETED, "past"),
        ("Musa Abdullahi", "Ngozi Eze", "English Language", RequestStatus.COMPLETED, "past"),
        ("Tobi Alabi", "Folake Adeyemi", "Financial Accounting", RequestStatus.COMPLETED, "past"),
        ("Dr. Peter Okon", "Grace Danjuma", "French", RequestStatus.COMPLETED, "past"),
        ("Mrs. Adaeze Nwankwo", "Bola Ogundipe", "Music", RequestStatus.COMPLETED, "past"),
        ("Halima Sani", "Chinedu Okafor", "Mathematics", RequestStatus.REJECTED, "past"),
        ("Tobi Alabi", "Ibrahim Musa", "Physics", RequestStatus.CANCELLED, "past"),
    ]

    messages = {
        RequestStatus.PENDING: (
            "Hello, I would like to book regular sessions with you. Please let me know if this "
            "time still works and whether you can share a study plan beforehand."
        ),
        RequestStatus.ACCEPTED: (
            "Thank you for accepting! I will arrive ten minutes early with my notebook and the "
            "textbook we agreed on."
        ),
        RequestStatus.COMPLETED: (
            "Looking forward to consolidating what we covered last term before the exams start."
        ),
        RequestStatus.REJECTED: (
            "I need extra help with the topics we struggle with most ahead of the exams."
        ),
        RequestStatus.CANCELLED: (
            "Requesting a weekend session to prepare for the upcoming test."
        ),
    }

    created = 0
    for student_name, tutor_name, subject_name, request_status, when in plan:
        student = student_profiles.get(student_name)
        tutor = tutor_profiles.get(tutor_name)
        subject = subject_map.get(subject_name)
        if student is None or tutor is None or subject is None:
            continue

        slots = [s for s in tutor.availability if s.is_active]
        if not slots:
            continue

        if when == "past":
            slot = random.choice(slots)
            target = _previous_weekday(today, slot.day_index, min_offset=random.randint(10, 40))
        elif when == "soon":
            slot = random.choice(slots)
            target = _next_weekday(today, slot.day_index, min_offset=random.randint(1, 4))
        else:
            slot = random.choice(slots)
            target = _next_weekday(today, slot.day_index, min_offset=random.randint(2, 21))

        duration = tutor.session_duration_minutes
        start_minutes = slot.start_time.hour * 60 + slot.start_time.minute
        latest = slot.end_time.hour * 60 + slot.end_time.minute - duration
        start_minutes = random.randint(start_minutes, max(start_minutes, latest))
        start_time = time(start_minutes // 60, start_minutes % 60)

        exists = db.scalar(
            select(BookingRequest).where(
                BookingRequest.tutor_profile_id == tutor.id,
                BookingRequest.student_id == student.id,
                BookingRequest.subject_id == subject.id,
                BookingRequest.preferred_date == target,
                BookingRequest.preferred_time == start_time,
            )
        )
        if exists is not None:
            continue

        budget = float(tutor.hourly_rate) * (duration / 60.0)
        request = BookingRequest(
            tutor_profile_id=tutor.id,
            student_id=student.id,
            subject_id=subject.id,
            status=request_status,
            preferred_date=target,
            preferred_time=start_time,
            duration_minutes=duration,
            mode=slot.mode,
            budget=round(budget, 2),
            message=messages[request_status],
            location_note=(
                "Online via Google Meet"
                if slot.mode == TeachingMode.ONLINE
                else f"{student.city}, {student.state}"
            ),
        )
        if request_status in (RequestStatus.ACCEPTED, RequestStatus.REJECTED):
            request.responded_at = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 5))
            request.read_by_student = True
        if request_status == RequestStatus.ACCEPTED:
            request.tutor_response_note = (
                "Confirmed. Please come with your last test script so we can target weak areas."
            )
        if request_status == RequestStatus.COMPLETED:
            request.completed_at = datetime.combine(target, start_time, tzinfo=timezone.utc)
            request.responded_at = datetime.combine(target - timedelta(days=2), time(9, 0), tzinfo=timezone.utc)
            request.tutor_response_note = "Looking forward to our session!"
            request.read_by_student = True
            request.read_by_tutor = True
        if request_status == RequestStatus.REJECTED:
            request.tutor_response_note = (
                "Sorry, my schedule is fully booked this term. I can offer a slot next month."
            )
        if request_status == RequestStatus.CANCELLED:
            request.cancelled_at = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 6))
            request.cancel_reason = "Student rescheduled to a later date."

        db.add(request)
        created += 1

    db.flush()
    return created


def _seed_reviews(db: Session) -> int:
    """Attach reviews to completed bookings, spread across as many tutors as possible.

    Round-robin over tutors rather than over bookings: if the completed sessions
    happen to cluster on one tutor, that tutor would collect every review and the
    rest of the marketplace would show "no reviews yet". Picking the least-reviewed
    tutor each time gives the demo data a realistic rating distribution.
    """
    reviewed_ids = set(db.scalars(select(Review.booking_request_id)).all())
    completed = [
        b
        for b in db.scalars(
            select(BookingRequest)
            .where(BookingRequest.status == RequestStatus.COMPLETED)
            .order_by(BookingRequest.id)
        ).all()
        if b.id not in reviewed_ids
    ]

    per_tutor: Dict[int, int] = {}
    for row in db.execute(select(Review.tutor_profile_id, func.count(Review.id)).group_by(Review.tutor_profile_id)):
        per_tutor[int(row[0])] = int(row[1])

    queue = list(completed)
    chosen: List[BookingRequest] = []
    while queue and len(chosen) < len(REVIEWS_SEED):
        queue.sort(key=lambda b: (per_tutor.get(b.tutor_profile_id, 0), b.id))
        booking = queue.pop(0)
        chosen.append(booking)
        per_tutor[booking.tutor_profile_id] = per_tutor.get(booking.tutor_profile_id, 0) + 1
    # any remaining completed sessions still get a review, cycling the pool
    chosen.extend(queue)

    created = 0
    for index, booking in enumerate(chosen):
        template = REVIEWS_SEED[index % len(REVIEWS_SEED)]
        review = Review(
            tutor_profile_id=booking.tutor_profile_id,
            student_id=booking.student_id,
            booking_request_id=booking.id,
            rating=template["rating"],
            title=template["title"],
            comment=template["comment"],
        )
        db.add(review)
        created += 1

        if created <= 3:
            tutor_user = booking.tutor_profile.user
            db.add(
                Notification(
                    user_id=tutor_user.id,
                    type=NotificationType.REVIEW_NEW,
                    title=f"New {template['rating']}-star review",
                    body=f"{booking.student_profile.user.full_name.split()[0]} reviewed your "
                         f"{booking.subject.name} session.",
                    link="dashboard.html?view=reviews",
                )
            )

    db.flush()
    return created


def _seed_favorites(
    db: Session,
    student_profiles: Dict[str, StudentProfile],
    tutor_profiles: Dict[str, TutorProfile],
) -> int:
    pairs = [
        ("Chiamaka Obi", "Chinedu Okafor"),
        ("Chiamaka Obi", "Grace Danjuma"),
        ("Tobi Alabi", "Tunde Bakare"),
        ("Musa Abdullahi", "Aisha Bello"),
        ("Halima Sani", "Zainab Yusuf"),
        ("Dr. Peter Okon", "Folake Adeyemi"),
    ]
    created = 0
    for student_name, tutor_name in pairs:
        student = student_profiles.get(student_name)
        tutor = tutor_profiles.get(tutor_name)
        if student is None or tutor is None:
            continue
        exists = db.scalar(
            select(Favorite).where(
                Favorite.student_id == student.id, Favorite.tutor_profile_id == tutor.id
            )
        )
        if exists is None:
            db.add(Favorite(student_id=student.id, tutor_profile_id=tutor.id))
            created += 1
    db.flush()
    return created


def _wipe(db: Session) -> None:
    for model in (
        Review, Favorite, Notification, BookingRequest, AvailabilityException,
        Availability, TutorSubject, TutorProfile, StudentProfile, ActivityLog, Subject, User,
    ):
        db.query(model).delete()
    db.commit()


def normalize(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def print_demo_credentials() -> None:
    admin_email = normalize(settings.admin_email) or SEED_MARKER_EMAIL
    admin_password = settings.admin_password or "AdminDemo123"
    line = "=" * 62
    print(line)
    print("  DEMO ACCOUNTS (seeded - change these in production!)")
    print(line)
    print(f"  Admin   : {admin_email} / {admin_password}")
    print("  Tutor   : chinedu.okafor@example.com / TutorDemo123")
    print("  Tutor   : aisha.bello@example.com / TutorDemo123")
    print("  Student : chiamaka@example.com / StudentDemo123")
    print("  Student : tobi@example.com / StudentDemo123")
    print(line)
