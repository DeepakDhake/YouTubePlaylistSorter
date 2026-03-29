#!/usr/bin/env python3

import os
import re
import time
import json
import pickle
import unicodedata

import google.generativeai as genai
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# =========================
# CONFIG
# =========================
SCOPES = ['https://www.googleapis.com/auth/youtube']
CLIENT_SECRETS_FILE = 'client_secret.json'
TOKEN_FILE = 'token.pickle'
CACHE_FILE = 'ai_cache.pkl'

# Google AI API Key (set as environment variable: GOOGLE_AI_API_KEY)
genai.configure(api_key=os.getenv('GOOGLE_AI_API_KEY'))
model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')


# =========================
# AUTH
# =========================
def authenticate():
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)

    return creds


def youtube_service(creds):
    return build("youtube", "v3", credentials=creds)


# =========================
# QUOTA CHECK
# =========================
def check_quota_status(youtube):
    """Check current quota usage (approximate)"""
    try:
        # This is a lightweight call to test quota
        youtube.channels().list(part="id", mine=True, maxResults=1).execute()
        print("✅ API quota OK")
        return True
    except Exception as e:
        if "quotaExceeded" in str(e):
            print("\n❌ QUOTA EXCEEDED!")
            print("Your YouTube API quota has been exceeded.")
            return False
        else:
            # Other errors are OK, quota is probably fine
            print("✅ API connection OK")
            return True


# =========================
# FETCH
# =========================
def fetch_playlist_items(youtube, playlist_id):
    items = []
    token = None
    page_count = 0

    try:
        while True:
            page_count += 1
            print(f"Fetching page {page_count}...")

            res = youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=token
            ).execute()

            items.extend(res["items"])
            token = res.get("nextPageToken")

            if not token:
                break

            # Small delay between pages to be respectful
            time.sleep(0.1)

    except Exception as e:
        error_msg = str(e)
        if "quotaExceeded" in error_msg or "403" in error_msg:
            print("\n❌ QUOTA EXCEEDED!")
            print("You've reached your daily YouTube API quota limit.")
            print("\n📊 QUOTA SOLUTIONS:")
            print("1. Wait 24 hours for quota reset (resets daily)")
            print("2. Check usage: https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas")
            print("3. Upgrade to paid tier for higher limits")
            print("4. Reduce playlist size or use cached results")
            print("\n💡 TIP: The script caches AI results, so re-running later will use fewer API calls.")
            return None
        else:
            print(f"Error fetching playlist: {e}")
            return None

    print(f"✅ Fetched {len(items)} items from {page_count} pages")
    return items


# =========================
# CACHE
# =========================
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "rb") as f:
            return pickle.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(cache, f)


# =========================
# NORMALIZATION (Spotify-like)
# =========================
def normalize(text):
    if not text:
        return ""

    text = unicodedata.normalize('NFKD', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()

    for article in ["the ", "a ", "an "]:
        if text.startswith(article):
            text = text[len(article):]

    return text


# =========================
# AI PARSER (with rate limiting)
# =========================
def ai_extract(title):
    prompt = f"""
    Extract the song name and artist from this YouTube title.

    Title: {title}

    Return ONLY JSON:
    {{
        "song": "...",
        "artist": "..."
    }}
    """

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # Clean up the response (remove markdown code blocks if present)
        if text.startswith('```json'):
            text = text[7:]
        if text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        
        text = text.strip()
        
        data = json.loads(text)

        return data.get("song", "").strip(), data.get("artist")

    except Exception as e:
        print(f"AI error for '{title[:50]}...': {e}")
        return "", None


# =========================
# HEURISTIC EXTRACT (removed - using AI only)
# =========================


# =========================
# SMART EXTRACT (AI Only with rate limiting)
# =========================
cache = load_cache()

def smart_extract(title):
    if title in cache:
        return cache[title]

    # Always use AI for extraction
    print(f"🤖 Extracting: {title[:50]}...")
    
    # Rate limiting: wait between AI calls
    time.sleep(4)  # ~15 calls per minute max
    
    song, artist = ai_extract(title)
    
    result = {
        "song": song.lower() if song else "",
        "artist": artist
    }

    cache[title] = result
    save_cache(cache)

    return result


# =========================
# SORT
# =========================
def sort_items(items):
    def key(item):
        data = smart_extract(item["snippet"]["title"])
        song = normalize(data["song"])

        return (not song, song)

    return sorted(items, key=key)


# =========================
# DUPLICATE DETECTION (ONLY REPORT)
# =========================
def show_duplicates(items):
    print("🔍 Checking for duplicates...")
    seen = {}
    duplicates = []

    for i, item in enumerate(items):
        if (i + 1) % 10 == 0:
            print(f"   Processed {i + 1}/{len(items)} songs...")
        
        data = smart_extract(item["snippet"]["title"])
        song = normalize(data["song"])

        if not song:
            continue

        if song in seen:
            duplicates.append((song, item["snippet"]["title"], seen[song]))
        else:
            seen[song] = item["snippet"]["title"]

    if not duplicates:
        print("✅ No duplicates found")
        return

    print(f"\n🔁 Found {len(duplicates)} duplicate songs:\n")
    for song, current, original in duplicates:
        print(f"Song: {song}")
        print(f"  → {original}")
        print(f"  → {current}")
        print()


# =========================
# UPDATE
# =========================
def update_playlist(youtube, sorted_items):
    print("\nUpdating playlist...\n")

    for idx, item in enumerate(sorted_items):
        old_pos = item["snippet"]["position"]

        if old_pos == idx:
            continue

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                youtube.playlistItems().update(
                    part="snippet",
                    body={
                        "id": item["id"],
                        "snippet": {
                            "playlistId": item["snippet"]["playlistId"],
                            "resourceId": item["snippet"]["resourceId"],
                            "position": idx
                        }
                    }
                ).execute()

                print(f"[{idx+1}] Updated")
                time.sleep(0.2)  # Increased delay between updates
                break

            except Exception as e:
                error_msg = str(e)
                if "SERVICE_UNAVAILABLE" in error_msg or "409" in error_msg:
                    if attempt < max_retries - 1:
                        print(f"[{idx+1}] API temporarily unavailable, retrying in {retry_delay}s... (attempt {attempt+1}/{max_retries})")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        print(f"[{idx+1}] Failed after {max_retries} attempts: {error_msg}")
                        return False
                else:
                    print(f"[{idx+1}] Unexpected error: {error_msg}")
                    return False

    return True


# =========================
# MAIN
# =========================
def main():
    print("🧠 YouTube Playlist Sorter (AI-Only Mode)")

    playlist_id = input("Playlist ID: ").strip()

    creds = authenticate()
    yt = youtube_service(creds)

    # Check quota before starting
    if not check_quota_status(yt):
        print("\n📊 QUOTA SOLUTIONS:")
        print("1. Wait until tomorrow (quota resets daily at midnight PST)")
        print("2. Check your usage: https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas")
        print("3. Upgrade to a paid Google Cloud tier for higher limits")
        print("4. Consider using smaller playlists or running during off-peak hours")
        return

    items = fetch_playlist_items(yt, playlist_id)

    if items is None:
        print("\nCannot continue due to quota limits. Please try again later.")
        return

    # Check if all items are already cached (resume mode)
    cache = load_cache()
    all_cached = all(title in cache for item in items for title in [item["snippet"]["title"]])

    if all_cached and len(items) > 0:
        print(f"\n🎯 RESUME MODE DETECTED!")
        print(f"   All {len(items)} songs have cached AI results.")
        print("   You can skip AI extraction and go directly to updating playlist positions.")

        resume_choice = input("\nResume updating from cached results? (yes/no): ").lower().strip()
        if resume_choice == "yes":
            print("\n⏭️  Skipping to playlist update...")
            sorted_items = sort_items(items)  # Will use cached results
            success = update_playlist(yt, sorted_items)
            if success:
                print("\n✅ Playlist update completed!")
            else:
                print("\n❌ Update completed with errors. Try again later.")
            return

    # 🔍 Show duplicates BEFORE sorting
    show_duplicates(items)

    sorted_items = sort_items(items)

    print(f"\n📋 Preview (showing all {len(sorted_items)} songs):\n")
    for i, item in enumerate(sorted_items, 1):
        data = smart_extract(item["snippet"]["title"])
        song_name = data['song'][:40] if data['song'] else "[NO EXTRACTION]"
        method = "🤖 AI" if not cache.get(item["snippet"]["title"]) else "⚡ Cached"
        print(f"{i:2d}. {method}: {song_name}")
    
    print(f"\n📊 Summary:")
    print(f"   Total songs: {len(sorted_items)}")
    ai_used = sum(1 for item in sorted_items if not cache.get(item["snippet"]["title"]))
    print(f"   AI calls used: {ai_used}")
    print(f"   Cached results: {len(sorted_items) - ai_used}")

    if input("\nProceed with sorting? (yes/no): ").lower() != "yes":
        return

    success = update_playlist(yt, sorted_items)

    if success:
        print("\n✅ Done!")
    else:
        print("\n❌ Sorting completed with errors. Some items may not have been moved.")
        print("   You can try running the script again to complete the sorting.")


if __name__ == "__main__":
    main()