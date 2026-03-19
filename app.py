"""
Voice Generator Panel — MVP
Internal tool for generating voice notes using ElevenLabs cloned voice.
Built with Streamlit • Logs to Google Sheets • Admin Dashboard with Plotly
"""

import io
import datetime

import requests

import streamlit as st
import plotly.express as px
import pandas as pd
from elevenlabs import ElevenLabs
from streamlit_gsheets import GSheetsConnection
from pydub import AudioSegment
from pydub.effects import normalize, compress_dynamic_range

# ── Page Config ──────────────────────────────────────────────
st.set_page_config(
    page_title="Voice Generator Panel",
    page_icon="🎙️",
    layout="centered",
)

# ── Custom CSS ───────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* Card style for history items */
    .history-card {
        background: linear-gradient(135deg, #1e1e2f 0%, #2d2d44 100%);
        border: 1px solid #3a3a5c;
        border-radius: 12px;
        padding: 1.2rem;
        margin-bottom: 1rem;
    }
    .history-card h4 { margin: 0 0 0.3rem 0; color: #c0c0ff; }
    .history-card p  { margin: 0; color: #a0a0c0; font-size: 0.9rem; }

    /* Login container */
    .login-box {
        max-width: 400px;
        margin: 4rem auto;
    }

    /* Metric override for cost */
    [data-testid="stMetricValue"] { font-size: 2rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _check_credentials(username: str, password: str) -> dict | None:
    """Return user dict {role} if credentials are valid, else None."""
    users = st.secrets.get("users", {})
    user_data = users.get(username)
    if user_data and user_data.get("password") == password:
        return {"username": username, "role": user_data["role"]}
    return None


def _get_gsheets_conn():
    """Return a cached GSheetsConnection."""
    return st.connection("gsheets", type=GSheetsConnection)


def _log_to_gsheets(username: str, prompt_text: str, voice_name: str = "Layla"):
    """Append a log row to the Google Sheet."""
    try:
        conn = _get_gsheets_conn()
        # Read existing data using worksheet from secrets.toml
        existing = conn.read(ttl=0)
        if existing is None or existing.empty:
            existing = pd.DataFrame(columns=["Timestamp", "User", "Voice", "Prompt"])
        # Remove any fully‑NaN rows that may appear from empty sheets
        existing = existing.dropna(how="all")

        new_row = pd.DataFrame(
            [
                {
                    "Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "User": username,
                    "Voice": voice_name,
                    "Prompt": prompt_text,
                }
            ]
        )
        updated = pd.concat([existing, new_row], ignore_index=True)
        # Update using worksheet from secrets.toml
        conn.update(data=updated)
    except Exception as exc:
        st.warning(f"⚠️ Could not log to Google Sheets: {exc}")


# ── Voice catalogue (extensible) ─────────────────────────────
# Add more voices here as needed. The key is the display name,
# the value is the ElevenLabs voice ID.
VOICES: dict[str, str] = {
    "Layla": "3Sl1cTs9wQnylOVqg5cO",
    "Paula": "CTfxK2mrqXgEt3Wh7ltC",
}


def _generate_audio(prompt_text: str, voice_id: str) -> bytes | None:
    """Call ElevenLabs TTS and return raw mp3 bytes, or None on failure."""
    try:
        client = ElevenLabs(api_key=st.secrets["elevenlabs"]["api_key"])
        audio_iter = client.text_to_speech.convert(
            voice_id=voice_id,
            model_id="eleven_v3",
            text=prompt_text,
            output_format="mp3_44100_128",
        )
        audio_bytes = b"".join(audio_iter)
        return audio_bytes
    except Exception as exc:
        st.error(f"❌ ElevenLabs API error: {exc}")
        return None


def _degrade_audio_to_phone_quality(input_audio_bytes: bytes) -> bytes:
    """Apply EQ + compression to simulate a phone mic voice note."""
    # 1. Load audio from bytes
    audio = AudioSegment.from_mp3(io.BytesIO(input_audio_bytes))

    # 2. Dynamic range compression (flattens volume, typical of phone recorders)
    audio = compress_dynamic_range(audio)

    # 3. Band-pass EQ — simulate phone microphone frequency response
    #    Low-pass: cut crisp highs above 3500 Hz
    audio = audio.low_pass_filter(3500)
    #    High-pass: cut studio bass below 300 Hz
    audio = audio.high_pass_filter(300)

    # 4. Normalize so it doesn't sound too quiet
    audio = normalize(audio)

    # 5. Export at low bitrate for extra "amateur" realism
    output_buffer = io.BytesIO()
    audio.export(output_buffer, format="mp3", bitrate="64k")
    return output_buffer.getvalue()


# ── Prompt Enhancer (OpenRouter) ─────────────────────────────

_ENHANCE_SYSTEM_PROMPT = """\
You are an AI assistant specializing in enhancing dialogue text for ElevenLabs v3 speech generation.

Your PRIMARY GOAL is to dynamically integrate audio tags (e.g., [laughing], [sighs], [whispers]) into the user's dialogue, making it more expressive and engaging for auditory experiences, while STRICTLY preserving the original text and meaning.

The user will provide:
1. The raw text to enhance.
2. A "Tone / Mood" description (e.g., "playful and sexy", "horny", "sweet and loving").

Core Rules:
- DO integrate audio tags that match the requested mood/tone.
- DO add emphasis via CAPITALS, ellipses (...), exclamation marks, or question marks where it fits the mood.
- DO NOT alter, add, or remove any words from the original dialogue text. Only prepend/append audio tags and adjust punctuation/emphasis.
- DO NOT invent new dialogue lines.
- Audio tags MUST be in square brackets, e.g. [whispers], [sighs], [laughing], [excited], [mischievously], [giggles], [exhales], [playful], [seductive], [curious], [happy], [shy].
- Reply ONLY with the enhanced text. No explanations, no preamble.

Examples of enhancement:

Input: "Hey, I was thinking about you" | Mood: playful and flirty
Output: [giggles] Hey... I was thinking about you [whispers] a LOT.

Input: "I made something special for you" | Mood: sweet and soft
Output: [softly] I made something... SPECIAL for you [sighs happily]

Input: "Did you like what I sent you?" | Mood: teasing
Output: [mischievously] Did you LIKE... what I sent you? [giggles]
"""


def _enhance_prompt(raw_text: str, mood: str) -> str | None:
    """Send raw text + mood to OpenRouter LLM and return enhanced text."""
    api_key = st.secrets.get("openrouter", {}).get("api_key")
    if not api_key:
        st.error("OpenRouter API key not configured in secrets.")
        return None

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "google/gemini-3.1-flash-lite-preview",
                "messages": [
                    {"role": "system", "content": _ENHANCE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Tone / Mood: {mood}\n\nText to enhance:\n{raw_text}",
                    },
                ],
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        st.error(f"❌ Prompt enhancer error: {exc}")
        return None


# ══════════════════════════════════════════════════════════════
#  LOGIN SCREEN
# ══════════════════════════════════════════════════════════════

def _show_login():
    """Render the login form and handle authentication."""
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.markdown("## 🎙️ Voice Generator Panel")
    st.caption("Internal tool — authorized personnel only")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log In", use_container_width=True)

    if submitted:
        user = _check_credentials(username, password)
        if user:
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("Invalid username or password.")
    st.markdown("</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  TAB 1 — VOICE GENERATOR (4-step workflow)
# ══════════════════════════════════════════════════════════════

def _tab_generator():
    st.header("🎙️ Voice Generator")

    # ── Step 1: Select Voice ─────────────────────────────────
    st.subheader("Step 1 — Select Voice")
    voice_names = list(VOICES.keys())
    selected_voice = st.radio(
        "Choose a voice:",
        voice_names,
        index=0,
        horizontal=True,
        help="More voices can be added in the future.",
    )
    voice_id = VOICES[selected_voice]

    st.divider()

    # ── Step 2: Write Text ───────────────────────────────────
    st.subheader("Step 2 — Write Your Text")

    # Apply pending enhanced text BEFORE the widget renders
    if "_pending_enhanced" in st.session_state:
        st.session_state["prompt_input"] = st.session_state.pop("_pending_enhanced")

    prompt_text = st.text_area(
        "Prompt (English)",
        height=150,
        placeholder="Hey babe, I just recorded this for you…",
        key="prompt_input",
    )

    char_count = len(prompt_text)
    st.caption(f"Characters: **{char_count}** · Est. cost: **${char_count * 0.00004:.4f}**")

    st.divider()

    # ── Step 3: Tone / Mood + Enhance ────────────────────────
    st.subheader("Step 3 — Enhance Prompt (optional)")
    st.caption(
        "Describe the tone or mood you want and click **Enhance**. "
        "The AI will add ElevenLabs v3 audio tags (e.g. [whispers], [giggles]) "
        "to make the voice sound more natural and expressive."
    )

    mood = st.text_input(
        "Tone / Mood",
        placeholder="e.g. playful and sexy, soft whisper, teasing, horny, sweet…",
    )

    if st.button("✨ Enhance Text", use_container_width=True):
        if not prompt_text.strip():
            st.warning("Write some text in Step 2 first.")
        elif not mood.strip():
            st.warning("Please describe a tone or mood.")
        else:
            with st.spinner("Enhancing prompt…"):
                enhanced = _enhance_prompt(prompt_text, mood)
            if enhanced:
                # Store in temp key; it will be applied before the widget on next rerun
                st.session_state["_pending_enhanced"] = enhanced
                st.rerun()

    st.divider()

    # ── Step 4: Generate Audio ───────────────────────────────
    st.subheader("Step 4 — Generate Audio")

    use_phone_filter = st.checkbox(
        "📱 Apply 'Phone voice note' filter (Recommended)",
        value=True,
        help="Degrades the studio-quality audio to sound like it was recorded on a phone mic.",
    )

    if st.button("🔊 Generate Audio", type="primary", use_container_width=True):
        if not prompt_text.strip():
            st.warning("Please enter some text in Step 2 first.")
            return

        with st.spinner("Generating audio — this may take a few seconds…"):
            audio_bytes = _generate_audio(prompt_text, voice_id)


        if audio_bytes:
            # Apply phone-quality filter if enabled
            if use_phone_filter:
                try:
                    audio_bytes = _degrade_audio_to_phone_quality(audio_bytes)
                    st.success("✅ Audio generated with phone filter applied!")
                except Exception as exc:
                    st.warning(f"⚠️ Phone filter failed, using original audio: {exc}")
                    st.success("✅ Audio generated successfully (original quality).")
            else:
                st.success("✅ Audio generated successfully!")

            # Play in browser
            st.audio(audio_bytes, format="audio/mp3")

            # Download button
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{selected_voice.lower()}_{timestamp_str}.mp3"
            st.download_button(
                label="⬇️ Download MP3",
                data=audio_bytes,
                file_name=filename,
                mime="audio/mpeg",
                use_container_width=True,
            )

            # Save to session history
            if "history" not in st.session_state:
                st.session_state["history"] = []
            st.session_state["history"].append(
                {
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "user": st.session_state["user"]["username"],
                    "voice": selected_voice,
                    "prompt": prompt_text,
                    "audio": audio_bytes,
                    "filename": filename,
                }
            )

            # Log to Google Sheets
            _log_to_gsheets(st.session_state["user"]["username"], prompt_text, selected_voice)


# ══════════════════════════════════════════════════════════════
#  TAB 2 — SESSION HISTORY
# ══════════════════════════════════════════════════════════════

def _tab_history():
    st.header("📜 Shift History")
    history = st.session_state.get("history", [])

    if not history:
        st.info("No audio generated yet in this session. Go to the **Generator** tab to get started.")
        return

    st.write(f"Showing **{len(history)}** generation(s) from this session.")

    # Show most recent first
    for idx, item in enumerate(reversed(history), start=1):
        with st.container():
            st.markdown(
                f"""
                <div class='history-card'>
                    <h4>#{len(history) - idx + 1} — {item['timestamp']}</h4>
                    <p>👤 <strong>{item['user']}</strong> · 🎙️ {item.get('voice', 'Layla')}</p>
                    <p>💬 {item['prompt'][:120]}{'…' if len(item['prompt']) > 120 else ''}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col1, col2 = st.columns([3, 1])
            with col1:
                st.audio(item["audio"], format="audio/mp3")
            with col2:
                st.download_button(
                    label="⬇️ MP3",
                    data=item["audio"],
                    file_name=item["filename"],
                    mime="audio/mpeg",
                    key=f"dl_{idx}",
                )
            st.divider()


# ══════════════════════════════════════════════════════════════
#  TAB 3 — ADMIN DASHBOARD
# ══════════════════════════════════════════════════════════════

def _tab_dashboard():
    st.header("📊 Admin Dashboard")

    try:
        conn = _get_gsheets_conn()
        # Read using worksheet from secrets.toml
        df = conn.read(ttl=60)
    except Exception as exc:
        st.error(f"Could not read from Google Sheets: {exc}")
        return

    if df is None or df.empty:
        st.info("No data yet. Logs will appear once the team starts generating audio.")
        return

    # Clean up
    df = df.dropna(how="all")
    if df.empty:
        st.info("No data yet.")
        return

    # Ensure correct types
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df["CharCount"] = df["Prompt"].astype(str).apply(len)

    # ── KPIs ─────────────────────────────────────────────────
    total_gens = len(df)
    total_chars = df["CharCount"].sum()
    est_cost = total_chars * 0.00004

    k1, k2, k3 = st.columns(3)
    k1.metric("Total Generations", f"{total_gens:,}")
    k2.metric("Total Characters", f"{total_chars:,}")
    k3.metric("Estimated Cost", f"${est_cost:,.2f}")

    st.divider()

    # ── Charts ───────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Usage by User")
        user_counts = df["User"].value_counts().reset_index()
        user_counts.columns = ["User", "Generations"]
        fig_pie = px.pie(
            user_counts,
            values="Generations",
            names="User",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_right:
        st.subheader("Generations per Day")
        df["Date"] = df["Timestamp"].dt.date
        daily = df.groupby("Date").size().reset_index(name="Generations")
        fig_bar = px.bar(
            daily,
            x="Date",
            y="Generations",
            color_discrete_sequence=["#636EFA"],
        )
        fig_bar.update_layout(
            margin=dict(t=20, b=20, l=20, r=20),
            xaxis_title="Date",
            yaxis_title="Generations",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # ── Detailed table ───────────────────────────────────────
    st.subheader("Full Log")
    st.dataframe(
        df[["Timestamp", "User", "Voice", "Prompt", "CharCount"]].sort_values(
            "Timestamp", ascending=False
        ),
        use_container_width=True,
        hide_index=True,
    )


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    # ── Auth gate ────────────────────────────────────────────
    if "user" not in st.session_state:
        _show_login()
        return

    user = st.session_state["user"]
    is_admin = user["role"] in ("ceo", "manager")

    # ── Sidebar ──────────────────────────────────────────────
    with st.sidebar:
        st.markdown(f"### 👤 {user['username']}")
        st.caption(f"Role: **{user['role'].upper()}**")
        if st.button("Log Out", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # ── Tabs ─────────────────────────────────────────────────
    if is_admin:
        tab_gen, tab_hist, tab_dash = st.tabs(
            ["🎙️ Generator", "📜 Shift History", "📊 Admin Dashboard"]
        )
    else:
        tab_gen, tab_hist = st.tabs(["🎙️ Generator", "📜 Shift History"])
        tab_dash = None

    with tab_gen:
        _tab_generator()

    with tab_hist:
        _tab_history()

    if tab_dash is not None:
        with tab_dash:
            _tab_dashboard()


if __name__ == "__main__":
    main()
