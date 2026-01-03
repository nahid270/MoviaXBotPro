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

CAPTION_LANGUAGES = ["Bhojpuri", "Hindi", "Bengali", "Tamil", "English", "Bangla", "Telugu", "Malayalam", "Kannada", "Marathi", "Punjabi", "Bengoli", "Gujrati", "Korean", "Gujarati", "Spanish", "French", "German", "Chinese", "Arabic", "Portuguese", "Russian", "Japanese", "Odia", "Assamese", "Urdu"]

DEFAULT_IMAGE_URL = "https://te.legra.ph/file/88d845b4f8a024a71465d.jpg"

# === আপনার পছন্দ করা নতুন টেমপ্লেট ===
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

<b>🚀 Pᴏᴡᴇʀᴇᴅ Bʏ @SilentXBotz</b>
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
    success, silentxbotz = await save_file(media)
    try:  
        if success and silentxbotz == 1 and await get_status(bot.me.id):            
            await send_movie_update(bot, file_name=media.file_name, caption=media.caption)
    except Exception as e:
        LOGGER.error(f"Error In Movie Update - {e}")
        pass

async def send_movie_update(bot, file_name, caption):
    try:
        file_name = clean_filename(file_name)
        caption = clean_filename(caption)
        year_match = re.search(r"\b(19|20)\d{2}\b", caption)
        year = year_match.group(0) if year_match else None      
        season_match = re.search(r"(?i)(?:s|season)0*(\d{1,2})", caption) or re.search(r"(?i)(?:s|season)0*(\d{1,2})", file_name)
        if year:
            file_name = file_name[:file_name.find(year) + 4]
        elif season_match:
            season = season_match.group(1)
            file_name = file_name[:file_name.find(season) + 1]
        quality = await get_qualities(caption) or "HDRip"
        pixel = await get_pixels(caption) or "720p"
        language = await get_languages(caption) or "Multi-Audio"      
        if file_name in notified_movies:
            return 
        notified_movies.add(file_name)      
        tmdb_data = await fetch_tmdb_data(file_name, year)
        search_movie = file_name.replace(" ", "-")
        if not tmdb_data:
            return
        
        # ফরম্যাটিং সেটআপ (নতুন টেমপ্লেট অনুযায়ী)
        full_caption = SILENTX_PREMIUM_UPDATE.format(
            escape_html(tmdb_data.get("title")),                 # {0}
            tmdb_data.get("kind", "Movie"),                      # {1}
            escape_html(language),                               # {2}
            "MKV" if "mkv" in file_name.lower() else "MP4",      # {3}
            escape_html(tmdb_data.get("director") or "N/A"),     # {4}
            escape_html(tmdb_data.get("release_date") or "TBA"), # {5}
            tmdb_data.get("vote_average", 0),                    # {6}
            tmdb_data.get("vote_count", 0),                      # {7}
            escape_html(", ".join(tmdb_data.get("genres", [])[:3])) # {8}
        )        
        await send_with_visual(bot, full_caption, tmdb_data, search_movie)        
    except Exception as e:
        LOGGER.error(f"Error In Movie Update: {e}")

def escape_html(text: str) -> str:
    if not text:
        return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

async def get_director_from_crew(crew: list) -> str:
    directors = [person["name"] for person in crew if person.get("job") == "Director"]
    return directors[0] if directors else None

def get_trailer_button(tmdb_data: Dict) -> list:
    videos = tmdb_data.get("videos", [])
    # যদি videos লিস্ট আকারে না থাকে, সেফটি চেক
    if not isinstance(videos, list):
         videos = []
         
    yt_videos = [v for v in videos if "youtube" in str(v.get("url", "")).lower() or v.get("site") == "YouTube"]    
    if yt_videos:
        key = yt_videos[0].get("key")
        url = yt_videos[0].get("url")
        # YouTube URL জেনারেট করা
        final_url = url if url else f"https://www.youtube.com/watch?v={key}"
        return [InlineKeyboardButton("▶️ Watch Trailer", url=final_url)]
    return []
    
async def send_with_visual(bot, caption: str, tmdb_data: Dict, search_movie):
    try:
        # === পরিবর্তন: এখানে সরাসরি পোস্টার পাথ চেক করা হচ্ছে ===
        # আগে get_best_visual কল করা হতো যা ল্যান্ডস্কেপ দিতো
        poster_path = tmdb_data.get("poster_path")
        backdrop_path = tmdb_data.get("backdrop_path")
        
        visual_url = None
        
        # ১. ভার্টিক্যাল পোস্টার (Portrait) প্রায়োরিটি
        if poster_path:
            visual_url = f"https://image.tmdb.org/t/p/original{poster_path}"
        # ২. না পেলে ব্যাকড্রপ (Landscape)
        elif backdrop_path:
            visual_url = f"https://image.tmdb.org/t/p/original{backdrop_path}"
        # ৩. তাও না পেলে আগের মেথড বা ডিফল্ট
        else:
             visual_url = await get_best_visual(tmdb_data)

        get_file = f'https://telegram.me/{temp.U_NAME}?start=getfile-{search_movie}'
        
        buttons = [
            [InlineKeyboardButton("📱 Get File", url=get_file)]
        ]
        
        # ট্রেইলার বাটন যোগ করা
        trailer_btn = get_trailer_button(tmdb_data)
        if trailer_btn:
            buttons.append(trailer_btn)
            
        keyboard = InlineKeyboardMarkup(buttons)
        
        if visual_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(visual_url, timeout=aiohttp.ClientTimeout(total=20)) as img_resp:
                    if img_resp.status == 200:
                        img_bytes = await img_resp.read()
                        photo_file = io.BytesIO(img_bytes)
                        photo_file.name = await generate_premium_filename(tmdb_data.get("title", "image"))
                        
                        await bot.send_photo(
                            chat_id=MOVIE_UPDATE_CHANNEL, 
                            photo=photo_file, 
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=keyboard
                        )
                        return       
        
        # কোনো কারণে ইমেজ না পেলে ডিফল্ট ইমেজ
        await bot.send_photo(
            chat_id=MOVIE_UPDATE_CHANNEL,
            photo=DEFAULT_IMAGE_URL,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )       
    except Exception as e:
        LOGGER.error(f"Visual Send Error: {e}")

async def generate_premium_filename(title: str, extension=".jpg") -> str:
    # ফাইলের নামে স্পেস সরিয়ে আন্ডারস্কোর দেওয়া হলো যাতে টেলিগ্রাম ভালো ভাবে প্রসেস করে
    clean_title = re.sub(r'[^\w\s-]', '', str(title))[:20].strip().replace(" ", "_")
    timestamp = datetime.now().strftime("%y%m%d%H%M")
    unique_id = hashlib.md5(str(title).encode()).hexdigest()[:6]
    return f"silentx_{clean_title}_{timestamp}_{unique_id}{extension}"

async def get_languages(text: str) -> str:
    if not text: return "Multi-Audio"
    found_langs = [lang for lang in CAPTION_LANGUAGES if lang.lower().replace(" ", "") in text.lower().replace(" ", "")]
    return ", ".join(found_langs[:2]) if found_langs else "Multi-Audio"

async def get_qualities(text): 
    qualities = ["ORG", "org", "hdcam", "HDCAM", "HQ", "hq", "HDRip", "hdrip", "camrip", "WEB-DL", "CAMRip", "hdtc", "predvd", "DVDscr", "dvdscr", "dvdrip", "HDTC", "dvdscreen", "HDTS", "hdts"]
    return ", ".join([q for q in qualities if q.lower() in text.lower()])

async def get_pixels(caption):
    pixels = ["480p", "480p HEVC", "720p", "720p HEVC", "1080p", "1080p HEVC", "2160p", "2K", "4K"]
    return ", ".join([p for p in pixels if p.lower() in caption.lower()])
