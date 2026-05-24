"""
server.py — ToolStack Dashboard API server
Bridges dashboard.html with toolstack.db

Usage:
    pip install flask --break-system-packages
    python server.py

Then open dashboard.html in your browser.
"""

import sqlite3
import subprocess
import os
from datetime import datetime
from flask import Flask, jsonify, request

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "../toolstack.db")
PIPELINE_CMD = ["python", "main.py", "run"]
PIPELINE_CWD = os.path.join(os.path.dirname(__file__), "..")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── CORS headers so dashboard.html (file://) can call localhost:5050 ──
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/stats")
def stats():
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM pipeline_stats ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            return jsonify(dict(row))

        # Compute on the fly if no stats table
        total  = conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
        queued = conn.execute("SELECT COUNT(*) FROM tools WHERE queued=1").fetchone()[0]
        scripted = conn.execute("SELECT COUNT(*) FROM tools WHERE script_generated=1").fetchone()[0]
        skipped  = conn.execute("SELECT COUNT(*) FROM tools WHERE skipped=1").fetchone()[0]
        runs     = conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0]
        return jsonify({
            "total_seen":    total,
            "queued":        queued,
            "scripted":      scripted,
            "skipped":       skipped,
            "pipeline_runs": runs,
        })
    finally:
        conn.close()


@app.route("/queue")
def queue():
    limit = int(request.args.get("limit", 20))
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT name, url, source, source_url, score,
                   yt_video_count, script_generated
            FROM tools
            WHERE queued = 1
            ORDER BY score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route("/sources")
def sources():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM tools GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
        source_map = {"hn": "Hacker News", "gh": "GitHub", "rd": "Reddit", "ph": "Product Hunt"}
        data = {source_map.get(r["source"], r["source"]): r["cnt"] for r in rows}
        return jsonify(data)
    finally:
        conn.close()


@app.route("/runs")
def runs():
    limit = int(request.args.get("limit", 5))
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT run_at, found, gap_checked, queued, skipped
            FROM run_log
            ORDER BY run_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        result = []
        for r in rows:
            try:
                dt = datetime.fromisoformat(r["run_at"])
                ts = dt.strftime("%b %-d · %H:%M")
            except Exception:
                ts = r["run_at"]
            result.append({
                "ts":      ts,
                "found":   r["found"],
                "queued":  r["queued"],
                "skipped": r["skipped"],
            })
        return jsonify(result)
    finally:
        conn.close()


@app.route("/run", methods=["POST", "OPTIONS"])
def trigger_run():
    if request.method == "OPTIONS":
        return "", 204
    try:
        subprocess.Popen(PIPELINE_CMD, cwd=PIPELINE_CWD)
        return jsonify({"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print("ToolStack dashboard API running at http://localhost:5050")
    print(f"Reading from: {os.path.abspath(DB_PATH)}")
    app.run(host="0.0.0.0", port=5050, debug=False)
