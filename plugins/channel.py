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

# --- 1. ডাটাবেস হ্যান্ডলার ---
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
        # একসাথে অনেকগুলো ফাইল লিস্টে পুশ করা
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

# --- 2. সেটিংস এবং ব্যাচিং ভেরিয়েবল ---
MEDIA_FILTER = filters.document | filters.video | filters.audio
DEFAULT_IMAGE_URL = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"

# ব্যাচ প্রসেসিং এর জন্য ডিকশনারি
PENDING_QUEUE = {} 

CAPTION_LANGUAGES = {
    "hin": "Hindi", "eng": "English", "ben": "Bengali", "tam": "Tamil", 
    "tel": "Telugu", "mal": "Malayalam", "kan": "Kannada", "kor": "Korean", 
    "jpn": "Japanese", "spa": "Spanish", "fre": "French", "urd": "Urdu"
}

# Regex Patterns
QUALITY_PATTERN = re.compile(r"\b(?:480p|720p|1080p|2160p|4k|5k|8k|10bit|HDRip|WEB-DL|Bluray|HEVC|H264|H265)\b", re.IGNORECASE)
SEASON_EPISODE_PATTERN = re.compile(r'(?:S|Season)\s*(\d+).*?(?:E|Episode|Ep)\s*(\d+)', re.IGNORECASE)
YEAR_PATTERN = re.compile(r'\b(19|20)\d{2}\b')
JUNK_PATTERN = re.compile(r'[._]')

# --- 3. হেল্পার ফাংশন ---
def clean_filename(name):
    clean = JUNK_PATTERN.sub(" ", name)
    clean = re.sub(r'\[.*?\]|\(.*?\)', '', clean)
    
    year_match = YEAR_PATTERN.search(clean)
    year = year_match.group(0) if year_match else None
    
    if year:
        clean = clean.split(year)[0]
    
    junk_words = [
        "1080p", "720p", "480p", "360p", "web-dl", "webdl", "bluray", "mkv", "mp4", "avi",
        "hindi", "english", "dual", "audio", "sub", "esub", "x264", "x265", "hevc", "10bit",
        "org", "hdcam", "hdtc", "camrip", "dvdscr", "rip", "unknown", "sample"
    ]
    for junk in junk_words:
        clean = re.sub(r'\b' + junk + r'\b', '', clean, flags=re.IGNORECASE)
        
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean, year

def get_quality(name):
    match = QUALITY_PATTERN.findall(name)
    return ", ".join(list(set(match))) if match else "HD"

def get_language(name):
    langs = []
    name_lower = name.lower()
    for code, lang in CAPTION_LANGUAGES.items():
        if code in name_lower or lang.lower() in name_lower:
            langs.append(lang)
    return ", ".join(langs) if langs else "Multi-Audio"

# --- 4. TMDB এবং ক্যাপশন ---
async def fetch_tmdb(query, year):
    try:
        url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
        if year: url += f"&year={year}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
        
        if not data.get('results'): return None
        
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
            eps = sorted(list(set(seasons[s])), key=int)
            ep_display = []
            
            if len(eps) > 1:
                start = eps[0]
                end = eps[0]
                range_str = []
                for i in range(1, len(eps)):
                    if eps[i] == end + 1:
                        end = eps[i]
                    else:
                        if start == end: range_str.append(str(start))
                        else: range_str.append(f"{start}-{end}")
                        start = end = eps[i]
                if start == end: range_str.append(str(start))
                else: range_str.append(f"{start}-{end}")
                ep_display = range_str
            else:
                ep_display.append(str(eps[0]))
                
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

# --- 5. ব্যাকগ্রাউন্ড প্রসেসর (Worker) ---
async def batch_processor(bot, unique_id, clean_name, year):
    await asyncio.sleep(BATCH_TIME) # ১০ সেকেন্ড অপেক্ষা
    
    # কিউ থেকে ফাইলগুলো বের করা
    if unique_id not in PENDING_QUEUE:
        return
        
    files_to_process = PENDING_QUEUE.pop(unique_id)
    
    try:
        search_slug = clean_name.replace(" ", "-")
        db_movie = await mdb.get_movie(unique_id)
        
        # --- নতুন মুভি ---
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
                "files": files_to_process, # সব ফাইল একসাথে
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
            
        # --- আপডেট মুভি ---
        else:
            # শুধু নতুন ইউনিক ফাইলগুলো ফিল্টার করা
            existing_filenames = [f['filename'] for f in db_movie['files']]
            new_files = [f for f in files_to_process if f['filename'] not in existing_filenames]
            
            if not new_files: return

            await mdb.update_movie_files(unique_id, new_files)
            
            # ডাটাবেস থেকে ফ্রেশ ডাটা আনা
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
    except Exception as e:
        print(f"Batch Processor Error: {e}")

# --- 6. মেইন হ্যান্ডলার (Collector) ---
@Client.on_message(filters.chat(CHANNELS) & MEDIA_FILTER)
async def media_handler(bot, message):
    try:
        media = getattr(message, message.media.value)
        filename = media.file_name
        caption = message.caption or ""
        
        # ১. অরিজিনাল ডাটাবেসে সেভ (সার্চের জন্য - ইনস্ট্যান্ট)
        success, info = await save_file(media)
        if not success: return 
        
        # ২. তথ্য বের করা
        clean_name, year = clean_filename(filename)
        quality = get_quality(filename)
        language = get_language(filename + caption)
        
        unique_id = f"{clean_name}_{year}" if year else clean_name
        
        se_match = SEASON_EPISODE_PATTERN.search(filename)
        season = int(se_match.group(1)) if se_match else None
        episode = int(se_match.group(2)) if se_match else None
        
        file_data = {
            "filename": filename,
            "quality": quality,
            "language": language,
            "season": season,
            "episode": episode
        }
        
        # ৩. ব্যাচিং লজিক
        # যদি এই মুভিটি কিউতে না থাকে, তবে নতুন কিউ তৈরি করে টাইমার চালু করো
        if unique_id not in PENDING_QUEUE:
            PENDING_QUEUE[unique_id] = [file_data]
            # ব্যাকগ্রাউন্ড টাস্ক চালু করা
            asyncio.create_task(batch_processor(bot, unique_id, clean_name, year))
        else:
            # আর যদি টাইমার চলতে থাকে, তাহলে শুধু ফাইলটা লিস্টে যোগ করে দাও
            PENDING_QUEUE[unique_id].append(file_data)
            
    except Exception as e:
        print(f"Media Handler Error: {e}")
