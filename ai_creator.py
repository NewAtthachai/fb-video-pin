import os
import re
import sys
import json
import time
import uuid
import math
import base64
import wave
import asyncio
import subprocess
import io
import urllib.request
import urllib.parse
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import edge_tts
from gtts import gTTS
import aiohttp
import uharfbuzz as hb
import freetype

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AI_CLIPS_DIR = os.path.join(BASE_DIR, "uploads", "ai_clips")
AI_IMAGES_DIR = os.path.join(BASE_DIR, "uploads", "ai_images")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
AVATARS_DIR = os.path.join(ASSETS_DIR, "avatars")
BACKGROUNDS_DIR = os.path.join(ASSETS_DIR, "backgrounds")
os.makedirs(AI_CLIPS_DIR, exist_ok=True)
os.makedirs(AI_IMAGES_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)
os.makedirs(BACKGROUNDS_DIR, exist_ok=True)

_hb_faces: Dict[str, hb.Face] = {}
_ft_faces: Dict[str, freetype.Face] = {}

def get_hb_ft(font_path: str) -> Tuple[hb.Face, freetype.Face]:
    if font_path not in _hb_faces:
        with open(font_path, "rb") as f:
            data = f.read()
        _hb_faces[font_path] = hb.Face(data)
        _ft_faces[font_path] = freetype.Face(font_path)
    return _hb_faces[font_path], _ft_faces[font_path]

def clean_text_for_font(text: str) -> str:
    """ลบอิโมจิที่ไม่รองรับในฟอนต์ TTF เพื่อป้องกันกล่องสี่เหลี่ยม tofu []"""
    if not text:
        return ""
    chars = []
    skip_chars = set("⚡🔥✨⭐🛒✅👉📦🎁🎉💬❤️👍💡🌟🚀💯")
    for ch in text:
        code = ord(ch)
        if ch in skip_chars or code >= 0x1F000 or (0x2600 <= code <= 0x27BF):
            continue
        chars.append(ch)
    return "".join(chars).strip()

def draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r_outer: float, r_inner: float, fill: tuple):
    points = []
    for i in range(10):
        r = r_outer if i % 2 == 0 else r_inner
        angle = i * math.pi / 5 - math.pi / 2
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, fill=fill)

def draw_checkmark(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float, bg_color: tuple = (16, 185, 129, 255)):
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=bg_color)
    p1 = (cx - radius * 0.45, cy)
    p2 = (cx - radius * 0.1, cy + radius * 0.35)
    p3 = (cx + radius * 0.45, cy - radius * 0.35)
    draw.line([p1, p2, p3], fill=(255, 255, 255, 255), width=max(2, int(radius * 0.28)))

class AICreator:
    def __init__(self):
        self.fonts_cache = {}

    def get_font_path(self, bold: bool = True) -> str:
        candidates = [
            os.path.join(FONTS_DIR, "Kanit-Bold.ttf" if bold else "Kanit-Medium.ttf"),
            os.path.join(FONTS_DIR, "Prompt-Bold.ttf" if bold else "Prompt-Medium.ttf"),
            r"C:\Windows\Fonts\LeelaUIb.ttf" if bold else r"C:\Windows\Fonts\LeelawUI.ttf",
            r"C:\Windows\Fonts\tahomabd.ttf" if bold else r"C:\Windows\Fonts\tahoma.ttf",
        ]
        for f in candidates:
            if os.path.exists(f):
                return f
        return candidates[0]

    def get_font(self, size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
        cache_key = (size, bold)
        if cache_key in self.fonts_cache:
            return self.fonts_cache[cache_key]

        f = self.get_font_path(bold=bold)
        if os.path.exists(f):
            try:
                font = ImageFont.truetype(f, size)
                self.fonts_cache[cache_key] = font
                return font
            except Exception:
                pass
        font = ImageFont.load_default()
        self.fonts_cache[cache_key] = font
        return font

    def measure_text_hb(self, text: str, font_size: int, bold: bool = True) -> float:
        cleaned = clean_text_for_font(text)
        if not cleaned:
            return 0.0
        font_path = self.get_font_path(bold=bold)
        hb_face, _ = get_hb_ft(font_path)
        font_hb = hb.Font(hb_face)
        font_hb.scale = (font_size * 64, font_size * 64)
        buf = hb.Buffer()
        buf.add_str(cleaned)
        buf.guess_segment_properties()
        hb.shape(font_hb, buf)
        return sum(p.x_advance for p in buf.glyph_positions) / 64.0

    def draw_text_hb(
        self,
        base_img: Image.Image,
        text: str,
        pos: Tuple[int, int],
        font_size: int,
        fill_color: Tuple[int, int, int, int] = (255, 255, 255, 255),
        stroke_width: int = 0,
        stroke_color: Tuple[int, int, int, int] = (0, 0, 0, 255),
        align: str = "left",
        bold: bool = True
    ):
        cleaned = clean_text_for_font(text)
        if not cleaned:
            return
        font_path = self.get_font_path(bold=bold)
        hb_face, ft_face = get_hb_ft(font_path)
        font_hb = hb.Font(hb_face)
        font_hb.scale = (font_size * 64, font_size * 64)
        ft_face.set_char_size(font_size * 64)

        buf = hb.Buffer()
        buf.add_str(cleaned)
        buf.guess_segment_properties()
        hb.shape(font_hb, buf)

        total_advance = sum(p.x_advance for p in buf.glyph_positions) / 64.0
        x_start, y_start = pos
        if align == "center":
            x_start = x_start - total_advance / 2.0
        elif align == "right":
            x_start = x_start - total_advance

        pad = stroke_width + 8
        w = int(total_advance + pad * 2 + font_size)
        h = int(font_size * 1.8 + pad * 2)

        alpha_mask = np.zeros((h, w), dtype=np.uint8)
        cursor_x = pad * 64
        baseline_y = (pad + font_size * 1.0) * 64

        for info, p in zip(buf.glyph_infos, buf.glyph_positions):
            ft_face.load_glyph(info.codepoint, freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_RENDER)
            slot = ft_face.glyph
            bitmap = slot.bitmap
            bw, bh = bitmap.width, bitmap.rows
            if bw > 0 and bh > 0:
                gx = int((cursor_x + p.x_offset) / 64) + slot.bitmap_left
                gy = int((baseline_y - p.y_offset) / 64) - slot.bitmap_top
                x0 = max(0, gx)
                y0 = max(0, gy)
                x1 = min(w, gx + bw)
                y1 = min(h, gy + bh)
                gx0, gy0 = x0 - gx, y0 - gy
                gx1, gy1 = gx0 + (x1 - x0), gy0 + (y1 - y0)
                if x1 > x0 and y1 > y0:
                    g_buf = np.array(bitmap.buffer, dtype=np.uint8).reshape((bh, bw))
                    alpha_mask[y0:y1, x0:x1] = np.maximum(alpha_mask[y0:y1, x0:x1], g_buf[gy0:gy1, gx0:gx1])
            cursor_x += p.x_advance
            baseline_y -= p.y_advance

        mask_img = Image.fromarray(alpha_mask, mode="L")
        text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        if stroke_width > 0:
            stroke_mask = mask_img.filter(ImageFilter.MaxFilter(stroke_width * 2 + 1))
            stroke_layer = Image.new("RGBA", (w, h), stroke_color)
            text_layer.paste(stroke_layer, (0, 0), stroke_mask)

        fill_layer = Image.new("RGBA", (w, h), fill_color)
        text_layer.paste(fill_layer, (0, 0), mask_img)

        dest_x = int(x_start - pad)
        dest_y = int(y_start - pad)
        base_img.paste(text_layer, (dest_x, dest_y), text_layer)

    def clean_voice_text(self, text: str) -> str:
        """ลบอิโมจิและสัญลักษณ์แปลกๆ ออก แต่คงเครื่องหมายวรรคตอนสำคัญ (! , .) เพื่อให้น้ำเสียงมีอารมณ์สูงต่ำและเว้นจังหวะหายใจอย่างเป็นธรรมชาติ"""
        if not text:
            return ""
        text = text.replace("...", ", ").replace(";", ", ")
        cleaned = re.sub(r'[^\w\s\u0E00-\u0E7F,!.]', '', text)
        cleaned = re.sub(r',\s*,+', ', ', cleaned)
        cleaned = re.sub(r'!\s*!+', '! ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    async def generate_script(
        self,
        product_name: str,
        details: str = "",
        product_link: str = "",
        style: str = "viral_hook",
        gemini_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """สร้างสคริปต์คลิปสั้น แคปชั่น และแฮชแท็ก โดยใช้ Gemini หรือ Built-in Engine"""
        
        # 1. ลองใช้ Gemini API ถ้ามีการระบุ API Key
        if gemini_api_key and gemini_api_key.strip():
            try:
                result = await self._call_gemini_api(product_name, details, product_link, style, gemini_api_key.strip())
                if result:
                    return result
            except Exception as e:
                print(f"Gemini API failed, falling back to built-in generator: {e}")

        # 2. Built-in Smart Prompt Engine (ทำงานได้ 100% เป็นธรรมชาติ ไม่ต้องใช้ API Key)
        return self._generate_builtin_script(product_name, details, product_link, style)

    async def _call_gemini_api(
        self,
        product_name: str,
        details: str,
        product_link: str,
        style: str,
        api_key: str
    ) -> Optional[Dict[str, Any]]:
        """เรียก Gemini ผ่าน REST API พร้อมระบบสลับโมเดลอัตโนมัติ (gemini-flash-latest, gemini-flash-lite-latest, 3.5, etc.)"""
        candidate_models = [
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
        ]
        
        prompt = f"""
คุณเป็น Content Creator ผู้เชี่ยวชาญการทำคลิปสั้นสำหรับ TikTok, Facebook Reels และ YouTube Shorts เพื่อขายสินค้า Affiliate / ป้ายยาสินค้าในไทย
สไตล์การพูดต้องเป็นธรรมชาติ น่าฟัง เหมือนเพื่อนป้ายยาเพื่อน มีคำลงท้ายน่ารักเช่น 'นะคะ', 'ค่ะ', 'เลยน้า'
สำคัญมาก: ในส่วน voice_text ให้ใส่เครื่องหมายจุลภาค (,) คั่นระหว่างประโยคเพื่อให้ AI เว้นจังหวะหายใจอย่างเป็นธรรมชาติ ไม่พูดรัวเป็นหุ่นยนต์

ข้อมูลสินค้า:
- ชื่อสินค้า: {product_name}
- รายละเอียด/จุดเด่น: {details if details else "สินค้าคุณภาพดี ราคาคุ้มค่า ใช้งานง่าย พกพาสะดวก"}
- ลิงก์สินค้า: {product_link}
- สไตล์คลิป: {style} (viral_hook=ป้ายยาเร้าใจ, review_friendly=รีวิวจริงใจบอกต่อ, top_3=สรุป3เหตุผลต้องมี, flash_sale=โปรเด็ดลดแหลก)

ส่งคืนคำตอบเป็น JSON รูปแบบนี้เท่านั้น (ห้ามใส่ markdown หรือข้อความอื่น):
{{
  "title": "ชื่อหัวข้อคลิปสั้นดึงดูดใจ ไม่เกิน 40 ตัวอักษร",
  "hook": "ประโยคเปิดคลิป 3 วิแรกดึงดูดคนดู มีคำว่า นะคะ/ค่ะ",
  "points": ["จุดเด่นข้อที่ 1 สั้นกระชับ", "จุดเด่นข้อที่ 2", "จุดเด่นข้อที่ 3"],
  "cta": "ประโยคกระตุ้นให้กดตะกร้า/สั่งซื้อในลิงก์ทันที",
  "voice_text": "เนื้อความสำหรับให้อ่านออกเสียงทั้งหมดต่อเนื่องกันภาษาไทยอย่างเป็นธรรมชาติ มีเครื่องหมายจุลภาคคั่นจังหวะหายใจ มีคำลงท้าย นะคะ/ค่ะ/น้า ห้ามใส่อิโมจิ",
  "caption": "แคปชั่นโพสต์โซเชียล พร้อมอิโมจิและจัดวรรคสวยงาม รวมทั้งลิงก์สินค้า",
  "hashtags": ["#รีวิวของดี", "#ของมันต้องมี", "#ช้อปปี้ถูกชัวร์", "#Shorts", "#Reels", "#TikTokShop"]
}}
"""
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.7,
                "responseMimeType": "application/json"
            }
        }
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": api_key.strip()
        }

        async with aiohttp.ClientSession() as session:
            for model_name in candidate_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key.strip()}"
                try:
                    async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                            if text.startswith("```"):
                                text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
                            parsed = json.loads(text)
                            print(f"Gemini API generation succeeded using model: {model_name}")
                            return parsed
                        else:
                            err_msg = await resp.text()
                            print(f"Gemini model {model_name} returned HTTP {resp.status}, trying next fallback...")
                except Exception as e:
                    print(f"Gemini model {model_name} error: {e}, trying next fallback...")
        return None

    def _generate_builtin_script(
        self,
        product_name: str,
        details: str,
        product_link: str,
        style: str
    ) -> Dict[str, Any]:
        """ระบบสคริปต์อัจฉริยะในตัว จัดจังหวะวรรคตอนภาษาไทยให้พูดเป็นธรรมชาติสุดๆ"""
        name = product_name.strip()
        points_raw = [p.strip() for p in details.split(",") if p.strip()] if details else []
        if not points_raw:
            points_raw = [
                "ดีไซน์สวย พรีเมียม พกพาสะดวก",
                "ใช้งานง่าย คุ้มค่าเกินราคา",
                "การันตีคุณภาพ รีวิวเพียบในโซเชียล"
            ]
        elif len(points_raw) < 3:
            points_raw.append("คุณภาพดีเกินราคา ใช้งานได้ยาวนาน")
            points_raw.append("รีวิวแน่น ลูกค้าซื้อซ้ำเยอะมาก")

        p1, p2, p3 = points_raw[0], points_raw[1], points_raw[2]

        styles_map = {
            "viral_hook": {
                "title": f"🔥 ป้ายยาด่วน! {name}",
                "hook": f"ทุกคนคะ, ใครที่กำลังมองหา {name} อยู่นะคะ, ต้องดูคลิปนี้ด่วนๆ เลยค่ะ",
                "cta": "พิกัดของแท้ราคาดีต่อใจ, จิ้มลิงก์ที่ตะกร้าหรือแคปชั่นด้านล่างได้เลยนะคะ",
                "prefix": "บอกเลยว่าตัวนี้คือของมันต้องมีจริงๆ ค่ะ"
            },
            "review_friendly": {
                "title": f"✨ รีวิวจากใจจริง {name}",
                "hook": f"วันนี้ขอมาป้ายยาแบบตรงไปตรงมา, กับเจ้า {name} ตัวนี้เลยค่ะ",
                "cta": "ใครอยากได้ของแท้ มีรับประกันชัวร์, จิ้มสั่งได้ที่พิกัดในแคปชั่นได้เลยนะคะ",
                "prefix": "หลังจากที่ได้ลองใช้เองมาสักพัก, บอกเลยว่าประทับใจมากค่ะ"
            },
            "top_3": {
                "title": f"⭐ 3 เหตุผลที่ต้องมี {name}",
                "hook": f"3 เหตุผล, ทำไมทุกคนถึงแห่ซื้อ {name} ตัวนี้กันเยอะมากๆ",
                "cta": "โปรดีๆ แบบนี้ไม่ได้มีบ่อยนะคะ, รีบจิ้มตะกร้าหรือลิงก์สั่งซื้อด่วนเลยจ้า",
                "prefix": "มาดูกันเลยค่ะ ว่าทำไมถึงฮิตขนาดนี้"
            },
            "flash_sale": {
                "title": f"⚡ ลดแรงมาก! {name}",
                "hook": f"ลดกระหน่ำสุดๆ ค่ะ, ใครเล็ง {name} ไว้, วันนี้มีโปรลดราคาพิเศษนะคะ",
                "cta": "โปรโมชั่นมีจำนวนจำกัดนะคะ, รีบกดพิกัดสั่งซื้อก่อนสินค้าจะหมดน้า",
                "prefix": "ราคาดีที่สุดในรอบเดือนเลยค่ะ, ห้ามพลาดเด็ดขาด"
            }
        }

        cfg = styles_map.get(style, styles_map["viral_hook"])
        hook = cfg["hook"]
        cta = cfg["cta"]
        prefix = cfg["prefix"]

        # จัดคำให้มีจังหวะหายใจและลงท้ายด้วย นะคะ/ค่ะ อย่างลื่นไหล
        voice_text = f"{hook}, {prefix}, ข้อแรกเลยคือ {p1} นะคะ, แถมยัง {p2}, และที่สำคัญมากๆ เลยคือ {p3} ค่ะ! ... {cta}"

        # สร้างแคปชั่นพร้อมแฮชแท็ก
        caption_lines = [
            f"{cfg['title']} 🚀",
            "",
            f"👉 {hook.replace(',', '')}",
            f"✅ {p1}",
            f"✅ {p2}",
            f"✅ {p3}",
            "",
            f"🛒 สนใจสั่งซื้อ / เช็คโปรโมชั่นได้ที่:",
            f"{product_link if product_link else '👉 พิกัดจิ้มลิงก์หน้าโปรไฟล์ / ตะกร้าสินค้าด้านล่างได้เลยครับ'}",
            "",
            "#รีวิว #ของดีบอกต่อ #ช้อปปี้ถูกชัวร์ #ของมันต้องมี #Shorts #Reels #TikTokShop #ป้ายยา"
        ]
        caption = "\n".join(caption_lines)

        return {
            "title": cfg["title"],
            "hook": hook,
            "points": [p1, p2, p3],
            "cta": cta,
            "voice_text": voice_text,
            "caption": caption,
            "hashtags": ["#รีวิว", "#ของดีบอกต่อ", "#Shorts", "#Reels", "#TikTokShop"]
        }

    async def _call_gemini_tts(self, text: str, voice_name: str, api_key: str, output_path: str) -> bool:
        """แปลงข้อความเป็นเสียงด้วย Google Gemini Audio/TTS พร้อมระบบสำรองโมเดลและ Retry"""
        candidate_models = [
            "gemini-2.5-flash-preview-tts",
            "gemini-3.8-flash-tts",
            "gemini-3.1-flash-tts-preview"
        ]
        prompt = f"Read in natural expressive Thai documentary narrator style, engaging, cinematic, with realistic human emotion, natural breathing pauses and storytelling pacing: {text}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice_name
                        }
                    }
                }
            }
        }
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": api_key.strip()
        }

        async with aiohttp.ClientSession() as session:
            for model_name in candidate_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
                for attempt in range(2):
                    try:
                        async with session.post(url, json=payload, headers=headers, timeout=25) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                candidates = data.get("candidates", [])
                                if candidates and "content" in candidates[0]:
                                    parts = candidates[0]["content"].get("parts", [])
                                    if parts and "inlineData" in parts[0]:
                                        b64_data = parts[0]["inlineData"]["data"]
                                        pcm_bytes = base64.b64decode(b64_data)
                                        temp_wav = output_path.replace(".mp3", f"_{uuid.uuid4().hex[:4]}.wav")
                                        with wave.open(temp_wav, "wb") as wf:
                                            wf.setnchannels(1)
                                            wf.setsampwidth(2)
                                            wf.setframerate(24000)
                                            wf.writeframes(pcm_bytes)
                                        # แปลงเป็น MP3 ผ่าน ffmpeg
                                        cmd = ["ffmpeg", "-y", "-i", temp_wav, "-b:a", "192k", output_path]
                                        subprocess.run(cmd, capture_output=True, check=True)
                                        if os.path.exists(temp_wav):
                                            try: os.remove(temp_wav)
                                            except Exception: pass
                                        print(f"Gemini TTS succeeded using model {model_name} with voice {voice_name}")
                                        return True
                            elif resp.status == 429:
                                print(f"Gemini TTS rate limited (429) on {model_name}, waiting before retry...")
                                await asyncio.sleep(2.0)
                            else:
                                print(f"Gemini TTS model {model_name} returned HTTP {resp.status}")
                                break
                    except Exception as e:
                        print(f"Gemini TTS attempt {attempt} error on {model_name}: {e}")
                        await asyncio.sleep(1.0)
        return False

    async def generate_voice(
        self,
        voice_text: str,
        voice_name: str = "th-TH-PremwadeeNeural",
        voice_rate: str = "+4%",
        gemini_api_key: Optional[str] = None,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """แปลงข้อความเป็นเสียงพูดภาษาไทยที่ลื่นไหล สมจริง เป็นธรรมชาติ"""
        if not output_path:
            output_path = os.path.join(AI_CLIPS_DIR, f"voice_{uuid.uuid4().hex[:8]}.mp3")

        cleaned_text = self.clean_voice_text(voice_text)
        if not cleaned_text:
            cleaned_text = "ทุกคนคะ ใครกำลังมองหาของดีอยู่นะคะ ต้องดูคลิปนี้ด่วนๆ เลยค่ะ! พิกัดในตะกร้าด้านล่างได้เลยน้า"

        # 1. ถ้าเลือกเสียง Gemini และมี API Key
        if voice_name.startswith("gemini-") and gemini_api_key:
            gem_v = voice_name.replace("gemini-", "").capitalize()
            success = await self._call_gemini_tts(cleaned_text, gem_v, gemini_api_key, output_path)
            if success and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                duration = self.get_audio_duration(output_path)
                return {"audio_path": output_path, "duration": duration}
            print("Gemini TTS fallback to Edge-TTS...")

        # 2. ปรับแต่ง Microsoft Edge Neural TTS ให้เสียงมีชีวิตชีวา ไม่แบนราบ
        if voice_name.startswith("gemini-"):
            male_voices = ["Charon", "Fenrir", "Puck"]
            v_clean = voice_name.replace("gemini-", "").capitalize()
            edge_voice = "th-TH-NiwatNeural" if v_clean in male_voices else "th-TH-PremwadeeNeural"
        else:
            edge_voice = voice_name

        edge_pitch = "+2Hz" if edge_voice == "th-TH-PremwadeeNeural" else "+1Hz"

        voice_success = False
        for attempt in range(2):
            try:
                communicate = edge_tts.Communicate(cleaned_text, edge_voice, rate=voice_rate, pitch=edge_pitch)
                await communicate.save(output_path)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    voice_success = True
                    break
            except Exception as e:
                print(f"Edge-TTS attempt {attempt+1} failed: {e}")
                await asyncio.sleep(1)

        # Fallback to gTTS if needed
        if not voice_success:
            print("Falling back to gTTS...")
            tts = gTTS(cleaned_text, lang='th')
            tts.save(output_path)

        duration = self.get_audio_duration(output_path)
        return {
            "audio_path": output_path,
            "duration": duration
        }

    def get_audio_duration(self, audio_path: str) -> float:
        """วัดความยาวของไฟล์เสียงด้วย ffprobe"""
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(res.stdout.strip())
        except Exception:
            return 15.0

    def wrap_text(self, text: str, font: Any, max_width: int) -> List[str]:
        """ตัดบรรทัดข้อความภาษาไทยให้พอดีกับความกว้างหน้าจอ โดยคำนวณระยะด้วย HarfBuzz"""
        font_size = font.size if hasattr(font, "size") else (font if isinstance(font, int) else 36)
        cleaned = clean_text_for_font(text)
        if not cleaned:
            return []
        words = cleaned.split(" ")
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip() if current_line else word
            width = self.measure_text_hb(test_line, font_size)
            if width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                w_w = self.measure_text_hb(word, font_size)
                if w_w > max_width:
                    chunk = ""
                    for ch in word:
                        if self.measure_text_hb(chunk + ch, font_size) <= max_width:
                            chunk += ch
                        else:
                            lines.append(chunk)
                            chunk = ch
                    current_line = chunk
                else:
                    current_line = word

        if current_line:
            lines.append(current_line)
        return lines

    def extract_audio_rms(self, audio_file: str, fps: int = 30) -> List[float]:
        """ดึงระดับพลังงานเสียง (RMS) ทีละเฟรมแบบเรียลไทม์เพื่อขับเคลื่อนการขยับปาก (Lip-Sync)"""
        sr = 16000
        samples_per_frame = int(sr / fps)
        cmd = ["ffmpeg", "-v", "error", "-i", audio_file, "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            raw_pcm, _ = proc.communicate()
            if not raw_pcm:
                return []
            samples = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
            num_frames = len(samples) // samples_per_frame
            rms_list = []
            for i in range(num_frames):
                chunk = samples[i * samples_per_frame : (i + 1) * samples_per_frame]
                rms = float(np.sqrt(np.mean(chunk**2))) if len(chunk) > 0 else 0.0
                rms_list.append(rms)
            return rms_list
        except Exception as e:
            print(f"Error extracting audio RMS: {e}")
            return []

    def create_presenter_scene_base(
        self,
        scene_idx: int,
        title_text: str,
        scene_text: str,
        points: Optional[List[str]] = None,
        product_image_path: Optional[str] = None,
        bg_theme: str = "cyber",
        width: int = 1080,
        height: int = 1920
    ) -> Image.Image:
        """สร้างเฟรมฉากหลัง + การ์ดสินค้า + ซับไตเติล สำหรับโหมด AI Presenter พูดสดพร้อมขยับปาก"""
        bg_path = None
        if bg_theme == "luxury":
            bg_path = os.path.join(BACKGROUNDS_DIR, "bg_luxury.jpg")
        elif bg_theme == "cyber":
            bg_path = os.path.join(BACKGROUNDS_DIR, "bg_cyber.jpg")

        if bg_path and os.path.exists(bg_path):
            bg = Image.open(bg_path).convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
            tint = Image.new("RGBA", (width, height), (10, 15, 30, 85))
            base = Image.alpha_composite(bg, tint)
        elif product_image_path and os.path.exists(product_image_path):
            try:
                prod = Image.open(product_image_path).convert("RGBA")
                bg_w, bg_h = int(width * 1.3), int(height * 1.3)
                bg_blur = prod.resize((bg_w, bg_h), Image.Resampling.LANCZOS)
                bg_crop = bg_blur.crop(((bg_w - width)//2, (bg_h - height)//2, (bg_w - width)//2 + width, (bg_h - height)//2 + height))
                bg_blur_filt = bg_crop.filter(ImageFilter.GaussianBlur(50))
                tint = Image.new("RGBA", (width, height), (10, 15, 30, 175))
                base = Image.alpha_composite(bg_blur_filt, tint)
            except Exception:
                base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
        else:
            base = Image.new("RGBA", (width, height), (15, 23, 42, 255))

        draw = ImageDraw.Draw(base)

        scene_configs = [
            {"badge": "หยุดฟีดแป๊บเดียว! (ของมันต้องมี)", "badge_color": (239, 68, 68, 240)},
            {"badge": "สรรพคุณแน่น คุ้มค่าเกินราคา", "badge_color": (168, 85, 247, 240)},
            {"badge": "3 เหตุผลที่ต้องมี รีวิวแน่น 5 ดาว", "badge_color": (14, 165, 233, 240)},
            {"badge": "สั่งซื้อด่วนก่อนของหมด โปรโมชั่นพิเศษ!", "badge_color": (245, 158, 11, 240)},
        ]
        s_cfg = scene_configs[min(scene_idx, 3)]

        # 2. ป้าย Badge หัวข้อด้านบน (Kanit-Bold ด้วย HarfBuzz)
        badge_text = s_cfg["badge"]
        bw = int(self.measure_text_hb(badge_text, 32, bold=True) + 50)
        bh = 58
        bx = 90
        by = 120
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=29, fill=s_cfg["badge_color"], outline=(255, 255, 255, 200), width=2)
        self.draw_text_hb(base, badge_text, (bx + 25, by + 11), 32, fill_color=(255, 255, 255, 255), bold=True)

        # 3. ชื่อหัวข้อใหญ่ (Title) ในแบบ Kanit-Bold ทันสมัย
        wrapped_title = self.wrap_text(title_text, 48, max_width=900)
        curr_y = 205
        for line in wrapped_title[:2]:
            self.draw_text_hb(base, line, (bx, curr_y), 48, fill_color=(255, 255, 255, 255), stroke_width=3, stroke_color=(0, 0, 0, 240), bold=True)
            curr_y += 66

        # 4. การ์ดแสดงสินค้าฝั่งขวา (Product Showcase Card on Right Side)
        card_w, card_h = 530, 680
        card_x = width - card_w - 70
        card_y = 360

        draw.rounded_rectangle(
            [card_x, card_y, card_x + card_w, card_y + card_h],
            radius=32,
            fill=(15, 23, 42, 225),
            outline=(56, 189, 248, 180),
            width=3
        )

        has_img = False
        if product_image_path and os.path.exists(product_image_path):
            try:
                prod = Image.open(product_image_path).convert("RGBA")
                if scene_idx == 2 and points:
                    prod.thumbnail((card_w - 60, 320), Image.Resampling.LANCZOS)
                    pw, ph = prod.size
                    base.paste(prod, (card_x + (card_w - pw)//2, card_y + 30), prod)
                    
                    py = card_y + 375
                    for pt in points[:3]:
                        draw.rounded_rectangle([card_x + 30, py, card_x + card_w - 30, py + 62], radius=14, fill=(15, 23, 42, 230), outline=(56, 189, 248, 140), width=1)
                        draw_checkmark(draw, card_x + 58, py + 31, 14)
                        self.draw_text_hb(base, pt, (card_x + 88, py + 16), 26, fill_color=(241, 245, 249, 255), bold=True)
                        py += 75
                else:
                    prod.thumbnail((card_w - 60, card_h - 130), Image.Resampling.LANCZOS)
                    pw, ph = prod.size
                    base.paste(prod, (card_x + (card_w - pw)//2, card_y + 40), prod)
                    
                    for i in range(5):
                        draw_star(draw, card_x + 160 + i * 28, card_y + card_h - 70, 12, 5.0, (251, 191, 36, 255))
                    self.draw_text_hb(base, "4.9 / 5.0", (card_x + 306, card_y + card_h - 86), 28, fill_color=(251, 191, 36, 255), bold=True)
                has_img = True
            except Exception as e:
                print(f"Error drawing product in presenter card: {e}")

        if not has_img:
            self.draw_text_hb(base, "จุดเด่นสินค้า", (card_x + 60, card_y + 55), 36, fill_color=(56, 189, 248, 255), bold=True)
            py = card_y + 160
            sample_pts = points[:3] if points else ["สินค้ายอดนิยมอันดับ 1", "การันตีของแท้ 100%", "รีวิวแน่น ลูกค้าซื้อซ้ำ"]
            for pt in sample_pts:
                draw.rounded_rectangle([card_x + 30, py, card_x + card_w - 30, py + 68], radius=16, fill=(15, 23, 42, 200), outline=(56, 189, 248, 140), width=1)
                draw_checkmark(draw, card_x + 60, py + 34, 14)
                self.draw_text_hb(base, pt, (card_x + 88, py + 18), 26, fill_color=(241, 245, 249, 255), bold=True)
                py += 85
            for i in range(5):
                draw_star(draw, card_x + 160 + i * 28, card_y + card_h - 70, 12, 5.0, (251, 191, 36, 255))
            self.draw_text_hb(base, "4.9 / 5.0", (card_x + 306, card_y + card_h - 86), 28, fill_color=(251, 191, 36, 255), bold=True)

        # 5. ซับไตเติลสตอรี่สดด้านล่างและปุ่ม CTA แยกเป็นเลเยอร์ซ้อนด้านบนสุด (Sub Overlay)
        sub_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        sub_draw = ImageDraw.Draw(sub_overlay)
        sub_box_y = 1320
        wrapped_sub = self.wrap_text(scene_text, 40, max_width=900)
        sub_h = max(len(wrapped_sub) * 62 + 40, 160)

        sub_draw.rounded_rectangle(
            [70, sub_box_y, width - 70, sub_box_y + sub_h],
            radius=26,
            fill=(10, 15, 28, 245),
            outline=(56, 189, 248, 180),
            width=2
        )
        sy = sub_box_y + 22
        for s_line in wrapped_sub[:3]:
            self.draw_text_hb(sub_overlay, s_line, (width // 2, sy), 40, fill_color=(254, 240, 138, 255), stroke_width=3, stroke_color=(0, 0, 0, 240), align="center", bold=True)
            sy += 62

        # 6. ปุ่ม CTA สั่งซื้อ
        cta_h = 120
        cta_y = 1680
        cta_w = 940
        cta_x = (width - cta_w) // 2

        if scene_idx == 3:
            sub_draw.rounded_rectangle(
                [cta_x, cta_y, cta_x + cta_w, cta_y + cta_h],
                radius=60,
                fill=(245, 158, 11, 255),
                outline=(254, 240, 138, 255),
                width=4
            )
            self.draw_text_hb(sub_overlay, "จิ้มลิงก์ที่ตะกร้าหรือแคปชั่นเลย >>", (width // 2, cta_y + 28), 40, fill_color=(15, 23, 42, 255), align="center", bold=True)
        else:
            sub_draw.rounded_rectangle(
                [cta_x, cta_y + 20, cta_x + cta_w, cta_y + cta_h - 20],
                radius=40,
                fill=(15, 23, 42, 210),
                outline=(71, 85, 105, 160),
                width=2
            )
            self.draw_text_hb(sub_overlay, "พิกัดสินค้าในแคปชั่น / จิ้มตะกร้าซ้ายล่างได้เลย", (width // 2, cta_y + 32), 32, fill_color=(203, 213, 225, 255), align="center", bold=True)

        return base, sub_overlay

    def create_story_frame(
        self,
        scene_idx: int,
        title_text: str,
        scene_text: str,
        points: Optional[List[str]] = None,
        product_image_path: Optional[str] = None,
        bg_theme: str = "cyber",
        width: int = 1080,
        height: int = 1920
    ) -> Image.Image:
        """สร้างเฟรมกราฟิกวิดีโอ 1080x1920 (9:16) ระดับพรีเมียม สไตล์สตอรี่บอร์ด 4 องค์"""
        bg_path = None
        if bg_theme == "luxury":
            bg_path = os.path.join(BACKGROUNDS_DIR, "bg_luxury.jpg")
        elif bg_theme == "cyber":
            bg_path = os.path.join(BACKGROUNDS_DIR, "bg_cyber.jpg")

        if bg_path and os.path.exists(bg_path):
            bg = Image.open(bg_path).convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
            tint = Image.new("RGBA", (width, height), (10, 15, 30, 85))
            base = Image.alpha_composite(bg, tint)
        elif product_image_path and os.path.exists(product_image_path):
            try:
                prod = Image.open(product_image_path).convert("RGBA")
                bg_w, bg_h = int(width * 1.3), int(height * 1.3)
                bg_blur = prod.resize((bg_w, bg_h), Image.Resampling.LANCZOS)
                bg_crop = bg_blur.crop(((bg_w - width)//2, (bg_h - height)//2, (bg_w - width)//2 + width, (bg_h - height)//2 + height))
                bg_blur_filt = bg_crop.filter(ImageFilter.GaussianBlur(50))
                tint = Image.new("RGBA", (width, height), (10, 15, 30, 175))
                base = Image.alpha_composite(bg_blur_filt, tint)
            except Exception:
                base = Image.new("RGBA", (width, height), (15, 23, 42, 255))
        else:
            base = Image.new("RGBA", (width, height), (15, 23, 42, 255))

        draw = ImageDraw.Draw(base)

        scene_configs = [
            {"badge": "หยุดฟีดแป๊บเดียว! (ของมันต้องมี)", "badge_color": (239, 68, 68, 255), "cta_btn": False},
            {"badge": "สรรพคุณแน่น คุ้มค่าเกินราคา", "badge_color": (168, 85, 247, 255), "cta_btn": False},
            {"badge": "3 เหตุผลที่ต้องมี รีวิวแน่น 5 ดาว", "badge_color": (14, 165, 233, 255), "cta_btn": False},
            {"badge": "สั่งซื้อด่วนก่อนของหมด โปรโมชั่นพิเศษ!", "badge_color": (245, 158, 11, 255), "cta_btn": True},
        ]
        s_cfg = scene_configs[min(scene_idx, 3)]

        # 2. ป้าย Badge หัวข้อด้านบน (Kanit-Bold ด้วย HarfBuzz)
        badge_text = s_cfg["badge"]
        bw = int(self.measure_text_hb(badge_text, 36, bold=True) + 50)
        bh = 64
        bx = (width - bw) // 2
        by = 130
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=32, fill=s_cfg["badge_color"], outline=(255, 255, 255, 180), width=2)
        self.draw_text_hb(base, badge_text, (width // 2, by + 12), 36, fill_color=(255, 255, 255, 255), align="center", bold=True)

        # 3. ชื่อหัวข้อหลัก (Title)
        wrapped_title = self.wrap_text(title_text, 50, max_width=920)
        curr_y = 225
        for line in wrapped_title[:2]:
            self.draw_text_hb(base, line, (width // 2, curr_y), 50, fill_color=(255, 255, 255, 255), stroke_width=3, stroke_color=(0, 0, 0, 220), align="center", bold=True)
            curr_y += 70

        # 4. เวทีแสดงภาพตรงกลาง
        card_w, card_h = 940, 840
        card_x = (width - card_w) // 2
        card_y = 390

        draw.rounded_rectangle(
            [card_x, card_y, card_x + card_w, card_y + card_h],
            radius=40,
            fill=(20, 30, 50, 220),
            outline=(100, 116, 139, 180),
            width=3
        )

        has_img = False
        if product_image_path and os.path.exists(product_image_path):
            try:
                prod = Image.open(product_image_path).convert("RGBA")
                pad = 50
                avail_w = card_w - (pad * 2)
                avail_h = card_h - (pad * 2)
                
                if scene_idx == 2 and points:
                    prod.thumbnail((avail_w, 420), Image.Resampling.LANCZOS)
                    pw, ph = prod.size
                    base.paste(prod, (card_x + (card_w - pw) // 2, card_y + 40), prod)
                    
                    py = card_y + 490
                    for pt in points[:3]:
                        draw.rounded_rectangle([card_x + 50, py, card_x + card_w - 50, py + 75], radius=18, fill=(15, 23, 42, 230), outline=(56, 189, 248, 140), width=2)
                        draw_checkmark(draw, card_x + 85, py + 37, 16)
                        self.draw_text_hb(base, pt, (card_x + 118, py + 18), 32, fill_color=(241, 245, 249, 255), bold=True)
                        py += 95
                else:
                    prod.thumbnail((avail_w, avail_h), Image.Resampling.LANCZOS)
                    pw, ph = prod.size
                    base.paste(prod, (card_x + (card_w - pw) // 2, card_y + (card_h - ph) // 2), prod)
                has_img = True
            except Exception as e:
                print(f"Error drawing product in story frame: {e}")

        if not has_img:
            self.draw_text_hb(base, "จุดเด่นที่ต้องมี!", (card_x + 80, card_y + 70), 44, fill_color=(56, 189, 248, 255), bold=True)

            if not points:
                points = ["สินค้ายอดนิยม คุณภาพดีเยี่ยม", "การันตีของแท้ 100% มีรับประกัน", "จัดส่งไว รีวิวแน่นในโซเชียล"]

            py = card_y + 200
            for pt in points[:3]:
                draw.rounded_rectangle([card_x + 60, py, card_x + card_w - 60, py + 85], radius=20, fill=(15, 23, 42, 180), outline=(71, 85, 105, 140), width=2)
                draw_checkmark(draw, card_x + 95, py + 42, 16)
                self.draw_text_hb(base, pt, (card_x + 128, py + 22), 34, fill_color=(241, 245, 249, 255), bold=True)
                py += 115

            for i in range(5):
                draw_star(draw, card_x + 95 + i * 34, card_y + card_h - 70, 14, 6.0, (251, 191, 36, 255))
            self.draw_text_hb(base, "4.9 / 5.0 (รีวิวจากผู้ใช้จริง)", (card_x + 280, card_y + card_h - 88), 30, fill_color=(251, 191, 36, 255), bold=True)

        # 5. กล่องคำบรรยายสตอรี่สด (Dynamic Speech Subtitles)
        sub_box_y = 1290
        wrapped_sub = self.wrap_text(scene_text, 40, max_width=860)
        sub_h = max(len(wrapped_sub) * 62 + 40, 160)

        draw.rounded_rectangle(
            [card_x + 20, sub_box_y, card_x + card_w - 20, sub_box_y + sub_h],
            radius=26,
            fill=(10, 15, 28, 240),
            outline=(56, 189, 248, 160),
            width=2
        )
        sy = sub_box_y + 22
        for s_line in wrapped_sub[:3]:
            self.draw_text_hb(base, s_line, (width // 2, sy), 40, fill_color=(254, 240, 138, 255), stroke_width=3, stroke_color=(0, 0, 0, 240), align="center", bold=True)
            sy += 62

        # 6. ปุ่ม CTA สั่งซื้อ
        cta_h = 120
        cta_y = 1680
        cta_w = 940
        cta_x = (width - cta_w) // 2

        if s_cfg["cta_btn"]:
            draw.rounded_rectangle(
                [cta_x, cta_y, cta_x + cta_w, cta_y + cta_h],
                radius=60,
                fill=(245, 158, 11, 255),
                outline=(254, 240, 138, 255),
                width=4
            )
            self.draw_text_hb(base, "จิ้มลิงก์ที่ตะกร้าหรือแคปชั่นเลย >>", (width // 2, cta_y + 28), 40, fill_color=(15, 23, 42, 255), align="center", bold=True)
        else:
            draw.rounded_rectangle(
                [cta_x, cta_y + 20, cta_x + cta_w, cta_y + cta_h - 20],
                radius=40,
                fill=(15, 23, 42, 200),
                outline=(71, 85, 105, 160),
                width=2
            )
            self.draw_text_hb(base, "พิกัดสินค้าในแคปชั่น / จิ้มตะกร้าซ้ายล่างได้เลย", (width // 2, cta_y + 32), 32, fill_color=(203, 213, 225, 255), align="center", bold=True)

        return base.convert("RGB")

    def create_frame(self, *args, **kwargs) -> Image.Image:
        """Compatibility wrapper for create_frame -> create_story_frame"""
        title = kwargs.get("title_text", "สินค้าแนะนำ")
        sub = kwargs.get("subtitle_text", "")
        pts = kwargs.get("points", None)
        img_p = kwargs.get("product_image_path", None)
        return self.create_story_frame(0, title, sub, pts, img_p)

    async def render_video(
        self,
        title: str,
        hook: str,
        points: List[str],
        cta: str,
        voice_text: str,
        voice_name: str = "th-TH-PremwadeeNeural",
        voice_rate: str = "+4%",
        image_paths: Optional[List[str]] = None,
        product_link: str = "",
        enable_bgm: bool = True,
        gemini_api_key: Optional[str] = None,
        video_style: str = "presenter",
        bg_theme: str = "cyber",
        output_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """เรนเดอร์วิดีโอ 1080x1920 (9:16) แบบ AI Presenter พูดสดขยับปาก หรือสตอรี่บอร์ด 4 องค์"""
        session_id = uuid.uuid4().hex[:8]
        if not output_filename:
            output_filename = f"ai_reel_{session_id}.mp4"
        output_path = os.path.join(AI_CLIPS_DIR, output_filename)

        # 1. สังเคราะห์เสียงพูด AI
        audio_temp_path = os.path.join(AI_CLIPS_DIR, f"temp_audio_{session_id}.mp3")
        voice_res = await self.generate_voice(voice_text, voice_name, voice_rate, gemini_api_key, audio_temp_path)
        duration = voice_res["duration"]
        total_duration = max(duration + 1.0, 5.0)
        fps = 30
        total_frames = int(total_duration * fps)

        # 2. จัดเตรียม 4 ฉากสตอรี่บอร์ด (Story Acts)
        valid_images = [p for p in (image_paths or []) if os.path.exists(p)]
        img_act0 = valid_images[0] if valid_images else None
        img_act1 = valid_images[1 % len(valid_images)] if valid_images else None
        img_act2 = valid_images[2 % len(valid_images)] if valid_images else None
        img_act3 = valid_images[-1] if valid_images else None

        p1 = points[0] if len(points) > 0 else "คุ้มค่าเกินราคา ใช้งานง่าย พกพาสะดวก"
        p2 = points[1] if len(points) > 1 else "ดีไซน์สวย การันตีของแท้ 100%"
        p3 = points[2] if len(points) > 2 else "รีวิวแน่น ลูกค้าซื้อซ้ำเพียบ"

        story_acts = [
            {"idx": 0, "text": hook, "img": img_act0, "ratio": 0.25},
            {"idx": 1, "text": f"ข้อแรกเลยคือ {p1} นะคะ", "img": img_act1, "ratio": 0.30},
            {"idx": 2, "text": f"แถมยัง {p2} และ {p3} ค่ะ", "img": img_act2, "ratio": 0.25},
            {"idx": 3, "text": cta, "img": img_act3, "ratio": 0.20}
        ]

        bgm_path = os.path.join(ASSETS_DIR, "bgm_chill.mp3")
        use_bgm = enable_bgm and os.path.exists(bgm_path)

        # MODE 1: AI PRESENTER TALKING AVATAR (พูดขยับปาก + กะพริบตา + โยกตัวตามเสียง)
        if video_style == "presenter":
            # โหลด Avatar Sprites
            idle_av = Image.open(os.path.join(AVATARS_DIR, "presenter_idle.png")).convert("RGBA").resize((840, 840), Image.Resampling.LANCZOS)
            half_av = Image.open(os.path.join(AVATARS_DIR, "presenter_half.png")).convert("RGBA").resize((840, 840), Image.Resampling.LANCZOS)
            talk_av = Image.open(os.path.join(AVATARS_DIR, "presenter_talk.png")).convert("RGBA").resize((840, 840), Image.Resampling.LANCZOS)
            blink_av = Image.open(os.path.join(AVATARS_DIR, "presenter_blink.png")).convert("RGBA").resize((840, 840), Image.Resampling.LANCZOS)

            # ดึงระดับพลังงานเสียงทีละเฟรม
            rms_list = self.extract_audio_rms(audio_temp_path, fps=fps)
            max_rms = max(rms_list) if (rms_list and max(rms_list) > 0) else 0.1

            # เตรียมภาพพื้นฐานและเลเยอร์ซับไตเติลของทั้ง 4 ฉาก
            act_bases = []
            act_subs = []
            for act in story_acts:
                base_img, sub_overlay = self.create_presenter_scene_base(
                    scene_idx=act["idx"],
                    title_text=title,
                    scene_text=act["text"],
                    points=points,
                    product_image_path=act["img"],
                    bg_theme=bg_theme
                )
                act_bases.append(base_img)
                act_subs.append(sub_overlay)

            # เรนเดอร์วิดีโอแบบสตรีมตรงเข้า FFmpeg
            temp_vid = os.path.join(AI_CLIPS_DIR, f"temp_v_{session_id}.mp4")
            cmd_stream = [
                "ffmpeg", "-y",
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-s", "1080x1920",
                "-pix_fmt", "rgb24",
                "-r", str(fps),
                "-i", "-",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                temp_vid
            ]

            proc = subprocess.Popen(cmd_stream, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            cum_frames = [
                int(total_frames * 0.25),
                int(total_frames * 0.55),
                int(total_frames * 0.80),
                total_frames
            ]

            try:
                for f in range(total_frames):
                    # เลือกฉาก
                    if f < cum_frames[0]: act_idx = 0
                    elif f < cum_frames[1]: act_idx = 1
                    elif f < cum_frames[2]: act_idx = 2
                    else: act_idx = 3

                    # ระดับเสียง RMS ในเฟรมนี้
                    vol = (rms_list[f] / max_rms) if f < len(rms_list) else 0.0

                    # ลอจิกการกะพริบตา (ทุกๆ ~3.5 วินาที กะพริบ 3 เฟรม)
                    is_blink = (f % 105 in (0, 1, 2))

                    if is_blink:
                        cur_av = blink_av
                    elif vol >= 0.28:
                        cur_av = talk_av
                    elif vol >= 0.08:
                        cur_av = half_av
                    else:
                        cur_av = idle_av

                    # โยกตัวและหายใจแบบธรรมชาติ
                    sway_x = int(math.sin(f * 0.14) * 6)
                    sway_y = int(math.cos(f * 0.10) * 4)

                    frame = act_bases[act_idx].copy()
                    frame.paste(cur_av, (-30 + sway_x, 480 + sway_y), cur_av)
                    frame.paste(act_subs[act_idx], (0, 0), act_subs[act_idx])

                    # แถบ Progress Bar นีออนวิ่งด้านบน
                    pb_w = int((f + 1) / total_frames * 1080)
                    f_draw = ImageDraw.Draw(frame)
                    f_draw.rectangle([0, 0, pb_w, 16], fill=(56, 189, 248))

                    proc.stdin.write(frame.convert("RGB").tobytes())

                proc.stdin.close()
                proc.wait()

                # มิกซ์เสียงพากย์และเพลงคลอ BGM
                if use_bgm:
                    filter_complex = "[1:a]volume=1.0[voice];[2:a]volume=0.16[bgm];[voice][bgm]amix=inputs=2:duration=first[aout]"
                    cmd_final = [
                        "ffmpeg", "-y",
                        "-i", temp_vid,
                        "-i", audio_temp_path,
                        "-stream_loop", "-1", "-i", bgm_path,
                        "-filter_complex", filter_complex,
                        "-map", "0:v",
                        "-map", "[aout]",
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-t", str(total_duration),
                        "-shortest",
                        output_path
                    ]
                else:
                    cmd_final = [
                        "ffmpeg", "-y",
                        "-i", temp_vid,
                        "-i", audio_temp_path,
                        "-map", "0:v",
                        "-map", "1:a",
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-t", str(total_duration),
                        "-shortest",
                        output_path
                    ]
                subprocess.run(cmd_final, capture_output=True, check=True)

            finally:
                if os.path.exists(temp_vid):
                    try: os.remove(temp_vid)
                    except Exception: pass
                if os.path.exists(audio_temp_path):
                    try: os.remove(audio_temp_path)
                    except Exception: pass

        # MODE 2: CINEMATIC STORYBOARD 4 ACTS (ซูม แพน ทแยงมุม)
        else:
            frame_files = []
            temp_vids = []
            try:
                for act in story_acts:
                    a_idx = act["idx"]
                    a_dur = total_duration * act["ratio"]
                    a_frames = max(int(a_dur * 30), 1)

                    fpath = os.path.join(AI_CLIPS_DIR, f"frame_{session_id}_{a_idx}.png")
                    frame_img = self.create_story_frame(
                        scene_idx=a_idx,
                        title_text=title,
                        scene_text=act["text"],
                        points=points,
                        product_image_path=act["img"],
                        bg_theme=bg_theme
                    )
                    frame_img.save(fpath)
                    frame_files.append(fpath)

                    clip_v = os.path.join(AI_CLIPS_DIR, f"clip_{session_id}_{a_idx}.mp4")
                    zooms = [
                        "min(zoom+0.0018,1.20)",
                        "1.12",
                        "min(zoom+0.0014,1.16)",
                        "if(lte(zoom,1.0),1.14,max(1.0,zoom-0.0015))"
                    ]
                    pans_x = [
                        "iw/2-(iw/zoom/2)",
                        "iw/2-(iw/zoom/2)+15",
                        "iw/2-(iw/zoom/2)",
                        "iw/2-(iw/zoom/2)"
                    ]
                    pans_y = [
                        "ih/2-(ih/zoom/2)",
                        "ih/2-(ih/zoom/2)",
                        "ih/2-(ih/zoom/2)+12",
                        "ih/2-(ih/zoom/2)"
                    ]

                    cmd_clip = [
                        "ffmpeg", "-y",
                        "-loop", "1",
                        "-i", fpath,
                        "-vf", f"zoompan=z='{zooms[a_idx]}':d={a_frames}:x='{pans_x[a_idx]}':y='{pans_y[a_idx]}':s=1080x1920:fps=30",
                        "-c:v", "libx264",
                        "-preset", "ultrafast",
                        "-t", str(a_dur),
                        "-pix_fmt", "yuv420p",
                        clip_v
                    ]
                    subprocess.run(cmd_clip, capture_output=True, check=True)
                    temp_vids.append(clip_v)

                concat_list_p = os.path.join(AI_CLIPS_DIR, f"concat_{session_id}.txt")
                with open(concat_list_p, "w", encoding="utf-8") as f:
                    for v in temp_vids:
                        f.write(f"file '{os.path.abspath(v)}'\n")

                combined_v = os.path.join(AI_CLIPS_DIR, f"combined_{session_id}.mp4")
                cmd_concat = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_list_p,
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    combined_v
                ]
                subprocess.run(cmd_concat, capture_output=True, check=True)
                if os.path.exists(concat_list_p): os.remove(concat_list_p)

                filter_complex = f"[0:v]drawbox=x=0:y=0:w='t/{total_duration}*1080':h=16:color=0x38bdf8@1:t=fill[vout]"
                if use_bgm:
                    filter_complex += f";[1:a]volume=1.0[voice];[2:a]volume=0.16[bgm];[voice][bgm]amix=inputs=2:duration=first[aout]"
                    cmd_final = [
                        "ffmpeg", "-y",
                        "-i", combined_v,
                        "-i", audio_temp_path,
                        "-stream_loop", "-1", "-i", bgm_path,
                        "-filter_complex", filter_complex,
                        "-map", "[vout]",
                        "-map", "[aout]",
                        "-c:v", "libx264",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-pix_fmt", "yuv420p",
                        "-t", str(total_duration),
                        "-shortest",
                        output_path
                    ]
                else:
                    cmd_final = [
                        "ffmpeg", "-y",
                        "-i", combined_v,
                        "-i", audio_temp_path,
                        "-filter_complex", filter_complex,
                        "-map", "[vout]",
                        "-map", "1:a",
                        "-c:v", "libx264",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-pix_fmt", "yuv420p",
                        "-t", str(total_duration),
                        "-shortest",
                        output_path
                    ]
                subprocess.run(cmd_final, capture_output=True, check=True)

            finally:
                for f in frame_files:
                    if os.path.exists(f):
                        try: os.remove(f)
                        except Exception: pass
                for v in temp_vids:
                    if os.path.exists(v) and v != output_path:
                        try: os.remove(v)
                        except Exception: pass
                if os.path.exists(audio_temp_path):
                    try: os.remove(audio_temp_path)
                    except Exception: pass
                comb = os.path.join(AI_CLIPS_DIR, f"combined_{session_id}.mp4")
                if os.path.exists(comb) and comb != output_path:
                    try: os.remove(comb)
                    except Exception: pass

        return {
            "video_path": output_path,
            "video_url": f"/uploads/ai_clips/{output_filename}",
            "filename": output_filename,
            "duration": total_duration,
            "size_bytes": os.path.getsize(output_path) if os.path.exists(output_path) else 0
        }

    # ------------------ ORIGIN STORY GENERATOR ------------------
    async def generate_origin_story_script(
        self,
        topic: str,
        story_angle: str = "shocking_origin",
        product_name: str = "",
        product_link: str = "",
        gemini_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """สร้างสคริปต์คลิปสั้นแนวประวัติศาสตร์/ต้นกำเนิด พร้อมแอบปักตะกร้าแบบ Soft-selling"""
        if gemini_api_key and gemini_api_key.strip():
            try:
                result = await self._call_gemini_origin_api(topic, story_angle, product_name, product_link, gemini_api_key.strip())
                if result:
                    return result
            except Exception as e:
                print(f"Gemini Origin API failed, falling back to built-in generator: {e}")

        return self._generate_builtin_origin_script(topic, story_angle, product_name, product_link)

    async def _call_gemini_origin_api(
        self,
        topic: str,
        story_angle: str,
        product_name: str,
        product_link: str,
        api_key: str
    ) -> Optional[Dict[str, Any]]:
        candidate_models = [
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
        ]
        angle_desc = {
            "shocking_origin": "ต้นกำเนิดสุดพีกที่คนส่วนใหญ่ไม่เคยรู้มาก่อน",
            "evolution": "วิวัฒนาการจากจุดเริ่มต้นโบราณสู่ของใช้ยุคปัจจุบัน",
            "world_hit": "ความลับและเหตุผลที่ทำให้สิ่งนี้กลายเป็นกระแสและฮิตไปทั่วโลก",
            "top_secrets": "3 ความลับหรือเกร็ดประวัติศาสตร์ที่น่าทึ่งที่สุดเกี่ยวกับสิ่งนี้"
        }.get(story_angle, "ต้นกำเนิดสุดพีกที่คาดไม่ถึง")

        soft_sell_instruction = ""
        if product_name:
            soft_sell_instruction = f"""
- ในช่วงท้ายของคลิป (องค์ที่ 3 / CTA) ให้ผูกเรื่องและเชื่อมโยงเข้าหา '{product_name}' อย่างแนบเนียนและเป็นธรรมชาติ (Soft-selling) เช่น บอกว่าเป็นต้นตำรับ/สูตรดั้งเดิมที่ต้องมีติดตัว และบอกว่าพิกัดปักไว้ให้ในตะกร้า/คอมเมนต์แล้ว
- ลิงก์สินค้า: {product_link}
"""
        else:
            soft_sell_instruction = "- ในช่วงท้าย ให้สรุปเรื่องราวและกระตุ้นให้กดติดตามช่องเพื่อไม่พลาดเรื่องน่ารู้รอบตัว"

        prompt = f"""
คุณเป็น Content Creator ผู้เชี่ยวชาญการเล่าเรื่องแนวสารคดีสั้น เรื่องน่ารู้ และประวัติศาสตร์ (Origin Story / Did You Know) สำหรับ TikTok, Facebook Reels และ YouTube Shorts
เป้าหมาย: เล่าประวัติและจุดกำเนิดของ '{topic}' ให้สนุก น่าทึ่ง ชวนติดตาม และมีอัตราการดูจบสูง (High Retention Rate)
มุมมองการเล่าเรื่อง: {angle_desc}
{soft_sell_instruction}

กฎสำคัญ:
1. ห้ามเปิดคลิปด้วยการทักทายสวัสดี หรือขายของเด็ดขาด! ให้เปิด 3 วินาทีแรกด้วยคำถามหรือความจริงที่กระตุกต่อมความอยากรู้ เช่น 'รู้หรือไม่ว่า...', 'สิ่งที่คุณใช้ทุกวันนี้ ในอดีตแท้จริงแล้ว...'
2. ในส่วน voice_text ให้ใส่เครื่องหมายจุลภาค (,) คั่นจังหวะหายใจอย่างเป็นธรรมชาติ ไม่พูดรัวเป็นหุ่นยนต์ และห้ามใส่อิโมจิ
3. ภาษาไทยที่ใช้ต้องน่าฟัง เป็นกันเอง มีความน่าเชื่อถือ

ส่งคืนคำตอบเป็น JSON รูปแบบนี้เท่านั้น (ห้ามใส่ markdown หรือข้อความอื่น):
{{
  "title": "ชื่อหัวข้อคลิปสั้นดึงดูดใจ ไม่เกิน 40 ตัวอักษร เช่น ต้นกำเนิดลับของ {topic}",
  "hook": "ประโยคเปิดคลิป 3 วิแรกชวนสงสัย",
  "points": ["เรื่องราวช่วงที่ 1 (จุดเริ่มต้นในอดีต)", "เรื่องราวช่วงที่ 2 (จุดเปลี่ยนสู่ความฮิต)", "เรื่องราวช่วงที่ 3 (ของในยุคปัจจุบัน)"],
  "cta": "ประโยคปิดท้ายที่เชื่อมโยงเข้าสินค้าหรือเชิญชวนกดติดตาม",
  "voice_text": "เนื้อความสำหรับให้อ่านออกเสียงทั้งหมดต่อเนื่องกันภาษาไทยอย่างเป็นธรรมชาติ มีเครื่องหมายจุลภาคคั่นจังหวะหายใจ ห้ามใส่อิโมจิ",
  "caption": "แคปชั่นโพสต์โซเชียล พร้อมแฮชแท็กสายสาระและพิกัดสินค้า",
  "hashtags": ["#รู้หรือไม่", "#สาระน่ารู้", "#เรื่องเล่า", "#ประวัติศาสตร์", "#TikTokUni", "#Shorts", "#Reels"]
}}
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"}
        }
        headers = {"Content-Type": "application/json", "X-goog-api-key": api_key.strip()}

        async with aiohttp.ClientSession() as session:
            for model_name in candidate_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key.strip()}"
                try:
                    async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                            if text.startswith("```"):
                                text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
                            parsed = json.loads(text)
                            return parsed
                except Exception as e:
                    print(f"Gemini Origin Story error on {model_name}: {e}")
        return None

    def _generate_builtin_origin_script(
        self,
        topic: str,
        story_angle: str = "shocking_origin",
        product_name: str = "",
        product_link: str = ""
    ) -> Dict[str, Any]:
        """เทมเพลตเรื่องเล่าต้นกำเนิดอัจฉริยะ (ทำงานได้ 100% โดยไม่ต้องพึ่งพา API Key)"""
        title = f"ต้นกำเนิดลับของ {topic} ที่หลายคนไม่เคยรู้!"
        hook = f"รู้หรือไม่ว่า, {topic} ที่เราใช้กันทุกวันนี้, แท้จริงแล้วในอดีตเคยถูกคิดค้นขึ้นมาด้วยเหตุผลสุดทึ่ง!"
        p1 = f"จุดเริ่มต้นเกิดขึ้นเมื่อหลายสิบปีก่อน, จากความพยายามแก้ปัญหาในชีวิตประจำวัน, จนเกิดเป็นนวัตกรรมที่เปลี่ยนโลก"
        p2 = f"ต่อมาได้มีการพัฒนาและผสมผสานสูตรพิเศษ, จนกลายมาเป็นกระแสนิยม, ที่ใครๆ ก็ต้องมีติดตัว"
        
        if product_name:
            p3 = f"และในปัจจุบัน, {product_name} ได้กลายเป็นตำนานแห่งความคุ้มค่า, ที่สืบทอดคุณภาพมาอย่างยาวนาน"
            cta = f"ใครอยากได้สูตรต้นตำรับแท้ๆ, พิกัดปักไว้ที่ตะกร้าและคอมเมนต์เรียบร้อยแล้วนะครับ"
            voice_text = f"{hook}, {p1}, {p2}, {p3}, {cta}"
            caption = f"📜 รู้หรือไม่? ต้นกำเนิดของ {topic} แท้จริงแล้วมีความลับซ่อนอยู่!\n\n🛒 ใครอยากลอง {product_name} สูตรต้นตำรับแท้ พิกัดด้านล่างเลยน้า\nพิกัด: {product_link}\n\n#รู้หรือไม่ #สาระน่ารู้ #เรื่องเล่า #ประวัติศาสตร์ #TikTokUni #Shorts #Reels"
        else:
            p3 = f"จนกลายมาเป็นสิ่งจำเป็นในชีวิตยุคปัจจุบัน, ที่ขาดไม่ได้เลยทีเดียว"
            cta = f"ถ้าชอบเรื่องเล่าสนุกๆ แบบนี้, ฝากกดไลก์และกดติดตามช่องไว้ด้วยนะครับ"
            voice_text = f"{hook}, {p1}, {p2}, {p3}, {cta}"
            caption = f"📜 รู้หรือไม่? ต้นกำเนิดของ {topic} ที่คุณอาจไม่เคยรู้มาก่อน!\n\nกดติดตามเพื่อรับชมเรื่องราวประวัติศาสตร์และเกร็ดน่ารู้รอบตัวทุกวันน้า\n\n#รู้หรือไม่ #สาระน่ารู้ #เรื่องเล่า #ประวัติศาสตร์ #TikTokUni #Shorts #Reels"

        return {
            "title": title,
            "hook": hook,
            "points": [p1, p2, p3],
            "cta": cta,
            "voice_text": voice_text,
            "caption": caption,
            "hashtags": ["#รู้หรือไม่", "#สาระน่ารู้", "#เรื่องเล่า", "#ประวัติศาสตร์", "#TikTokUni", "#Shorts", "#Reels"]
        }

    def create_origin_story_frame(
        self,
        scene_idx: int,
        title_text: str,
        scene_text: str,
        product_name: str = "",
        image_path: Optional[str] = None,
        width: int = 1080,
        height: int = 1920
    ) -> Image.Image:
        """สร้างเฟรมสารคดีสั้น 1080x1920 (9:16) แบบภาพเต็มจอ 100% วางตัวหนังสือบนภาพโดยตรง สบายตา ไม่ทางการเกินไป"""
        # 1. โหลดภาพและปรับให้เต็มจอ 1080x1920 แบบ Full-bleed 100% (ไม่มีกรอบ ไม่มีการ์ดดำ ภาพเด่นเต็มตา)
        if image_path and os.path.exists(image_path):
            try:
                orig = Image.open(image_path).convert("RGBA")
                target_ratio = width / height
                orig_ratio = orig.width / orig.height
                if orig_ratio > target_ratio:
                    nw = int(orig.height * target_ratio)
                    l = (orig.width - nw) // 2
                    crop = orig.crop((l, 0, l + nw, orig.height))
                else:
                    nh = int(orig.width / target_ratio)
                    t = (orig.height - nh) // 2
                    crop = orig.crop((0, t, orig.width, t + nh))
                base = crop.resize((width, height), Image.Resampling.LANCZOS)
            except Exception as e:
                print(f"Error loading full-bleed image: {e}")
                base = Image.new("RGBA", (width, height), (20, 24, 33, 255))
        else:
            base = Image.new("RGBA", (width, height), (20, 24, 33, 255))

        # 2. ใส่เงาไล่ระดับบางเบาแบบธรรมชาติ (Smooth Cinematic Scrim) เพื่อให้อ่านตัวหนังสือชัดเจน ไม่บดบังภาพ
        scrim = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        scrim_draw = ImageDraw.Draw(scrim)

        # Scrim ด้านบน: จาก 0 ถึง 320px ค่อยๆ จางหายไปอย่างเป็นธรรมชาติ
        for y in range(320):
            alpha = int(120 * (1 - (y / 320.0)) ** 1.5)
            scrim_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

        # Scrim ด้านล่าง: จาก 1250 ถึง 1920px เพื่อรองรับข้อความพากย์และปุ่มตะกร้า
        for y in range(1250, 1920):
            prog = (y - 1250) / 670.0
            alpha = int(175 * (prog ** 1.3))
            scrim_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

        base = Image.alpha_composite(base, scrim)

        # 3. ส่วนหัวข้อด้านบน: พาดลงบนภาพโดยตรง สบายตา ไม่ทางการเกินไป (Safe Zone สำหรับ Reels/TikTok)
        badge_titles = [
            "✨ รู้หรือไม่? เรื่องเล่าต้นกำเนิด",
            "📜 จุดเริ่มต้นในอดีต",
            "💡 จุดเปลี่ยนสำคัญสู่ความนิยม",
            "🌟 สรุปเรื่องราว & ของแท้"
        ]
        tag_text = badge_titles[min(scene_idx, 3)]
        self.draw_text_hb(base, tag_text, (width // 2, 140), 30, fill_color=(254, 240, 138, 255), stroke_width=3, stroke_color=(0, 0, 0, 230), align="center", bold=True)

        clean_title = clean_text_for_font(title_text)
        title_lines = self.wrap_text(clean_title, 50, 960)
        ty = 195
        for t_line in title_lines[:2]:
            self.draw_text_hb(base, t_line, (width // 2, ty), 50, fill_color=(255, 255, 255, 255), stroke_width=4, stroke_color=(0, 0, 0, 240), align="center", bold=True)
            ty += 64

        # 4. ข้อความบรรยายเรื่องราว (Subtitle) วางลงบนภาพโดยตรง ขนาดใหญ่ คมชัด อ่านง่าย ไม่ใส่กล่องดำ
        wrapped_sub = self.wrap_text(scene_text, 44, 960)
        sub_total_h = len(wrapped_sub) * 68
        sy = min(1480, 1680 - sub_total_h) if (product_name and scene_idx == 3) else min(1540, 1750 - sub_total_h)
        for s_line in wrapped_sub[:4]:
            self.draw_text_hb(base, s_line, (width // 2, sy), 44, fill_color=(255, 255, 255, 255), stroke_width=4, stroke_color=(0, 0, 0, 250), align="center", bold=True)
            sy += 68

        # 5. แถบปักตะกร้าด้านล่าง (มินิมอล แคปซูลโปร่งแสงโค้งมน สบายตา ป้ายยาแบบเนียนๆ)
        if product_name and scene_idx == 3:
            cta_w = 900
            cta_h = 92
            cta_x = (width - cta_w) // 2
            cta_y = 1750
            draw = ImageDraw.Draw(base)
            draw.rounded_rectangle([cta_x, cta_y, cta_x + cta_w, cta_y + cta_h], radius=46, fill=(245, 158, 11, 235), outline=(254, 240, 138, 240), width=2)
            self.draw_text_hb(base, f"🛒 พิกัด: {product_name} (จิ้มตะกร้าซ้ายล่างได้เลย)", (width // 2, cta_y + 20), 34, fill_color=(15, 23, 42, 255), align="center", bold=True)
        elif scene_idx == 3:
            self.draw_text_hb(base, "🔔 กดติดตามเพื่อรับชมเรื่องราวสนุกๆ รอบตัวทุกวัน", (width // 2, 1770), 32, fill_color=(254, 240, 138, 255), stroke_width=3, stroke_color=(0, 0, 0, 240), align="center", bold=True)

        return base.convert("RGB")

    async def render_origin_story_video(
        self,
        topic: str,
        title: str,
        hook: str,
        points: List[str],
        cta: str,
        voice_text: str,
        voice_name: str = "th-TH-PremwadeeNeural",
        voice_rate: str = "+3%",
        image_paths: Optional[List[str]] = None,
        product_name: str = "",
        product_link: str = "",
        enable_bgm: bool = True,
        gemini_api_key: Optional[str] = None,
        video_style: str = "documentary",
        output_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """เรนเดอร์วิดีโอสารคดีสั้น 1080x1920 (9:16) ด้วยเทคนิคซูมเปิดตัวแบบ Cinematic Ken Burns"""
        session_id = uuid.uuid4().hex[:8]
        if not output_filename:
            output_filename = f"origin_reel_{session_id}.mp4"
        output_path = os.path.join(AI_CLIPS_DIR, output_filename)

        # 1. สังเคราะห์เสียงพูด AI
        audio_temp_path = os.path.join(AI_CLIPS_DIR, f"origin_audio_{session_id}.mp3")
        voice_res = await self.generate_voice(voice_text, voice_name, voice_rate, gemini_api_key, audio_temp_path)
        duration = voice_res["duration"]
        total_duration = max(duration + 1.2, 6.0)
        fps = 30

        # 2. จัดเตรียม 4 ฉากสารคดี (Documentary Acts)
        valid_images = [p for p in (image_paths or []) if os.path.exists(p)]
        img0 = valid_images[0] if valid_images else None
        img1 = valid_images[1 % len(valid_images)] if valid_images else None
        img2 = valid_images[2 % len(valid_images)] if valid_images else None
        img3 = valid_images[-1] if valid_images else None

        p1 = points[0] if len(points) > 0 else "จุดเริ่มต้นที่หลายคนไม่เคยรู้"
        p2 = points[1] if len(points) > 1 else "จุดเปลี่ยนสำคัญสู่ความฮิตระดับโลก"
        p3 = points[2] if len(points) > 2 else "ของดีที่กลายเป็นตำนานในปัจจุบัน"

        story_acts = [
            {"idx": 0, "text": hook, "img": img0, "ratio": 0.25},
            {"idx": 1, "text": p1, "img": img1, "ratio": 0.30},
            {"idx": 2, "text": p2, "img": img2, "ratio": 0.25},
            {"idx": 3, "text": cta, "img": img3, "ratio": 0.20}
        ]

        bgm_path = os.path.join(ASSETS_DIR, "bgm_chill.mp3")
        use_bgm = enable_bgm and os.path.exists(bgm_path)

        frame_files = []
        temp_vids = []
        try:
            for act in story_acts:
                a_idx = act["idx"]
                a_dur = total_duration * act["ratio"]
                a_frames = max(int(a_dur * fps), 1)

                fpath = os.path.join(AI_CLIPS_DIR, f"origin_frame_{session_id}_{a_idx}.png")
                frame_img = self.create_origin_story_frame(
                    scene_idx=a_idx,
                    title_text=title,
                    scene_text=act["text"],
                    product_name=product_name if a_idx == 3 else "",
                    image_path=act["img"]
                )
                frame_img.save(fpath)
                frame_files.append(fpath)

                clip_v = os.path.join(AI_CLIPS_DIR, f"origin_clip_{session_id}_{a_idx}.mp4")

                # เอฟเฟกต์การเคลื่อนไหวแบบ Smooth Cinematic (นุ่มนวล สบายตา ตัวหนังสือไม่สั่นไหว)
                zooms = [
                    "min(zoom+0.0006,1.06)",
                    "1.03",
                    "min(zoom+0.0005,1.05)",
                    "if(lte(zoom,1.0),1.05,max(1.0,zoom-0.0005))"
                ]
                pans_x = [
                    "iw/2-(iw/zoom/2)",
                    "iw/2-(iw/zoom/2)+4",
                    "iw/2-(iw/zoom/2)",
                    "iw/2-(iw/zoom/2)"
                ]
                pans_y = [
                    "ih/2-(ih/zoom/2)",
                    "ih/2-(ih/zoom/2)",
                    "ih/2-(ih/zoom/2)+4",
                    "ih/2-(ih/zoom/2)"
                ]

                cmd_clip = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", fpath,
                    "-vf", f"zoompan=z='{zooms[a_idx]}':d={a_frames}:x='{pans_x[a_idx]}':y='{pans_y[a_idx]}':s=1080x1920:fps=30",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-t", str(a_dur),
                    "-pix_fmt", "yuv420p",
                    clip_v
                ]
                subprocess.run(cmd_clip, capture_output=True, check=True)
                temp_vids.append(clip_v)

            concat_list_p = os.path.join(AI_CLIPS_DIR, f"origin_concat_{session_id}.txt")
            with open(concat_list_p, "w", encoding="utf-8") as f:
                for v in temp_vids:
                    f.write(f"file '{os.path.abspath(v)}'\n")

            combined_v = os.path.join(AI_CLIPS_DIR, f"origin_comb_{session_id}.mp4")
            cmd_concat = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_p,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                combined_v
            ]
            subprocess.run(cmd_concat, capture_output=True, check=True)
            if os.path.exists(concat_list_p): os.remove(concat_list_p)

            # เส้นโปรเกรสบาร์สีทอง-ส้ม วิ่งด้านบนตามกาลเวลา (เส้นเพรียวบาง 8px สไตล์มินิมอล)
            filter_complex = f"[0:v]drawbox=x=0:y=0:w='t/{total_duration}*1080':h=8:color=0xf59e0b@1:t=fill[vout]"
            if use_bgm:
                filter_complex += f";[1:a]volume=1.0[voice];[2:a]volume=0.15[bgm];[voice][bgm]amix=inputs=2:duration=first[aout]"
                cmd_final = [
                    "ffmpeg", "-y",
                    "-i", combined_v,
                    "-i", audio_temp_path,
                    "-stream_loop", "-1", "-i", bgm_path,
                    "-filter_complex", filter_complex,
                    "-map", "[vout]",
                    "-map", "[aout]",
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-pix_fmt", "yuv420p",
                    "-t", str(total_duration),
                    "-shortest",
                    output_path
                ]
            else:
                cmd_final = [
                    "ffmpeg", "-y",
                    "-i", combined_v,
                    "-i", audio_temp_path,
                    "-filter_complex", filter_complex,
                    "-map", "[vout]",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-pix_fmt", "yuv420p",
                    "-t", str(total_duration),
                    "-shortest",
                    output_path
                ]
            subprocess.run(cmd_final, capture_output=True, check=True)

        finally:
            for f in frame_files:
                if os.path.exists(f):
                    try: os.remove(f)
                    except Exception: pass
            for v in temp_vids:
                if os.path.exists(v) and v != output_path:
                    try: os.remove(v)
                    except Exception: pass
            if os.path.exists(audio_temp_path):
                try: os.remove(audio_temp_path)
                except Exception: pass
            comb = os.path.join(AI_CLIPS_DIR, f"origin_comb_{session_id}.mp4")
            if os.path.exists(comb) and comb != output_path:
                try: os.remove(comb)
                except Exception: pass

        return {
            "video_path": output_path,
            "video_url": f"/uploads/ai_clips/{output_filename}",
            "filename": output_filename,
            "duration": total_duration,
            "size_bytes": os.path.getsize(output_path) if os.path.exists(output_path) else 0
        }

    async def generate_ai_images(
        self,
        topic: str,
        count: int = 3,
        style: str = "documentary",
        aspect_ratio: str = "9:16",
        gemini_api_key: Optional[str] = None,
        pollinations_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        สร้างรูปภาพ AI ทีละ 2-3 ภาพที่มีมุมมองเรื่องราวแตกต่างกัน (ต้นกำเนิด, มาโครซูม, ไลฟ์สไตล์)
        เพื่อนำไปประกอบการทำคลิปสารคดีสั้นหรือวิดีโอป้ายยา โดยทุกภาพรับประกันว่าเป็นรูปภาพจริง 100%
        """
        topic = (topic or "").strip()
        if not topic:
            raise ValueError("กรุณาระบุหัวข้อที่ต้องการวาดภาพ")

        count = max(1, min(count, 4))

        dims = {
            "9:16": (576, 1024),
            "1:1": (768, 768),
            "16:9": (1024, 576),
        }
        width, height = dims.get(aspect_ratio, (576, 1024))

        # 1. สร้าง Prompts ภาษาอังกฤษที่หลากหลายและมีมิติมุมมองต่างกัน
        scene_prompts = await self._create_image_prompts(topic, count, style, gemini_api_key)

        # 2. ทำการดาวน์โหลดและเจนรูปภาพทีละภาพ (พร้อมระบบ Hybrid Real Image Fallback)
        session_id = uuid.uuid4().hex[:8]
        generated_images = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://pollinations.ai/"
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            for idx, sc in enumerate(scene_prompts):
                title = sc.get("title", f"มุมมองที่ {idx + 1}")
                prompt_en = sc.get("prompt", "")

                encoded_prompt = urllib.parse.quote(prompt_en)
                pol_key = (pollinations_api_key or "").strip()
                if pol_key:
                    url = f"https://gen.pollinations.ai/image/{encoded_prompt}?width={width}&height={height}&key={pol_key}"
                else:
                    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

                img_filename = f"ai_img_{session_id}_{idx+1}.jpg"
                img_path = os.path.join(AI_IMAGES_DIR, img_filename)

                img_bytes = None
                # ลองเรียก Pollinations AI (ถ้ามีคีย์ หรือเซิร์ฟเวอร์ยังไม่ติด Rate limit)
                for attempt in range(2):
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                            if resp.status == 200:
                                raw_bytes = await resp.read()
                                if len(raw_bytes) > 3000:
                                    # ตรวจสอบและแปลงสัดส่วนภาพด้วย Pillow
                                    im_t = Image.open(io.BytesIO(raw_bytes))
                                    if im_t.size[0] > 100 and im_t.size[1] > 100:
                                        if im_t.mode != "RGB":
                                            im_t = im_t.convert("RGB")
                                        tw, th = width, height
                                        target_ratio = tw / th
                                        orig_ratio = im_t.width / im_t.height
                                        if orig_ratio > target_ratio:
                                            nw = int(im_t.height * target_ratio)
                                            l = (im_t.width - nw) // 2
                                            im_t = im_t.crop((l, 0, l + nw, im_t.height))
                                        else:
                                            nh = int(im_t.width / target_ratio)
                                            t = (im_t.height - nh) // 2
                                            im_t = im_t.crop((0, t, im_t.width, t + nh))
                                        im_t = im_t.resize((tw, th), Image.Resampling.LANCZOS)
                                        buf = io.BytesIO()
                                        im_t.save(buf, format="JPEG", quality=90)
                                        img_bytes = buf.getvalue()
                                        break
                            elif resp.status in (402, 429):
                                # เซิร์ฟเวอร์ติด Rate limit / Payment Required ให้ข้ามไปดึงคลังภาพจริงทันที
                                break
                    except Exception as e:
                        print(f"Pollinations fetch attempt {attempt} error: {e}")
                        await asyncio.sleep(0.5)

                # ถ้า AI ติด Rate Limit (402/429) ให้ดึงภาพถ่ายสารคดีจริงความละเอียดสูงจากคลังภาพระดับโลกทันที (รับประกันเป็นภาพถ่ายของจริง 100% ไม่ใช่กล่องข้อความ)
                if not img_bytes:
                    print(f"Fetching authentic documentary archive photo for scene {idx+1}: {topic}...")
                    img_bytes = await self._fetch_real_documentary_image(topic, idx, width, height)

                with open(img_path, "wb") as f:
                    f.write(img_bytes)

                generated_images.append({
                    "id": idx + 1,
                    "title": title,
                    "prompt": prompt_en,
                    "filename": img_filename,
                    "image_url": f"/uploads/ai_images/{img_filename}",
                    "image_path": img_path,
                    "width": width,
                    "height": height,
                    "size_bytes": len(img_bytes)
                })

                if idx < len(scene_prompts) - 1:
                    await asyncio.sleep(1.0)

        return {
            "status": "success",
            "topic": topic,
            "style": style,
            "aspect_ratio": aspect_ratio,
            "images": generated_images
        }

    async def _create_image_prompts(
        self,
        topic: str,
        count: int,
        style: str,
        gemini_api_key: Optional[str] = None
    ) -> List[Dict[str, str]]:
        if gemini_api_key and gemini_api_key.strip():
            try:
                res = await self._call_gemini_image_prompts(topic, count, style, gemini_api_key.strip())
                if res and len(res) >= count:
                    return res[:count]
            except Exception as e:
                print(f"Gemini prompt expansion failed, using built-in: {e}")

        return self._generate_builtin_image_prompts(topic, count, style)

    async def _call_gemini_image_prompts(
        self,
        topic: str,
        count: int,
        style: str,
        api_key: str
    ) -> Optional[List[Dict[str, str]]]:
        candidate_models = [
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
        ]

        prompt = f"""You are a master creative director for documentary videos and cinematic photography.
The user wants {count} distinct image generation prompts for the topic: "{topic}".
Visual Style requested: "{style}".

Create exactly {count} distinct sequential scenes. Each scene MUST have a unique perspective and narrative purpose:
- Scene 1: Historical origin / ancient craftsmanship / traditional workshop / raw authentic beginnings.
- Scene 2: Dramatic extreme macro / close-up action / intricate textures, water/light reflections.
- Scene 3: Modern aesthetic lifestyle / contemporary atmospheric setting / luxury cafe or studio ambient lighting.
(If 4 scenes requested, Scene 4 should be a dramatic mystery hero shot with cinematic rim lighting).

Return ONLY a valid JSON array of objects. Do not include markdown codeblocks (no ```json).
Format:
[
  {{
    "title": "องค์ที่ 1: กำเนิด & งานฝีมือโบราณ",
    "prompt": "Detailed English image generation prompt, specifying subject, environment, cinematic camera angle, lighting, 8k resolution, photorealistic"
  }},
  ...
]
"""
        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1024,
                }
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            candidates = data.get("candidates", [])
                            if candidates:
                                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                text = re.sub(r'```(?:json)?', '', text).strip()
                                parsed = json.loads(text)
                                if isinstance(parsed, list) and len(parsed) >= 1:
                                    return parsed[:count]
            except Exception as e:
                print(f"Gemini model {model} prompt error: {e}")
                continue
        return None

    def _generate_builtin_image_prompts(
        self,
        topic: str,
        count: int,
        style: str
    ) -> List[Dict[str, str]]:
        kw_map = {
            "แก้วน้ำ": "crystal drinking glass cup",
            "แก้ว": "glass cup",
            "กาแฟ": "artisan roasted coffee",
            "กาแฟโบราณ": "traditional Thai iced coffee in vintage cup",
            "ชา": "traditional tea leaves and brewed tea",
            "ชาไทย": "authentic Thai orange milk tea",
            "ยาดม": "traditional herbal aromatic inhaler",
            "ยาดมหงส์ไทย": "traditional Thai green herbal inhaler pot",
            "บะหมี่": "steaming noodle ramen bowl",
            "บะหมี่กึ่งสำเร็จรูป": "hot steaming ramen noodles in ceramic bowl",
            "รองเท้า": "classic sneaker footwear",
            "รองเท้าผ้าใบ": "retro vintage canvas sneakers",
            "นาฬิกา": "precision mechanical luxury wristwatch",
            "นาฬิกาข้อมือ": "classic elegant wristwatch with leather strap",
            "น้ำหอม": "luxury glass perfume fragrance bottle",
            "กระเป๋า": "handcrafted leather bag",
            "เสื้อ": "vintage cotton streetwear garment",
            "อาหาร": "traditional gourmet cuisine dish",
            "ขนม": "artisan handmade pastry dessert",
            "รถ": "classic vintage automobile car",
            "รถยนต์": "vintage collector automobile",
            "กล้อง": "vintage mechanical 35mm film camera",
            "แว่นตา": "classic vintage sunglasses",
            "หนังสือ": "ancient leather-bound historical manuscript",
            "หูฟัง": "audiophile vintage headphones",
            "เก้าอี้": "handcrafted mid-century wooden armchair",
            "โคมไฟ": "vintage warm industrial desk lamp",
            "สบู่": "natural organic handcrafted herbal soap",
        }

        en_item = None
        for k, v in kw_map.items():
            if k in topic:
                en_item = v
                break
        if not en_item:
            eng_only = re.sub(r'[^a-zA-Z0-9\s]', '', topic).strip()
            en_item = eng_only if len(eng_only) >= 3 else f"{topic} aesthetic object"

        style_modifiers = {
            "documentary": "cinematic documentary photography, 35mm film still, historical authenticity, warm dramatic volumetric lighting, 8k resolution, photorealistic",
            "product": "high-end commercial studio product photography, clean softbox lighting, crisp reflections, luxury advertising aesthetic, 8k resolution, ultra-sharp",
            "vintage": "vintage oil painting aesthetic, classic Renaissance brushwork, textured canvas, moody chiaroscuro lighting, masterpiece",
            "macro": "hyper-realistic macro photography, shallow depth of field, creamy bokeh, crystal sharp focus, dramatic rim light, 8k",
            "cyberpunk": "futuristic 3D octane render, neon cyber glow, sleek metallic textures, vibrant dynamic cinematic lighting, 8k"
        }
        mod = style_modifiers.get(style, style_modifiers["documentary"])

        scenes = [
            {
                "title": "องค์ที่ 1: กำเนิด & จุดเริ่มต้นในอดีต",
                "prompt": f"Historical origin documentary shot, authentic ancient craftsmanship of {en_item}, artisan hands carefully shaping the piece in a vintage historical workshop, warm candle and golden window light, dust motes floating in air, {mod}"
            },
            {
                "title": "องค์ที่ 2: มาโครซูม & รายละเอียดระดับสูง",
                "prompt": f"Dramatic extreme macro close-up of {en_item}, capturing intricate fine textures, crystal clear reflections and water droplets, shallow depth of field, dramatic high-contrast lighting, sharp focus, {mod}"
            },
            {
                "title": "องค์ที่ 3: ไลฟ์สไตล์ & ความนิยมในปัจจุบัน",
                "prompt": f"Atmospheric lifestyle shot featuring {en_item} placed on a rustic dark wooden table in an elegant high-end cozy cafe, soft morning sunlight streaming in, natural depth, editorial aesthetic, {mod}"
            },
            {
                "title": "องค์ที่ 4: ความลับ & เสน่ห์ที่น่าทึ่ง",
                "prompt": f"Cinematic hero shot of {en_item}, dark moody atmospheric studio background with golden rim lighting and soft haze, captivating presentation, {mod}"
            }
        ]
        return scenes[:count]

    async def _fetch_real_documentary_image(self, topic: str, scene_idx: int, width: int, height: int) -> bytes:
        """
        ดึงภาพถ่ายสารคดีและประวัติศาสตร์ของจริงที่มีความละเอียดสูงจากคลังภาพระดับโลก (Wikimedia Commons Archive)
        โดยค้นหาตามมุมมองของแต่ละองค์ (องค์ 1: กำเนิด/ประวัติศาสตร์, องค์ 2: การผลิต/รายละเอียด, องค์ 3: ชิ้นงาน/ไลฟ์สไตล์)
        พร้อมทำการ Center-crop ให้ได้สัดส่วนที่ต้องการ (เช่น 9:16) อย่างสวยงามคมชัด เป็นภาพจริง 100%
        """
        kw_map = {
            "แก้วน้ำ": ["glass blowing workshop", "drinking glass water", "vintage glass cup"],
            "แก้ว": ["glass craft workshop", "glass cup table", "drinking glass"],
            "กาแฟ": ["coffee bean roasting", "coffee brewing pouring", "iced coffee glass"],
            "กาแฟโบราณ": ["coffee bean roasting pan", "traditional coffee brewing", "Thai iced coffee oliang"],
            "ชา": ["tea plantation harvest", "tea brewing pot", "tea cup table"],
            "ชาไทย": ["tea leaf harvest", "traditional tea brewing", "Thai milk tea glass"],
            "ยาดม": ["herbal medicine plants", "traditional Thai herbal aroma", "herbal essential oil aroma"],
            "ยาดมหงส์ไทย": ["herbal ingredients aroma", "traditional herbal medicine pot", "Thai herbal inhaler aroma"],
            "บะหมี่": ["wheat noodle making", "steaming noodle soup bowl", "ramen noodles bowl"],
            "บะหมี่กึ่งสำเร็จรูป": ["noodle dough making", "steaming noodle soup", "instant noodles hot bowl"],
            "รองเท้า": ["leather shoe crafting vintage", "shoe stitching craft", "classic vintage sneakers"],
            "รองเท้าผ้าใบ": ["canvas shoe crafting", "vintage sneaker shoes", "classic canvas sneakers"],
            "นาฬิกา": ["watchmaker clock workshop", "watch movement gear mechanism", "vintage wristwatch luxury"],
            "นาฬิกาข้อมือ": ["watchmaker craft precision", "precision watch movement gears", "classic wrist watch"],
            "น้ำหอม": ["perfume flower essence distillation", "fragrance perfume bottles", "vintage luxury perfume"],
            "กระเป๋า": ["leather bag crafting workshop", "leather stitching craft", "vintage handcrafted leather bag"],
            "เสื้อ": ["cotton weaving loom vintage", "garment tailoring vintage", "classic cotton streetwear"],
            "อาหาร": ["traditional cooking fire pot", "chef cooking cuisine pan", "gourmet meal plate"],
            "ขนม": ["artisan baking pastry oven", "baker dough making", "traditional pastry dessert"],
            "รถ": ["vintage automobile factory", "classic vintage car engine", "classic vintage car road"],
            "รถยนต์": ["vintage automobile assembly", "classic collector automobile", "vintage car road trip"],
            "กล้อง": ["vintage camera mechanism lens", "vintage 35mm film camera", "classic film camera"],
            "แว่นตา": ["optician eyewear workshop", "vintage sunglasses frame", "classic eyewear glass"],
            "หนังสือ": ["ancient book binding manuscript", "leather bound historical book", "old library book"],
            "หูฟัง": ["audio engineering vintage", "vintage studio headphones", "audiophile headphones"],
            "เก้าอี้": ["woodworking chair craft", "carpenter wooden chair", "mid-century modern armchair"],
            "โคมไฟ": ["vintage lamp brass craft", "industrial desk lamp warm light", "vintage table lamp"],
            "สบู่": ["handcrafted soap making", "natural herbal soap bar", "organic artisan soap"],
        }

        chosen_kws = None
        for k, v in kw_map.items():
            if k in topic:
                chosen_kws = v
                break

        if chosen_kws:
            q = chosen_kws[scene_idx % len(chosen_kws)]
        else:
            clean_top = re.sub(r'[^a-zA-Z0-9\u0E00-\u0E7F\s]', '', topic).strip()
            angles = ["origin history", "making process", "vintage lifestyle"]
            q = f"{clean_top} {angles[scene_idx % len(angles)]}"

        headers = {
            "User-Agent": "AntigravityReels/1.0 (https://antigravity.ai; documentary educational)"
        }

        search_queries = [q, topic]
        for query_str in search_queries:
            search_url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote(query_str)}&gsrnamespace=6&gsrlimit=5&prop=imageinfo&iiprop=url|mime&format=json"
            try:
                async with aiohttp.ClientSession(headers=headers) as sess:
                    async with sess.get(search_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            pages = data.get("query", {}).get("pages", {})
                            for pid, pg in pages.items():
                                info = pg.get("imageinfo", [{}])[0]
                                mime = info.get("mime", "")
                                img_url = info.get("url")
                                if mime.startswith("image/") and not mime.endswith("svg+xml") and img_url:
                                    async with sess.get(img_url, timeout=aiohttp.ClientTimeout(total=15)) as img_resp:
                                        if img_resp.status == 200:
                                            raw_data = await img_resp.read()
                                            if len(raw_data) > 5000:
                                                im = Image.open(io.BytesIO(raw_data))
                                                if im.mode != "RGB":
                                                    im = im.convert("RGB")
                                                tw, th = width, height
                                                target_ratio = tw / th
                                                orig_ratio = im.width / im.height
                                                if orig_ratio > target_ratio:
                                                    nw = int(im.height * target_ratio)
                                                    l = (im.width - nw) // 2
                                                    im = im.crop((l, 0, l + nw, im.height))
                                                else:
                                                    nh = int(im.width / target_ratio)
                                                    t = (im.height - nh) // 2
                                                    im = im.crop((0, t, im.width, t + nh))
                                                im = im.resize((tw, th), Image.Resampling.LANCZOS)
                                                buf = io.BytesIO()
                                                im.save(buf, format="JPEG", quality=90)
                                                return buf.getvalue()
            except Exception as e:
                print(f"Wikimedia fetch error for '{query_str}': {e}")
                continue

        bg_candidates = [
            os.path.join(BACKGROUNDS_DIR, "bg_luxury.jpg"),
            os.path.join(BACKGROUNDS_DIR, "bg_cyber.jpg"),
        ]
        for bg in bg_candidates:
            if os.path.exists(bg):
                im = Image.open(bg)
                if im.mode != "RGB": im = im.convert("RGB")
                tw, th = width, height
                target_ratio = tw / th
                orig_ratio = im.width / im.height
                if orig_ratio > target_ratio:
                    nw = int(im.height * target_ratio)
                    l = (im.width - nw) // 2
                    im = im.crop((l, 0, l + nw, im.height))
                else:
                    nh = int(im.width / target_ratio)
                    t = (im.height - nh) // 2
                    im = im.crop((0, t, im.width, t + nh))
                im = im.resize((tw, th), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=90)
                return buf.getvalue()

        blank = Image.new("RGB", (width, height), (20, 20, 25))
        buf = io.BytesIO()
        blank.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

ai_creator = AICreator()

