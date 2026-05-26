# perf-coach

Personal performance dashboard. Tracks weight and habits.

## Run locally

### With the FastAPI backend (recommended)

1. Copy `.env.example` to `.env` and fill in your Neon connection strings:

       cp .env.example .env

2. Install Python dependencies:

       pip install -r requirements.txt

3. Start the server:

       ./run.sh

4. Visit http://localhost:8000

The server serves the static HTML pages and exposes `/api/health` to verify the DB connection.

### Static-only (no backend)

Open `index.html` in a browser, or serve the directory:

    python3 -m http.server 8080

Then visit http://localhost:8080
