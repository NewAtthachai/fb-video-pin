import os
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Any
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROFILES_DIR = os.path.join(BASE_DIR, "browser_profiles")
QUEUE_FILE = os.path.join(DATA_DIR, "queue.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PROFILES_DIR, exist_ok=True)

class ReelItem(BaseModel):
    id: str
    video_path: str
    filename: str
    caption: str = ""
    product_name_or_link: str = ""
    product_tag_enabled: bool = True
    first_comment: str = ""
    platforms: List[str] = ["facebook"]  # ["facebook", "tiktok", "youtube"]
    platform_status: Dict[str, str] = {}  # {"facebook": "pending", "tiktok": "pending", ...}
    status: str = "pending"  # pending, running, completed, failed
    error_message: Optional[str] = None
    created_at: str = ""
    completed_at: Optional[str] = None

class AppConfig(BaseModel):
    fb_platform: str = "business_suite"  # "business_suite" or "facebook_web"
    headless: bool = False
    delay_between_posts_minutes: int = 5
    auto_comment_product_link: bool = True
    profiles_dir: str = PROFILES_DIR
    gemini_api_key: Optional[str] = ""
    pollinations_api_key: Optional[str] = ""

class QueueManager:
    def __init__(self):
        self.queue: List[Dict[str, Any]] = []
        self.config: Dict[str, Any] = AppConfig().model_dump()
        self.is_running = False
        self.should_stop = False
        self.current_task_id: Optional[str] = None
        self.logs: List[Dict[str, Any]] = []
        self.log_subscribers: List[asyncio.Queue] = []
        self.load()

    def log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = {"time": timestamp, "message": message, "level": level}
        self.logs.append(entry)
        if len(self.logs) > 500:
            self.logs.pop(0)
        
        # Broadcast to SSE subscribers
        for sub in list(self.log_subscribers):
            try:
                sub.put_nowait(entry)
            except Exception:
                pass

    def add_subscriber(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.log_subscribers.append(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue):
        if q in self.log_subscribers:
            self.log_subscribers.remove(q)

    def load(self):
        if os.path.exists(QUEUE_FILE):
            try:
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    self.queue = json.load(f)
                    # Normalize existing items
                    for item in self.queue:
                        if "platforms" not in item:
                            item["platforms"] = ["facebook"]
                        if "platform_status" not in item:
                            item["platform_status"] = {p: item.get("status", "pending") for p in item["platforms"]}
            except Exception:
                self.queue = []
        else:
            self.queue = []

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
            except Exception:
                pass

    def save(self):
        try:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.queue, f, ensure_ascii=False, indent=2)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"Error saving data: {str(e)}", "error")

    def add_item(self, video_path: str, caption: str, product_name_or_link: str, first_comment: str = "", platforms: Optional[List[str]] = None) -> Dict[str, Any]:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"ไม่พบไฟล์วิดีโอ: {video_path}")
        
        target_platforms = platforms if platforms and len(platforms) > 0 else ["facebook"]
        item_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        item = {
            "id": item_id,
            "video_path": os.path.abspath(video_path),
            "filename": os.path.basename(video_path),
            "caption": caption.strip(),
            "product_name_or_link": product_name_or_link.strip(),
            "product_tag_enabled": bool(product_name_or_link.strip()),
            "first_comment": first_comment.strip(),
            "platforms": target_platforms,
            "platform_status": {p: "pending" for p in target_platforms},
            "status": "pending",
            "error_message": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": None
        }
        self.queue.append(item)
        self.save()
        platform_names = ", ".join(target_platforms).upper()
        self.log(f"เพิ่มคลิปเข้าคิว [{platform_names}] สำเร็จ: {item['filename']}", "success")
        return item

    def delete_item(self, item_id: str):
        self.queue = [item for item in self.queue if item["id"] != item_id]
        self.save()
        self.log(f"ลบคลิป ID {item_id} ออกจากคิว", "info")

    def update_platform_status(self, item_id: str, platform: str, status: str, error_message: Optional[str] = None):
        for item in self.queue:
            if item["id"] == item_id:
                if "platform_status" not in item:
                    item["platform_status"] = {}
                item["platform_status"][platform] = status
                
                # Update overall status
                statuses = list(item["platform_status"].values())
                if all(s == "completed" for s in statuses):
                    item["status"] = "completed"
                    item["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    item["error_message"] = None
                elif any(s == "running" for s in statuses):
                    item["status"] = "running"
                elif any(s == "failed" for s in statuses) and all(s in ("completed", "failed") for s in statuses):
                    item["status"] = "failed"
                    item["error_message"] = error_message or f"ล้มเหลวในแพลตฟอร์ม {platform}"
                elif any(s == "completed" for s in statuses):
                    item["status"] = "partial"  # some completed, some pending
                else:
                    item["status"] = status
                break
        self.save()

    def update_item_status(self, item_id: str, status: str, error_message: Optional[str] = None):
        for item in self.queue:
            if item["id"] == item_id:
                item["status"] = status
                if status == "completed":
                    item["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    item["error_message"] = None
                    for p in item.get("platforms", []):
                        item.setdefault("platform_status", {})[p] = "completed"
                elif status == "failed":
                    item["error_message"] = error_message
                elif status == "pending":
                    item["error_message"] = None
                    for p in item.get("platforms", []):
                        item.setdefault("platform_status", {})[p] = "pending"
                break
        self.save()

    def clear_completed(self):
        self.queue = [item for item in self.queue if item["status"] != "completed"]
        self.save()
        self.log("ล้างรายการคลิปที่โพสต์สำเร็จแล้ว", "info")

    def update_config(self, new_config: Dict[str, Any]):
        self.config.update(new_config)
        self.save()
        self.log("บันทึกการตั้งค่าเรียบร้อย", "info")

queue_manager = QueueManager()
