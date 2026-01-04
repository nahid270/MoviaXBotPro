import re
import asyncio
import aiohttp
from datetime import datetime
from pyrogram import Client, filters, enums
from info import CHANNELS, MOVIE_UPDATE_CHANNEL, DATABASE_URI, DATABASE_NAME
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from utils import temp

# ====================================================================
# 🔥 TMDB API KEY
TMDB_API_KEY = "7dc544d9253bccc3cfecc1c677f69819"
# ⏳ কত সেকেন্ড অপেক্ষা করবে? (ডিফল্ট ১০ সেকেন্ড)
BATCH_TIME = 10 
# ====================================================================

# --- 1. কনফিগারেশন এবং ইগনোর লিস্ট ---

IGNORE_WORDS = {
    "rarbg", "dub", "sub", "sample", "mkv", "aac", "combined",
    "action", "adventure", "animation", "biography", "comedy", "crime", 
    "documentary", "drama", "fantasy", "film-noir", "history", 
    "horror", "music", "musical", "mystery", "romance", "sci-fi", "sport", 
    "thriller", "war", "western", "hdcam", "hdtc", "camrip", "ts", "tc", 
    "telesync", "dvdscr", "dvdrip", "predvd", "webrip", "web-dl", "tvrip", 
    "hdtv", "web dl", "webdl", "bluray", "brrip", "bdrip", "360p", "480p", 
    "720p", "1080p", "2160p", "4k", "1440p", "540p", "240p", "140p", "hevc", 
    "hdrip", "hin", "hindi", "tam", "tamil", "kan", "kannada", "tel", "telugu", 
    "mal", "malayalam", "eng", "english", "pun", "punjabi", "ben", "bengali", 
    "mar", "marathi", "guj", "gujarati", "urd", "urdu", "kor", "korean", "jpn", 
    "japanese", "nf", "netflix", "sonyliv", "sony", "sliv", "amzn", "prime", 
    "primevideo", "hotstar", "zee5", "jio", "jhs", "aha", "hbo", "paramount", 
    "apple", "hoichoi", "sunnxt", "viki", "official", "download", "link", 
    "original", "part", "vol", "season", "episode", "ep", "s0", "e0",
    "cinevood", "hdhub4u", "skymoviedhd", "p-23", "moviesmod"
}

OTT_PLATFORMS = {
    "nf": "Netflix", "netflix": "Netflix",
    "sonyliv": "SonyLiv", "sony": "SonyLiv", "sliv": "SonyLiv",
    "amzn": "Amazon Prime Video", "prime": "Amazon Prime Video", "primevideo": "Amazon Prime Video",
    "hotstar": "Disney+ Hotstar", "zee5": "Zee5",
    "jio": "JioHotstar", "jhs": "JioHotstar",
    "aha": "Aha", "hbo": "HBO Max", "paramount": "Paramount+",
    "apple": "Apple TV+", "hoichoi": "Hoichoi", "sunnxt": "Sun NXT", "viki": "Viki"
}

CAPTION_LANGUAGES = {
    "hin": "Hindi", "hindi": "Hindi", "tam": "Tamil", "tamil": "Tamil",
    "tel": "Telugu", "telugu": "Telugu", "mal": "Malayalam", "malayalam": "Malayalam",
    "eng": "English", "english": "English", "ben": "Bengali", "bengali": "Bengali"
}

# Regex Patterns
CLEAN_PATTERN = re.compile(r'@[^ \n\r\t\.,:;!?()\[\]{}<>\\/"\'=_%]+|\bwww\.[^\s\]\)]+|\([\@^]+\)|\[[\@^]+\]')
NORMALIZE_PATTERN = re.compile(r"[._]+|[()\[\]{}:;'–!,.?_]")
QUALITY_PATTERN = re.compile(r"\b(?:HDCam|HDTC|CamRip|TS|TC|TeleSync|DVDScr|DVDRip|PreDVD|WEBRip|WEB-DL|TVRip|HDTV|WEB DL|WebDl|BluRay|BRRip|BDRip|360p|480p|720p|1080p|2160p|4K|1440p|540p|240p|140p|HEVC|HDRip)\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d{2}(?![A-Za-z0-9])")
RANGE_REGEX = re.compile(r'\bS(\d{1,2})[^\w\n\r]*E(?:p(?:isode)?)?0*(\d{1,2})\s*(?:to|-)\s*(?:E(?:p(?:isode)?)?)?0*(\d{1,2})',re.IGNORECASE)
SINGLE_REGEX = re.compile(r'\bS(\d{1,2})[^\w\n\r]*E(?:p(?:isode)?)?0*(\d{1,3})', re.IGNORECASE)
NAMED_REGEX = re.compile(r'Season\s*0*(\d{1,2})[\s\-,:]*Ep(?:isode)?\s*0*(\d{1,3})', re.IGNORECASE)
EP_ONLY_RANGE = re.compile(r'\b(?:EP|Episode)0*(\d{1,3})\s*-\s*0*(\d{1,3})\b',re.IGNORECASE)

# --- 2. ডাটাবেস হ্যান্ডলার ---
class MovieUpdateDB:
    def __init__(self, uri, database_name):
        self._client = AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db["movie_updates_v3"] 

    async def get_movie(self, unique_id):
        return await self.col.find_one({"_id": unique_id})

    async def add_movie(self, unique_id, data):
        await self.col.insert_one(data)

    async def update_movie_files(self, unique_id, new_files_list):
        await self.col.update_one(
            {"_id": unique_id},
            {"$push": {"files": {"$each": new_files_list}}}
        )
    
    async def update_message_id(self, unique_id, msg_id):
        await self.col.update_one(
            {"_id": unique_id},
            {"$set": {"message_id": msg_id}}
        )

mdb = MovieUpdateDB(DATABASE_URI, DATABASE_NAME)
PENDING_QUEUE = {}
MEDIA_FILTER = filters.document | filters.video | filters.audio
DEFAULT_IMAGE_URL = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"

# --- 3. হেল্পার ফাংশন ---

def clean_mentions_links(text: str) -> str:
    return CLEAN_PATTERN.sub("", text or "").strip()

def normalize(s: str) -> str:
    s = NORMALIZE_PATTERN.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def remove_ignored_words(text: str) -> str:
    IGNORE_WORDS_LOWER = {w.lower() for w in IGNORE_WORDS}
    return " ".join(word for word in text.split() if word.lower() not in IGNORE_WORDS_LOWER)

def get_qualities(text: str) -> str:
    qualities = QUALITY_PATTERN.findall(text)
    return ", ".join(list(set(qualities))) if qualities else "HD"

def extract_ott_platform(text: str) -> str:
    text = text.lower()
    platforms = {plat for key, plat in OTT_PLATFORMS.items() if key in text}
    return " | ".join(platforms) if platforms else "N/A"

def extract_season_episode(filename: str):
    if m := EP_ONLY_RANGE.search(filename):
        return 1, f"{int(m.group(1))}-{int(m.group(2))}"
    for pattern in (RANGE_REGEX, SINGLE_REGEX, NAMED_REGEX):
        if m := pattern.search(filename):
            season = int(m.group(1))
            if pattern == RANGE_REGEX:
                ep = f"{m.group(2)}-{m.group(3)}"
            else:
                ep = m.group(2)
            return season, ep
    return None, None

def extract_media_info(filename: str, caption: str):
    filename = normalize(clean_mentions_links(filename).title())
    caption_clean = clean_mentions_links(caption).lower() if caption else ""
    
    season = episode = year = None
    tag = "#MOVIE"
    
    quality = get_qualities(filename) or get_qualities(caption_clean) or "HD"
    ott_platform = extract_ott_platform(f"{filename} {caption_clean}")
    
    lang_keys = {k for k in CAPTION_LANGUAGES if k in caption_clean or k in filename.lower()}
    language = ", ".join(sorted({CAPTION_LANGUAGES[k] for k in lang_keys})) if lang_keys else "Multi-Audio"

    season, episode = extract_season_episode(filename)
    processed_raw = filename
    
    if season is not None:
        tag = "#SERIES"
        for pattern in (RANGE_REGEX, SINGLE_REGEX, NAMED_REGEX, EP_ONLY_RANGE):
            if m := pattern.search(filename):
                match_str = m.group(0)
                start_idx = filename.find(match_str)
                processed_raw = filename[:start_idx] 
                break
    else:
        if year_match := YEAR_PATTERN.search(filename):
            year = year_match.group(0)
            year_idx = filename.find(year)
            processed_raw = filename[:year_idx] 
        
    base_name = normalize(remove_ignored_words(normalize(processed_raw)))
    
    if len(base_name) < 2:
        base_name = processed_raw.split()[0] if processed_raw else "Unknown"

    return {
        "base_name": base_name.strip(),
        "year": year,
        "quality": quality,
        "language": language,
        "season": season,
        "episode": episode,
        "tag": tag,
        "ott_platform": ott_platform
    }

# --- 4. TMDB Fetcher ---
async def fetch_tmdb(query, year):
    try:
        url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
        if year: url += f"&year={year}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
        
        if not data.get('results'):
             clean_query = re.sub(r'[^\w\s]', '', query)
             if clean_query != query and len(clean_query) > 1:
                 return await fetch_tmdb(clean_query, year)
             return None
        
        res = data['results'][0]
        m_id = res['id']
        m_type = res['media_type']
        
        det_url = f"https://api.themoviedb.org/3/{m_type}/{m_id}?api_key={TMDB_API_KEY}"
        async with aiohttp.ClientSession() as session:
            async with session.get(det_url) as resp:
                details = await resp.json()
                
        poster = details.get('poster_path')
        backdrop = details.get('backdrop_path')
        
        img_url = DEFAULT_IMAGE_URL
        if poster:
            img_url = f"https://image.tmdb.org/t/p/original{poster}"
        elif backdrop:
            img_url = f"https://image.tmdb.org/t/p/original{backdrop}"
        
        return {
            "title": details.get('title') or details.get('name'),
            "rating": round(details.get('vote_average', 0), 1),
            "genres": ", ".join([g['name'] for g in details.get('genres', [])][:3]),
            "year": (details.get('release_date') or details.get('first_air_date') or "N/A")[:4],
            "plot": details.get('overview', "No overview available."),
            "poster": img_url,
            "type": "Series" if m_type == "tv" else "Movie"
        }
    except Exception as e:
        print(f"TMDB Error: {e}")
        return None

# --- 🔥 FIX: SAFE SORT KEY ---
def get_ep_sort_key(ep):
    try:
        return int(ep)
    except:
        try:
            # যদি "1-8" হয় তবে প্রথম সংখ্যাটি (1) রিটার্ন করবে
            return int(str(ep).split('-')[0])
        except:
            return 0

def generate_caption(data, files_list):
    seasons = {}
    qualities = set()
    languages = set()
    
    for f in files_list:
        if f.get('quality'): qualities.add(f['quality'])
        if f.get('language'): languages.add(f['language'])
        
        if f.get('season'):
            s = f['season']
            e = f['episode']
            if s not in seasons: seasons[s] = []
            seasons[s].append(e)
            
    epi_text = ""
    if seasons:
        for s in sorted(seasons.keys()):
            # এখানে ক্র্যাশ হচ্ছিল, তাই কাস্টম sort key ব্যবহার করা হয়েছে
            eps_list = list(set(seasons[s]))
            eps_list.sort(key=get_ep_sort_key)
            
            ep_display = []
            
            # সিঙ্গেল এপিসোড এবং রেঞ্জ আলাদা করা
            singles = []
            ranges = []
            
            for ep in eps_list:
                try:
                    singles.append(int(ep))
                except:
                    ranges.append(str(ep))
            
            # সিঙ্গেল এপিসোডগুলো স্মার্টলি গ্রুপ করা (1,2,3 -> 1-3)
            if singles:
                singles.sort()
                start = singles[0]
                end = singles[0]
                for i in range(1, len(singles)):
                    if singles[i] == end + 1:
                        end = singles[i]
                    else:
                        if start == end: ep_display.append(str(start))
                        else: ep_display.append(f"{start}-{end}")
                        start = end = singles[i]
                if start == end: ep_display.append(str(start))
                else: ep_display.append(f"{start}-{end}")
            
            # রেঞ্জগুলো (যেমন "1-8") যোগ করে দেওয়া
            ep_display.extend(ranges)
            
            epi_text += f"\n┠ 📺 <b>Season {s}:</b> Ep {', '.join(ep_display)}"

    caption = f"""
<b>⚡️ ℕ𝔼𝕎 ℙℝ𝔼𝕄𝕀𝕌𝕄 𝔸ℝℝ𝕀𝕍𝔼𝔻 ⚡️</b>

┏━━━━━━━━━━━━━━━━━━━┫
┃🎬 <b>Title:</b> {data['title']}
┃⭐️ <b>Rating:</b> {data['rating']}/10
┃🎭 <b>Genre:</b> {data['genres']}
┃📅 <b>Year:</b> {data['year']}
┗━━━━━━━━━━━━━━━━━━━┫

<b>⚡️ Media Info:</b>
┠ 🔊 <b>Languages:</b> {", ".join(list(languages)[:3])}
┠ 💿 <b>Quality:</b> {", ".join(list(qualities)[:3])}
┠ 📂 <b>Type:</b> {data['type']}{epi_text}

<b>📖 Plot Summary:</b>
❝ <i>{data['plot'][:250]}...</i> ❞

<b>🚀 Pᴏᴡᴇʀᴇᴅ Bʏ @TGLinkBase</b>
"""
    return caption

# --- 5. ব্যাকগ্রাউন্ড প্রসেসর ---
async def batch_processor(bot, unique_id, clean_name, year):
    await asyncio.sleep(BATCH_TIME)
    
    if unique_id not in PENDING_QUEUE:
        return
        
    files_to_process = PENDING_QUEUE.pop(unique_id)
    
    try:
        search_slug = clean_name.replace(" ", "-")
        db_movie = await mdb.get_movie(unique_id)
        
        # --- NEW MOVIE ---
        if not db_movie:
            tmdb_data = await fetch_tmdb(clean_name, year)
            if not tmdb_data: 
                tmdb_data = {
                    "title": clean_name, "rating": "N/A", "genres": "Unknown",
                    "year": year or "N/A", "plot": "N/A", "poster": DEFAULT_IMAGE_URL, "type": "Movie"
                }
            
            full_data = {
                "_id": unique_id,
                "tmdb": tmdb_data,
                "files": files_to_process, 
                "message_id": None
            }
            await mdb.add_movie(unique_id, full_data)
            
            cap = generate_caption(tmdb_data, files_to_process)
            btn = InlineKeyboardMarkup([[InlineKeyboardButton('ɢᴇᴛ ғɪʟᴇs', url=f"https://t.me/{bot.me.username}?start=getfile-{search_slug}")]])
            
            msg = await bot.send_photo(
                chat_id=MOVIE_UPDATE_CHANNEL,
                photo=tmdb_data['poster'],
                caption=cap,
                reply_markup=btn,
                parse_mode=enums.ParseMode.HTML
            )
            await mdb.update_message_id(unique_id, msg.id)
            
        # --- UPDATE MOVIE ---
        else:
            existing_filenames = [f['filename'] for f in db_movie['files']]
            new_files = [f for f in files_to_process if f['filename'] not in existing_filenames]
            
            if new_files:
                await mdb.update_movie_files(unique_id, new_files)
            
            db_movie = await mdb.get_movie(unique_id)
            cap = generate_caption(db_movie['tmdb'], db_movie['files'])
            btn = InlineKeyboardMarkup([[InlineKeyboardButton('ɢᴇᴛ ғɪʟᴇs', url=f"https://t.me/{bot.me.username}?start=getfile-{search_slug}")]])
            
            if db_movie.get('message_id'):
                try:
                    await bot.edit_message_caption(
                        chat_id=MOVIE_UPDATE_CHANNEL,
                        message_id=db_movie['message_id'],
                        caption=cap,
                        reply_markup=btn,
                        parse_mode=enums.ParseMode.HTML
                    )
                except Exception:
                    msg = await bot.send_photo(
                        chat_id=MOVIE_UPDATE_CHANNEL,
                        photo=db_movie['tmdb']['poster'],
                        caption=cap,
                        reply_markup=btn,
                        parse_mode=enums.ParseMode.HTML
                    )
                    await mdb.update_message_id(unique_id, msg.id)
            else:
                msg = await bot.send_photo(
                    chat_id=MOVIE_UPDATE_CHANNEL,
                    photo=db_movie['tmdb']['poster'],
                    caption=cap,
                    reply_markup=btn,
                    parse_mode=enums.ParseMode.HTML
                )
                await mdb.update_message_id(unique_id, msg.id)

    except Exception as e:
        print(f"Batch Processor Error: {e}")

# --- 6. Main Handler ---
@Client.on_message(filters.chat(CHANNELS) & MEDIA_FILTER)
async def media_handler(bot, message):
    try:
        for file_type in ("document", "video", "audio"):
            media = getattr(message, file_type, None)
            if media is not None:
                break
        else:
            return

        media.file_type = file_type 
        media.caption = message.caption or ""
        filename = media.file_name
        
        # Save to DB
        await save_file(media)
        
        info_data = extract_media_info(filename, media.caption)
        
        clean_name = info_data["base_name"]
        year = info_data["year"]
        unique_id = f"{clean_name}_{year}" if year else clean_name
        
        file_data = {
            "filename": filename,
            "quality": info_data["quality"],
            "language": info_data["language"],
            "season": info_data["season"],
            "episode": info_data["episode"]
        }
        
        if unique_id not in PENDING_QUEUE:
            PENDING_QUEUE[unique_id] = [file_data]
            asyncio.create_task(batch_processor(bot, unique_id, clean_name, year))
        else:
            PENDING_QUEUE[unique_id].append(file_data)
            
    except Exception as e:
        print(f"Media Handler Error: {e}")
