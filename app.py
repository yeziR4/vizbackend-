import os
import json
import time
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ------------------------
# LOAD MOCK DATA
# ------------------------

MOCK_FILE = "premier_league_goals_2025_202644.json"

def load_mock_goals():
    """Load mock Premier League goals from JSON file."""
    path = os.path.join(os.path.dirname(__file__), MOCK_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"✅ Loaded mock goals from {MOCK_FILE}")
            return data
    except Exception as e:
        print(f"❌ Could not load mock file: {e}")
        return []

MOCK_GOALS = load_mock_goals()

# ------------------------
# SIMPLE CACHE (still useful)
# ------------------------

cache = {}
CACHE_DURATION = 3600  # 1 hour

def get_cache(key):
    if key in cache:
        value, timestamp = cache[key]
        if time.time() - timestamp < CACHE_DURATION:
            return value
    return None

def set_cache(key, value):
    cache[key] = (value, time.time())

# ------------------------
# GOALS ENDPOINT (MOCK ONLY)
# ------------------------

@app.route("/api/goals/<league>")
def get_goals(league):
    """
    Always returns the mock Premier League data.
    The <league> argument is ignored for now (for your screenshots).
    """

    force_refresh = request.args.get("refresh", "false").lower() == "true"
    cache_key = f"mock_goals_{league}"

    if not force_refresh:
        cached = get_cache(cache_key)
        if cached:
            return jsonify(cached)

    response = {
        "season": "2025",
        "league": league,
        "data": {
            "league": "Premier League",
            "goals": MOCK_GOALS,
            "is_mock": True
        }
    }

    set_cache(cache_key, response)
    return jsonify(response)

# ------------------------
# BASIC MOCK MATCH HIGHLIGHTS ENDPOINT
# (Does nothing but keeps your frontend from breaking)
# ------------------------

@app.route("/api/highlights/<league>")
def get_highlights(league):
    return jsonify({
        "league": league,
        "highlights": [],
        "error": "Highlights disabled in mock mode"
    })

# ------------------------
# AI ENDPOINT (KEPT AS-IS)
# ------------------------

@app.route("/api/ai/ask", methods=["POST"])
def ai_ask():
    data = request.get_json()
    question = data.get("question", "")

    return jsonify({
        "answer": "AI disabled in mock mode for now.",
        "search_used": False,
        "data_used": False
    })

# ------------------------
# CACHE STATUS
# ------------------------

@app.route("/api/cache/status")
def cache_status():
    items = []
    for key, (value, ts) in cache.items():
        items.append({
            "key": key,
            "age_minutes": int((time.time() - ts) / 60)
        })
    return jsonify({
        "total_cached": len(cache),
        "items": items
    })

@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    size = len(cache)
    cache.clear()
    return jsonify({"message": "Cache cleared", "items_removed": size})

# ------------------------
# HEALTH ENDPOINT
# ------------------------

@app.route("/api/health")
def health():
    return jsonify({
        "status": "healthy",
        "mock_file_loaded": len(MOCK_GOALS),
        "cache_items": len(cache),
        "message": "Mock backend running"
    })

# ------------------------

if __name__ == "__main__":
    app.run(debug=True)
