# Voice Generator Panel — Deployment Guide

Complete instructions to deploy this app on **Streamlit Community Cloud**.

---

## Prerequisites

| Tool | Purpose |
|------|---------|
| GitHub account | Host the code repository |
| Google Cloud account | Service account for Google Sheets API |
| ElevenLabs account | API key + cloned voice ID |
| Streamlit Community Cloud account | Free hosting at [share.streamlit.io](https://share.streamlit.io) |

---

## Step 1 — Google Cloud Setup (Service Account)

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or use an existing one).
3. Enable **Google Drive API** and **Google Sheets API**:
   - Navigation menu → *APIs & Services* → *Library* → search and enable both.
4. Create a Service Account:
   - *APIs & Services* → *Credentials* → **Create Credentials** → *Service account*.
   - Give it a name (e.g., `voice-panel-sa`), click **Create and Continue**, then **Done**.
5. Create a JSON key:
   - Click the service account → *Keys* tab → **Add Key** → *Create new key* → **JSON**.
   - Download the JSON file — you'll need the values inside for `secrets.toml`.

---

## Step 2 — Google Sheets Setup

1. Create a new Google Sheet.
2. Rename the first worksheet tab to **`Logs`**.
3. Add these headers in row 1:

   | A | B | C | D |
   |---|---|---|---|
   | Timestamp | User | Voice | Prompt |

4. **Share the sheet** with the `client_email` from your service account JSON (give it **Editor** access).
5. Copy the spreadsheet URL — you'll need it for `secrets.toml`.

---

## Step 3 — ElevenLabs Setup

1. Sign in at [elevenlabs.io](https://elevenlabs.io).
2. Go to *Profile + API Key* and copy your **API Key**.
3. Go to *Voices* → find your cloned voice → copy the **Voice ID** (from the URL or voice settings).

---

## Step 4 — Push to GitHub

```bash
# Create a new repository on GitHub, then:
git init
git add app.py requirements.txt .streamlit/secrets.toml.example DEPLOY.md .gitignore
git commit -m "Initial commit — Voice Generator Panel MVP"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

> ⚠️ **Never commit `.streamlit/secrets.toml`** — it's in `.gitignore`.

---

## Step 5 — Deploy on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **New app** → select your repo, branch `main`, and file `app.py`.
3. Before deploying, click **Advanced settings** → **Secrets**.
4. Paste the full contents of your `secrets.toml` (use `.streamlit/secrets.toml.example` as template):

```toml
[elevenlabs]
api_key   = "sk_REAL_KEY"
voice_id  = "REAL_VOICE_ID"

[users.chatter1]
password = "secure_pass_1"
role     = "chatter"

[users.chatter2]
password = "secure_pass_2"
role     = "chatter"

[users.chatter3]
password = "secure_pass_3"
role     = "chatter"

[users.chatter4]
password = "secure_pass_4"
role     = "chatter"

[users.Manager_Laila]
password = "secure_pass_mgr"
role     = "manager"

[users.Danilo_CEO]
password = "secure_pass_ceo"
role     = "ceo"

[connections.gsheets]
spreadsheet = "https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit"
worksheet   = "0"
type        = "service_account"
project_id  = "your-project-id"
private_key_id = "key-id-from-json"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "voice-panel-sa@your-project.iam.gserviceaccount.com"
client_id   = "123456789"
auth_uri    = "https://accounts.google.com/o/oauth2/auth"
token_uri   = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
```

5. Click **Deploy!**

---

## Step 6 — Run Locally (Optional)

```bash
# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Copy the secrets template and fill in your values
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
# Edit .streamlit/secrets.toml with your real credentials

# Run the app
streamlit run app.py
```

The app will open at `http://localhost:8501`.

---

## Cost Reference

ElevenLabs charges approximately **$0.00004 per character** (varies by plan). The Admin Dashboard tracks estimated costs automatically. Monitor your ElevenLabs dashboard for exact billing.
