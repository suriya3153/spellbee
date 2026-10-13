import streamlit as st
from sarvamai import SarvamAI
import os
import tempfile
import random
import mimetypes

# Prevent audio MIME type errors on Linux servers
mimetypes.add_type('audio/wav', '.wav')

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
# 2. SARVAM API WRAPPERS (Moved UP so they exist before they are called)
# -----------------------------------------------------------------------------
def generate_tts(text: str) -> str:
    """Generates Text-to-Speech audio and returns the temporary file path."""
    response = client.text_to_speech.convert_stream(
        text=text,
        language_code="en-IN", 
        speaker="ritu", 
        model="bulbul:v3",
        pace=1
    )
    
    # Hash the text to create a unique filename so we don't regenerate existing audio
    tmp_path = os.path.join(tempfile.gettempdir(), f"spelling_{hash(text)}.mp3")
    if not os.path.exists(tmp_path):
        with open(tmp_path, "wb") as f:
            for chunk in response:
                if chunk:
                    f.write(chunk)
    return tmp_path

def evaluate_spelling(target: str, attempt: str) -> str:
    """Sends the target and attempt to the LLM for phonetic evaluation."""
    system_prompt = """You are an expert English phonetics and spelling tutor.
    You will be given a TARGET WORD and the USER'S ATTEMPT.
    
    If the attempt is CORRECT:
    - Briefly congratulate them.
    
    If the attempt is INCORRECT:
    - Do NOT just tell them the correct spelling right away.
    - Break the word down into its syllables and phonetic sounds.
    - Explain any tricky spelling rules, silent letters, or origins that explain why it is spelled that way.
    - Guide them on how to map the sounds to the correct letters.
    - Keep your tone warm, encouraging, and conversational so it sounds natural when spoken aloud."""

    user_prompt = f"TARGET WORD: {target}\nUSER'S ATTEMPT: {attempt}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    response = client.chat.completions(
        model="sarvam-105b-conversations", 
        messages=messages,
        temperature=0.3
    )
    
    return response.choices[0].message.content

# -----------------------------------------------------------------------------
# 3. WORD BANK & SESSION STATE (Moved DOWN to fix the NameError)
# -----------------------------------------------------------------------------
# A starter list of words that are commonly misspelled
WORD_BANK = [
    "accommodation", "rhythm", "embarrass", "fluorescent", 
    "necessary", "pronunciation", "fascinating", "restaurant",
    "mischievous", "definitely"
]

def init_new_word():
    """Selects a new word and resets the UI state."""
    st.session_state.current_word = random.choice(WORD_BANK)
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

# Step 1: Audio-First Word Presentation (Text remains hidden)
st.write("### 1. Listen to the word")
st.audio(st.session_state.word_audio, format="audio/mp3")

# Step 2: User Input
st.write("### 2. Type your spelling")
with st.form("spelling_form"):
    user_attempt = st.text_input("How do you spell it?", key="user_input")
    submitted = st.form_submit_button("Submit")

# Step 3 & 4: LLM Evaluation and Phonetic Logic
if submitted and user_attempt:
    with st.spinner("Analyzing your spelling..."):
        # Check strict correctness for state management
        if user_attempt.strip().lower() == st.session_state.current_word.lower():
            st.session_state.is_correct = True
        else:
            st.session_state.is_correct = False
            
        # Get teaching response from LLM
        feedback = evaluate_spelling(st.session_state.current_word, user_attempt)
        st.session_state.feedback_text = feedback
        
        # Step 5: Multimodal Feedback Generation
        st.session_state.feedback_audio = generate_tts(feedback)

# Display the Feedback
if st.session_state.feedback_text:
    st.divider()
    st.write("### Tutor Feedback")
    
    if st.session_state.is_correct:
        st.success(st.session_state.feedback_text)
    else:
        st.warning(st.session_state.feedback_text)
        
    st.audio(st.session_state.feedback_audio, format="audio/mp3", autoplay=True)

# Step 6: Session State & Next Word Logic
if st.session_state.is_correct:
    st.balloons()
    if st.button("🎉 Next Word", use_container_width=True):
        init_new_word()
        st.rerun()
elif st.session_state.feedback_text and not st.session_state.is_correct:
    if st.button("Try typing it again", use_container_width=True):
        # Clears feedback to let them try the same word again
        st.session_state.feedback_text = None
        st.session_state.feedback_audio = None
        st.rerun()
