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

# === আপনার পছন্দ করা মডার্ন টেমপ্লেট ===
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
    success, silentxbotz = await save_file(media)
    try:  
        if success and silentxbotz == 1 and await get_status(bot.me.id):            
            await send_movie_update(bot, file_name=media.file_name, caption=media.caption)
    except Exception as e:
        LOGGER.error(f"Error In Movie Update - {e}")
        pass

async def send_movie_update(bot, file_name, caption):
    try:
        # ফাইলের নাম ক্লিন করা এবং অরিজিনাল নাম সংরক্ষণ করা
        original_file_name = file_name
        file_name = clean_filename(file_name)
        caption_text = clean_filename(caption) if caption else file_name
        
        # সাল (Year) বের করা
        year_match = re.search(r"\b(19|20)\d{2}\b", caption_text) or re.search(r"\b(19|20)\d{2}\b", file_name)
        year = year_match.group(0) if year_match else None      
        
        # ডুপ্লিকেট চেক
        if original_file_name in notified_movies:
            return 
        
        # ভাষা এবং অন্যান্য তথ্য
        language = await get_languages(caption_text) or "Multi-Audio"      
        
        # TMDB ডাটা ফেচ করা
        tmdb_data = await fetch_tmdb_data(file_name, year)
        
        if not tmdb_data:
            return          
            
        notified_movies.add(original_file_name)
        
        search_movie = tmdb_data.get("title", file_name).replace(" ", "-")

        # নতুন টেমপ্লেট অনুযায়ী ফরম্যাটিং
        full_caption = SILENTX_PREMIUM_UPDATE.format(
            escape_html(tmdb_data["title"]),                   # {0} Title
            tmdb_data.get("kind", "Movie"),                    # {1} Kind
            escape_html(language),                             # {2} Language
            "MKV" if "mkv" in original_file_name.lower() else "MP4", # {3} Format
            escape_html(tmdb_data.get("director", "N/A")),     # {4} Director
            escape_html(tmdb_data.get("release_date", "TBA")), # {5} Release
            tmdb_data.get("vote_average", 0),                  # {6} Rating
            tmdb_data.get("vote_count", 0),                    # {7} Votes
            escape_html(", ".join(tmdb_data.get("genres", [])[:3]))  # {8} Genres
        )        
        await send_with_visual(bot, full_caption, tmdb_data, search_movie)        
    except Exception as e:
        LOGGER.error(f"Error In Movie Update Logic: {e}")

def escape_html(text: str) -> str:
    if not text:
        return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def get_trailer_button(tmdb_data: Dict) -> list:
    videos = tmdb_data.get("videos", [])
    # অনেক সময় ভিডিও 'results' এর মধ্যে থাকে
    if not videos and "results" in tmdb_data:
        videos = tmdb_data["results"]
        
    yt_videos = [v for v in videos if "youtube" in str(v.get("url", "")).lower() or v.get("site") == "YouTube"]    
    
    if yt_videos:
        key = yt_videos[0].get("key")
        url = yt_videos[0].get("url")
        final_url = url if url else f"https://www.youtube.com/watch?v={key}"
        return [InlineKeyboardButton("▶️ Watch Trailer", url=final_url)]
    return []
    
async def send_with_visual(bot, caption: str, tmdb_data: Dict, search_movie):
    try:
        # === পোস্টার লজিক (অরিজিনাল ভার্টিক্যাল পোস্টার প্রায়োরিটি) ===
        poster_path = tmdb_data.get("poster_path")
        backdrop_path = tmdb_data.get("backdrop_path")
        
        visual_url = None
        
        # ১. আগে দেখবে পোস্টার (লম্বা ছবি) আছে কিনা
        if poster_path:
            visual_url = f"https://image.tmdb.org/t/p/original{poster_path}"
        # ২. না থাকলে ব্যাকড্রপ (ল্যান্ডস্কেপ)
        elif backdrop_path:
            visual_url = f"https://image.tmdb.org/t/p/original{backdrop_path}"
        # ৩. তাও না থাকলে ডিফল্ট
        else:
            visual_url = DEFAULT_IMAGE_URL

        get_file = f'https://telegram.me/{temp.U_NAME}?start=getfile-{search_movie}'
        
        buttons = [
            [InlineKeyboardButton("📱 Get File", url=get_file)]
        ]
        trailer_btn = get_trailer_button(tmdb_data)
        if trailer_btn:
            buttons.append(trailer_btn)
            
        keyboard = InlineKeyboardMarkup(buttons)
        
        if visual_url and visual_url != DEFAULT_IMAGE_URL:
            async with aiohttp.ClientSession() as session:
                async with session.get(visual_url, timeout=aiohttp.ClientTimeout(total=20)) as img_resp:
                    if img_resp.status == 200:
                        img_bytes = await img_resp.read()
                        photo_file = io.BytesIO(img_bytes)
                        photo_file.name = await generate_premium_filename(tmdb_data.get("title", "movie"))
                        
                        await bot.send_photo(
                            chat_id=MOVIE_UPDATE_CHANNEL, 
                            photo=photo_file, 
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=keyboard
                        )
                        return       
        
        # কোনো কারণে ইমেজ লোড না হলে ডিফল্ট ইমেজ
        await bot.send_photo(
            chat_id=MOVIE_UPDATE_CHANNEL,
            photo=DEFAULT_IMAGE_URL,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )       
    except Exception as e:
        LOGGER.error(f"Visual Send Error: {e}")
        try:
             await bot.send_photo(
                chat_id=MOVIE_UPDATE_CHANNEL,
                photo=DEFAULT_IMAGE_URL,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        except:
            pass

async def generate_premium_filename(title: str, extension=".jpg") -> str:
    clean_title = re.sub(r'[^\w\s-]', '', title)[:20].strip().replace(" ", "_")
    timestamp = datetime.now().strftime("%y%m%d%H%M")
    unique_id = hashlib.md5(title.encode()).hexdigest()[:6]
    return f"silentx_{clean_title}_{timestamp}_{unique_id}{extension}"

async def get_languages(text: str) -> str:
    if not text: return "Multi-Audio"
    found_langs = [lang for lang in CAPTION_LANGUAGES if lang.lower().replace(" ", "") in text.lower().replace(" ", "")]
    return ", ".join(found_langs[:2]) if found_langs else "Multi-Audio"

# Get Qualities এবং Get Pixels ফাংশনগুলো আগের মতোই আপনার utils এ থাকবে।
async def get_qualities(text): 
    qualities = ["ORG", "org", "hdcam", "HDCAM", "HQ", "hq", "HDRip", "hdrip", "camrip", "WEB-DL", "CAMRip", "hdtc", "predvd", "DVDscr", "dvdscr", "dvdrip", "HDTC", "dvdscreen", "HDTS", "hdts"]
    return ", ".join([q for q in qualities if q.lower() in text.lower()])

async def get_pixels(caption):
    pixels = ["480p", "480p HEVC", "720p", "720p HEVC", "1080p", "1080p HEVC", "2160p", "2K", "4K"]
    return ", ".join([p for p in pixels if p.lower() in caption.lower()])
