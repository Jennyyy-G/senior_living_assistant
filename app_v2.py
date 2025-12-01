import streamlit as st
import tempfile
import json
import pandas as pd
from pathlib import Path
from openai import OpenAI
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import pgeocode
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# =======================================
# GOOGLE SHEET LOADER
# =======================================
def load_private_google_sheet(sheet_name: str, worksheet_name: str = None):
    scope = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gcp_service_account"], scope
    )
    client = gspread.authorize(creds)
    sheet = client.open(sheet_name)
    ws = sheet.worksheet(worksheet_name) if worksheet_name else sheet.sheet1
    return pd.DataFrame(ws.get_all_records())


# =======================================
# STREAMLIT PAGE SETUP
# =======================================
st.set_page_config(page_title="Senior Living Placement Assistant", layout="wide")
st.title("Assisted Living Locators - Senior Living Placement Assistant")


# =======================================
# SESSION STATE INIT
# =======================================
default_sessions = {
    "step": "upload",
    "audio_files": None,
    "transcription": None,
    "preferences": None,
    "results": None,
}
for k, v in default_sessions.items():
    st.session_state.setdefault(k, v)

with st.sidebar:
    st.header("⚙️ Configuration")
    api_key = st.text_input("OpenAI API Key", type="password")
    if api_key:
        st.success("API Key Loaded")


# =======================================
# STEP 1 — UPLOAD AUDIO
# =======================================
if st.session_state.step == "upload":
    st.header("Step 1: Upload Audio File")

    audio = st.file_uploader(
        "Upload audio file", type=["m4a", "mp3", "wav", "mp4"]
    )

    if audio:
        st.session_state.audio_files = audio
        st.session_state.step = "transcribe"
        st.rerun()


# =======================================
# STEP 2 — TRANSCRIBE AUDIO
# =======================================
if st.session_state.step == "transcribe":
    st.header("Step 2: Transcribing Audio...")

    if not api_key:
        st.warning("Please enter your OpenAI API Key.")
        st.stop()

    try:
        client = OpenAI(api_key=api_key)
        audio_file = st.session_state.audio_files
        ext = audio_file.name.split('.')[-1]

        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(audio_file.getbuffer())
            fp = tmp.name

        with open(fp, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f
            )

        Path(fp).unlink()

        st.session_state.transcription = transcript.text
        st.success("Transcription complete!")
        st.text_area("Transcribed Text:", transcript.text)

        st.session_state.step = "preferences"
        st.rerun()

    except Exception as e:
        st.error(f"Transcription Error: {e}")


# =======================================
# STEP 3 — EXTRACT PREFERENCES (SAFE JSON)
# =======================================
if st.session_state.step == "preferences":
    st.header("Step 3: Extracting Preferences...")

    try:
        client = OpenAI(api_key=api_key)

        system_prompt = """
        You are a JSON generator.
        You MUST output ONLY valid JSON.
        Do NOT add explanations or markdown.

        JSON STRUCTURE:
        {
            "name_of_patient": "",
            "age_of_patient": "",
            "injury_or_reason": "",
            "primary_contact_information": {
                "name": "",
                "phone_number": "",
                "email": ""
            },
            "mentally": "",
            "care_level": "",
            "preferred_location": [],
            "enhanced": "",
            "enriched": "",
            "move_in_window": "",
            "max_budget": "",
            "pet_friendly": "",
            "tour_availability": [],
            "other_keywords": {}
        }
        """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": st.session_state.transcription},
            ],
        )

        raw = response.choices[0].message.content

        if not raw or raw.strip() == "":
            raise ValueError("Empty response from GPT")

        prefs = json.loads(raw)

        st.session_state.preferences = prefs
        st.subheader("Extracted Preferences")
        st.json(prefs)

        st.session_state.step = "rank"
        st.rerun()

    except Exception as e:
        st.error(f"Preference Extraction Error: {e}")


# =======================================
# STEP 4 — FILTERING & RANKING
# =======================================
if st.session_state.step == "rank":
    st.header("Step 4: Ranking Communities...")

    try:
        prefs = st.session_state.preferences

        st.write("⏳ Loading Google Sheet...")
        df = load_private_google_sheet("Living_Locators_Data", "Rochester")
        st.write(f"Loaded {len(df)} communities.")

        # ---------- FIX BUDGET ----------
        if prefs.get("max_budget"):
            try:
                prefs["max_budget"] = float(str(prefs["max_budget"]).replace(",", "").strip())
            except:
                prefs["max_budget"] = None

        # ---------- CLEAN MONTHLY FEE ----------
        if "Monthly Fee" in df.columns:
            df["Monthly Fee"] = (
                df["Monthly Fee"]
                .astype(str)
                .str.replace("$", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.extract(r"(\d+\.?\d*)")[0]
            )
            df["Monthly Fee"] = pd.to_numeric(df["Monthly Fee"], errors="coerce")

        # ---------- SMART CARE LEVEL ----------
        if prefs.get("care_level"):
            text = str(prefs["care_level"]).lower()

            if any(k in text for k in ["assisted", "al", "enhanced"]):
                df = df[df["Type of Service"].str.contains("Assisted", case=False, na=False)]

            elif any(k in text for k in ["memory", "dementia"]):
                df = df[df["Type of Service"].str.contains("Memory", case=False, na=False)]

            elif any(k in text for k in ["independent", "il"]):
                df = df[df["Type of Service"].str.contains("Independent", case=False, na=False)]

        # ---------- ENHANCED ----------
        if prefs.get("enhanced") in [True, "true", "True", "Yes"]:
            df = df[df["Enhanced"].astype(str).str.lower() == "yes"]

        # ---------- ENRICHED ----------
        if prefs.get("enriched") in [True, "true", "True", "Yes"]:
            df = df[df["Enriched"].astype(str).str.lower() == "yes"]

        # ---------- BUDGET FILTER ----------
        if prefs.get("max_budget") is not None:
            df = df[df["Monthly Fee"] <= prefs["max_budget"]]

        # ---------- PRIORITY ----------
        def assign_priority(row):
            c = str(row.get("Contract (w rate)?", "")).lower()
            p = str(row.get("Work with Placement?", "")).lower()
            if c not in ["no", "nan", ""]:
                return 1
            if c == "no" and p == "yes":
                return 2
            return 3

        df["Priority_Level"] = df.apply(assign_priority, axis=1)

        # ---------- GEOCODING ----------
        geolocator = Nominatim(user_agent="assisted_living")

        locs = prefs.get("preferred_location", ["Rochester, NY"])
        if isinstance(locs, str):
            locs = [locs]

        coords_list = []
        for l in locs:
            try:
                geo = geolocator.geocode(l)
                if geo:
                    coords_list.append((geo.latitude, geo.longitude))
                time.sleep(1)
            except:
                pass

        if not coords_list:
            coords_list = [(43.1566, -77.6088)]  # Rochester default

        zip_col = next((c for c in df.columns if "zip" in c.lower()), None)

        def get_coord(row):
            if zip_col:
                z = row.get(zip_col)
                if pd.notna(z):
                    try:
                        loc = geolocator.geocode(f"{int(float(z)):05d}, NY")
                        time.sleep(1)
                        if loc:
                            return (loc.latitude, loc.longitude)
                    except:
                        pass
            return None

        df["Community_Coords"] = df.apply(get_coord, axis=1)

        def dist(c):
            if c is None:
                return None
            try:
                return min(geodesic(c, k).miles for k in coords_list)
            except:
                return None

        df["Distance_miles"] = df["Community_Coords"].apply(dist)

        df = df.sort_values(by=["Priority_Level", "Distance_miles"])

        st.session_state.results = df
        st.session_state.step = "results"
        st.rerun()

    except Exception as e:
        st.error(f"Ranking Error: {e}")


# =======================================
# STEP 5 — RESULTS
# =======================================
if st.session_state.step == "results":
    st.header("Step 5: Top Recommendations")

    df = st.session_state.results
    st.success("🎉 Top Community Matches Ready!")

    top5 = df.head(5)

    for idx, r in top5.iterrows():
        with st.expander(f"{idx+1}. {r.get('Type of Service')}"):
            st.write(r)

    st.download_button(
        "Download All Results (CSV)",
        df.to_csv(index=False),
        "community_results.csv",
        "text/csv"
    )
