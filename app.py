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
    word = Column(String, primary_key=True)
    last_correct = Column(DateTime, nullable=True)
    attempts = relationship("WordAttempt", back_populates="word_stat", cascade="all, delete-orphan")

class WordAttempt(Base):
    __tablename__ = 'word_attempts'
    id = Column(Integer, primary_key=True, autoincrement=True)
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
# 2. SARVAM API WRAPPERS (Optimized & Publicly Available)
# -----------------------------------------------------------------------------
def generate_tts(text: str) -> str:
    # Optimized to bulbul:v4-flash (₹1 per 1,000 characters)
    response = client.text_to_speech.convert_stream(
        text=text, language_code="en-IN", speaker="ritu", model="bulbul:v4-flash", pace=1
    )
    tmp_path = os.path.join(tempfile.gettempdir(), f"spelling_{hash(text)}.mp3")
    if not os.path.exists(tmp_path):
        with open(tmp_path, "wb") as f:
            for chunk in response:
                if chunk: f.write(chunk)
    return tmp_path

def evaluate_spelling(target: str, attempt: str) -> str:
    # Strict brevity constraint keeps TTS audio under ~200 characters, saving 70%+ credits
    system_prompt = """You are a highly empathetic English phonetics and spelling tutor. 
    You will be given a TARGET WORD and the USER'S ATTEMPT.
    
    If the attempt is CORRECT:
    - Briefly congratulate them.
    
    If the attempt is INCORRECT, reverse-engineer their thought process:
    1. Validate their phonetic logic for specific wrong letters.
    2. Break down the attempt vs. the target syllable by syllable.
    3. Correct the wrong letters using the specific English rule.
    4. Reveal the final spelling clearly.
    
    CRITICAL CONSTRAINT: Keep your entire response under 40 words so audio generation stays ultra-fast and cost-effective. Speak warmly and naturally for Text-to-Speech."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"TARGET WORD: {target}\nUSER'S ATTEMPT: {attempt}"}
    ]

    # UPGRADED TO SARVAM'S FLAGSHIP REASONING MODEL
    # "sarvam-105b" has superior logic capabilities compared to the "conversations" variant, 
    # but still works out-of-the-box with standard, non-beta API keys on the V1 endpoint.
    response = client.chat.completions(
        model="sarvam-105b", 
        messages=messages, 
        temperature=0.3
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
    for w in WORD_BANK:
        if not db.query(WordStat).filter_by(word=w).first():
            db.add(WordStat(word=w))
    db.commit()

    now = datetime.utcnow()
    # Spaced repetition: words correctly spelled in the last 4 days are excluded
    cooldown_period = now - timedelta(days=4)
    
    candidates = db.query(WordStat).filter(
        (WordStat.last_correct == None) | (WordStat.last_correct < cooldown_period)
    ).all()

    if not candidates:
        candidates = db.query(WordStat).order_by(WordStat.last_correct.asc()).limit(3).all()
        
    if 'current_word' in st.session_state and len(candidates) > 1:
        candidates = [c for c in candidates if c.word != st.session_state.current_word]

    chosen = random.choice(candidates).word
    db.close()
    return chosen

def save_attempt_to_db(word, typed, feedback, is_correct):
    db = SessionLocal()
    now = datetime.utcnow()
    
    attempt = WordAttempt(
        word_id=word, typed_word=typed, ai_feedback=feedback, 
        is_correct=is_correct, timestamp=now
    )
    db.add(attempt)
    
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
