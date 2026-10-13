import streamlit as st
from sarvamai import SarvamAI
import os
import tempfile

# -----------------------------------------------------------------------------
# 1. API KEY SETUP & SECURE LOAD
# -----------------------------------------------------------------------------
st.set_page_config(page_title="My English Character", layout="centered")

# Securely fetch the API key from Streamlit Secrets (Cloud) or local environment
try:
    api_key = st.secrets["SARVAM_API_KEY"]
except (KeyError, FileNotFoundError):
    api_key = os.environ.get("SARVAM_API_KEY")

if not api_key:
    st.error("⚠️ API Key not found. Please set 'SARVAM_API_KEY' in Streamlit Secrets.")
    st.stop()

client = SarvamAI(api_subscription_key=api_key)

# -----------------------------------------------------------------------------
# 2. SYSTEM PROMPT (Strict Grammar Enforcement)
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a strict English grammar corrector. 
Listen to the user's input and evaluate the grammar.
- If the sentence has a grammatical error, return ONLY the corrected English sentence. (Example: If user says 'I am going to my home yesterday', you output 'I went to my home yesterday.')
- If the sentence is already grammatically correct, output ONLY: 'The sentence is correct.'
- Do NOT provide explanations, greetings, or any other conversational text."""

if 'messages' not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# -----------------------------------------------------------------------------
# 3. SARVAM API WRAPPERS
# -----------------------------------------------------------------------------
def transcribe_audio_bytes(audio_bytes) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        # Using Saaras to transcribe the spoken English
        response = client.speech_to_text.transcribe(
            file=f,
            model="saaras:v4",
            mode="transcribe"
        )
    os.remove(tmp_path)
    return response.transcript

def generate_audio_response(text: str) -> str:
    # Using Bulbul to speak the corrected English sentence back
    response = client.text_to_speech.convert_stream(
        text=text,
        language_code="en-IN", 
        speaker="ritu", 
        model="bulbul:v3",
        pace=1
    )
    
    tmp_path = os.path.join(tempfile.gettempdir(), "english_character_response.mp3")
    with open(tmp_path, "wb") as f:
        for chunk in response:
            if chunk:
                f.write(chunk)
                
    return tmp_path

# -----------------------------------------------------------------------------
# 4. STREAMLIT FRONTEND
# -----------------------------------------------------------------------------
st.title("🗣️ My English Character")
st.markdown("Speak or type a sentence, and I will correct your grammar.")

audio_value = st.audio_input("Record your sentence:")
text_value = st.text_input("Or type your sentence here:")

user_input = None

if audio_value:
    with st.spinner("Transcribing..."):
        try:
            user_input = transcribe_audio_bytes(audio_value.getvalue())
            st.info(f"**You said:** {user_input}")
        except Exception as e:
            st.error(f"Transcription Error: {e}")
elif text_value:
    user_input = text_value

if user_input:
    with st.spinner("Checking grammar..."):
        # Temporarily append user input for this single turn
        current_messages = st.session_state.messages.copy()
        current_messages.append({"role": "user", "content": user_input})
        
        try:
            response = client.chat.completions(
                model="sarvam-105b-conversations", 
                messages=current_messages,
                temperature=0.1
            )
            
            final_text = response.choices[0].message.content
            st.success(f"**Correction:** {final_text}")
            
            with st.spinner("Generating voice..."):
                audio_file = generate_audio_response(final_text)
                st.audio(audio_file, format="audio/mp3")
                
        except Exception as e:
            st.error(f"Error: {e}")
