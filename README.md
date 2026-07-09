# 🧰 ToolStack

> An automated pipeline for discovering, scoring, and producing YouTube content around newly released AI tools.

---

## What It Does

ToolStack is a full content production system built for the [ToolStack YouTube channel] — a channel dedicated to reviewing the latest AI tools as they drop. Instead of manually hunting for tools to cover, ToolStack does the legwork: sourcing, scoring, scripting, and staging everything for production.

---

## Pipeline Overview

```
Sources → Scoring → Script Generation → Production Dashboard
```

### 1. 🔍 Discovery & Sourcing

Pulls newly released AI tools from:

- **Hacker News** — Show HN posts and launch threads
- **Reddit** — r/MachineLearning, r/artificial, r/SideProject, and more
- **GitHub** — Trending repos tagged with AI/ML
- **Product Hunt** — Daily launches filtered for AI tools

### 2. 📊 Scoring & Ranking

Each tool is evaluated against two signals:

- **YouTube Gap Score** — How underrepresented is this tool in existing YouTube content?
- **Freshness Score** — How recently was it released or trending?

Tools are ranked by a composite score to surface the highest-opportunity picks.

### 3. ✍️ Script Generation

Top-ranked tools are passed to the **Claude API** to generate structured video review scripts, including:

- Hook and intro framing
- Feature walkthrough
- Use case scenarios
- Honest take / verdict

### 4. 🎬 Production Dashboard

A local dashboard (`dashboard/dashboard.html`) provides a live view of the pipeline, powered by a lightweight Flask API server (`dashboard/server.py`):

- **Queue view** — All queued tools ranked by composite score with script status
- **Source breakdown** — Discovery distribution across HN, GitHub, Reddit, and Product Hunt
- **Run history** — Per-run stats with found / queued / skipped counts
- **Voiceover generation** via ElevenLabs integration
- **B-roll sourcing** — Visual reference gathering for each tool segment
- **Music curation** — Mood-matched background track suggestions

---

## Tech Stack

| Layer              | Tool                                                           |
|--------------------|----------------------------------------------------------------|
| Language           | Python                                                         |
| Script Generation  | Claude API (Anthropic)                                         |
| Voiceover          | ElevenLabs API                                                 |
| Sources            | Hacker News API, Reddit API, GitHub Trending, Product Hunt API |
| Dashboard API      | Flask                                                          |
| Dashboard UI       | HTML / Chart.js                                                |
| Queue & Storage    | SQLite                                                         |

---

## Project Structure

```
Youtube-AutoContent/
├── toolstack/
│   ├── connectors/
│   │   ├── hackernews.py
│   │   ├── reddit.py
│   │   ├── github.py
│   │   └── producthunt.py
│   ├── filters/
│   │   └── gap_check.py
│   ├── scoring/
│   │   └── scorer.py
│   ├── queue/
│   │   └── manager.py
│   ├── utils/
│   │   └── script_generator.py    # Claude API integration
│   ├── production/
│   │   ├── voiceover.py           # ElevenLabs integration
│   │   ├── broll_sourcer.py
│   │   └── music_curator.py
│   ├── models.py
│   └── config.py
├── dashboard/
│   ├── dashboard.html             # Production UI
│   └── server.py                  # Flask API — reads from toolstack.db
├── main.py                        # Pipeline orchestrator
├── requirements.txt
└── README.md
```

---

## Setup

```bash
git clone https://github.com/Apirith/Youtube-AutoContent.git
cd Youtube-AutoContent
pip install -r requirements.txt
```

Set your environment variables in a `.env` file:

```bash
ANTHROPIC_API_KEY=your_key
ELEVENLABS_API_KEY=your_key
REDDIT_CLIENT_ID=your_id
REDDIT_CLIENT_SECRET=your_secret
PRODUCTHUNT_TOKEN=your_token
PEXELS_API_KEY=your_key
```

---

## Usage

```bash
# Discover tools, score, queue, and auto-generate scripts for top picks
python main.py run

# Generate scripts for all queued tools not yet scripted
python main.py generate

# Generate a script for a specific tool by URL
python main.py script <tool_url>

# Show current queue
python main.py queue

# Show pipeline stats
python main.py stats

# Run automatically every 6 hours
python main.py schedule
```

---

## Dashboard

```bash
pip install flask
python dashboard/server.py
```

Then open `dashboard/dashboard.html` in your browser. The dashboard auto-refreshes every 60 seconds and the **Run pipeline** button triggers `main.py run` directly from the UI.

---

## Status

| Module                 | Status         |
|------------------------|----------------|
| Source scrapers        | ✅ Complete     |
| Scoring engine         | ✅ Complete     |
| Script generator       | ✅ Complete     |
| ElevenLabs integration | ✅ Complete     |
| Production dashboard   | ✅ Complete     |
