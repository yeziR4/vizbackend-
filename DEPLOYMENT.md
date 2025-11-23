# Deployment Guide for Render

This guide will help you deploy your Football Goals API to Render.

## Prerequisites
- A GitHub account
- A Render account (free tier available at https://render.com)
- Your code pushed to a GitHub repository

## Deployment Steps

### 1. Push Your Code to GitHub
```bash
git init
git add .
git commit -m "Initial commit - Football Goals API"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

### 2. Deploy on Render

#### Option A: Using render.yaml (Recommended)
1. Go to https://render.com/dashboard
2. Click "New +" and select "Blueprint"
3. Connect your GitHub repository
4. Render will automatically detect the `render.yaml` file
5. Click "Apply" to deploy

#### Option B: Manual Web Service Creation
1. Go to https://render.com/dashboard
2. Click "New +" and select "Web Service"
3. Connect your GitHub repository
4. Configure the following settings:
   - **Name**: football-goals-api (or your preferred name)
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 300 app:app`
   - **Instance Type**: Free (or your preferred tier)
5. Click "Create Web Service"

### 3. Configuration Notes

#### Timeout Settings
The API fetches data for all matches in a season, which can take several minutes. The configuration includes:
- **300-second timeout** in Gunicorn to allow time for data fetching
- **2 workers** to handle concurrent requests

#### Port Configuration
Render automatically sets the `PORT` environment variable. The Gunicorn command uses `$PORT` to bind to the correct port.

## Testing Your Deployment

Once deployed, Render will provide you with a URL like: `https://football-goals-api-xxxx.onrender.com`

Test your endpoints:

```bash
# Test root endpoint
curl https://your-app-name.onrender.com/

# Test goals endpoint (all leagues)
curl https://your-app-name.onrender.com/api/goals?season=2024

# Test specific leagues
curl https://your-app-name.onrender.com/api/goals?leagues=epl,la_liga&season=2024
```

## Important Notes

### First Request Delay
If using Render's free tier, your service will spin down after 15 minutes of inactivity. The first request after inactivity may take 30-60 seconds to respond.

### Request Duration
Fetching data for all 5 leagues can take 5-10 minutes depending on the number of matches. Plan your frontend accordingly:
- Show loading indicators
- Consider implementing request timeouts on the frontend
- Optionally, fetch leagues individually instead of all at once

### Free Tier Limitations
- **750 hours/month** of runtime
- Service spins down after 15 minutes of inactivity
- Limited CPU and memory

## Frontend Integration

Example frontend code to call your API:

```javascript
// Fetch all leagues
async function getAllGoals(season = 2024) {
  try {
    const response = await fetch(
      `https://your-app-name.onrender.com/api/goals?season=${season}`,
      { timeout: 600000 } // 10 minute timeout
    );
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching goals:', error);
    throw error;
  }
}

// Fetch specific leagues
async function getLeagueGoals(leagues, season = 2024) {
  try {
    const leaguesParam = leagues.join(',');
    const response = await fetch(
      `https://your-app-name.onrender.com/api/goals?leagues=${leaguesParam}&season=${season}`,
      { timeout: 600000 }
    );
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching goals:', error);
    throw error;
  }
}
```

## Monitoring

After deployment, monitor your service:
1. Check the **Logs** tab in Render dashboard
2. View deployment history
3. Monitor resource usage

## Troubleshooting

### Service fails to start
- Check the logs in Render dashboard
- Verify all dependencies in `requirements.txt` are correct
- Ensure `app.py` has no syntax errors

### Timeout errors
- The default 300-second timeout should be sufficient
- If needed, increase the timeout in `render.yaml` or start command
- Consider implementing caching for frequently requested data

### Memory issues
- Upgrade to a paid tier with more memory
- Optimize data fetching to process fewer leagues at once

## Next Steps

Consider implementing these improvements:
1. **Caching**: Store fetched data to avoid refetching on every request
2. **Background jobs**: Pre-fetch and cache data periodically
3. **Pagination**: Return data in chunks for large datasets
4. **Database**: Store historical data for faster retrieval
