# 🧰 ToolStack

> An automated pipeline for discovering, scoring, and producing YouTube content around newly released AI tools.

---

## What It Does

ToolStack is a full content production system built for the [ToolStack YouTube channel](https://youtube.com) — a channel dedicated to reviewing the latest AI tools as they drop. Instead of manually hunting for tools to cover, ToolStack does the legwork: sourcing, scoring, scripting, and staging everything for production.

---

## Pipeline Overview

```
Sources → Scoring → Script Generation → Production
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
A companion dashboard supports the full post-script workflow:
- **Voiceover generation** via ElevenLabs integration
- **B-roll sourcing** — visual reference gathering for each tool segment
- **Music curation** — mood-matched background track suggestions

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python |
| Script Generation | Claude API (Anthropic) |
| Voiceover | ElevenLabs API |
| Sources | Hacker News API, Reddit API, GitHub Trending, Product Hunt API |
| Dashboard | *(In progress)* |

---

## Project Structure

```
toolstack/
├── sources/
│   ├── hackernews.py
│   ├── reddit.py
│   ├── github_trending.py
│   └── producthunt.py
├── scoring/
│   ├── youtube_gap.py
│   └── freshness.py
├── pipeline/
│   ├── runner.py
│   └── ranker.py
├── scripts/
│   └── generator.py          # Claude API integration
├── production/
│   ├── voiceover.py          # ElevenLabs integration
│   ├── broll_sourcer.py
│   └── music_curator.py
├── dashboard/                # Production UI
├── config.py
└── README.md
```

---

## Setup

```bash
git clone https://github.com/yourusername/toolstack.git
cd toolstack
pip install -r requirements.txt
```

Set your environment variables:

```bash
ANTHROPIC_API_KEY=your_key
ELEVENLABS_API_KEY=your_key
REDDIT_CLIENT_ID=your_id
REDDIT_CLIENT_SECRET=your_secret
PRODUCTHUNT_TOKEN=your_token
```

Run the pipeline:

```bash
python pipeline/runner.py
```

---

## Status

| Module | Status |
|---|---|
| Source scrapers | ✅ Complete |
| Scoring engine | ✅ Complete |
| Script generator | ✅ Complete |
| ElevenLabs integration | ✅ Complete |
| Production dashboard | 🔄 In progress |

---

## About

Built by **ApMakes** — a TPM and builder at the intersection of AI tools, content, and systems thinking.

📺 [ToolStack on YouTube](#) · 🐙 [GitHub](https://github.com/yourusername)
