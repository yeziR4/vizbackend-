import asyncio
import json
from flask import Flask, jsonify, request
import aiohttp
from understat import Understat

app = Flask(__name__)

# -------------------------------------------------------------
# Configuration
# -------------------------------------------------------------
DEFAULT_SEASON = "2025"     # always use string
LEAGUE_MAP = {
    "epl": ("EPL", "Premier League"),
    "laliga": ("La_liga", "La Liga"),
    "bundesliga": ("Bundesliga", "Bundesliga"),
    "seriea": ("Serie_A", "Serie A"),
    "ligue1": ("Ligue_1", "Ligue 1"),
}
# -------------------------------------------------------------


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

        # merge home + away
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

        await asyncio.sleep(0.2)  # be nice to Understat

    print(f"✅ {league_name}: collected {len(all_goals)} goals")
    return {"league": league_name, "goals": all_goals, "error": None}


# -------------------------------------------------------------
# Fetch all leagues in parallel
# -------------------------------------------------------------
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

    # run async safely inside Flask
    results = asyncio.run(fetch_all_leagues(season, leagues))
    return jsonify({"season": season, "data": results})


@app.route("/api/goals/<league>")
def api_single_league(league):
    season = str(request.args.get("season", DEFAULT_SEASON))

    league_key = league.lower()
    if league_key not in LEAGUE_MAP:
        return jsonify({"error": "Unknown league"}), 400

    results = asyncio.run(fetch_all_leagues(season, [league_key]))
    return jsonify({"season": season, "data": results[0]})


# -------------------------------------------------------------
# Run server
# -------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
