import asyncio
from typing import Optional
from queue_manager import queue_manager
from automation import automation

class QueueWorker:
    def __init__(self):
        self.worker_task: Optional[asyncio.Task] = None
        self.is_running = False

    async def start(self):
        if self.is_running:
            queue_manager.log("คิวการโพสต์กำลังทำงานอยู่แล้ว", "warning")
            return
        
        self.is_running = True
        queue_manager.is_running = True
        queue_manager.should_stop = False
        queue_manager.log("▶️ เริ่มต้นการทำงานของคิวโพสต์วิดีโอ (Multi-Platform)", "info")
        self.worker_task = asyncio.create_task(self._run_loop())

    async def stop(self):
        if not self.is_running:
            return
        
        queue_manager.log("⏹️ กำลังสั่งหยุดคิวการโพสต์...", "warning")
        queue_manager.should_stop = True
        self.is_running = False
        queue_manager.is_running = False
        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        queue_manager.log("หยุดการทำงานของคิวเรียบร้อย", "info")

    async def _run_loop(self):
        try:
            while self.is_running and not queue_manager.should_stop:
                # หาคลิปถัดไปที่ยังโพสต์ไม่เสร็จทุกแพลตฟอร์ม
                pending_items = [i for i in queue_manager.queue if i["status"] in ("pending", "partial")]
                if not pending_items:
                    queue_manager.log("✅ โพสต์คลิปในคิวครบทั้งหมดทุกแพลตฟอร์มแล้ว!", "success")
                    break

                current_item = pending_items[0]
                queue_manager.current_task_id = current_item["id"]
                queue_manager.update_item_status(current_item["id"], "running")

                target_platforms = current_item.get("platforms", ["facebook"])
                platform_status = current_item.get("platform_status", {})

                for plat in target_platforms:
                    if queue_manager.should_stop or not self.is_running:
                        break

                    # ถ้าแพลตฟอร์มนี้โพสต์สำเร็จไปแล้ว ให้ข้าม
                    if platform_status.get(plat) == "completed":
                        continue

                    queue_manager.update_platform_status(current_item["id"], plat, "running")

                    try:
                        success = await automation.post_to_platform(current_item, plat, queue_manager.config)
                        if success:
                            queue_manager.update_platform_status(current_item["id"], plat, "completed")
                            queue_manager.log(f"✅ โพสต์คลิป [{plat.upper()}] สำเร็จ!", "success")
                        else:
                            queue_manager.update_platform_status(current_item["id"], plat, "failed", f"ไม่สามารถยืนยันการเผยแพร่บน {plat} ได้")
                    except Exception as e:
                        queue_manager.update_platform_status(current_item["id"], plat, "failed", str(e))

                    # พักช่วงสั้นๆ ระหว่างแพลตฟอร์มของคลิปเดียวกัน
                    await asyncio.sleep(3)

                queue_manager.current_task_id = None

                # ตรวจสอบว่ายังมีคิวต่อไหม
                remaining = [i for i in queue_manager.queue if i["status"] in ("pending", "partial")]
                if remaining and self.is_running and not queue_manager.should_stop:
                    delay_mins = queue_manager.config.get("delay_between_posts_minutes", 5)
                    queue_manager.log(f"⏳ รอเวลาหน่วง {delay_mins} นาทีก่อนโพสต์คลิปถัดไปเพื่อความปลอดภัย...", "info")
                    
                    for s in range(delay_mins * 60):
                        if queue_manager.should_stop or not self.is_running:
                            break
                        await asyncio.sleep(1)

        except asyncio.CancelledError:
            queue_manager.log("คิวโพสต์ถูกยกเลิก", "warning")
        except Exception as e:
            queue_manager.log(f"เกิดข้อผิดพลาดในคิว: {str(e)}", "error")
        finally:
            self.is_running = False
            queue_manager.is_running = False
            queue_manager.current_task_id = None

worker = QueueWorker()
