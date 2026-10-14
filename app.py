import streamlit as st
from sarvamai import SarvamAI
import os
import tempfile
import random
import mimetypes
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Prevent audio MIME type errors on Linux servers
mimetypes.add_type('audio/wav', '.wav')

# -----------------------------------------------------------------------------
# 0. SQLALCHEMY DATABASE SETUP (Spaced Repetition & History)
# -----------------------------------------------------------------------------
Base = declarative_base()

class WordStat(Base):
    __tablename__ = 'word_stats'
    word = Column(String, primary key=True)
    last_correct = Column(DateTime, nullable=True)
    attempts = relationship("WordAttempt", back_populates="word_stat", cascade="all, delete-orphan")

class WordAttempt(Base):
    __tablename__ = 'word_attempts'
    id = Column(Integer, primary key=True, autoincrement=True)
    word_id = Column(String, ForeignKey('word_stats.word'))
    typed_word = Column(String)
    ai_feedback = Column(String)
    is_correct = Column(Boolean)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    word_stat = relationship("WordStat", back_populates="attempts")

# Connect to a local SQLite database file
engine = create_engine('sqlite:///spelling_tutor.db', connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# -----------------------------------------------------------------------------
# 1. API SETUP & SECRETS
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Audio Spelling Tutor", layout="centered")

try:
    api_key = st.secrets["SARVAM_API_KEY"]
except (KeyError, FileNotFoundError):
    api_key = os.environ.get("SARVAM_API_KEY")

if not api_key:
    st.error("⚠️ API Key not found. Please set 'SARVAM_API_KEY' in Streamlit Secrets.")
    st.stop()

client = SarvamAI(api_subscription_key=api_key)

# -----------------------------------------------------------------------------
# 2. SARVAM API WRAPPERS
# -----------------------------------------------------------------------------
def generate_tts(text: str) -> str:
    response = client.text_to_speech.convert_stream(
        text=text, language_code="en-IN", speaker="ritu", model="bulbul:v3", pace=1
    )
    tmp_path = os.path.join(tempfile.gettempdir(), f"spelling_{hash(text)}.mp3")
    if not os.path.exists(tmp_path):
        with open(tmp_path, "wb") as f:
            for chunk in response:
                if chunk: f.write(chunk)
    return tmp_path

def evaluate_spelling(target: str, attempt: str) -> str:
    system_prompt = """You are a highly empathetic English phonetics and spelling tutor. 
    You will be given a TARGET WORD and the USER'S ATTEMPT.
    
    If the attempt is CORRECT:
    - Briefly congratulate them.
    
    If the attempt is INCORRECT, you must analyze their specific mistake to reverse-engineer their thought process:
    1. Validate their logic: Explain exactly WHY they likely spelled it that way based on phonetics. Address their specific letter choices (e.g., "I see exactly what you were thinking. You heard the strong 's' sound and wrote 'ss', and for the next part you wrote 'ce' because 'c' and 'e' often make that sound.")
    2. Break down the attempt vs. the target: Compare the word syllable by syllable.
    3. Highlight the correct parts: Tell them exactly which syllables or letters they got perfectly right.
    4. Correct the wrong parts: Point out exactly which letters are wrong and explain the specific English spelling rule, silent letter, or root word that makes their phonetic guess incorrect. (e.g., "However, in this specific word, that 's' sound is actually made by an 'sc' together, and the vowel is an 'i' instead of an 'e'.")
    5. Reveal the final spelling: Put it all together for them clearly.
    6. Conversational Tone: Speak directly to the user's specific spelling attempt using a warm, encouraging, and natural tone suitable for Text-to-Speech."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"TARGET WORD: {target}\nUSER'S ATTEMPT: {attempt}"}
    ]

    response = client.chat.completions(
        model="sarvam-105b-conversations", messages=messages, temperature=0.3
    )
    return response.choices[0].message.content

# -----------------------------------------------------------------------------
# 3. WORD BANK & SPACED REPETITION LOGIC
# -----------------------------------------------------------------------------
WORD_BANK = [
    "accommodation", "rhythm", "embarrass", "fluorescent", 
    "necessary", "pronunciation", "fascinating", "restaurant",
    "mischievous", "definitely", "umbrella", "knowledge", "schedule"
]

def get_next_word():
    db = SessionLocal()
    # Ensure all WORD_BANK words exist in the WordStat table
    for w in WORD_BANK:
        if not db.query(WordStat).filter_by(word=w).first():
            db.add(WordStat(word=w))
    db.commit()

    now = datetime.utcnow()
    # SPACED REPETITION: Word must not have been solved correctly in the last 4 days
    cooldown_period = now - timedelta(days=4)
    
    candidates = db.query(WordStat).filter(
        (WordStat.last_correct == None) | (WordStat.last_correct < cooldown_period)
    ).all()

    # If all words are recently solved, pick from the ones solved the longest time ago
    if not candidates:
        candidates = db.query(WordStat).order_by(WordStat.last_correct.asc()).limit(3).all()
        
    # Prevent the exact same word from showing up back-to-back
    if 'current_word' in st.session_state and len(candidates) > 1:
        candidates = [c for c in candidates if c.word != st.session_state.current_word]

    chosen = random.choice(candidates).word
    db.close()
    return chosen

def save_attempt_to_db(word, typed, feedback, is_correct):
    db = SessionLocal()
    now = datetime.utcnow()
    
    # Save the individual attempt to the relational table
    attempt = WordAttempt(
        word_id=word, typed_word=typed, ai_feedback=feedback, 
        is_correct=is_correct, timestamp=now
    )
    db.add(attempt)
    
    # Update the global word status timestamp if correct
    if is_correct:
        w_stat = db.query(WordStat).filter_by(word=word).first()
        if w_stat:
            w_stat.last_correct = now
            
    db.commit()
    db.close()

def init_new_word():
    st.session_state.current_word = get_next_word()
    st.session_state.word_audio = generate_tts(f"Please spell the word: {st.session_state.current_word}")
    st.session_state.feedback_text = None
    st.session_state.feedback_audio = None
    st.session_state.is_correct = False

if 'current_word' not in st.session_state:
    init_new_word()

# -----------------------------------------------------------------------------
# 4. STREAMLIT UI WORKFLOW
# -----------------------------------------------------------------------------
st.title("🎧 Interactive Spelling Tutor")
st.markdown("Listen to the word, type what you hear, and learn the phonetics behind it!")

st.write("### 1. Listen to the word")
st.audio(st.session_state.word_audio, format="audio/mp3")

st.write("### 2. Type your spelling")
with st.form("spelling_form"):
    user_attempt = st.text_input("How do you spell it?", key="user_input")
    submitted = st.form_submit_button("Submit")

if submitted and user_attempt:
    with st.spinner("Analyzing your spelling..."):
        is_correct = user_attempt.strip().lower() == st.session_state.current_word.lower()
        st.session_state.is_correct = is_correct

        feedback = evaluate_spelling(st.session_state.current_word, user_attempt)
        st.session_state.feedback_text = feedback
        st.session_state.feedback_audio = generate_tts(feedback)
        
        # Save attempt to SQLite database via SQLAlchemy
        save_attempt_to_db(st.session_state.current_word, user_attempt, feedback, is_correct)

if st.session_state.feedback_text:
    st.divider()
    st.write("### Tutor Feedback")
    if st.session_state.is_correct:
        st.success(st.session_state.feedback_text)
    else:
        st.warning(st.session_state.feedback_text)
    st.audio(st.session_state.feedback_audio, format="audio/mp3", autoplay=True)

if st.session_state.is_correct:
    st.balloons()
    if st.button("🎉 Next Word", use_container_width=True):
        init_new_word()
        st.rerun()
elif st.session_state.feedback_text and not st.session_state.is_correct:
    if st.button("Try typing it again", use_container_width=True):
        st.session_state.feedback_text = None
        st.session_state.feedback_audio = None
        st.rerun()

# -----------------------------------------------------------------------------
# 5. DATABASE HISTORY VIEW
# -----------------------------------------------------------------------------
with st.expander(f"📊 View My Learning History for '{st.session_state.current_word}'"):
    db = SessionLocal()
    attempts = db.query(WordAttempt).filter_by(word_id=st.session_state.current_word).order_by(WordAttempt.timestamp.desc()).all()
    if attempts:
        for att in attempts:
            status = "✅" if att.is_correct else "❌"
            st.markdown(f"**{att.timestamp.strftime('%Y-%m-%d %H:%M')}** | Typed: `{att.typed_word}` {status}")
            st.caption(att.ai_feedback)
            st.divider()
    else:
        st.info("No previous attempts recorded for this word yet.")
    db.close()
