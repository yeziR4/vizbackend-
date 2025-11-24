import asyncio
import json
from flask import Flask, jsonify, request
import aiohttp
from understat import Understat
from flask_cors import CORS
import time

app = Flask(__name__)
CORS(app)

# Simple in-memory cache
cache = {}
CACHE_DURATION = 3600  # 1 hour in seconds

DEFAULT_SEASON = "2025"
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

def get_cache_key(season, league_key):
    """Generate cache key"""
    return f"{season}_{league_key}"

def get_from_cache(cache_key):
    """Get data from cache if not expired"""
    if cache_key in cache:
        data, timestamp = cache[cache_key]
        if time.time() - timestamp < CACHE_DURATION:
            print(f"✅ Cache HIT for {cache_key}")
            return data
    print(f"❌ Cache MISS for {cache_key}")
    return None

def save_to_cache(cache_key, data):
    """Save data to cache with timestamp"""
    cache[cache_key] = (data, time.time())
    print(f"💾 Cached {cache_key}")

# -------------------------------------------------------------
# Core async worker: fetch goals for a single league
# -------------------------------------------------------------
async def fetch_league_goals(session, league_code, league_name, season):
    understat = Understat(session)

    print(f"\n📌 Fetching {league_name} {season}-{int(season)+1}")

    try:
        results = await understat.get_league_results(league_code, season)
    except Exception as e:
        print(f"❌ ERROR fetching results for {league_name}: {e}")
        return {"league": league_name, "goals": [], "error": str(e)}

    all_goals = []

    for match in results:
        match_id = match.get("id")
        if not match_id:
            continue

        try:
            shots = await understat.get_match_shots(match_id)
        except Exception as e:
            print(f"⚠️ Could not fetch shots for match {match_id}: {e}")
            continue

        all_shots = shots["h"] + shots["a"]

        for shot in all_shots:
            if shot["result"] != "Goal":
                continue

            all_goals.append({
                "id": shot["id"],
                "x": float(shot["X"]),
                "y": float(shot["Y"]),
                "player": shot["player"],
                "minute": shot["minute"],
                "match_id": match_id,
                "team": shot["h_team"] if shot["h_a"] == "h" else shot["a_team"],
                "opponent": shot["a_team"] if shot["h_a"] == "h" else shot["h_team"],
                "xg": float(shot["xG"]),
                "situation": shot.get("situation", "Unknown"),
                "shotType": shot.get("shotType", "Unknown"),
                "match_date": match.get("datetime"),
            })

        await asyncio.sleep(0.2)

    print(f"✅ {league_name}: collected {len(all_goals)} goals")
    return {"league": league_name, "goals": all_goals, "error": None}


async def fetch_all_leagues(season, leagues=None):
    season = str(season)

    if leagues is None:
        leagues = list(LEAGUE_MAP.keys())

    async with aiohttp.ClientSession() as session:
        tasks = []

        for league_key in leagues:
            code, name = LEAGUE_MAP[league_key]
            tasks.append(fetch_league_goals(session, code, name, season))

        return await asyncio.gather(*tasks)


# -------------------------------------------------------------
# Flask Endpoints
# -------------------------------------------------------------
@app.route("/api/goals")
def api_goals():
    season = str(request.args.get("season", DEFAULT_SEASON))
    leagues = request.args.get("leagues")

    if leagues:
        leagues = [l.strip().lower() for l in leagues.split(",")]
    else:
        leagues = list(LEAGUE_MAP.keys())

    results = asyncio.run(fetch_all_leagues(season, leagues))
    return jsonify({"season": season, "data": results})


@app.route("/api/goals/<league>")
def api_single_league(league):
    season = str(request.args.get("season", DEFAULT_SEASON))

    league_url = league.lower()
    
    if league_url in URL_ALIASES:
        league_key = URL_ALIASES[league_url]
    else:
        league_key = league_url
    
    if league_key not in LEAGUE_MAP:
        return jsonify({
            "error": f"Unknown league: {league}",
            "valid_leagues": list(URL_ALIASES.keys())
        }), 400

    # Check cache first
    cache_key = get_cache_key(season, league_key)
    cached_data = get_from_cache(cache_key)
    
    if cached_data is not None:
        return jsonify(cached_data)

    # Fetch fresh data
    print(f"🔄 Fetching fresh data for {league_key}...")
    results = asyncio.run(fetch_all_leagues(season, [league_key]))
    response_data = {"season": season, "data": results[0]}
    
    # Save to cache
    save_to_cache(cache_key, response_data)
    
    return jsonify(response_data)


if __name__ == "__main__":
    app.run(debug=True)
