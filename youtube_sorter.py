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
from urllib.parse import urlparse, parse_qs
from googleapiclient.http import BatchHttpRequest
import argparse

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
    # Fallback: if no OAuth credentials are provided, allow using a YouTube API key
    yt_api_key = os.getenv('YT_API_KEY')
    if creds:
        return build("youtube", "v3", credentials=creds)
    if yt_api_key:
        return build("youtube", "v3", developerKey=yt_api_key)
    # No credentials provided — caller will be unauthenticated (may get PERMISSION_DENIED)
    return build("youtube", "v3")


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

            # Request only necessary fields to minimize payload
            res = youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=token,
                fields='nextPageToken,items(id,snippet(title,position,playlistId,resourceId))'
            ).execute()

            items.extend(res["items"])
            token = res.get("nextPageToken")

            if not token:
                break

            # Small delay between pages to be respectful
            time.sleep(0.1)

    except Exception as e:
        error_msg = str(e)

        # Invalid playlist id (often caused by pasting a full URL with extra params)
        if "Invalid Value" in error_msg or "invalid" in error_msg:
            print("\n❌ INVALID PLAYLIST ID")
            print("It looks like the playlist ID you provided is malformed (contains extra URL params).")
            print("Please pass only the playlist `list` id (e.g. PLllZjwlbUqgCQP5C_Rw8-CJayoQSzPOJ1) or a full URL.")
            print("The script can accept a full YouTube URL now — it will extract the `list` parameter.")
            return None

        # Permission / unregistered caller (no API key or OAuth credentials)
        if "unregistered callers" in error_msg or "forbidden" in error_msg or "PERMISSION_DENIED" in error_msg:
            print("\n❌ PERMISSION DENIED")
            print("Method doesn't allow unregistered callers. Provide valid credentials:")
            print("- Use OAuth (client_secret.json + run the auth flow) to access private or write operations")
            print("- Or set a YouTube API key via the YT_API_KEY environment variable for public reads")
            return None

        # Quota exceeded
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

        # Generic fallback
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


# Extract playlist id from a full YouTube URL or return the string unchanged
def extract_playlist_id(s):
    if not s:
        return s

    s = s.strip()
    # If it's a URL, parse query params
    if s.startswith('http') or s.startswith('www'):
        try:
            q = parse_qs(urlparse(s).query)
            if 'list' in q:
                return q['list'][0]
        except Exception:
            pass

    # Remove trailing query params if someone pasted a URL fragment
    if '?' in s:
        s = s.split('?', 1)[0]
    if '&' in s:
        s = s.split('&', 1)[0]

    return s


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


def batch_ai_extract(titles, chunk_size=20, delay=1.0):
    """Batch titles and call the AI in chunks. Returns a list of dicts with song/artist keyed by title."""
    results = {}

    for i in range(0, len(titles), chunk_size):
        chunk = titles[i:i+chunk_size]

        # Build prompt: provide JSON array of titles and request JSON array of results
        prompt = (
            "You are given a JSON array of YouTube video titles. For each title, extract the song name and artist.\n\n"
            "Input titles JSON:\n"
            + json.dumps(chunk)
            + "\n\nReturn ONLY JSON: an array of objects with keys: \"title_index\", \"song\", \"artist\".\n"
            "Example: [{\"title_index\":0,\"song\":\"...\",\"artist\":\"...\"}, ...]\n"
        )

        try:
            response = model.generate_content(prompt)
            text = response.text.strip()

            # strip markdown codeblocks
            if text.startswith('```json'):
                text = text[7:]
            if text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]

            text = text.strip()

            batch_data = json.loads(text)

            # Map results
            for entry in batch_data:
                idx = int(entry.get('title_index'))
                title = chunk[idx]
                song = entry.get('song', '') or ''
                artist = entry.get('artist')
                results[title] = {"song": song.lower().strip(), "artist": artist}

        except Exception as e:
            print(f"Batch AI error: {e}")
            # Fallback: mark entries with empty extraction
            for title in chunk:
                if title not in results:
                    results[title] = {"song": "", "artist": None}

        # polite delay between batches
        time.sleep(delay)

    return results


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

    # Fallback single-item AI extraction
    print(f"🤖 Extracting: {title[:50]}...")
    time.sleep(4)
    song, artist = ai_extract(title)
    result = {"song": song.lower() if song else "", "artist": artist}
    cache[title] = result
    save_cache(cache)
    return result


def precompute_extractions(items, batch_size=20, delay=1.0):
    """Ensure `cache` contains extractions for all titles in `items`. Uses batch AI calls."""
    titles = [it["snippet"]["title"] for it in items]
    missing = [t for t in titles if t not in cache]
    if not missing:
        return

    print(f"⏳ Precomputing AI extractions for {len(missing)} missing titles (batches of {batch_size})...")
    batch_results = batch_ai_extract(missing, chunk_size=batch_size, delay=delay)

    # Update cache
    for title, data in batch_results.items():
        cache[title] = data

    save_cache(cache)
    print("⚡ AI extractions cached.")


# =========================
# SORT
# =========================
def sort_items(items):
    def key(item):
        title = item["snippet"]["title"]
        data = cache.get(title) or smart_extract(title)
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
        
        title = item["snippet"]["title"]
        data = cache.get(title) or smart_extract(title)
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
def update_playlist(youtube, sorted_items, max_updates=None, dry_run=False):
    print("\nPreparing playlist updates...\n")

    to_update = []
    for idx, item in enumerate(sorted_items):
        old_pos = item["snippet"]["position"]
        if old_pos == idx:
            continue
        to_update.append((idx, item))

    if not to_update:
        print("No items need moving.")
        return True

    if dry_run:
        print("Dry-run mode: the following moves would be applied:")
        for idx, item in to_update:
            print(f"Move to {idx}: {item['snippet']['title']}")
        return True

    if max_updates:
        to_update = to_update[:max_updates]

    print(f"Applying {len(to_update)} updates (sequential)...")

    for update_idx, (pos, item) in enumerate(to_update):
        max_retries = 3
        retry_delay = 1.0

        body = {
            "id": item["id"],
            "snippet": {
                "playlistId": item["snippet"]["playlistId"],
                "resourceId": item["snippet"]["resourceId"],
                "position": pos
            }
        }

        for attempt in range(max_retries):
            try:
                youtube.playlistItems().update(part="snippet", body=body).execute()
                print(f"[{update_idx+1}] Updated")
                time.sleep(0.2)
                break
            except Exception as e:
                err = str(e)
                if "SERVICE_UNAVAILABLE" in err or "409" in err or "500" in err:
                    if attempt < max_retries - 1:
                        print(f"[{update_idx+1}] Temporary error, retrying in {retry_delay}s... (attempt {attempt+1}/{max_retries})")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        print(f"[{update_idx+1}] Failed after {max_retries} attempts: {err}")
                        return False
                else:
                    print(f"[{update_idx+1}] Unexpected error: {err}")
                    return False

    print("All updates applied.")
    return True


# =========================
# MAIN
# =========================
def main():
    parser = argparse.ArgumentParser(description='YouTube Playlist Sorter')
    parser.add_argument('--max-updates', type=int, default=None, help='Limit number of playlist moves this run')
    parser.add_argument('--dry-run', action='store_true', help='Do not perform updates; just show moves')
    parser.add_argument('--batch-size', type=int, default=20, help='AI batch size per request')
    parser.add_argument('--batch-delay', type=float, default=1.0, help='Seconds delay between AI batches')
    args = parser.parse_args()

    print("🧠 YouTube Playlist Sorter (AI-Only Mode)")

    playlist_id = extract_playlist_id(input("Playlist ID or URL: "))

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
        print("\nCannot continue due to previous error. See messages above for details.")
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
            print("\n⏭️  Using cached results — showing preview before update...")
            sorted_items = sort_items(items)  # Will use cached results

            print(f"\n📋 Preview (showing all {len(sorted_items)} songs):\n")
            for i, item in enumerate(sorted_items, 1):
                data = cache.get(item["snippet"]["title"]) or smart_extract(item["snippet"]["title"])
                song_name = data['song'][:40] if data['song'] else "[NO EXTRACTION]"
                method = "⚡ Cached"
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
                print("\n✅ Playlist update completed!")
            else:
                print("\n❌ Update completed with errors. Try again later.")
            return

    # Precompute AI extractions in one pass (reduces AI calls)
    precompute_extractions(items, batch_size=args.batch_size, delay=args.batch_delay)

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

    success = update_playlist(yt, sorted_items, max_updates=args.max_updates, dry_run=args.dry_run)

    if success:
        print("\n✅ Done!")
    else:
        print("\n❌ Sorting completed with errors. Some items may not have been moved.")
        print("   You can try running the script again to complete the sorting.")


if __name__ == "__main__":
    main()