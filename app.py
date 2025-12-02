import os
import json
import time
import traceback
from flask import Flask, jsonify, request
from flask_cors import CORS

# --- PATCH for Selenium set_headless issue (must run BEFORE understatapi import) ---
# Some versions of understatapi call opts.set_headless(), which doesn't exist in newer Selenium.
# This patch adds a set_headless method to Chrome Options if it is missing.
try:
    from selenium.webdriver.chrome.options import Options as _ChromeOptions
    if not hasattr(_ChromeOptions, "set_headless"):
        def _set_headless(self):
            # modern selenium expects add_argument instead
            self.add_argument("--headless")
        _ChromeOptions.set_headless = _set_headless
except Exception:
    # If selenium isn't installed or import fails, ignore — this is just a defensive patch.
    pass

# Now import UnderstatClient safely
from understatapi import UnderstatClient

# Flask app
app = Flask(__name__)
CORS(app)

# ---------- Simple in-memory cache ----------
cache = {}
CACHE_DURATION = int(os.environ.get("CACHE_DURATION_SECONDS", 60 * 60))  # default 1 hour

# ---------- Config & maps ----------
DEFAULT_SEASON = os.environ.get("DEFAULT_SEASON", "2025")

LEAGUE_MAP = {
    "epl": ("EPL", "Premier League"),
    "laliga": ("La_liga", "La Liga"),
    "bundesliga": ("Bundesliga", "Bundesliga"),
    "seriea": ("Serie_A", "Serie A"),
    "ligue1": ("Ligue_1", "Ligue 1"),
}

URL_ALIASES = {
    "epl": "epl",
    "la_liga": "laliga",
    "laliga": "laliga",
    "bundesliga": "bundesliga",
    "serie_a": "seriea",
    "seriea": "seriea",
    "ligue_1": "ligue1",
    "ligue1": "ligue1",
}

# Load mock data (optional)
def load_mock_data():
    possible_files = [
        'premier_league_goals_2025_2026 (2).json',
        'premier_league_goals_2025_2026.json',
        'mock_data.json'
    ]
    for filename in possible_files:
        try:
            file_path = os.path.join(os.path.dirname(__file__), filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and "epl" in data:
                    return data
                # normalize to { "epl": { "league": "...", "goals": [..] } }
                if isinstance(data, list):
                    goals = data
                elif isinstance(data, dict) and "goals" in data:
                    goals = data["goals"]
                else:
                    goals = data
                return {
                    "epl": {
                        "league": "Premier League",
                        "goals": goals,
                        "is_mock": True
                    }
                }
        except Exception:
            continue
    return {}

MOCK_DATA = load_mock_data()

# ---------- Cache helpers ----------
def get_cache_key(season, league_key):
    return f"{season}_{league_key}_goals"

def get_from_cache(cache_key):
    item = cache.get(cache_key)
    if not item:
        return None
    data, ts = item
    if time.time() - ts < CACHE_DURATION:
        return data
    # expired
    del cache[cache_key]
    return None

def save_to_cache(cache_key, data):
    cache[cache_key] = (data, time.time())

# ---------- Core synchronous fetcher (single league) ----------
def fetch_league_goals_sync(league_code, league_name, season_str):
    """
    Synchronous fetch using UnderstatClient (keeps logic close to your working script).
    Returns a dict: {"league": league_name, "goals": [...], "error": None}
    """
    try:
        goals = []
        with UnderstatClient() as understat:
            teams_data = understat.league(league=league_code).get_team_data(season=season_str)
            team_names = [teams_data[team]['title'].replace(' ', '_') for team in teams_data]

            all_matches = []
            for team_name in team_names:
                try:
                    team_matches = understat.team(team=team_name).get_match_data(season=season_str)
                    all_matches.extend(team_matches)
                except Exception as e:
                    # non-fatal, continue with other teams
                    print(f"Could not fetch matches for {team_name}: {e}")

            # dedupe
            unique_matches = list({m['id']: m for m in all_matches}.values())

            for idx, match_info in enumerate(unique_matches, start=1):
                match_id = match_info.get('id')
                match_date = match_info.get('datetime', None)
                home_team = match_info['h']['title'] if match_info.get('h') else None
                away_team = match_info['a']['title'] if match_info.get('a') else None

                try:
                    shots = understat.match(match=match_id).get_shot_data()
                    all_shots = shots.get('h', []) + shots.get('a', [])
                    for shot in all_shots:
                        if shot.get('result') == 'Goal':
                            goals.append({
                                "id": shot.get('id'),
                                "x": float(shot.get('X', 0)) if shot.get('X') is not None else 0.0,
                                "y": float(shot.get('Y', 0)) if shot.get('Y') is not None else 0.0,
                                "player": shot.get('player'),
                                "minute": int(shot.get('minute', 0)) if shot.get('minute') is not None else 0,
                                "match_id": match_id,
                                "team": shot.get('h_team') if shot.get('h_a') == 'h' else shot.get('a_team'),
                                "opponent": shot.get('a_team') if shot.get('h_a') == 'h' else shot.get('h_team'),
                                "xg": float(shot.get('xG', 0)) if shot.get('xG') is not None else 0.0,
                                "situation": shot.get('situation'),
                                "shotType": shot.get('shotType'),
                                "match_date": match_date,
                                "home_team": home_team,
                                "away_team": away_team
                            })
                except Exception as e:
                    print(f"Warning: could not fetch shots for match {match_id}: {e}")
                    continue

        return {"league": league_name, "goals": goals, "error": None, "is_mock": False}

    except Exception as e:
        tb = traceback.format_exc()
        print("ERROR in fetch_league_goals_sync:", e, tb)
        return {"league": league_name, "goals": [], "error": str(e)}

# ---------- Flask routes ----------
@app.route("/api/goals/<league>")
def api_single_league(league):
    """
    Main endpoint for single-league requests.
    Params:
      - season (optional)
      - refresh=true (optional) to bypass cache
      - mock=true (optional) to return mock data if available
    """
    season_param = request.args.get("season", DEFAULT_SEASON)
    try:
        season = int(season_param)
    except (ValueError, TypeError):
        season = int(DEFAULT_SEASON)
    season_str = str(season)

    force_refresh = request.args.get("refresh", "false").lower() == "true"
    use_mock = request.args.get("mock", "false").lower() == "true"

    league_url = league.lower()
    if league_url in URL_ALIASES:
        league_key = URL_ALIASES[league_url]
    else:
        league_key = league_url

    if league_key not in LEAGUE_MAP:
        return jsonify({"error": f"Unknown league: {league}", "valid_leagues": list(URL_ALIASES.keys())}), 400

    # Return mock data if requested and available
    if use_mock and league_key in MOCK_DATA:
        return jsonify({"season": season_str, "data": MOCK_DATA[league_key]})

    cache_key = get_cache_key(season_str, league_key)
    if not force_refresh:
        cached = get_from_cache(cache_key)
        if cached is not None:
            return jsonify(cached)

    # Fetch live (single-league) synchronously (UnderstatClient is synchronous)
    league_code, league_name = LEAGUE_MAP[league_key]
    result = fetch_league_goals_sync(league_code, league_name, season_str)

    response_data = {"season": season_str, "data": result}
    # only cache successful non-error results
    if not result.get("error"):
        save_to_cache(cache_key, response_data)

    return jsonify(response_data)

@app.route("/api/mock/<league>")
def api_mock(league):
    # simple mock endpoint
    league_url = league.lower()
    if league_url in URL_ALIASES:
        league_key = URL_ALIASES[league_url]
    else:
        league_key = league_url

    if league_key in MOCK_DATA:
        return jsonify({"season": DEFAULT_SEASON, "data": MOCK_DATA[league_key]})
    else:
        return jsonify({
            "season": DEFAULT_SEASON,
            "data": {
                "league": LEAGUE_MAP.get(league_key, ("Unknown", "Unknown"))[1],
                "goals": [],
                "is_mock": True,
                "message": "No mock data available for this league."
            }
        })

@app.route("/api/cache/status")
def cache_status():
    items = []
    now = time.time()
    for key, (data, ts) in cache.items():
        items.append({
            "key": key,
            "age_minutes": int((now - ts) / 60),
            "expires_in_minutes": int((CACHE_DURATION - (now - ts)) / 60),
            "is_expired": now - ts > CACHE_DURATION
        })
    return jsonify({"total_cached": len(cache), "items": items})

@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    count = len(cache)
    cache.clear()
    return jsonify({"message": "Cache cleared", "cleared": count})

@app.route("/api/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "cache_size": len(cache),
        "mock_data_loaded": bool(MOCK_DATA)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
