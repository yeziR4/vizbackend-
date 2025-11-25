import asyncio
import json
import os
from flask import Flask, jsonify, request
import aiohttp
from understat import Understat
from flask_cors import CORS
import time
import datetime

app = Flask(__name__)
CORS(app)

# Simple in-memory cache
cache = {}
CACHE_DURATION = 3600  # 1 hour in seconds

# Highlightly API Configuration
HIGHLIGHTLY_API_KEY = os.environ.get("HIGHLIGHTLY_API_KEY", "your-api-key-here")
HIGHLIGHTLY_BASE_URL = "https://api.highlightly.app/v1"

DEFAULT_SEASON = "2025"
LEAGUE_MAP = {
    "epl": ("EPL", "Premier League"),
    "laliga": ("La_liga", "La Liga"),
    "bundesliga": ("Bundesliga", "Bundesliga"),
    "seriea": ("Serie_A", "Serie A"),
    "ligue1": ("Ligue_1", "Ligue 1"),
}

# Map league keys to highlight API league names
HIGHLIGHTS_LEAGUE_MAP = {
    "epl": "Premier League",
    "laliga": "LaLiga",
    "bundesliga": "Bundesliga",
    "seriea": "Serie A",
    "ligue1": "Ligue 1",
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

def get_cache_key(season, league_key, data_type="goals"):
    """Generate cache key"""
    return f"{season}_{league_key}_{data_type}"

def get_from_cache(cache_key):
    """Get data from cache if not expired"""
    if cache_key in cache:
        data, timestamp = cache[cache_key]
        if time.time() - timestamp < CACHE_DURATION:
            age_minutes = int((time.time() - timestamp) / 60)
            print(f"✅ Cache HIT for {cache_key} (age: {age_minutes} min)")
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
# Highlights API Integration
# -------------------------------------------------------------
async def fetch_league_highlights(league_key, date=None, limit=40):
    """Fetch highlights for a specific league"""
    
    if league_key not in HIGHLIGHTS_LEAGUE_MAP:
        return {"error": "League not supported for highlights"}
    
    league_name = HIGHLIGHTS_LEAGUE_MAP[league_key]
    
    url = f"{HIGHLIGHTLY_BASE_URL}/highlights"
    
    headers = {
        "Authorization": f"Bearer {HIGHLIGHTLY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    params = {
        "leagueName": league_name,
        "limit": limit,
        "offset": 0
    }
    
    # Add date filter if provided
    if date:
        params["date"] = date
    
    print(f"🎬 Fetching highlights for {league_name}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    highlights = data.get("data", [])
                    print(f"✅ Found {len(highlights)} highlights for {league_name}")
                    return {
                        "league": league_name,
                        "highlights": highlights,
                        "pagination": data.get("pagination", {}),
                        "error": None
                    }
                else:
                    error_text = await response.text()
                    error_msg = f"API returned status {response.status}: {error_text}"
                    print(f"❌ {error_msg}")
                    return {"league": league_name, "highlights": [], "error": error_msg}
    except Exception as e:
        print(f"❌ ERROR fetching highlights for {league_name}: {e}")
        return {"league": league_name, "highlights": [], "error": str(e)}


async def search_match_highlights(home_team, away_team, date=None):
    """Search for highlights of a specific match"""
    
    url = f"{HIGHLIGHTLY_BASE_URL}/highlights"
    
    headers = {
        "Authorization": f"Bearer {HIGHLIGHTLY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    params = {
        "homeTeamName": home_team,
        "awayTeamName": away_team,
        "limit": 10
    }
    
    if date:
        params["date"] = date
    
    print(f"🎬 Searching highlights for {home_team} vs {away_team}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    highlights = data.get("data", [])
                    print(f"✅ Found {len(highlights)} highlights")
                    return {
                        "match": f"{home_team} vs {away_team}",
                        "highlights": highlights,
                        "error": None
                    }
                else:
                    error_text = await response.text()
                    error_msg = f"API returned status {response.status}: {error_text}"
                    print(f"❌ {error_msg}")
                    return {"highlights": [], "error": error_msg}
    except Exception as e:
        print(f"❌ ERROR searching match highlights: {e}")
        return {"highlights": [], "error": str(e)}


# -------------------------------------------------------------
# Flask Endpoints - Goals
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
    force_refresh = request.args.get("refresh", "false").lower() == "true"

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

    cache_key = get_cache_key(season, league_key, "goals")
    
    # Skip cache if force refresh
    if not force_refresh:
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


# -------------------------------------------------------------
# Flask Endpoints - Highlights
# -------------------------------------------------------------
@app.route("/api/highlights/<league>")
def api_league_highlights(league):
    """Get highlights for a specific league"""
    force_refresh = request.args.get("refresh", "false").lower() == "true"
    date = request.args.get("date")  # Optional: YYYY-MM-DD format
    limit = int(request.args.get("limit", 40))
    
    league_url = league.lower()
    
    if league_url in URL_ALIASES:
        league_key = URL_ALIASES[league_url]
    else:
        league_key = league_url
    
    if league_key not in HIGHLIGHTS_LEAGUE_MAP:
        return jsonify({
            "error": f"Highlights not available for: {league}",
            "available_leagues": list(HIGHLIGHTS_LEAGUE_MAP.keys())
        }), 400
    
    # Check cache
    cache_key = get_cache_key(date or "latest", league_key, "highlights")
    
    if not force_refresh:
        cached_data = get_from_cache(cache_key)
        if cached_data is not None:
            return jsonify(cached_data)
    
    # Fetch fresh highlights
    result = asyncio.run(fetch_league_highlights(league_key, date, limit))
    
    # Cache the result
    save_to_cache(cache_key, result)
    
    return jsonify(result)


@app.route("/api/highlights/match")
def api_match_highlights():
    """Search for highlights of a specific match"""
    home_team = request.args.get("homeTeam")
    away_team = request.args.get("awayTeam")
    date = request.args.get("date")  # Optional: YYYY-MM-DD
    
    if not home_team or not away_team:
        return jsonify({
            "error": "Both homeTeam and awayTeam parameters are required"
        }), 400
    
    result = asyncio.run(search_match_highlights(home_team, away_team, date))
    return jsonify(result)


# -------------------------------------------------------------
# Cache Management Endpoints
# -------------------------------------------------------------
@app.route("/api/cache/status")
def cache_status():
    """Check what's currently cached"""
    cached_items = []
    current_time = time.time()
    
    for cache_key, (data, timestamp) in cache.items():
        age_seconds = current_time - timestamp
        cached_items.append({
            "key": cache_key,
            "age_minutes": int(age_seconds / 60),
            "expires_in_minutes": int((CACHE_DURATION - age_seconds) / 60),
            "is_expired": age_seconds > CACHE_DURATION
        })
    
    return jsonify({
        "total_cached": len(cache),
        "cache_duration_minutes": int(CACHE_DURATION / 60),
        "items": cached_items
    })


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    """Clear all cached data"""
    count = len(cache)
    cache.clear()
    return jsonify({"message": "Cache cleared successfully", "cleared_items": count})


@app.route("/api/cache/clear/<league>", methods=["POST"])
def clear_league_cache(league):
    """Clear cache for a specific league"""
    season = str(request.args.get("season", DEFAULT_SEASON))
    data_type = request.args.get("type", "goals")  # "goals" or "highlights"
    
    league_url = league.lower()
    if league_url in URL_ALIASES:
        league_key = URL_ALIASES[league_url]
    else:
        league_key = league_url
    
    cache_key = get_cache_key(season, league_key, data_type)
    
    if cache_key in cache:
        del cache[cache_key]
        return jsonify({"message": f"Cache cleared for {league_key}", "key": cache_key})
    else:
        return jsonify({"message": "No cache found", "key": cache_key})


# -------------------------------------------------------------
# Health Check
# -------------------------------------------------------------
@app.route("/api/health")
def health_check():
    """Simple health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "cache_size": len(cache)
    })


if __name__ == "__main__":
    app.run(debug=True)
