# Football Goals API

## Overview
A Flask-based REST API that fetches goal data from 5 major European football leagues using the Understat API. The service collects detailed information about every goal including player, position (x,y coordinates), expected goals (xG), shot type, and match details.

## Supported Leagues
- **EPL**: English Premier League
- **La Liga**: Spanish La Liga
- **Bundesliga**: German Bundesliga
- **Serie A**: Italian Serie A
- **Ligue 1**: French Ligue 1

## API Endpoints

### GET /
Returns API information and available endpoints.

### GET /api/goals
Fetches goals data from all leagues or multiple leagues.

⚠️ **Warning:** This endpoint can take 5-10 minutes when fetching all leagues. Consider using individual league endpoints instead.

**Query Parameters:**
- `season` (optional, default: 2024): The starting year of the season (e.g., 2024 for 2024-2025 season)
- `leagues` (optional): Comma-separated list of league keys (e.g., `epl,la_liga,bundesliga`)

**Examples:**
```
GET /api/goals
GET /api/goals?season=2024
GET /api/goals?leagues=epl,la_liga
```

**Response Format:**
```json
{
  "season": "2024-2025",
  "total_goals": 1234,
  "league_stats": {
    "epl": {
      "total_goals": 250,
      "total_matches": 100
    },
    ...
  },
  "goals": [...]
}
```

### GET /api/goals/:league
**Recommended:** Fetches goals data from a specific league (much faster, ~2 minutes).

**Available League Routes:**
- `/api/goals/epl` - English Premier League
- `/api/goals/la_liga` - Spanish La Liga
- `/api/goals/bundesliga` - German Bundesliga
- `/api/goals/serie_a` - Italian Serie A
- `/api/goals/ligue_1` - French Ligue 1

**Query Parameters:**
- `season` (optional, default: 2024): The starting year of the season

**Examples:**
```
GET /api/goals/epl
GET /api/goals/la_liga?season=2024
GET /api/goals/bundesliga?season=2023
```

**Response Format:**
```json
{
  "league": "epl",
  "season": "2024-2025",
  "total_goals": 250,
  "total_matches": 100,
  "goals": [
    {
      "id": "123456",
      "x": 0.89,
      "y": 0.45,
      "player": "Player Name",
      "minute": "45",
      "match_id": "12345",
      "team": "Team Name",
      "opponent": "Opponent Name",
      "xg": 0.35,
      "situation": "OpenPlay",
      "shotType": "RightFoot",
      "match_date": "2024-08-15 19:00:00",
      "league": "epl"
    },
    ...
  ]
}
```

## Deployment

### Render
This project is configured for deployment on Render using the `render.yaml` configuration file.

1. Push your code to a GitHub repository
2. Connect your repository to Render
3. Render will automatically detect the `render.yaml` file
4. The service will be deployed with the specified configuration

The API uses Gunicorn as the production server with:
- 2 workers for handling concurrent requests
- 300-second timeout for long-running data fetches
- Automatic port binding to Render's PORT environment variable

### Local Development
```bash
pip install -r requirements.txt
python app.py
```

The server will start on `http://0.0.0.0:5000`

## Technical Details

### Architecture
- **Framework**: Flask with CORS enabled for cross-origin requests
- **Async Operations**: Uses aiohttp and asyncio for parallel league data fetching
- **Data Source**: Understat API for football statistics
- **Production Server**: Gunicorn for robust production deployment

### Performance
- Fetches all 5 leagues in parallel using async/await
- Includes rate limiting (0.3s delay between match requests) to respect API limits
- Comprehensive error handling per league and per match

## Recent Changes
- 2024-11-23: Added individual league endpoints for faster, one-at-a-time fetching
- 2024-11-23: Initial setup with multi-league support and Render deployment configuration

## User Preferences
- Prefers fetching leagues one at a time instead of all at once for better performance and user experience
