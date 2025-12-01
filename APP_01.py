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
    api_key = st.text_input("OpenAI API Key", type="password", help="Enter your OpenAI API key")
    
    if api_key:
        if api_key.startswith("sk-"):
            st.success("✅ API Key Loaded")
        else:
            st.warning("⚠️ API key should start with 'sk-'")
    
    st.divider()
    
    # Progress indicator
    st.subheader("📊 Progress")
    steps = {
        "upload": "1️⃣ Upload Audio",
        "transcribe": "2️⃣ Transcribe",
        "preferences": "3️⃣ Extract Preferences",
        "rank": "4️⃣ Rank Communities",
        "results": "5️⃣ View Results"
    }
    
    current_step = st.session_state.step
    for key, label in steps.items():
        if key == current_step:
            st.markdown(f"**➡️ {label}**")
        elif list(steps.keys()).index(key) < list(steps.keys()).index(current_step):
            st.markdown(f"✅ {label}")
        else:
            st.markdown(f"⚪ {label}")
    
    st.divider()
    
    # Reset button
    if st.button("🔄 Start Over", use_container_width=True):
        for k, v in default_sessions.items():
            st.session_state[k] = v
        st.rerun()


# =======================================
# STEP 1 – UPLOAD AUDIO
# =======================================
if st.session_state.step == "upload":
    st.header("Step 1: Upload Audio File")
    st.markdown("📤 Upload a recording of the client consultation call")

    audio = st.file_uploader(
        "Choose an audio file", type=["m4a", "mp3", "wav", "mp4"]
    )

    if audio:
        st.success(f"✅ File uploaded: **{audio.name}** ({len(audio.getbuffer()) / (1024*1024):.2f} MB)")
        st.session_state.audio_files = audio
        
        if st.button("▶️ Continue to Transcription", type="primary"):
            st.session_state.step = "transcribe"
            st.rerun()


# =======================================
# STEP 2 – TRANSCRIBE AUDIO
# =======================================
elif st.session_state.step == "transcribe":
    st.header("Step 2: Transcribe Audio")
    
    # Show uploaded file info
    if st.session_state.audio_files:
        st.info(f"📁 Processing: **{st.session_state.audio_files.name}**")

    if not api_key:
        st.warning("⚠️ Please enter your OpenAI API Key in the sidebar")
        st.stop()

    # Show transcription if already done
    if st.session_state.transcription:
        st.success("✅ Transcription completed!")
        with st.expander("📝 View Transcription", expanded=True):
            st.text_area("Transcribed Text:", st.session_state.transcription, height=200)
        
        if st.button("▶️ Continue to Preference Extraction", type="primary"):
            st.session_state.step = "preferences"
            st.rerun()
    else:
        # Transcribe button
        if st.button("🎧 Start Transcription", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                status_text.text("🔄 Initializing OpenAI client...")
                progress_bar.progress(10)
                client = OpenAI(api_key=api_key)
                
                audio_file = st.session_state.audio_files
                ext = audio_file.name.split('.')[-1]

                status_text.text("📦 Preparing audio file...")
                progress_bar.progress(30)
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                    tmp.write(audio_file.getbuffer())
                    fp = tmp.name

                status_text.text("🎤 Sending to Whisper API (this may take a minute)...")
                progress_bar.progress(50)
                
                with open(fp, "rb") as f:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f
                    )

                status_text.text("🧹 Cleaning up temporary files...")
                progress_bar.progress(90)
                Path(fp).unlink()

                st.session_state.transcription = transcript.text
                
                progress_bar.progress(100)
                status_text.empty()
                progress_bar.empty()
                
                st.success("✅ Transcription complete!")
                st.rerun()

            except Exception as e:
                status_text.empty()
                progress_bar.empty()
                st.error(f"❌ Transcription Error: {e}")
                st.info("💡 Tip: Make sure your API key is valid and has sufficient credits")


# =======================================
# STEP 3 – EXTRACT PREFERENCES
# =======================================
elif st.session_state.step == "preferences":
    st.header("Step 3: Extract Client Preferences")
    
    # Show transcription
    with st.expander("📝 View Transcription"):
        st.text_area("Transcribed Text:", st.session_state.transcription, height=150)
    
    # Show preferences if already extracted
    if st.session_state.preferences:
        st.success("✅ Preferences extracted successfully!")
        
        with st.expander("🎯 View Extracted Preferences", expanded=True):
            st.json(st.session_state.preferences)
        
        # Add option to edit budget if missing or seems wrong
        st.markdown("---")
        st.subheader("🔧 Review & Adjust (Optional)")
        
        col1, col2 = st.columns(2)
        
        with col1:
            current_budget = st.session_state.preferences.get("max_budget")
            if not current_budget or current_budget == "" or current_budget == "NULL":
                st.warning("⚠️ Budget not detected. Please enter manually if needed.")
                current_budget = None
            
            new_budget = st.number_input(
                "Monthly Budget ($)",
                min_value=0,
                max_value=50000,
                value=int(current_budget) if current_budget else 0,
                step=100,
                help="Leave as 0 if no budget constraint"
            )
            
            if new_budget > 0 and new_budget != current_budget:
                if st.button("💾 Update Budget"):
                    st.session_state.preferences["max_budget"] = new_budget
                    st.success(f"✅ Budget updated to ${new_budget:,}/month")
                    st.rerun()
        
        with col2:
            current_care = st.session_state.preferences.get("care_level", "")
            care_options = ["Independent Living", "Assisted Living", "Enhanced Assisted Living", "Memory Care"]
            
            if current_care and current_care in care_options:
                default_idx = care_options.index(current_care)
            else:
                default_idx = 1  # Default to Assisted Living
            
            new_care = st.selectbox(
                "Care Level",
                options=care_options,
                index=default_idx
            )
            
            if new_care != current_care:
                if st.button("💾 Update Care Level"):
                    st.session_state.preferences["care_level"] = new_care
                    st.success(f"✅ Care level updated to {new_care}")
                    st.rerun()
        
        st.markdown("---")
        
        if st.button("▶️ Continue to Community Ranking", type="primary"):
            st.session_state.step = "rank"
            st.rerun()
    else:
        # Extract button
        if st.button("🔍 Extract Preferences", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            try:
                status_text.text("🤖 Initializing AI model...")
                progress_bar.progress(20)
                client = OpenAI(api_key=api_key)

                system_prompt = """
                You are a JSON generator for senior living placement.
                You MUST output ONLY valid JSON with NO markdown, NO explanations, NO code blocks.

                EXTRACTION RULES:
                1. Extract the PATIENT's information (the person who needs care), NOT the contact person
                2. For "max_budget": Extract ANY mention of monthly cost, budget, or price limit
                   - Look for phrases like: "$X per month", "$X/month", "budget is $X", "maximum $X", "up to $X"
                   - IMPORTANT: Extract ONLY the number (e.g., if text says "$4,000 per month", extract: 4000)
                   - If multiple budgets mentioned, use the MAXIMUM value
                   - If no budget mentioned, use null
                3. For "care_level": Choose ONE from ["Independent Living", "Assisted Living", "Enhanced Assisted Living", "Memory Care"]
                   - "Enhanced" or "higher level" care = "Enhanced Assisted Living"
                4. For "enhanced": Extract "yes" ONLY if explicitly mentioned as requirement
                5. For "enriched": Extract "yes" ONLY if explicitly mentioned as requirement
                6. For "preferred_location": Extract ALL cities/towns mentioned as preferences (format: ["City, State"])
                7. For "move_in_window": Choose ONE from ["Immediate (0-1 months)", "Near-term (1-6 months)", "Flexible (6+ months)"]
                   - "discharges in X" or "moving in X" = timeframe
                8. For "mentally": Describe cognitive state (e.g., "sharp", "mild impairment", "moderate dementia")

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
                    "max_budget": null,
                    "pet_friendly": "",
                    "tour_availability": [],
                    "other_keywords": {}
                }
                
                CRITICAL: For max_budget, extract ONLY the numeric value (e.g., 4000, not "$4,000" or "4000 per month")
                """

                status_text.text("🧠 Analyzing transcription and extracting preferences...")
                progress_bar.progress(50)
                
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"""Extract structured information from this consultation call transcript.

TRANSCRIPT:
{st.session_state.transcription}

IMPORTANT REMINDERS:
- For max_budget: Look carefully for ANY mention of dollar amounts, monthly costs, or budget limits
- Extract ONLY the numeric value (e.g., if "$4,000 per month" is mentioned, extract: 4000)
- If multiple people or budgets are mentioned, extract the MAXIMUM value
- Patient is the person RECEIVING care, not the family member calling

Return ONLY valid JSON, no explanations."""},
                    ],
                )

                status_text.text("📊 Processing AI response...")
                progress_bar.progress(80)
                
                raw = response.choices[0].message.content
                
                # Clean response if it has markdown
                if "```json" in raw:
                    raw = raw.split("```json")[1].split("```")[0].strip()
                elif "```" in raw:
                    raw = raw.split("```")[1].split("```")[0].strip()

                if not raw or raw.strip() == "":
                    raise ValueError("Empty response from GPT")

                prefs = json.loads(raw)
                
                # Post-processing: If budget is missing, try to extract with regex
                if not prefs.get("max_budget") or prefs.get("max_budget") == "":
                    import re
                    # Look for patterns like "$4,000", "$4000", "4000 dollars", etc.
                    budget_patterns = [
                        r'\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',  # $4,000 or $4000.00
                        r'(\d{1,3}(?:,\d{3})*)\s*(?:dollars?|per\s*month|/month)',  # 4000 dollars
                        r'(?:budget|maximum|max|up to)\s*(?:is|of)?\s*\$?\s*(\d{1,3}(?:,\d{3})*)',  # budget is $4000
                    ]
                    
                    transcript_lower = st.session_state.transcription.lower()
                    for pattern in budget_patterns:
                        matches = re.findall(pattern, st.session_state.transcription, re.IGNORECASE)
                        if matches:
                            # Extract all numbers, remove commas, and take the maximum
                            try:
                                budget_values = [float(m.replace(',', '')) for m in matches]
                                max_budget = max(budget_values)
                                prefs["max_budget"] = int(max_budget)
                                st.info(f"💡 Detected budget from transcript: ${int(max_budget):,}/month")
                                break
                            except:
                                pass
                
                st.session_state.preferences = prefs
                
                progress_bar.progress(100)
                status_text.empty()
                progress_bar.empty()
                
                st.success("✅ Preferences extracted!")
                st.rerun()

            except Exception as e:
                status_text.empty()
                progress_bar.empty()
                st.error(f"❌ Preference Extraction Error: {e}")
                if 'raw' in locals():
                    with st.expander("🔍 Debug: Raw AI Response"):
                        st.code(raw)


# =======================================
# STEP 4 – FILTERING & RANKING
# =======================================
elif st.session_state.step == "rank":
    st.header("Step 4: Rank & Filter Communities")
    
    # Show previous results
    col1, col2 = st.columns(2)
    with col1:
        with st.expander("📝 View Transcription"):
            st.text_area("", st.session_state.transcription, height=100)
    with col2:
        with st.expander("🎯 View Preferences"):
            st.json(st.session_state.preferences)
    
    # Show results if already ranked
    if st.session_state.results is not None:
        st.success(f"✅ Found {len(st.session_state.results)} matching communities!")
        
        # Quick stats
        df = st.session_state.results
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Matches", len(df))
        with col2:
            priority1 = len(df[df['Priority_Level'] == 1])
            st.metric("Priority 1", priority1)
        with col3:
            if 'Distance_miles' in df.columns and df['Distance_miles'].notna().any():
                avg_dist = df['Distance_miles'].mean()
                st.metric("Avg Distance", f"{avg_dist:.1f} mi")
        with col4:
            if 'Monthly Fee' in df.columns and df['Monthly Fee'].notna().any():
                avg_fee = df['Monthly Fee'].mean()
                st.metric("Avg Fee", f"${int(avg_fee):,}")
        
        if st.button("▶️ View Top Recommendations", type="primary"):
            st.session_state.step = "results"
            st.rerun()
    else:
        # Ranking button
        if st.button("🎯 Start Ranking", type="primary"):
            progress_container = st.container()
            
            with progress_container:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    prefs = st.session_state.preferences

                    status_text.text("📥 Loading community database from Google Sheets...")
                    progress_bar.progress(10)
                    df = load_private_google_sheet("Living_Locators_Data", "Rochester")
                    initial_count = len(df)
                    st.info(f"📊 Loaded {initial_count} communities from database")

                    # ---------- FIX BUDGET ----------
                    status_text.text("💰 Processing budget information...")
                    progress_bar.progress(20)
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
                    status_text.text("🏥 Filtering by care level...")
                    progress_bar.progress(30)
                    if prefs.get("care_level"):
                        text = str(prefs["care_level"]).lower()

                        if any(k in text for k in ["assisted", "al", "enhanced"]):
                            df = df[df["Type of Service"].str.contains("Assisted", case=False, na=False)]
                            st.info(f"✓ After care level filter: {len(df)} communities")

                        elif any(k in text for k in ["memory", "dementia"]):
                            df = df[df["Type of Service"].str.contains("Memory", case=False, na=False)]
                            st.info(f"✓ After care level filter: {len(df)} communities")

                        elif any(k in text for k in ["independent", "il"]):
                            df = df[df["Type of Service"].str.contains("Independent", case=False, na=False)]
                            st.info(f"✓ After care level filter: {len(df)} communities")

                    # ---------- ENHANCED ----------
                    status_text.text("⭐ Applying enhanced/enriched filters...")
                    progress_bar.progress(40)
                    if prefs.get("enhanced") in [True, "true", "True", "Yes"]:
                        df = df[df["Enhanced"].astype(str).str.lower() == "yes"]
                        st.info(f"✓ After enhanced filter: {len(df)} communities")

                    # ---------- ENRICHED ----------
                    if prefs.get("enriched") in [True, "true", "True", "Yes"]:
                        df = df[df["Enriched"].astype(str).str.lower() == "yes"]
                        st.info(f"✓ After enriched filter: {len(df)} communities")

                    # ---------- BUDGET FILTER ----------
                    if prefs.get("max_budget") is not None:
                        df = df[df["Monthly Fee"] <= prefs["max_budget"]]
                        st.info(f"✓ After budget filter: {len(df)} communities")

                    # ---------- PRIORITY ----------
                    status_text.text("🎯 Assigning priority levels...")
                    progress_bar.progress(50)
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
                    status_text.text("🗺️ Calculating distances (this may take a moment)...")
                    progress_bar.progress(60)
                    
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

                    progress_bar.progress(70)
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

                    status_text.text("📍 Geocoding communities...")
                    progress_bar.progress(80)
                    df["Community_Coords"] = df.apply(get_coord, axis=1)

                    def dist(c):
                        if c is None:
                            return None
                        try:
                            return min(geodesic(c, k).miles for k in coords_list)
                        except:
                            return None

                    df["Distance_miles"] = df["Community_Coords"].apply(dist)

                    # Add Town/State
                    if zip_col:
                        nomi = pgeocode.Nominatim('us')
                        df["Town"] = df[zip_col].apply(
                            lambda z: nomi.query_postal_code(str(int(float(z))).zfill(5)).place_name if pd.notna(z) else None
                        )
                        df["State"] = df[zip_col].apply(
                            lambda z: nomi.query_postal_code(str(int(float(z))).zfill(5)).state_code if pd.notna(z) else None
                        )

                    status_text.text("📊 Sorting results by priority tiers and distance...")
                    progress_bar.progress(95)
                    
                    # Sort by Priority first, then Distance within each priority
                    df = df.sort_values(
                        by=["Priority_Level", "Distance_miles"], 
                        ascending=[True, True],
                        na_position='last'
                    )
                    
                    # Add a rank within each priority level
                    df['Rank_Within_Priority'] = df.groupby('Priority_Level').cumcount() + 1

                    st.session_state.results = df
                    
                    progress_bar.progress(100)
                    time.sleep(0.5)
                    status_text.empty()
                    progress_bar.empty()
                    
                    st.success(f"✅ Ranking complete! Found {len(df)} matching communities")
                    st.rerun()

                except Exception as e:
                    status_text.empty()
                    progress_bar.empty()
                    st.error(f"❌ Ranking Error: {e}")
                    import traceback
                    with st.expander("🔍 Debug: Full Error Trace"):
                        st.code(traceback.format_exc())


# =======================================
# STEP 5 – RESULTS WITH AI EXPLANATIONS
# =======================================
elif st.session_state.step == "results":
    st.header("🏆 Step 5: Top Recommendations")

    df = st.session_state.results
    prefs = st.session_state.preferences

    # Quick access to previous steps
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        with st.expander("📝 View Transcription"):
            st.text_area("", st.session_state.transcription, height=100, key="result_transcript")
    with col2:
        with st.expander("🎯 View Preferences"):
            st.json(st.session_state.preferences)
    with col3:
        with st.expander("📊 All Matching Communities"):
            st.dataframe(df[['Type of Service', 'Town', 'Monthly Fee', 'Distance_miles', 'Priority_Level']].head(10))
    st.markdown("---")

    st.success(f"🎉 Found {len(df)} matching communities!")

    # Display client summary
    with st.expander("👤 Client Summary", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Patient Name", prefs.get("name_of_patient", "N/A"))
            st.metric("Age", prefs.get("age_of_patient", "N/A"))
        with col2:
            st.metric("Care Level", prefs.get("care_level", "N/A"))
            budget_val = prefs.get('max_budget')
            if budget_val:
                st.metric("Max Budget", f"${budget_val:,.0f}" if isinstance(budget_val, (int, float)) else budget_val)
            else:
                st.metric("Max Budget", "N/A")
        with col3:
            locations = prefs.get("preferred_location", [])
            if isinstance(locations, list) and locations:
                st.metric("Preferred Areas", len(locations))
                st.caption(", ".join(locations))
            elif locations:
                st.metric("Preferred Area", locations)
            else:
                st.metric("Preferred Area", "N/A")

    st.subheader("🏅 Top Community Matches by Priority Tier")
    
    # Get priority level descriptions
    priority_descriptions = {
        1: "🥇 Priority 1 - Communities with Contracted Rates",
        2: "🥈 Priority 2 - Placement Partners (No Contract)",
        3: "🥉 Priority 3 - Other Communities"
    }
    
    # Display communities grouped by priority
    for priority_level in [1, 2, 3]:
        priority_communities = df[df['Priority_Level'] == priority_level]
        
        if len(priority_communities) == 0:
            continue
        
        st.markdown("---")
        st.markdown(f"### {priority_descriptions[priority_level]}")
        st.caption(f"Found {len(priority_communities)} communities in this tier")
        
        # Show top 5 from this priority level (or all if less than 5)
        display_count = min(5, len(priority_communities))
        
        for idx, (_, row) in enumerate(priority_communities.head(display_count).iterrows(), 1):
            # Create label with priority tier info
            distance_text = f"{round(row['Distance_miles'], 1)} mi" if pd.notna(row.get('Distance_miles')) else "N/A"
            expander_label = f"P{priority_level}-{idx}. {row.get('Type of Service', 'N/A')} | {distance_text} | {row.get('Town', 'N/A')}"
            
            with st.expander(expander_label, expanded=(priority_level == 1 and idx <= 2)):
                col1, col2 = st.columns([2, 1])

                with col1:
                    st.markdown(f"### 📍 Location & Details")
                    town_val = row.get('Town', 'N/A')
                    state_val = row.get('State', 'N/A')
                    st.write(f"**Town:** {town_val}, {state_val}")
                    
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
                    st.metric("Priority Tier", f"Level {int(row.get('Priority_Level', 0))}")
                    st.metric("Rank in Tier", f"#{int(row.get('Rank_Within_Priority', 0))}")

                # AI Explanation - Fixed version
                if api_key and api_key.startswith("sk-"):
                    try:
                        client = OpenAI(api_key=api_key)

                        prompt = f"""As a senior living placement advisor, explain in 2-3 concise sentences why this community is a good match for the client.

Client Needs:
- Care Level: {prefs.get('care_level', 'Not specified')}
- Budget: ${prefs.get('max_budget', 'Not specified')}
- Preferred Location: {prefs.get('preferred_location', 'Not specified')}
- Special Requirements: Enhanced={prefs.get('enhanced', 'No')}, Enriched={prefs.get('enriched', 'No')}

Community Details:
- Type: {row.get('Type of Service', 'N/A')}
- Location: {town_val}, {state_val}
- Monthly Fee: ${row.get('Monthly Fee', 'N/A')}
- Distance: {round(row.get('Distance_miles', 0), 1) if pd.notna(row.get('Distance_miles')) else 'N/A'} miles
- Priority Level: {row.get('Priority_Level', 'N/A')} ({"Contracted rates" if row.get('Priority_Level') == 1 else "Placement partner" if row.get('Priority_Level') == 2 else "Other"})

Focus on: care level match, location convenience, value proposition, and why this priority tier makes sense."""

                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.5,
                            max_tokens=200
                        )

                        explanation = response.choices[0].message.content
                        st.info(f"**🎯 Why This Community Matches:** {explanation}")

                    except Exception as e:
                        st.warning(f"⚠️ Could not generate AI explanation: {str(e)}")
                elif not api_key:
                    st.info("💡 Enter your OpenAI API key in the sidebar to see AI-powered match explanations")

                # More Details - NOT nested, just in the same expander
                st.markdown("---")
                st.markdown("#### 📋 Additional Details")
                details_col1, details_col2 = st.columns(2)
                with details_col1:
                    st.write(f"**Enhanced:** {row.get('Enhanced', 'N/A')}")
                    st.write(f"**Enriched:** {row.get('Enriched', 'N/A')}")
                    st.write(f"**Contract Status:** {row.get('Contract (w rate)?', 'N/A')}")
                with details_col2:
                    st.write(f"**Works with Placement:** {row.get('Work with Placement?', 'N/A')}")
                    st.write(f"**Est. Waitlist:** {row.get('Est. Waitlist Length', 'N/A')}")
                    st.write(f"**Community ID:** {row.get('CommunityID', 'N/A')}")
        
        # Show "View More" button if there are more than 5 in this tier
        if len(priority_communities) > 5:
            with st.expander(f"📋 View All {len(priority_communities)} Priority {priority_level} Communities"):
                display_cols = ['Type of Service', 'Town', 'State', 'Monthly Fee', 'Distance_miles', 'Rank_Within_Priority']
                available_cols = [col for col in display_cols if col in priority_communities.columns]
                st.dataframe(
                    priority_communities[available_cols],
                    use_container_width=True,
                    hide_index=True
                )

    # Download section
    st.markdown("---")
    st.subheader("📥 Download Results")

    col1, col2, col3 = st.columns(3)

    patient_name = prefs.get('name_of_patient', 'client').replace(' ', '_')
    
    with col1:
        # Download Priority 1 communities
        priority1_df = df[df['Priority_Level'] == 1]
        if len(priority1_df) > 0:
            download_cols = [col for col in ['Type of Service', 'Town', 'State', 'Monthly Fee',
                                             'Distance_miles', 'Rank_Within_Priority', 'Apartment Type',
                                             'Enhanced', 'Enriched', 'CommunityID'] if col in priority1_df.columns]
            csv_p1 = priority1_df[download_cols].to_csv(index=False)
            st.download_button(
                label=f"🥇 Priority 1 ({len(priority1_df)} communities)",
                data=csv_p1,
                file_name=f"priority1_{patient_name}.csv",
                mime="text/csv",
                use_container_width=True
            )
        else:
            st.info("No Priority 1 matches")

    with col2:
        # Download Priority 2 communities
        priority2_df = df[df['Priority_Level'] == 2]
        if len(priority2_df) > 0:
            download_cols = [col for col in ['Type of Service', 'Town', 'State', 'Monthly Fee',
                                             'Distance_miles', 'Rank_Within_Priority', 'Apartment Type',
                                             'Enhanced', 'Enriched', 'CommunityID'] if col in priority2_df.columns]
            csv_p2 = priority2_df[download_cols].to_csv(index=False)
            st.download_button(
                label=f"🥈 Priority 2 ({len(priority2_df)} communities)",
                data=csv_p2,
                file_name=f"priority2_{patient_name}.csv",
                mime="text/csv",
                use_container_width=True
            )
        else:
            st.info("No Priority 2 matches")
    
    with col3:
        # Download all results
        csv_all = df.to_csv(index=False)
        st.download_button(
            label=f"📊 All Results ({len(df)} total)",
            data=csv_all,
            file_name=f"all_matches_{patient_name}.csv",
            mime="text/csv",
            use_container_width=True
        )

    # Statistics by Priority Tier
    st.markdown("---")
    st.subheader("📈 Matching Statistics by Priority Tier")
    
    # Overall stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Matches", len(df))
    with col2:
        priority1_count = len(df[df['Priority_Level'] == 1])
        st.metric("Priority 1 (Contracted)", priority1_count)
    with col3:
        priority2_count = len(df[df['Priority_Level'] == 2])
        st.metric("Priority 2 (Partners)", priority2_count)
    with col4:
        priority3_count = len(df[df['Priority_Level'] == 3])
        st.metric("Priority 3 (Other)", priority3_count)
    
    # Detailed stats per priority
    st.markdown("#### 📊 Average Metrics by Priority Tier")
    
    stats_data = []
    for priority in [1, 2, 3]:
        priority_df = df[df['Priority_Level'] == priority]
        if len(priority_df) > 0:
            avg_distance = priority_df['Distance_miles'].mean() if 'Distance_miles' in priority_df.columns else None
            avg_fee = priority_df['Monthly Fee'].mean() if 'Monthly Fee' in priority_df.columns else None
            
            stats_data.append({
                'Priority Tier': f"Level {priority}",
                'Count': len(priority_df),
                'Avg Distance (mi)': f"{avg_distance:.1f}" if pd.notna(avg_distance) else "N/A",
                'Avg Monthly Fee': f"${int(avg_fee):,}" if pd.notna(avg_fee) else "N/A",
                'Closest Community (mi)': f"{priority_df['Distance_miles'].min():.1f}" if pd.notna(priority_df['Distance_miles'].min()) else "N/A"
            })
    
    if stats_data:
        st.table(pd.DataFrame(stats_data))
