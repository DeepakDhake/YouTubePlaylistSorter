# YouTube Playlist AI Sorter

A Python script that uses Google Gemini AI to intelligently sort your YouTube playlist alphabetically by actual song names, not just video titles.

## Features

- 🧠 **AI-Powered**: Google Gemini analyzes YouTube titles to extract actual song names
- ⚡ **Efficient**: Pure AI extraction with intelligent caching and rate limiting
- 🔍 **Duplicate Detection**: Identifies potential duplicate songs before sorting
- � **Resume Mode**: If AI extraction is cached but update failed, skip straight to updating
- �🔐 **Secure**: OAuth 2.0 authentication with automatic token refresh
- 📊 **Full Preview**: Shows complete new order before applying changes
- 💾 **Cached**: Saves AI results to avoid repeat API calls
- 🕒 **Rate Limited**: Respects API limits with automatic delays between requests

## Setup Instructions

### 1. Create Google Cloud Project and Get Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing one)
3. Enable the **YouTube Data API v3**:
   - Go to APIs & Services > Library
   - Search for "YouTube Data API v3"
   - Click "Enable"
4. Create OAuth 2.0 credentials:
   - Go to APIs & Services > Credentials
   - Click "Create Credentials" > "OAuth 2.0 Client ID"
   - Select "Desktop application"
   - Download the JSON file
5. Place the JSON file in the YouTubeSorter folder and rename it to `client_secret.json`

### 2. Get Google AI API Key

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Sign in with your Google account
3. Create a new API key or use an existing one
4. Set the API key as an environment variable:

**Windows:**
```cmd
set GOOGLE_AI_API_KEY=your_api_key_here
```

**Linux/Mac:**
```bash
export GOOGLE_AI_API_KEY=your_api_key_here
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the Script

```bash
python youtube_sorter.py
```

### 4. First Run

- The script will open a browser for OAuth authentication
- Authorize the application to access your YouTube account
- A `token.pickle` file will be created for future runs (no re-authentication needed)
- Enter your playlist ID when prompted

## Getting Your Playlist ID

1. Go to your YouTube playlist
2. Click "Share"
3. The URL will look like: `https://www.youtube.com/playlist?list=PLxxxxxxxxxx`
4. Copy the part after `list=` (e.g., `PLxxxxxxxxxx`)

## How It Works

1. **AI Analysis**: Google Gemini analyzes each YouTube title to extract the actual song name
2. **Normalization**: Song names are normalized (removes articles like "The", "A", "An")
3. **Duplicate Detection**: Identifies potential duplicate songs before sorting
4. **Sorting**: Arranges songs alphabetically by extracted song name
5. **Preview**: Shows the new order before applying changes
6. **Update**: Reorders the playlist using YouTube Data API

**Resume Mode**: If you've run the script before and AI results are cached, but the playlist update failed due to quota/API issues, the script will detect this and offer to skip straight to updating positions using cached results.

## Quota Management

The YouTube Data API v3 has daily quota limits:

- **Free Tier**: ~10,000 units per day
- **Paid Tier**: Higher limits available ($0.50 per 1,000 units)

**API Costs per operation:**
- Fetch playlist items: 1 unit per page (50 items)
- Update playlist position: 50 units per item
- AI extraction: Handled by Google Gemini API (separate quota)

**Optimization Strategies:**
- Results are cached locally and persist between runs to avoid repeat AI calls
- Script checks quota before starting operations
- Use during off-peak hours for better success rates
- Consider paid tier for large playlists (>500 songs)

**Monitor Usage:** https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas

## Troubleshooting

**"client_secret.json not found"**
- Make sure you've downloaded the OAuth credentials from Google Cloud Console
- Place the file in the YouTubeSorter directory

**"Quota exceeded" or rate limit errors**
- The script automatically checks quota before starting
- YouTube API has daily limits (usually 10,000 units/day for free tier)
- Each playlist fetch costs ~1-2 units per page of 50 items
- Each AI call costs ~1 unit
- **Solutions:**
  - Wait 24 hours for daily reset (midnight PST)
  - Check usage: https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas
  - Upgrade to paid Google Cloud tier ($0.50/1,000 units)
  - Use smaller playlists or run during off-peak hours
  - The script caches AI results to minimize repeat calls

**"GOOGLE_AI_API_KEY environment variable not set"**
- Get an API key from [Google AI Studio](https://aistudio.google.com/)
- Set it as an environment variable: `set GOOGLE_AI_API_KEY=your_key_here` (Windows) or `export GOOGLE_AI_API_KEY=your_key_here` (Linux/Mac)

**"403 Forbidden"**
- Make sure YouTube Data API v3 is enabled in Google Cloud Console
- Re-authenticate by deleting `token.pickle` and running the script again

**"SERVICE_UNAVAILABLE" or "The operation was aborted"**
- This is a temporary YouTube API issue
- The script will automatically retry with exponential backoff
- If it persists, wait 5-10 minutes and try again
- YouTube API sometimes has temporary outages during peak hours
- **Resume Mode**: If update fails, run the script again - it will offer to resume from cached results

**"Quota exceeded" during update but AI extraction completed**
- Choose "yes" when prompted for resume mode
- This skips AI calls and goes directly to playlist position updates
- Much more quota-efficient for completion

**"Playlist sort type need to be MANUAL"**
- Go to your YouTube playlist settings and change sort order to "Manual"

**"Permission denied"**
- Make sure you selected the correct OAuth scopes during credential creation
- The app needs access to modify your playlists

## Security

- Your credentials are stored locally in `token.pickle`
- No passwords are stored
- Optional: Delete `token.pickle` if you want to re-authenticate with a different account

---

**Happy sorting!** 🎵
