import re
import io
import math
import random
import string
import aiohttp
import asyncio
import hashlib
import requests
from info import *
from utils import *
from utils import clean_filename
from logging_helper import LOGGER
from typing import Optional, Dict, Any
from datetime import datetime
from pyrogram import Client, filters
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

# ====================================================================
# TMDB কনফিগারেশন (আপনার info.py তে হাত দেওয়ার দরকার নেই)
# আপনি চাইলে নিজের API KEY এখানে বসাতে পারেন
TMDB_API_KEY = "7dc544d9253bccc3cfecc1c677f69819" 
# ====================================================================

CAPTION_LANGUAGES = ["Bhojpuri", "Hindi", "Bengali", "Tamil", "English", "Bangla", "Telugu", "Malayalam", "Kannada", "Marathi", "Punjabi", "Gujrati", "Korean", "Spanish", "French", "Urdu"]

DEFAULT_IMAGE_URL = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"

SILENTX_PREMIUM_UPDATE = """
<b>⚡️ ℕ𝔼𝕎 ℙℝ𝔼𝕄𝕀𝕌𝕄 𝔸ℝℝ𝕀𝕍𝔼𝔻 ⚡️</b>

🎬 <b><u>{0}</u></b>

⭐️ <b>Rᴀᴛɪɴɢ:</b> {6}/10 <i>({7} Vᴏᴛᴇs)</i>
🎭 <b>Gᴇɴʀᴇ:</b> {8}
📅 <b>Rᴇʟᴇᴀsᴇ:</b> {5}

<b>╭──────── [ ᴍᴇᴅɪᴀ ɪɴꜰᴏ ]</b>
<b>│</b>
<b>│</b> 📂 <b>Tʏᴘᴇ:</b> <code>#{1}</code>
<b>│</b> 🔊 <b>Lᴀɴɢᴜᴀɢᴇ:</b> {2}
<b>│</b> 💿 <b>Fᴏʀᴍᴀᴛ:</b> {3}
<b>│</b> 🎥 <b>Dɪʀᴇᴄᴛᴏʀ:</b> {4}
<b>│</b>
<b>╰───────────────────</b>

<b>🚀 Pᴏᴡᴇʀᴇᴅ Bʏ @TGLinkBase</b>
"""

notified_movies = set()
media_filter = filters.document | filters.video | filters.audio

@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    for file_type in ("document", "video", "audio"):
        media = getattr(message, file_type, None)
        if media is not None:
            break
    else:
        return
    
    media.file_type = file_type
    media.caption = message.caption
    
    # ডাটাবেসে ফাইল সেভ করা
    success, silentxbotz = await save_file(media)
    
    try:  
        if success and silentxbotz == 1: 
            # ফাইল প্রসেসিং এর জন্য পাঠানো
            await send_movie_update(bot, file_name=media.file_name, caption=media.caption)
    except Exception as e:
        LOGGER.error(f"Error In Media Handler: {e}")
        pass

# --- উন্নত নাম ক্লিনিং ফাংশন ---
def parse_filename(filename):
    # কমন ফালতু শব্দ রিমুভ করা
    filename = filename.replace("_", " ").replace(".", " ")
    tags = [
        r"1080p", r"720p", r"480p", r"360p", r"2160p", r"4k", r"5k", r"8k", r"HDRip", 
        r"WEB-DL", r"BluRay", r"ESub", r"Dual Audio", r"H\.?264", r"H\.?265", r"HEVC", 
        r"10bit", r"x264", r"x265", r"AAC", r"Esub", r"Sub", r"mkv", r"mp4", r"avi",
        r"Hindi", r"English", r"Bengali", r"Tamil", r"Telugu", r"Kannada", r"Malayalam"
    ]
    
    clean_name = filename
    # ব্র্যাকেটের ভেতরের জিনিস রিমুভ (যেমন [Quality] বা (2024))
    # তবে সালটা রেখে দেওয়ার চেষ্টা করবো
    
    # সাল খোঁজা (1970-2030)
    year_match = re.search(r'\b(19|20)\d{2}\b', filename)
    year = year_match.group(0) if year_match else None
    
    # সাল পেলে সালের পরের সব অংশ কেটে ফেলা ভালো (বেশিরভাগ ক্ষেত্রে)
    if year:
        clean_name = filename.split(year)[0]
    
    # ট্যাগগুলো রিমুভ করা
    for tag in tags:
        clean_name = re.sub(tag, "", clean_name, flags=re.IGNORECASE)
    
    # অপ্রয়োজনীয় ক্যারেক্টার রিমুভ
    clean_name = re.sub(r"[^\w\s]", "", clean_name)
    clean_name = re.sub(r"\s+", " ", clean_name).strip()
    
    return clean_name, year

# --- TMDB ডাটা ফেচিং ফাংশন ---
async def fetch_tmdb_data(query, year=None):
    try:
        if not query:
            return None
            
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}&include_adult=true"
        if year:
            search_url += f"&year={year}"
            
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url) as resp:
                data = await resp.json()
                
        if not data.get("results"):
            return None
            
        # প্রথম রেজাল্ট নেওয়া
        result = data["results"][0]
        media_type = result.get("media_type", "movie")
        media_id = result.get("id")
        
        # ডিটেইলস আনা (Genre, Director এর জন্য)
        details_url = f"https://api.themoviedb.org/3/{media_type}/{media_id}?api_key={TMDB_API_KEY}&append_to_response=credits,videos"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(details_url) as resp:
                details = await resp.json()
                
        # প্রয়োজনীয় তথ্য সাজানো
        director = "N/A"
        if "credits" in details:
            crew = details["credits"].get("crew", [])
            directors = [member["name"] for member in crew if member["job"] == "Director"]
            if directors:
                director = directors[0]
                
        genres = [g["name"] for g in details.get("genres", [])]
        
        return {
            "title": details.get("title") or details.get("name"),
            "original_title": details.get("original_title") or details.get("original_name"),
            "kind": "Movie" if media_type == "movie" else "Series",
            "poster_path": details.get("poster_path"),
            "backdrop_path": details.get("backdrop_path"),
            "release_date": details.get("release_date") or details.get("first_air_date"),
            "vote_average": round(details.get("vote_average", 0), 1),
            "vote_count": details.get("vote_count", 0),
            "overview": details.get("overview"),
            "director": director,
            "genres": genres,
            "videos": details.get("videos", {}).get("results", [])
        }
        
    except Exception as e:
        LOGGER.error(f"TMDB Fetch Error: {e}")
        return None

async def send_movie_update(bot, file_name, caption):
    try:
        # ১. নাম ও সাল আলাদা করা
        search_query, year = parse_filename(file_name)
        
        if len(search_query) < 2:
            search_query = file_name # যদি ক্লিনিং এর পর নাম খুব ছোট হয়ে যায়
        
        # ডুপ্লিকেট চেক (মেমোরিতে)
        if file_name in notified_movies:
            return 

        # ২. TMDB থেকে ডাটা আনা
        tmdb_data = await fetch_tmdb_data(search_query, year)
        
        # যদি TMDB তে ডাটা না পাওয়া যায়, তবুও পোস্ট করার চেষ্টা করবো (Optional)
        # আপনি যদি চান ডাটা না পেলে পোস্ট হবে না, তাহলে নিচের লাইন আনকমেন্ট করুন
        if not tmdb_data: 
             LOGGER.info(f"No TMDB data found for: {search_query}")
             return 

        notified_movies.add(file_name)
        
        # লিংক তৈরির জন্য নাম ফরম্যাট
        search_movie = search_query.replace(" ", "-")

        # অন্যান্য তথ্য
        language = await get_languages(file_name) or "Multi-Audio"      
        
        # টেমপ্লেট ফিল করা
        full_caption = SILENTX_PREMIUM_UPDATE.format(
            escape_html(tmdb_data.get("title")),                 
            tmdb_data.get("kind", "Movie"),                      
            escape_html(language),                               
            "MKV" if "mkv" in file_name.lower() else "MP4",      
            escape_html(tmdb_data.get("director") or "N/A"),     
            escape_html(tmdb_data.get("release_date") or "TBA"), 
            tmdb_data.get("vote_average", 0),                    
            tmdb_data.get("vote_count", 0),                      
            escape_html(", ".join(tmdb_data.get("genres", [])[:3])) 
        )        
        
        await send_with_visual(bot, full_caption, tmdb_data, search_movie)        
    except Exception as e:
        LOGGER.error(f"Error In Movie Update Logic: {e}")

def escape_html(text: str) -> str:
    if not text: return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def get_trailer_button(tmdb_data: Dict) -> list:
    videos = tmdb_data.get("videos", [])
    if not isinstance(videos, list): videos = []
    yt_videos = [v for v in videos if "youtube" in str(v.get("url", "")).lower() or v.get("site") == "YouTube"]    
    
    url = None
    if yt_videos:
        key = yt_videos[0].get("key")
        site_url = yt_videos[0].get("url")
        if site_url:
            url = site_url
        elif key:
            url = f"https://www.youtube.com/watch?v={key}"
            
    if url:
        return [InlineKeyboardButton("▶️ Watch Trailer", url=url)]
    return []
    
async def send_with_visual(bot, caption: str, tmdb_data: Dict, search_movie):
    try:
        poster_path = tmdb_data.get("poster_path")
        backdrop_path = tmdb_data.get("backdrop_path")
        
        visual_url = DEFAULT_IMAGE_URL
        if poster_path:
            visual_url = f"https://image.tmdb.org/t/p/w500{poster_path}" # w500 is faster than original
        elif backdrop_path:
            visual_url = f"https://image.tmdb.org/t/p/w780{backdrop_path}"

        # ইউজারনেম সেফটি
        try:
            bot_username = bot.me.username
        except:
            bot_username = "TGLinkBase" # Fallback

        get_file = f'https://telegram.me/{bot_username}?start=getfile-{search_movie}'
        
        buttons = [
            [InlineKeyboardButton("📱 Get File", url=get_file)]
        ]
        trailer_btn = get_trailer_button(tmdb_data)
        if trailer_btn:
            buttons.append(trailer_btn)
            
        keyboard = InlineKeyboardMarkup(buttons)
        
        # ছবি ডাউনলোড করে পাঠানো (যাতে টেলিগ্রাম সার্ভারে ক্যাশ থাকে)
        if visual_url and visual_url != DEFAULT_IMAGE_URL:
            try:
                await bot.send_photo(
                    chat_id=MOVIE_UPDATE_CHANNEL, 
                    photo=visual_url, 
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard
                )
                return
            except Exception as e:
                LOGGER.error(f"Primary Image Failed: {e}")

        # প্রাইমারি ফেইল করলে ডিফল্ট
        await bot.send_photo(
            chat_id=MOVIE_UPDATE_CHANNEL,
            photo=DEFAULT_IMAGE_URL,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )       
    except Exception as e:
        LOGGER.error(f"Visual Send Error: {e}")

async def get_languages(text: str) -> str:
    if not text: return "Multi-Audio"
    found_langs = [lang for lang in CAPTION_LANGUAGES if lang.lower().replace(" ", "") in text.lower().replace(" ", "")]
    return ", ".join(found_langs[:2]) if found_langs else "Multi-Audio"
