import asyncio
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
import aiohttp
from understat import Understat
import logging

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LEAGUE_CODES = {
    'epl': 'EPL',
    'la_liga': 'La_liga',
    'bundesliga': 'Bundesliga',
    'serie_a': 'Serie_A',
    'ligue_1': 'Ligue_1'
}

async def fetch_league_goals(session, league_code, league_name, season_year=2025):
    """Fetch all goals for a specific league and season"""
    try:
        understat = Understat(session)
        logger.info(f"Fetching {league_name} {season_year}-{season_year+1} season data...")
        
        goals_data = []
        
        results = await understat.get_league_results(league_code, str(season_year))
        logger.info(f"Found {len(results)} matches for {league_name}")
        
        for idx, match in enumerate(results, 1):
            match_id = match['id']
            match_date = match.get('datetime', 'Unknown date')
            
            try:
                shots = await understat.get_match_shots(str(match_id))
                all_shots = shots['h'] + shots['a']
                
                for shot in all_shots:
                    if shot['result'] == 'Goal':
                        goals_data.append({
                            "id": shot['id'],
                            "x": float(shot['X']),
                            "y": float(shot['Y']),
                            "player": shot['player'],
                            "minute": shot['minute'],
                            "match_id": match_id,
                            "team": shot['h_team'] if shot['h_a'] == 'h' else shot['a_team'],
                            "opponent": shot['a_team'] if shot['h_a'] == 'h' else shot['h_team'],
                            "xg": float(shot['xG']),
                            "situation": shot.get('situation', 'Unknown'),
                            "shotType": shot.get('shotType', 'Unknown'),
                            "match_date": match_date,
                            "league": league_name
                        })
                
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.error(f"Error fetching shots for match {match_id} in {league_name}: {e}")
                continue
        
        logger.info(f"✅ {league_name}: Collected {len(goals_data)} goals")
        return {
            'league': league_name,
            'goals': goals_data,
            'total_goals': len(goals_data),
            'total_matches': len(results)
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching {league_name} data: {e}")
        return {
            'league': league_name,
            'goals': [],
            'total_goals': 0,
            'total_matches': 0,
            'error': str(e)
        }

async def fetch_all_leagues(season_year=2025, leagues=None):
    """Fetch goals from all specified leagues in parallel"""
    if leagues is None:
        leagues = list(LEAGUE_CODES.keys())
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for league_key in leagues:
            if league_key in LEAGUE_CODES:
                league_code = LEAGUE_CODES[league_key]
                tasks.append(fetch_league_goals(session, league_code, league_key, season_year))
        
        results = await asyncio.gather(*tasks)
        return results

@app.route('/')
def home():
    return jsonify({
        'message': 'Football Goals API',
        'endpoints': {
            '/api/goals': 'Get goals from all leagues (can take 5-10 minutes)',
            '/api/goals/<league>': 'Get goals from a specific league (faster, ~2 minutes)',
            '/api/goals/<league>?season=2024': 'Get goals from specific league and season'
        },
        'individual_league_endpoints': {
            '/api/goals/epl': 'English Premier League',
            '/api/goals/la_liga': 'Spanish La Liga',
            '/api/goals/bundesliga': 'German Bundesliga',
            '/api/goals/serie_a': 'Italian Serie A',
            '/api/goals/ligue_1': 'French Ligue 1'
        },
        'available_leagues': list(LEAGUE_CODES.keys())
    })

@app.route('/api/goals', methods=['GET'])
def get_goals():
    """Endpoint to fetch goals data"""
    season = request.args.get('season', '2025', type=int)
    leagues_param = request.args.get('leagues', None)
    
    leagues = None
    if leagues_param:
        leagues = [l.strip() for l in leagues_param.split(',')]
        invalid_leagues = [l for l in leagues if l not in LEAGUE_CODES]
        if invalid_leagues:
            return jsonify({
                'error': f'Invalid leagues: {invalid_leagues}',
                'available_leagues': list(LEAGUE_CODES.keys())
            }), 400
    
    logger.info(f"Fetching goals for season {season}, leagues: {leagues or 'all'}")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        results = loop.run_until_complete(fetch_all_leagues(season, leagues))
        
        all_goals = []
        league_stats = {}
        
        for result in results:
            league_stats[result['league']] = {
                'total_goals': result['total_goals'],
                'total_matches': result['total_matches']
            }
            if 'error' in result:
                league_stats[result['league']]['error'] = result['error']
            all_goals.extend(result['goals'])
        
        response = {
            'season': f"{season}-{season+1}",
            'total_goals': len(all_goals),
            'league_stats': league_stats,
            'goals': all_goals
        }
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error in /api/goals: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        loop.close()

@app.route('/api/goals/<league>', methods=['GET'])
def get_league_goals(league):
    """Endpoint to fetch goals data for a specific league"""
    if league not in LEAGUE_CODES:
        return jsonify({
            'error': f'Invalid league: {league}',
            'available_leagues': list(LEAGUE_CODES.keys())
        }), 404
    
    season = request.args.get('season', '2024', type=int)
    logger.info(f"Fetching goals for {league}, season {season}")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        results = loop.run_until_complete(fetch_all_leagues(season, [league]))
        
        if not results:
            return jsonify({'error': 'No data found'}), 500
        
        result = results[0]
        
        response = {
            'league': result['league'],
            'season': f"{season}-{season+1}",
            'total_goals': result['total_goals'],
            'total_matches': result['total_matches'],
            'goals': result['goals']
        }
        
        if 'error' in result:
            response['error'] = result['error']
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error in /api/goals/{league}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        loop.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
