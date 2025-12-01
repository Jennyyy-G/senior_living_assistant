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
# STEP 5 – RESULTS WITH AI EXPLANATIONS
# =======================================
if st.session_state.step == "results":
    st.header("🏆 Step 5: Top Recommendations")

    df = st.session_state.results
    prefs = st.session_state.preferences
    
    st.success(f"🎉 Found {len(df)} matching communities!")
    
    # Display client summary
    with st.expander("👤 Client Summary", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Patient Name", prefs.get("name_of_patient", "N/A"))
            st.metric("Age", prefs.get("age_of_patient", "N/A"))
        with col2:
            st.metric("Care Level", prefs.get("care_level", "N/A"))
            st.metric("Max Budget", f"${prefs.get('max_budget', 'N/A')}")
        with col3:
            locations = prefs.get("preferred_location", [])
            if isinstance(locations, list):
                st.metric("Preferred Areas", len(locations))
                st.caption(", ".join(locations))
            else:
                st.metric("Preferred Area", locations)

    st.subheader("🏅 Top 5 Community Matches")

    top5 = df.head(5)

    for idx, (_, row) in enumerate(top5.iterrows(), 1):
        with st.expander(f"#{idx} - {row.get('Type of Service', 'N/A')} | Priority Level {int(row.get('Priority_Level', 0))}", expanded=(idx <= 3)):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.markdown(f"### 📍 Location & Details")
                st.write(f"**Town:** {row.get('Town', 'N/A')}, {row.get('State', 'N/A')}")
                if pd.notna(row.get('Distance_miles')):
                    st.write(f"**Distance:** {round(row['Distance_miles'], 1)} miles from preferred location")
                st.write(f"**Service Type:** {row.get('Type of Service', 'N/A')}")
                st.write(f"**Apartment Type:** {row.get('Apartment Type', 'N/A')}")
                
            with col2:
                st.markdown(f"### 💰 Pricing")
                if pd.notna(row.get('Monthly Fee')):
                    st.metric("Monthly Fee", f"${int(row['Monthly Fee']):,}")
                else:
                    st.metric("Monthly Fee", "Contact for pricing")
                st.metric("Priority", int(row.get('Priority_Level', 0)))
            
            # Generate AI explanation
            if api_key:
                try:
                    with st.spinner("Generating personalized match explanation..."):
                        client = OpenAI(api_key=api_key)
                        
                        prompt = f"""As a senior living placement advisor, explain in 2-3 concise sentences why this community is an excellent match for the client.

Client Needs:
- Care Level: {prefs.get('care_level')}
- Budget: ${prefs.get('max_budget')}
- Preferred Location: {prefs.get('preferred_location')}
- Special Requirements: Enhanced={prefs.get('enhanced')}, Enriched={prefs.get('enriched')}

Community Details:
- Type: {row.get('Type of Service')}
- Location: {row.get('Town')}, {row.get('State')}
- Monthly Fee: ${row.get('Monthly Fee')}
- Distance: {round(row.get('Distance_miles', 0), 1)} miles
- Priority Level: {row.get('Priority_Level')}

Focus on: care level match, location convenience, value proposition, and any special features."""
                        
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.5,
                            max_tokens=200
                        )
                        
                        explanation = response.choices[0].message.content
                        st.info(f"**🎯 Why This Community Matches:** {explanation}")
                        
                except Exception as e:
                    st.warning(f"Could not generate explanation: {str(e)}")
            
            # Additional details section
            with st.expander("📋 More Details"):
                details_col1, details_col2 = st.columns(2)
                with details_col1:
                    st.write(f"**Enhanced:** {row.get('Enhanced', 'N/A')}")
                    st.write(f"**Enriched:** {row.get('Enriched', 'N/A')}")
                    st.write(f"**Contract Status:** {row.get('Contract (w rate)?', 'N/A')}")
                with details_col2:
                    st.write(f"**Works with Placement:** {row.get('Work with Placement?', 'N/A')}")
                    st.write(f"**Est. Waitlist:** {row.get('Est. Waitlist Length', 'N/A')}")
                    st.write(f"**Community ID:** {row.get('CommunityID', 'N/A')}")

    # Download section
    st.subheader("📥 Download Results")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Prepare top 5 for download
        top5_download = top5[[col for col in ['Type of Service', 'Town', 'State', 'Monthly Fee', 
                                                'Distance_miles', 'Priority_Level', 'Apartment Type',
                                                'Enhanced', 'Enriched', 'CommunityID'] if col in top5.columns]]
        
        csv_top5 = top5_download.to_csv(index=False)
        st.download_button(
            label="📄 Download Top 5 Recommendations (CSV)",
            data=csv_top5,
            file_name=f"top5_recommendations_{prefs.get('name_of_patient', 'client')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col2:
        csv_all = df.to_csv(index=False)
        st.download_button(
            label="📊 Download All Matching Communities (CSV)",
            data=csv_all,
            file_name=f"all_matches_{prefs.get('name_of_patient', 'client')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    # Statistics
    st.subheader("📈 Matching Statistics")
    stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
    
    with stat_col1:
        st.metric("Total Matches", len(df))
    with stat_col2:
        priority1 = len(df[df['Priority_Level'] == 1])
        st.metric("Priority 1 Communities", priority1)
    with stat_col3:
        if 'Distance_miles' in df.columns:
            avg_distance = df['Distance_miles'].mean()
            st.metric("Avg Distance", f"{avg_distance:.1f} mi" if pd.notna(avg_distance) else "N/A")
    with stat_col4:
        if 'Monthly Fee' in df.columns:
            avg_price = df['Monthly Fee'].mean()
            st.metric("Avg Monthly Fee", f"${int(avg_price):,}" if pd.notna(avg_price) else "N/A")
