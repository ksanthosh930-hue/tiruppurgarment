# 🏭 DigiGarment - Garment Automation & Job Board Platform

DigiGarment is a high-performance web platform built with FastAPI, PostgreSQL (Supabase), and modern JavaScript to automate garment business workflows and provide a specialized job board for the Tiruppur textile industry.

---

## 🚀 Deployment Guide (GitHub to Render)

### 1. Push to GitHub
Make sure your changes are committed and pushed to your GitHub repository:
```bash
git add .
git commit -m "Prepare for Render deployment with production config"
git push origin main
```

*(Note: `.env` is automatically ignored in `.gitignore` to keep your credentials safe).*

---

### 2. Deploy on Render (Render.com)

#### Option A: 1-Click Blueprint (Recommended)
1. Log in to [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** > **Blueprint**.
3. Connect your GitHub repository.
4. Render will automatically read [`render.yaml`](file:///d:/WEBSITE/render.yaml) and configure:
   - **Environment:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path:** `/health`
5. In the **Environment Variables** prompt, fill in:
   - `DATABASE_URL`: Your Supabase connection string from `.env`
   - `ADMIN_INITIAL_PASSWORD`: Your admin password
6. Click **Apply**.

---

#### Option B: Manual Web Service
1. Log in to [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** > **Web Service**.
3. Select your GitHub repository.
4. Set the following settings:
   - **Name:** `digigarment`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path:** `/health`
5. Under **Environment Variables**, add:
   - `PYTHON_VERSION` = `3.11.8`
   - `DATABASE_URL` = `postgresql://postgres.[ref]:[password]@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require`
   - `ADMIN_INITIAL_PASSWORD` = `[your-admin-password]`
   - `SECRET_KEY` = `[your-secret-key]`
6. Click **Create Web Service**.

---

## 🛠 Local Development Setup

1. **Clone repository:**
   ```bash
   git clone <repo-url>
   cd WEBSITE
   ```

2. **Setup virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure `.env` file:**
   Copy `.env.example` to `.env` and enter your database details:
   ```bash
   cp .env.example .env
   ```

4. **Start local server:**
   ```bash
   python app:app
   # or
   uvicorn app:app --reload --port 8000
   ```
   Open `http://127.0.0.1:8000` in your browser.
