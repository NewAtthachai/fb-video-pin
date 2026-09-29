import os
import sys
import glob
import uuid
import asyncio
import json
import shutil

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from typing import Optional, List
from fastapi import FastAPI, Request, Form, UploadFile, File, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from queue_manager import queue_manager
from automation import automation
from worker import worker
from ai_creator import ai_creator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="Multi-Platform Video Auto-Poster & Product Pinner")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

class AddReelRequest(BaseModel):
    video_path: str
    caption: str = ""
    product_name_or_link: str = ""
    first_comment: str = ""
    platforms: List[str] = ["facebook"]

class ScanFolderRequest(BaseModel):
    folder_path: str
    caption_template: str = ""
    product_name_or_link: str = ""
    platforms: List[str] = ["facebook"]

class UpdateConfigRequest(BaseModel):
    fb_platform: str = "business_suite"
    headless: bool = False
    delay_between_posts_minutes: int = 5
    auto_comment_product_link: bool = True
    gemini_api_key: Optional[str] = None
    pollinations_api_key: Optional[str] = None

class AIScriptRequest(BaseModel):
    product_name: str
    details: str = ""
    product_link: str = ""
    style: str = "viral_hook"
    gemini_api_key: Optional[str] = None

class AIOriginScriptRequest(BaseModel):
    topic: str
    story_angle: str = "shocking_origin"
    product_name: str = ""
    product_link: str = ""
    gemini_api_key: Optional[str] = None

class AIImageGenRequest(BaseModel):
    topic: str
    count: int = 3
    style: str = "documentary"
    aspect_ratio: str = "9:16"
    gemini_api_key: Optional[str] = None
    pollinations_api_key: Optional[str] = None

class AISendToQueueRequest(BaseModel):
    video_path: str
    caption: str = ""
    product_name_or_link: str = ""
    platforms: List[str] = ["facebook", "tiktok", "youtube"]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "config": queue_manager.config,
            "queue": queue_manager.queue,
            "is_running": queue_manager.is_running
        }
    )

@app.get("/api/status")
async def get_status():
    return {
        "is_running": queue_manager.is_running,
        "current_task_id": queue_manager.current_task_id,
        "queue_count": len(queue_manager.queue),
        "pending_count": len([i for i in queue_manager.queue if i["status"] in ("pending", "partial")]),
        "completed_count": len([i for i in queue_manager.queue if i["status"] == "completed"]),
        "failed_count": len([i for i in queue_manager.queue if i["status"] == "failed"]),
        "config": queue_manager.config
    }

@app.get("/api/queue")
async def get_queue():
    return queue_manager.queue

@app.post("/api/queue/add")
async def add_reel(req: AddReelRequest):
    try:
        item = queue_manager.add_item(
            video_path=req.video_path,
            caption=req.caption,
            product_name_or_link=req.product_name_or_link,
            first_comment=req.first_comment,
            platforms=req.platforms
        )
        return {"status": "success", "item": item}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.post("/api/queue/upload")
async def upload_video(
    file: UploadFile = File(...),
    caption: str = Form(""),
    product_name_or_link: str = Form(""),
    first_comment: str = Form(""),
    platforms: str = Form("facebook")
):
    try:
        safe_filename = file.filename
        save_path = os.path.join(UPLOADS_DIR, safe_filename)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        plat_list = [p.strip() for p in platforms.split(",") if p.strip()]
        if not plat_list:
            plat_list = ["facebook"]

        item = queue_manager.add_item(
            video_path=save_path,
            caption=caption,
            product_name_or_link=product_name_or_link,
            first_comment=first_comment,
            platforms=plat_list
        )
        return {"status": "success", "item": item}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.post("/api/queue/scan_folder")
async def scan_folder(req: ScanFolderRequest):
    if not os.path.isdir(req.folder_path):
        return JSONResponse(status_code=400, content={"status": "error", "message": f"ไม่พบโฟลเดอร์: {req.folder_path}"})
    
    extensions = ("*.mp4", "*.mov", "*.m4v", "*.webm")
    files: List[str] = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(req.folder_path, ext)))
        files.extend(glob.glob(os.path.join(req.folder_path, ext.upper())))
    
    files = sorted(list(set(files)))
    if not files:
        return JSONResponse(status_code=400, content={"status": "error", "message": "ไม่พบไฟล์วิดีโอ (.mp4, .mov) ในโฟลเดอร์นี้"})
    
    target_platforms = req.platforms if req.platforms and len(req.platforms) > 0 else ["facebook"]
    added_items = []
    for f in files:
        base_name = os.path.splitext(os.path.basename(f))[0]
        final_caption = req.caption_template.replace("{filename}", base_name) if req.caption_template else base_name
        
        item = queue_manager.add_item(
            video_path=f,
            caption=final_caption,
            product_name_or_link=req.product_name_or_link,
            platforms=target_platforms
        )
        added_items.append(item)

    queue_manager.log(f"ดึงวิดีโอจากโฟลเดอร์สำเร็จ {len(added_items)} รายการ", "success")
    return {"status": "success", "count": len(added_items)}

@app.delete("/api/queue/{item_id}")
async def delete_item(item_id: str):
    queue_manager.delete_item(item_id)
    return {"status": "success"}

@app.post("/api/queue/retry/{item_id}")
async def retry_item(item_id: str):
    queue_manager.update_item_status(item_id, "pending")
    queue_manager.log(f"รีเซ็ตสถานะคลิป ID {item_id} ให้พร้อมรอโพสต์ใหม่ทุกแพลตฟอร์ม", "info")
    return {"status": "success"}

@app.post("/api/queue/clear_completed")
async def clear_completed():
    queue_manager.clear_completed()
    return {"status": "success"}

@app.post("/api/queue/start")
async def start_queue(background_tasks: BackgroundTasks):
    background_tasks.add_task(worker.start)
    return {"status": "success", "message": "กำลังเริ่มคิว"}

@app.post("/api/queue/stop")
async def stop_queue(background_tasks: BackgroundTasks):
    background_tasks.add_task(worker.stop)
    return {"status": "success", "message": "กำลังหยุดคิว"}

@app.post("/api/config")
async def update_config(req: UpdateConfigRequest):
    queue_manager.update_config(req.model_dump())
    return {"status": "success"}

@app.post("/api/browser/login")
async def launch_login_browser(background_tasks: BackgroundTasks, platform: str = Query("facebook")):
    background_tasks.add_task(automation.open_login_browser, platform)
    return {"status": "success", "message": f"กำลังเปิดหน้าต่างล็อกอิน {platform}"}

@app.get("/api/logs/stream")
async def logs_stream():
    """SSE endpoint สำหรับสตรีม log สดๆ ไปยังหน้าเว็บ"""
    async def event_generator():
        q = queue_manager.add_subscriber()
        try:
            for entry in queue_manager.logs[-20:]:
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"

            while True:
                entry = await q.get()
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            queue_manager.remove_subscriber(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ------------------ AI VIDEO STUDIO API ------------------
@app.post("/api/ai/script")
async def ai_generate_script(req: AIScriptRequest):
    try:
        api_key = req.gemini_api_key or queue_manager.config.get("gemini_api_key", "")
        script_data = await ai_creator.generate_script(
            product_name=req.product_name,
            details=req.details,
            product_link=req.product_link,
            style=req.style,
            gemini_api_key=api_key
        )
        return {"status": "success", "data": script_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/ai/create_video")
async def ai_create_video(
    product_name: str = Form(...),
    details: str = Form(""),
    product_link: str = Form(""),
    style: str = Form("viral_hook"),
    voice_name: str = Form("th-TH-PremwadeeNeural"),
    voice_rate: str = Form("+4%"),
    enable_bgm: bool = Form(True),
    title: Optional[str] = Form(None),
    hook: Optional[str] = Form(None),
    points: Optional[str] = Form(None),
    cta: Optional[str] = Form(None),
    voice_text: Optional[str] = Form(None),
    caption: Optional[str] = Form(None),
    gemini_api_key: Optional[str] = Form(None),
    video_style: str = Form("presenter"),
    bg_theme: str = Form("cyber"),
    images: List[UploadFile] = File(default=[])
):
    try:
        queue_manager.log(f"🎬 กำลังสร้างคลิปด้วย AI สำหรับ: {product_name} (รูปแบบ: {video_style}, ธีม: {bg_theme})", "info")
        api_key = gemini_api_key or queue_manager.config.get("gemini_api_key", "")
        
        # 1. ถ้ายังไม่มีสคริปต์ ให้สร้างอัตโนมัติ
        if not title or not voice_text:
            script_data = await ai_creator.generate_script(
                product_name=product_name,
                details=details,
                product_link=product_link,
                style=style,
                gemini_api_key=api_key
            )
            title = script_data["title"]
            hook = script_data["hook"]
            parsed_points = script_data["points"]
            cta = script_data["cta"]
            voice_text = script_data["voice_text"]
            caption = script_data["caption"]
        else:
            if points:
                try:
                    parsed_points = json.loads(points)
                except Exception:
                    parsed_points = [p.strip() for p in points.split(",") if p.strip()]
            else:
                parsed_points = ["ดีไซน์สวย ใช้งานง่าย", "คุ้มค่าเกินราคา การันตีคุณภาพ"]

        # 2. บันทึกรูปภาพสินค้าที่อัปโหลด (ถ้ามี)
        saved_image_paths = []
        if images:
            temp_img_dir = os.path.join(BASE_DIR, "uploads", "temp_images")
            os.makedirs(temp_img_dir, exist_ok=True)
            for idx, img_file in enumerate(images):
                if img_file.filename:
                    ext = os.path.splitext(img_file.filename)[1] or ".png"
                    img_path = os.path.join(temp_img_dir, f"img_{uuid.uuid4().hex[:6]}_{idx}{ext}")
                    with open(img_path, "wb") as buffer:
                        shutil.copyfileobj(img_file.file, buffer)
                    saved_image_paths.append(img_path)

        queue_manager.log("กำลังสังเคราะห์เสียงพูด AI และเรนเดอร์วิดีโอ 9:16...", "info")
        video_res = await ai_creator.render_video(
            title=title,
            hook=hook or title,
            points=parsed_points,
            cta=cta or "พิกัดในแคปชั่นจ้า",
            voice_text=voice_text,
            voice_name=voice_name,
            voice_rate=voice_rate,
            enable_bgm=enable_bgm,
            gemini_api_key=api_key,
            image_paths=saved_image_paths,
            product_link=product_link,
            video_style=video_style,
            bg_theme=bg_theme
        )
        
        queue_manager.log(f"🎉 สร้างคลิปด้วย AI สำเร็จ: {video_res['filename']} (ความยาว {video_res['duration']:.1f} วินาที)", "success")
        return {
            "status": "success",
            "video_url": video_res["video_url"],
            "video_path": video_res["video_path"],
            "filename": video_res["filename"],
            "duration": video_res["duration"],
            "title": title,
            "hook": hook,
            "points": parsed_points,
            "cta": cta,
            "voice_text": voice_text,
            "caption": caption,
            "product_link": product_link
        }
    except Exception as e:
        queue_manager.log(f"❌ ผิดพลาดในการสร้างคลิป AI: {str(e)}", "error")
        return {"status": "error", "message": str(e)}

@app.post("/api/ai/send_to_queue")
async def ai_send_to_queue(req: AISendToQueueRequest):
    try:
        if not os.path.exists(req.video_path):
            return {"status": "error", "message": "ไม่พบไฟล์วิดีโอบนเซิร์ฟเวอร์"}

        item = queue_manager.add_item(
            video_path=req.video_path,
            caption=req.caption,
            product_name_or_link=req.product_name_or_link,
            first_comment="",
            platforms=req.platforms
        )
        return {"status": "success", "message": "เพิ่มคลิป AI เข้าสู่คิวโพสต์สำเร็จแล้ว!", "item": item}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ------------------ AI ORIGIN STORY API ------------------
@app.post("/api/ai/origin_script")
async def ai_generate_origin_script(req: AIOriginScriptRequest):
    try:
        api_key = req.gemini_api_key or queue_manager.config.get("gemini_api_key", "")
        script_data = await ai_creator.generate_origin_story_script(
            topic=req.topic,
            story_angle=req.story_angle,
            product_name=req.product_name,
            product_link=req.product_link,
            gemini_api_key=api_key
        )
        return {"status": "success", "data": script_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/ai/create_origin_video")
async def ai_create_origin_video(
    topic: str = Form(...),
    story_angle: str = Form("shocking_origin"),
    product_name: str = Form(""),
    product_link: str = Form(""),
    voice_name: str = Form("th-TH-PremwadeeNeural"),
    voice_rate: str = Form("+3%"),
    enable_bgm: bool = Form(True),
    title: Optional[str] = Form(None),
    hook: Optional[str] = Form(None),
    points: Optional[str] = Form(None),
    cta: Optional[str] = Form(None),
    voice_text: Optional[str] = Form(None),
    caption: Optional[str] = Form(None),
    gemini_api_key: Optional[str] = Form(None),
    video_style: str = Form("documentary"),
    images: List[UploadFile] = File(default=[]),
    server_image_paths: Optional[str] = Form(None)
):
    try:
        queue_manager.log(f"📜 กำลังสร้างคลิปสารคดีสั้น & ต้นกำเนิดสำหรับ: {topic} (มุมมอง: {story_angle})", "info")
        api_key = gemini_api_key or queue_manager.config.get("gemini_api_key", "")

        # 1. สร้างสคริปต์อัตโนมัติหากยังไม่มี
        if not title or not voice_text:
            script_data = await ai_creator.generate_origin_story_script(
                topic=topic,
                story_angle=story_angle,
                product_name=product_name,
                product_link=product_link,
                gemini_api_key=api_key
            )
            title = script_data["title"]
            hook = script_data["hook"]
            parsed_points = script_data["points"]
            cta = script_data["cta"]
            voice_text = script_data["voice_text"]
            caption = script_data["caption"]
        else:
            if points:
                try:
                    parsed_points = json.loads(points)
                except Exception:
                    parsed_points = [p.strip() for p in points.split(",") if p.strip()]
            else:
                parsed_points = ["จุดเริ่มต้นในอดีตที่น่าทึ่ง", "จุดเปลี่ยนสำคัญสู่ความนิยม", "ของดีที่กลายเป็นตำนานในปัจจุบัน"]

        # 2. บันทึกรูปภาพประกอบ (ทั้งจาก AI Gen Images และที่อัปโหลดเอง)
        saved_image_paths = []
        if server_image_paths:
            try:
                paths = json.loads(server_image_paths) if server_image_paths.startswith("[") else [p.strip() for p in server_image_paths.split(",") if p.strip()]
                for p in paths:
                    clean_p = p.replace("\\", "/").strip()
                    if clean_p.startswith("/uploads/"):
                        full_p = os.path.join(BASE_DIR, clean_p.lstrip("/").replace("/", os.sep))
                    elif clean_p.startswith("uploads/"):
                        full_p = os.path.join(BASE_DIR, clean_p.replace("/", os.sep))
                    elif os.path.exists(clean_p):
                        full_p = clean_p
                    else:
                        full_p = os.path.join(BASE_DIR, "uploads", "ai_images", os.path.basename(clean_p))
                    if os.path.exists(full_p):
                        saved_image_paths.append(full_p)
            except Exception as e:
                queue_manager.log(f"Warning parsing server_image_paths: {e}", "warning")

        if images:
            temp_img_dir = os.path.join(BASE_DIR, "uploads", "temp_images")
            os.makedirs(temp_img_dir, exist_ok=True)
            for idx, img_file in enumerate(images):
                if img_file.filename:
                    ext = os.path.splitext(img_file.filename)[1] or ".png"
                    img_path = os.path.join(temp_img_dir, f"origin_{uuid.uuid4().hex[:6]}_{idx}{ext}")
                    with open(img_path, "wb") as buffer:
                        shutil.copyfileobj(img_file.file, buffer)
                    saved_image_paths.append(img_path)

        queue_manager.log(f"กำลังสังเคราะห์เสียงพากย์และเรนเดอร์ภาพสารคดีด้วยเอฟเฟกต์ซูม Cinematic (รูปภาพ: {len(saved_image_paths)} รูป)...", "info")
        video_res = await ai_creator.render_origin_story_video(
            topic=topic,
            title=title,
            hook=hook or title,
            points=parsed_points,
            cta=cta or "ฝากกดติดตามด้วยนะครับ",
            voice_text=voice_text,
            voice_name=voice_name,
            voice_rate=voice_rate,
            enable_bgm=enable_bgm,
            gemini_api_key=api_key,
            image_paths=saved_image_paths,
            product_name=product_name,
            product_link=product_link,
            video_style=video_style
        )

        queue_manager.log(f"✨ สร้างคลิปสารคดีสั้นสำเร็จ: {video_res['filename']} ({video_res['duration']:.1f} วินาที)", "success")

        return {
            "status": "success",
            "video_url": video_res["video_url"],
            "video_path": video_res["video_path"],
            "filename": video_res["filename"],
            "duration": video_res["duration"],
            "title": title,
            "hook": hook,
            "points": parsed_points,
            "cta": cta,
            "voice_text": voice_text,
            "caption": caption,
            "product_name": product_name,
            "product_link": product_link
        }
    except Exception as e:
        queue_manager.log(f"❌ ผิดพลาดในการสร้างคลิปสารคดีสั้น: {str(e)}", "error")
        return {"status": "error", "message": str(e)}

@app.post("/api/ai/generate_images")
async def ai_generate_images(req: AIImageGenRequest):
    try:
        api_key = req.gemini_api_key or queue_manager.config.get("gemini_api_key", "")
        poll_key = req.pollinations_api_key or queue_manager.config.get("pollinations_api_key", "")
        queue_manager.log(f"🎨 กำลังเริ่มสร้างภาพ AI จำนวน {req.count} ภาพ สำหรับหัวข้อ: '{req.topic}' (สไตล์: {req.style})", "info")
        res = await ai_creator.generate_ai_images(
            topic=req.topic,
            count=req.count,
            style=req.style,
            aspect_ratio=req.aspect_ratio,
            gemini_api_key=api_key,
            pollinations_api_key=poll_key
        )
        queue_manager.log(f"✨ สร้างภาพ AI สำเร็จ {len(res.get('images', []))} ภาพ พร้อมใช้งาน", "success")
        return res
    except Exception as e:
        queue_manager.log(f"❌ ผิดพลาดในการวาดภาพ AI: {str(e)}", "error")
        return {"status": "error", "message": str(e)}

class SaveGeminiKeyRequest(BaseModel):
    api_key: str

@app.post("/api/config/gemini_key")
async def save_gemini_key(req: SaveGeminiKeyRequest):
    key = req.api_key.strip()
    queue_manager.config["gemini_api_key"] = key
    queue_manager.save()
    status = "เชื่อมต่อ Gemini API สำเร็จแล้ว" if key else "ใช้ระบบสร้างสคริปต์อัตโนมัติในตัว (ฟรี)"
    queue_manager.log(f"🔑 บันทึกคีย์ AI: {status}", "success")
    return {"status": "success", "message": status, "has_key": bool(key)}

class SavePollinationsKeyRequest(BaseModel):
    api_key: str

@app.post("/api/config/pollinations_key")
async def save_pollinations_key(req: SavePollinationsKeyRequest):
    key = req.api_key.strip()
    queue_manager.config["pollinations_api_key"] = key
    queue_manager.save()
    status = "เชื่อมต่อ Pollinations API สำเร็จแล้ว" if key else "ใช้ระบบคลังภาพถ่ายสารคดีความละเอียดสูงอัตโนมัติ (ฟรี)"
    queue_manager.log(f"🔑 {status}", "success")
    return {"status": "success", "message": status, "has_key": bool(key)}

@app.get("/api/ai/preview_voice")
async def preview_voice(voice_name: str = Query("gemini-Charon")):
    """ส่งคืนไฟล์เสียงตัวอย่างของแต่ละเสียง เพื่อให้ผู้ใช้กดฟังก่อนเลือก"""
    safe_name = os.path.basename(voice_name)
    sample_file = os.path.join(STATIC_DIR, "voice_samples", f"{safe_name}.mp3")
    if os.path.exists(sample_file):
        return FileResponse(sample_file, media_type="audio/mpeg")
    
    # ถ้ายังไม่มี ให้สร้างสดทันที
    api_key = queue_manager.config.get("gemini_api_key", "")
    os.makedirs(os.path.join(STATIC_DIR, "voice_samples"), exist_ok=True)
    sample_text = "สวัสดีครับ นี่คือเสียงตัวอย่างสำหรับใช้พากย์คลิปของคุณครับ"
    await ai_creator.generate_voice(
        voice_text=sample_text,
        voice_name=voice_name,
        voice_rate="+0%",
        gemini_api_key=api_key,
        output_path=sample_file
    )
    if os.path.exists(sample_file):
        return FileResponse(sample_file, media_type="audio/mpeg")
    return {"status": "error", "message": "Voice sample not found"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
