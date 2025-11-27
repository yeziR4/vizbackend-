import asyncio
import json
import os
from flask import Flask, jsonify, request
import aiohttp
from understat import Understat
from flask_cors import CORS
import time
import datetime
from google import genai

app = Flask(__name__)
CORS(app)

# Simple in-memory cache
cache = {}
CACHE_DURATION = 3600  # 1 hour in seconds

# API Configuration
HIGHLIGHTLY_API_KEY = os.environ.get("HIGHLIGHTLY_API_KEY", "your-api-key-here")
HIGHLIGHTLY_BASE_URL = "https://api.highlightly.app/v1"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "your-gemini-api-key")

DEFAULT_SEASON = "2025"
LEAGUE_MAP = {
    "epl": ("EPL", "Premier League"),
    "laliga": ("La_liga", "La Liga"),
    "bundesliga": ("Bundesliga", "Bundesliga"),
    "seriea": ("Serie_A", "Serie A"),
    "ligue1": ("Ligue_1", "Ligue 1"),
}

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

# Load mock data from JSON file
def load_mock_data():
    """Load mock data from JSON file"""
    # List of possible filenames to try
    possible_files = [
        'premier_league_goals_2025_2026 (2).json',
        'premier_league_goals_2025_2026.json',
        'mock_data.json'
    ]
    
    for filename in possible_files:
        try:
            file_path = os.path.join(os.path.dirname(__file__), filename)
            with open(file_path, 'r') as f:
                data = json.load(f)
                print(f"✅ Loaded data from {filename}")
                
                # Handle different data structures
                if isinstance(data, list):
                    # If it's just a list of goals
                    goals = data
                elif isinstance(data, dict):
                    # If it has a structure already
                    if "epl" in data:
                        return data  # Already in correct format
                    elif "goals" in data:
                        goals = data["goals"]
                    else:
                        goals = data
                else:
                    goals = []
                
                # Return in our standard format
                return {
                    "epl": {
                        "league": "Premier League",
                        "goals": goals,
                        "is_mock": False
                    }
                }
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"⚠️ Could not load {filename}: {e}")
            continue
    
    print("⚠️ No data files found, returning empty mock data")
    return {}

MOCK_DATA = load_mock_data()

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
                "home_team": match.get("h", {}).get("title"),
                "away_team": match.get("a", {}).get("title"),
            })

        await asyncio.sleep(0.2)

    print(f"✅ {league_name}: collected {len(all_goals)} goals")
    return {"league": league_name, "goals": all_goals, "error": None, "is_mock": False}


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
async def fetch_match_highlights_by_teams(home_team, away_team, date=None):
    """Fetch highlights for a specific match by team names"""
    
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
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", [])
                else:
                    return []
    except Exception as e:
        print(f"⚠️ Error fetching match highlights: {e}")
        return []


async def enrich_goals_with_highlights(goals, league_key):
    """Enrich goal data with match highlights"""
    
    matches = {}
    for goal in goals:
        match_key = f"{goal.get('home_team')}_{goal.get('away_team')}_{goal.get('match_date')}"
        if match_key not in matches:
            matches[match_key] = {
                "home_team": goal.get("home_team"),
                "away_team": goal.get("away_team"),
                "date": goal.get("match_date", "").split("T")[0] if goal.get("match_date") else None,
                "goals": []
            }
        matches[match_key]["goals"].append(goal)
    
    print(f"🎬 Enriching {len(goals)} goals from {len(matches)} matches with highlights...")
    
    highlights_cache = {}
    
    for match_key, match_data in matches.items():
        home = match_data["home_team"]
        away = match_data["away_team"]
        date = match_data["date"]
        
        if not home or not away:
            continue
        
        cache_key = f"{home}_{away}_{date}"
        
        if cache_key not in highlights_cache:
            highlights = await fetch_match_highlights_by_teams(home, away, date)
            highlights_cache[cache_key] = highlights
            await asyncio.sleep(0.1)
        
        match_highlights = highlights_cache[cache_key]
        
        for goal in match_data["goals"]:
            goal["match_highlights"] = match_highlights
            goal["goal_highlights"] = []
            player_name = goal.get("player", "").lower()
            minute = goal.get("minute", 0)
            
            for highlight in match_highlights:
                title = highlight.get("title", "").lower()
                description = highlight.get("description", "").lower()
                
                if player_name in title or player_name in description:
                    goal["goal_highlights"].append({
                        "id": highlight.get("id"),
                        "title": highlight.get("title"),
                        "url": highlight.get("url"),
                        "embedUrl": highlight.get("embedUrl"),
                        "source": highlight.get("source"),
                        "type": highlight.get("type"),
                        "relevance": "player_match"
                    })
                elif f"{int(minute)}'" in title or f"{int(minute)} min" in title.lower():
                    goal["goal_highlights"].append({
                        "id": highlight.get("id"),
                        "title": highlight.get("title"),
                        "url": highlight.get("url"),
                        "embedUrl": highlight.get("embedUrl"),
                        "source": highlight.get("source"),
                        "type": highlight.get("type"),
                        "relevance": "minute_match"
                    })
    
    print(f"✅ Enrichment complete")
    return goals


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
# AI Assistant with Gemini
# -------------------------------------------------------------
def get_data_summary():
    """Get summary of available cached data for AI context"""
    summary = {
        "available_leagues": list(LEAGUE_MAP.keys()),
        "cached_data": []
    }
    
    for cache_key in cache.keys():
        if "goals" in cache_key:
            data, timestamp = cache[cache_key]
            age_minutes = int((time.time() - timestamp) / 60)
            summary["cached_data"].append({
                "key": cache_key,
                "age_minutes": age_minutes,
                "goal_count": len(data.get("data", {}).get("goals", []))
            })
    
    return summary

async def ask_gemini_with_search(question):
    """Ask Gemini with web search capabilities for all questions"""
    
    try:
        # Initialize Gemini client
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Build a clean, professional prompt
        system_context = """You are a professional football analytics expert. 

Key guidelines for your responses:
- Provide clear, direct answers without preambles like "According to..."
- Use clean formatting without asterisks or markdown symbols
- Be precise and factual
- Use web search to get current, accurate information
- Present statistics and data professionally
- Keep responses concise but informative

When answering:
- State facts directly
- Use numbers and statistics when relevant
- Provide context when needed
- Be authoritative but accessible"""
        
        user_prompt = f"{system_context}\n\nQuestion: {question}\n\nProvide a professional, well-formatted answer."
        
        # Generate response with search grounding enabled
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
            config={
                "search_grounding": True  # Enable web search
            }
        )
        
        # Clean up the response text
        answer_text = response.text
        
        # Remove common markdown symbols and clean formatting
        answer_text = answer_text.replace("**", "")  # Remove bold
        answer_text = answer_text.replace("*", "")   # Remove asterisks
        answer_text = answer_text.replace("##", "")  # Remove headers
        answer_text = answer_text.replace("#", "")   # Remove headers
        
        # Remove phrases like "According to the cache data"
        phrases_to_remove = [
            "According to the cache data,",
            "Based on the cached data,",
            "From the data provided,",
            "According to the data,",
            "Based on the available data,"
        ]
        for phrase in phrases_to_remove:
            answer_text = answer_text.replace(phrase, "")
        
        # Clean up extra whitespace
        answer_text = " ".join(answer_text.split())
        answer_text = answer_text.strip()
        
        return {
            "answer": answer_text,
            "search_used": True,
            "data_used": False
        }
    
    except Exception as e:
        print(f"❌ Gemini API error: {e}")
        return {
            "answer": f"I apologize, but I encountered an error: {str(e)}",
            "search_used": False,
            "data_used": False,
            "error": str(e)
        }


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
    include_highlights = request.args.get("highlights", "false").lower() == "true"
    use_mock = request.args.get("mock", "false").lower() == "true"

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

    # Return mock data if requested
    if use_mock and league_key in MOCK_DATA:
        print(f"📦 Returning mock data for {league_key}")
        return jsonify({"season": season, "data": MOCK_DATA[league_key]})

    cache_key = get_cache_key(season, league_key, "goals_with_highlights" if include_highlights else "goals")
    
    if not force_refresh:
        cached_data = get_from_cache(cache_key)
        if cached_data is not None:
            return jsonify(cached_data)

    print(f"🔄 Fetching fresh data for {league_key}...")
    results = asyncio.run(fetch_all_leagues(season, [league_key]))
    
    if include_highlights and results[0].get("goals"):
        goals = results[0]["goals"]
        enriched_goals = asyncio.run(enrich_goals_with_highlights(goals, league_key))
        results[0]["goals"] = enriched_goals
    
    response_data = {"season": season, "data": results[0]}
    save_to_cache(cache_key, response_data)
    
    return jsonify(response_data)


# -------------------------------------------------------------
# Flask Endpoints - Mock Data
# -------------------------------------------------------------
@app.route("/api/mock/<league>")
def get_mock_data(league):
    """Get mock data for instant loading"""
    league_url = league.lower()
    
    if league_url in URL_ALIASES:
        league_key = URL_ALIASES[league_url]
    else:
        league_key = league_url
    
    # If we have loaded mock data, return it
    if league_key in MOCK_DATA:
        return jsonify({"season": DEFAULT_SEASON, "data": MOCK_DATA[league_key]})
    
    # Otherwise return a minimal fallback
    fallback_data = {
        "league": LEAGUE_MAP.get(league_key, ("Unknown", "Unknown"))[1],
        "goals": [],
        "is_mock": True,
        "message": "Loading real data in background..."
    }
    return jsonify({"season": DEFAULT_SEASON, "data": fallback_data})


# -------------------------------------------------------------
# Flask Endpoints - Highlights
# -------------------------------------------------------------
@app.route("/api/highlights/<league>")
def api_league_highlights(league):
    """Get highlights for a specific league"""
    force_refresh = request.args.get("refresh", "false").lower() == "true"
    date = request.args.get("date")
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
    
    cache_key = get_cache_key(date or "latest", league_key, "highlights")
    
    if not force_refresh:
        cached_data = get_from_cache(cache_key)
        if cached_data is not None:
            return jsonify(cached_data)
    
    result = asyncio.run(fetch_league_highlights(league_key, date, limit))
    save_to_cache(cache_key, result)
    
    return jsonify(result)


@app.route("/api/highlights/match")
def api_match_highlights():
    """Search for highlights of a specific match"""
    home_team = request.args.get("homeTeam")
    away_team = request.args.get("awayTeam")
    date = request.args.get("date")
    
    if not home_team or not away_team:
        return jsonify({
            "error": "Both homeTeam and awayTeam parameters are required"
        }), 400
    
    result = asyncio.run(search_match_highlights(home_team, away_team, date))
    return jsonify(result)


# -------------------------------------------------------------
# Flask Endpoints - AI Assistant
# -------------------------------------------------------------
@app.route("/api/ai/ask", methods=["POST"])
def ai_ask():
    """Ask the AI assistant a question - now uses web search for all queries"""
    data = request.get_json()
    
    if not data or "question" not in data:
        return jsonify({"error": "Question is required"}), 400
    
    question = data["question"]
    
    # Use web search for all questions
    result = asyncio.run(ask_gemini_with_search(question))
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
    data_type = request.args.get("type", "goals")
    
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
        "cache_size": len(cache),
        "mock_data_leagues": list(MOCK_DATA.keys()),
        "features": {
            "goals": True,
            "highlights": bool(HIGHLIGHTLY_API_KEY),
            "ai_assistant": bool(GEMINI_API_KEY),
            "mock_data": len(MOCK_DATA) > 0
        }
    })


if __name__ == "__main__":
    app.run(debug=True)
