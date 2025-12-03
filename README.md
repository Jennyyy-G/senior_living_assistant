# 🏠 Senior Living Placement Assistant  
### *AI-Powered Tool for Assisted Living Locators*  
**Simon Business School – MSAIB Capstone Project (Team 2)**

---

## 📌 Overview

The **Senior Living Placement Assistant** is an AI-powered application designed to streamline and automate the **senior living placement workflow** used by Assisted Living Locators (ALL).

Advisors often spend **30+ minutes** manually reviewing consultation calls and searching for communities.  
This tool reduces that to **3–4 minutes** through:

- 🎧 Automated audio transcription  
- 🧠 AI-based extraction of client preferences  
- 🏡 Community matching + ranking  
- 📍 Distance calculation via geolocation  
- 🤖 AI-generated explanations for matches  
- 📊 Easy CSV exports  

This project demonstrates the impact of **AI in business operations**, enabling higher advisor capacity and greater accuracy.

---

## 🚀 Features

### **🎧 1. Audio Upload & Transcription**
- Supports **MP3, M4A, WAV, MP4**
- Uses **OpenAI Whisper API** for accurate speech-to-text conversion  

---

### **🧠 2. AI Preference Extraction**
Automatically extracts structured details such as:

- Patient name & age  
- Required care level  
- Cognitive condition  
- Preferred locations  
- Monthly budget  
- Enhanced / Enriched care needs  
- Move-in window  
- Other important details  

Implemented in `app_final.py`.

---

### **🏡 3. Community Database Matching**
Pulls data from a **private Google Sheet** and filters based on:

- Care level requirements  
- Enhanced / enriched availability  
- Budget alignment  
- Placement partnership or contracted rates  
- Distance to preferred areas  

---

### **🎯 4. Priority Ranking**
Communities are ranked into:

- 🥇 **Priority 1** – Contracted Rates  
- 🥈 **Priority 2** – Placement Partners  
- 🥉 **Priority 3** – Other Communities  

Sorted by **priority tier and geolocation distance**.

---

### **💬 5. AI Match Explanations**
The app uses GPT to create **short, professional explanations** for why a community is a good fit.

---

### **📥 6. CSV Export Options**
Export:
- Priority 1 communities  
- Priority 2 communities  
- All matching communities  
- Top 5 recommendations  

---

## 📂 Project Structure

├── app_final.py # Main Streamlit application
├── APP_01.py # Prior version / backup version
├── requirements.txt # Python dependencies
└── README.md # Project documentation

---

## 🛠️ Installation

### **1. Clone the repository**
```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
## 🛠️ Installation

---
### **2. Create a Virtual Environment**
```bash
python3 -m venv env
source env/bin/activate       # Mac/Linux
env\Scripts\activate          # Windows

---
3. Install Dependencies
bash
Copy code
pip install -r requirements.txt
🔐 Required Secrets
Create a file:

bash
Copy code
.streamlit/secrets.toml
Add the following:

toml
Copy code
# OpenAI API
OPENAI_API_KEY = "sk-..."

# Google Cloud Service Account (JSON)
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
▶️ Running the App
bash
Copy code
streamlit run app_final.py
The app will open automatically at:

arduino
Copy code
http://localhost:8501
📸 App Workflow
📤 Upload audio consultation file

🎧 Transcribe using Whisper

🧠 Extract preferences with GPT-4

📊 Load community database

🏡 Filter + rank communities

🤖 Generate AI explanations

📥 Download CSV reports

📈 Business Value
⏱️ 88% reduction in advisor processing time

📈 +70% advisor capacity increase

🚀 Faster advisor responses → higher placement conversions

🎯 Increased accuracy and consistency in recommendations

🌎 Scalable to multi-region community databases

🧩 Tech Stack
Component	Technology
Frontend	Streamlit
AI Models	OpenAI Whisper + GPT-4
Database	Google Sheets
Geolocation	geopy, pgeocode
Processing	Python, pandas

🔮 Future Enhancements
🌐 Multi-region community search

🤝 CRM Integrations (Salesforce, HubSpot)

📧 Auto-send recommendation emails

🤖 Automated advisor follow-up

📱 Mobile app version

👥 Team Members – MSAIB Team 2
Fathima Gousiya

Carli Zollo

Jianing Gu

Peng

Maeve

📜 License
MIT License (or your preferred license)


