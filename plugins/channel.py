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

# === আপনার পছন্দের মডার্ন টেমপ্লেট ===
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
    
    # ডাটাবেসে ফাইল সেভ করা
    success, silentxbotz = await save_file(media)
    
    try:  
        # পোস্ট পাঠানোর লজিক
        if success and silentxbotz == 1: 
            # get_status চেক যদি দরকার হয় তবে এখানে যোগ করতে পারেন, 
            # আপাতত ডাইরেক্ট আপডেট কল করছি যাতে পোস্ট মিস না হয়।
            await send_movie_update(bot, file_name=media.file_name, caption=media.caption)
    except Exception as e:
        LOGGER.error(f"Error In Media Handler: {e}")
        pass

async def send_movie_update(bot, file_name, caption):
    try:
        # === ১. নাম ক্লিনিং লজিক (যাতে সঠিক মুভি আসে) ===
        # ফাইলের নাম থেকে ডট, আন্ডারস্কোর সরিয়ে স্পেস দেওয়া
        clean_name = re.sub(r"[._-]", " ", file_name)
        # ব্র্যাকেটের ভেতরের লেখা রিমুভ করা
        clean_name = re.sub(r"\[.*?\]|\(.*?\)", "", clean_name)
        
        # সাল (Year) খোঁজা
        year_match = re.findall(r"\b(19|20)\d{2}\b", clean_name)
        year = None
        if year_match:
            year = year_match[-1] # শেষের সালটা নেওয়া (যেমন: Movie Name 2025 returns 2025)
        
        # সার্চ কুয়েরি তৈরি
        if year:
            # সাল পেলে, সালের আগের অংশটুকু নাম হিসেবে নেব
            search_query = clean_name.split(year)[0].strip()
        else:
            # সাল না পেলে ফালতু শব্দগুলো রিমুভ করব
            junk_words = [
                "1080p", "720p", "480p", "360p", "2160p", "4k", "5k", "8k", "hdr",
                "hdrip", "dvdrip", "web-dl", "webdl", "bluray", "remux", "h264",
                "x264", "h265", "x265", "hevc", "10bit", "dual audio", "multi audio",
                "hindi", "english", "bengali", "esub", "sub", "mkv", "mp4", "avi"
            ]
            temp_name = clean_name.lower()
            for junk in junk_words:
                temp_name = temp_name.replace(junk, "")
            search_query = temp_name.strip()

        # নাম খুব ছোট হয়ে গেলে অরিজিনাল নাম ব্যবহার করা
        if len(search_query) < 2:
            search_query = clean_name

        # ডুপ্লিকেট চেক
        if file_name in notified_movies:
            return 
            
        # === ২. TMDB ডাটা ফেচ (সঠিক নাম দিয়ে) ===
        tmdb_data = await fetch_tmdb_data(search_query, year)
        
        if not tmdb_data:
            return          
        
        notified_movies.add(file_name)
        
        # লিংকের জন্য স্লাগ তৈরি
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
    if yt_videos:
        key = yt_videos[0].get("key")
        url = yt_videos[0].get("url")
        final_url = url if url else f"https://www.youtube.com/watch?v={key}"
        return [InlineKeyboardButton("▶️ Watch Trailer", url=final_url)]
    return []
    
async def send_with_visual(bot, caption: str, tmdb_data: Dict, search_movie):
    try:
        # === ৩. পোস্টার লজিক (ভার্টিক্যাল/লম্বা ছবি) ===
        poster_path = tmdb_data.get("poster_path")
        backdrop_path = tmdb_data.get("backdrop_path")
        
        visual_url = None
        # আগে পোস্টার দেখবে
        if poster_path:
            visual_url = f"https://image.tmdb.org/t/p/original{poster_path}"
        # না পেলে ব্যাকড্রপ
        elif backdrop_path:
            visual_url = f"https://image.tmdb.org/t/p/original{backdrop_path}"
        # তাও না পেলে ডিফল্ট বা অন্য মেথড
        else:
             try:
                 visual_url = await get_best_visual(tmdb_data)
             except:
                 visual_url = DEFAULT_IMAGE_URL

        # ইউজারনেম সেফটি চেক
        try:
            bot_username = temp.U_NAME
        except:
            bot_username = bot.me.username

        get_file = f'https://telegram.me/{bot_username}?start=getfile-{search_movie}'
        
        buttons = [
            [InlineKeyboardButton("📱 Get File", url=get_file)]
        ]
        trailer_btn = get_trailer_button(tmdb_data)
        if trailer_btn:
            buttons.append(trailer_btn)
            
        keyboard = InlineKeyboardMarkup(buttons)
        
        if visual_url and visual_url != DEFAULT_IMAGE_URL:
            try:
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
            except Exception as e:
                LOGGER.error(f"Image Download Failed: {e}")

        # ডিফল্ট ইমেজ পাঠানো (যদি উপরেরটা ফেইল করে)
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
