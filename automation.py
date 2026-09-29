import os
import sys
import time
import asyncio
import concurrent.futures
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, BrowserContext, Page
from queue_manager import queue_manager, PROFILES_DIR

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def is_proactor_loop(loop=None):
    if sys.platform != "win32":
        return True
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return True
    return isinstance(loop, getattr(asyncio, "ProactorEventLoop", tuple()))

async def run_with_proactor_fallback(coro_fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    if is_proactor_loop(loop):
        return await coro_fn(*args, **kwargs)
    
    def worker():
        new_loop = asyncio.WindowsProactorEventLoopPolicy().new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(coro_fn(*args, **kwargs))
        finally:
            new_loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return await loop.run_in_executor(ex, worker)

class MultiPlatformAutomation:
    def __init__(self):
        pass

    def get_profile_dir(self, platform: str = "") -> str:
        """ใช้โปรไฟล์ร่วมกันเพียง 1 โฟลเดอร์สำหรับทุกแพลตฟอร์ม เพื่อไม่ต้องล็อกอินแยกเบราว์เซอร์"""
        profile_path = os.path.join(PROFILES_DIR, "shared_user_profile")
        os.makedirs(profile_path, exist_ok=True)
        return profile_path

    def get_chrome_exe(self) -> str:
        """ค้นหา Google Chrome ในระบบ Windows เท่านั้น"""
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return "chrome"

    async def open_login_browser(self, platform: str = "facebook"):
        return await run_with_proactor_fallback(self._open_login_browser_impl, platform)

    async def _open_login_browser_impl(self, platform: str = "facebook"):
        """เปิดแท็บใหม่ให้ผู้ใช้ทำการล็อกอินบัญชี Facebook, TikTok หรือ YouTube"""
        platform_names = {
            "facebook": "Facebook (Meta Business Suite)",
            "tiktok": "TikTok Creator",
            "youtube": "YouTube Studio"
        }
        target_urls = {
            "facebook": "https://business.facebook.com",
            "tiktok": "https://www.tiktok.com/login",
            "youtube": "https://studio.youtube.com"
        }

        url = target_urls.get(platform, "https://business.facebook.com")
        name = platform_names.get(platform, platform.upper())
        profile_dir = self.get_profile_dir()

        queue_manager.log(f"🔑 กำลังเปิดแท็บใหม่สำหรับเข้าสู่ระบบ {name} บน Google Chrome...", "info")

        # 1. ลองเชื่อมต่อ Chrome ผ่าน CDP เพื่อเปิดเป็นแท็บใหม่ในหน้าต่างเดิมทันที
        pw = None
        try:
            pw = await async_playwright().start()
            for attempt in range(2):
                try:
                    browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
                    if browser and browser.contexts:
                        context = browser.contexts[0]
                        page = await context.new_page()
                        await page.goto(url, wait_until="domcontentloaded")
                        queue_manager.log(f"เปิดแท็บใหม่สำหรับ {name} ใน Google Chrome เรียบร้อยแล้ว!", "success")
                        return {"status": "success", "message": f"เปิดแท็บใหม่ {name} สำเร็จ"}
                except Exception:
                    pass

                if attempt == 0:
                    import subprocess
                    chrome_exe = self.get_chrome_exe()
                    if chrome_exe:
                        subprocess.Popen([
                            chrome_exe,
                            "--remote-debugging-port=9222",
                            f"--user-data-dir={profile_dir}",
                            "http://127.0.0.1:8000"
                        ])
                        await asyncio.sleep(2)
                    else:
                        break

            # 2. Fallback: ถ้าไม่ได้เปิดโหมด CDP ให้เปิด Chrome ใหม่ขึ้นมา
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ],
                viewport=None,
                locale="th-TH"
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            queue_manager.log(f"เปิดหน้าต่าง Google Chrome สำหรับเข้าสู่ระบบ {name} เรียบร้อย", "warning")
            while len(context.pages) > 0:
                await asyncio.sleep(1)
            await context.close()
            await pw.stop()
            queue_manager.log(f"บันทึกข้อมูลเข้าสู่ระบบ {name} เรียบร้อยแล้ว", "success")
            return {"status": "success", "message": "เสร็จสิ้น"}

        except Exception as e:
            queue_manager.log(f"เกิดข้อผิดพลาดในการเปิดแท็บ {name}: {str(e)}", "error")
            return {"status": "error", "message": str(e)}

    async def post_to_platform(self, item: Dict[str, Any], platform: str, config: Dict[str, Any]) -> bool:
        return await run_with_proactor_fallback(self._post_to_platform_impl, item, platform, config)

    async def _post_to_platform_impl(self, item: Dict[str, Any], platform: str, config: Dict[str, Any]) -> bool:
        """โพสต์คลิปไปยังแพลตฟอร์มที่ระบุ (facebook, tiktok, youtube)"""
        video_path = item["video_path"]
        caption = item.get("caption", "")
        product = item.get("product_name_or_link", "")
        headless = config.get("headless", False)
        profile_dir = self.get_profile_dir(platform)

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"ไม่พบไฟล์วิดีโอ: {video_path}")

        queue_manager.log(f"🚀 เริ่มกระบวนการโพสต์ไปยัง [{platform.upper()}]: {item['filename']}", "info")

        pw = None
        context = None
        page = None
        is_cdp = False
        browser = None
        try:
            pw = await async_playwright().start()

            # 1. ลองเชื่อมต่อผ่าน CDP (http://127.0.0.1:9222) เพื่อเปิดเป็น New Tab ใน Google Chrome เดิมเสมอ
            try:
                browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
                if browser and browser.contexts:
                    context = browser.contexts[0]
                    page = await context.new_page()
                    is_cdp = True
                    queue_manager.log("⚡ เปิดแท็บใหม่ (New Tab) ใน Google Chrome เพื่อดำเนินการโพสต์คลิป...", "info")
            except Exception:
                pass

            # 2. ถ้ายังไม่ได้เปิด ให้เปิด Google Chrome เท่านั้น พร้อมพอร์ต 9222 แล้วเชื่อมต่อเป็นแท็บใหม่
            if not is_cdp:
                import subprocess
                chrome_exe = self.get_chrome_exe()

                if chrome_exe:
                    queue_manager.log("กำลังเปิดหน้าต่าง Google Chrome พร้อมพอร์ตแท็บ...", "info")
                    cmd = [
                        chrome_exe,
                        "--remote-debugging-port=9222",
                        f"--user-data-dir={self.get_profile_dir()}",
                        "http://127.0.0.1:8000"
                    ]
                    subprocess.Popen(cmd)
                    for _ in range(8):
                        await asyncio.sleep(0.5)
                        try:
                            browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
                            if browser and browser.contexts:
                                context = browser.contexts[0]
                                page = await context.new_page()
                                is_cdp = True
                                queue_manager.log("⚡ เปิดแท็บใหม่ (New Tab) ใน Google Chrome เรียบร้อยแล้ว!", "info")
                                break
                        except Exception:
                            pass

            # 3. Fallback กรณีไม่มี Google Chrome รองรับ CDP
            if not is_cdp:
                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars"
                ]
                if not headless:
                    launch_args.append("--start-maximized")

                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=self.get_profile_dir(),
                    headless=headless,
                    channel="chrome",
                    args=launch_args,
                    viewport=None if not headless else {"width": 1280, "height": 800},
                    locale="th-TH"
                )
                page = context.pages[0] if context.pages else await context.new_page()

            page.set_default_timeout(60000)

            success = False
            if platform == "facebook":
                fb_plat = config.get("fb_platform", "business_suite")
                if fb_plat == "business_suite":
                    success = await self._post_via_business_suite(page, video_path, caption, product, item)
                else:
                    success = await self._post_via_facebook_web(page, video_path, caption, product, item)
            elif platform == "tiktok":
                success = await self._post_via_tiktok(page, video_path, caption, product, item)
            elif platform == "youtube":
                success = await self._post_via_youtube(page, video_path, caption, product, item)
            else:
                raise ValueError(f"แพลตฟอร์มที่ไม่รู้จัก: {platform}")

            await asyncio.sleep(3)

            # ปิดแท็บเมื่อเสร็จสิ้น
            if is_cdp:
                await page.close()
            else:
                await context.close()
                await pw.stop()

            return success

        except Exception as e:
            err_msg = str(e).strip() or repr(e)
            queue_manager.log(f"❌ ผิดพลาดในการโพสต์ [{platform.upper()}]: {err_msg}", "error")
            try:
                if page:
                    err_screenshot = os.path.join(SCREENSHOTS_DIR, f"err_{platform}_{item['id']}.png")
                    await page.screenshot(path=err_screenshot)
                    queue_manager.log(f"บันทึกภาพหน้าจอข้อผิดพลาด: {err_screenshot}", "warning")
            except Exception:
                pass

            if is_cdp:
                if page:
                    try: await page.close()
                    except Exception: pass
            else:
                if context:
                    try: await context.close()
                    except Exception: pass
                if pw:
                    try: await pw.stop()
                    except Exception: pass
            raise e

    # ------------------ FACEBOOK REELS ------------------
    async def _post_via_business_suite(self, page: Page, video_path: str, caption: str, product: str, item: Dict[str, Any]) -> bool:
        url = "https://business.facebook.com/latest/reels_composer"
        queue_manager.log(f"กำลังเปิดหน้าต่างสร้าง Reels: {url}", "info")
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)

        if "login" in page.url or await page.locator('input[name="email"]').count() > 0:
            raise Exception("ยังไม่ได้เข้าสู่ระบบ Facebook! กรุณากดปุ่ม 'ล็อกอิน: Facebook' ที่เมนูด้านบนก่อน")

        queue_manager.log("กำลังอัปโหลดวิดีโอไปยัง Facebook Reels...", "info")
        file_input = page.locator('input[type="file"]')
        if await file_input.count() == 0:
            add_btn = page.locator('div[role="button"]:has-text("เพิ่มวิดีโอ"), button:has-text("เพิ่มวิดีโอ"), div[role="button"]:has-text("Add video")').first
            if await add_btn.count() > 0:
                await add_btn.click()
                await page.wait_for_timeout(1000)

        file_input = page.locator('input[type="file"]').first
        await file_input.set_input_files(video_path)
        await page.wait_for_timeout(5000)

        # Caption & Product
        full_caption = caption
        if product:
            full_caption += f"\n\n🛒 พิกัดสินค้าในตะกร้า / สั่งซื้อ: {product}"

        queue_manager.log("กำลังใส่คำบรรยายแคปชั่น...", "info")
        caption_box = page.locator('div[contenteditable="true"][role="textbox"], textarea[placeholder*="คำอธิบาย"], div[aria-label*="คำอธิบาย"], div[aria-label*="Describe your reel"]').first
        if await caption_box.count() > 0:
            await caption_box.click()
            await caption_box.fill(full_caption)
        else:
            generic_box = page.locator('div[contenteditable="true"]').first
            if await generic_box.count() > 0:
                await generic_box.click()
                await generic_box.fill(full_caption)

        await page.wait_for_timeout(2000)

        # Tag products
        if product:
            await self._handle_fb_product_tagging(page, product)

        # Next steps
        for step in range(3):
            next_btn = page.locator('div[role="button"]:has-text("ถัดไป"), button:has-text("ถัดไป"), div[role="button"]:has-text("Next"), button:has-text("Next")').first
            if await next_btn.count() > 0 and await next_btn.is_visible() and await next_btn.is_enabled():
                await next_btn.click()
                await page.wait_for_timeout(2500)
            else:
                break

        # Publish
        queue_manager.log("กำลังตรวจสอบและกดปุ่มเผยแพร่บน Facebook...", "info")
        await page.wait_for_timeout(3000)
        publish_btn = page.locator('div[role="button"]:has-text("เผยแพร่"), button:has-text("เผยแพร่"), div[role="button"]:has-text("Publish"), button:has-text("Publish"), div[role="button"]:has-text("แชร์")').first
        if await publish_btn.count() > 0:
            for _ in range(30):
                if await publish_btn.is_enabled():
                    break
                await page.wait_for_timeout(2000)
            await publish_btn.click()
            queue_manager.log("กดเผยแพร่บน Facebook สำเร็จ!", "success")
            await page.wait_for_timeout(8000)
            return True
        return True

    async def _handle_fb_product_tagging(self, page: Page, product: str):
        try:
            tag_buttons = page.locator('div[role="button"]:has-text("ติดแท็กสินค้า"), button:has-text("ติดแท็กสินค้า"), div[role="button"]:has-text("Tag products")')
            if await tag_buttons.count() > 0:
                queue_manager.log("พบปุ่มติดแท็กสินค้าใน Facebook Reels กำลังค้นหาสินค้า...", "info")
                await tag_buttons.first.click()
                await page.wait_for_timeout(2000)
                search_input = page.locator('input[placeholder*="ค้นหา"], input[placeholder*="Search"]').first
                if await search_input.count() > 0:
                    await search_input.fill(product)
                    await page.wait_for_timeout(1500)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(2000)
                    row = page.locator('div[role="checkbox"], div[role="listitem"]').first
                    if await row.count() > 0:
                        await row.click()
                        await page.wait_for_timeout(1000)
                    done = page.locator('div[role="button"]:has-text("บันทึก"), button:has-text("บันทึก"), button:has-text("Done")').first
                    if await done.count() > 0:
                        await done.click()
        except Exception:
            pass

    async def _post_via_facebook_web(self, page: Page, video_path: str, caption: str, product: str, item: Dict[str, Any]) -> bool:
        url = "https://www.facebook.com/reels/create"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        file_input = page.locator('input[type="file"]').first
        if await file_input.count() == 0:
            raise Exception("ไม่พบช่องอัปโหลดบน Facebook Web หรือยังไม่ได้ล็อกอิน")
        await file_input.set_input_files(video_path)
        await page.wait_for_timeout(5000)

        next_btn = page.locator('div[role="button"]:has-text("ถัดไป"), div[role="button"]:has-text("Next")').first
        if await next_btn.count() > 0:
            await next_btn.click()
            await page.wait_for_timeout(2000)

        full_caption = caption + (f"\n\n🛒 สั่งซื้อสินค้า: {product}" if product else "")
        caption_box = page.locator('div[contenteditable="true"][role="textbox"]').first
        if await caption_box.count() > 0:
            await caption_box.click()
            await caption_box.fill(full_caption)
            await page.wait_for_timeout(2000)

        pub_btn = page.locator('div[role="button"]:has-text("โพสต์"), div[role="button"]:has-text("Post"), div[role="button"]:has-text("เผยแพร่")').first
        if await pub_btn.count() > 0:
            await pub_btn.click()
            await page.wait_for_timeout(8000)
            queue_manager.log("โพสต์คลิปบน Facebook สำเร็จเรียบร้อย!", "success")
            return True
        return False

    # ------------------ TIKTOK ------------------
    async def _post_via_tiktok(self, page: Page, video_path: str, caption: str, product: str, item: Dict[str, Any]) -> bool:
        """โพสต์คลิปไปยัง TikTok Creator Center พร้อมข้อมูลปักตะกร้า"""
        url = "https://www.tiktok.com/creator-center/upload?from=upload"
        queue_manager.log(f"กำลังเปิดหน้าต่างสร้างคลิป TikTok: {url}", "info")
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        # ตรวจสอบการล็อกอิน
        if "login" in page.url:
            raise Exception("ยังไม่ได้เข้าสู่ระบบ TikTok! กรุณากดปุ่ม 'ล็อกอิน: TikTok' ที่เมนูด้านบนก่อน")

        queue_manager.log("กำลังอัปโหลดวิดีโอไปยัง TikTok...", "info")
        # TikTok upload file input
        file_input = page.locator('input[type="file"]').first
        if await file_input.count() == 0:
            # ลอง fallback ไปหน้า tiktok.com/upload
            await page.goto("https://www.tiktok.com/upload", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            file_input = page.locator('input[type="file"]').first

        if await file_input.count() == 0:
            raise Exception("ไม่พบช่องอัปโหลดวิดีโอบน TikTok กรุณาตรวจสอบการล็อกอิน")

        await file_input.set_input_files(video_path)
        queue_manager.log(f"กำลังอัปโหลด {os.path.basename(video_path)} ไปยัง TikTok...", "info")

        # รอให้อัปโหลดวิดีโอขึ้นแสดง
        await page.wait_for_timeout(6000)

        # Caption & Product
        full_caption = caption
        if product:
            full_caption += f" 🛒 พิกัดสินค้าในตะกร้า: {product}"
        if "#tiktok" not in full_caption.lower():
            full_caption += " #fyp #tiktokuni"

        queue_manager.log("กำลังพิมพ์แคปชั่นบน TikTok...", "info")
        caption_editor = page.locator('div[contenteditable="true"], div.notranslate[role="combobox"], [data-placeholder*="caption"]').first
        if await caption_editor.count() > 0:
            await caption_editor.click()
            await page.wait_for_timeout(500)
            # เคลียร์และพิมพ์แคปชั่น
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(full_caption, delay=30)
            await page.wait_for_timeout(2000)

        # ตรวจสอบว่ามีตัวเลือกปักตะกร้าสินค้า / TikTok Shop หรือ Anchor Link หรือไม่
        if product:
            queue_manager.log(f"ตรวจสอบตัวเลือกตะกร้าสินค้า TikTok Shop / ลิงก์สินค้า: {product}", "info")
            try:
                anchor_btn = page.locator('button:has-text("เพิ่มลิงก์"), div:has-text("เพิ่มลิงก์"), button:has-text("Add link"), div:has-text("Product")').first
                if await anchor_btn.count() > 0:
                    await anchor_btn.click()
                    await page.wait_for_timeout(1500)
            except Exception:
                pass

        # ปุ่มโพสต์ (Post / โพสต์)
        queue_manager.log("กำลังค้นหาปุ่มโพสต์บน TikTok...", "info")
        await page.wait_for_timeout(4000)
        post_btn = page.locator('button:has-text("โพสต์"), button:has-text("Post"), button:has-text("Publish")').first
        if await post_btn.count() > 0:
            # รอจนกว่าปุ่มจะกดได้
            for _ in range(30):
                if await post_btn.is_enabled():
                    break
                await page.wait_for_timeout(2000)

            await post_btn.click()
            queue_manager.log("กดปุ่มโพสต์คลิป TikTok เรียบร้อยแล้ว!", "success")
            await page.wait_for_timeout(8000)
            return True
        else:
            raise Exception("ไม่พบปุ่มโพสต์บนหน้า TikTok")

    # ------------------ YOUTUBE SHORTS ------------------
    async def _post_via_youtube(self, page: Page, video_path: str, caption: str, product: str, item: Dict[str, Any]) -> bool:
        """โพสต์คลิปไปยัง YouTube Studio เป็น YouTube Shorts พร้อมลิงก์สินค้าแบบสาธารณะ (Public)"""
        url = "https://studio.youtube.com"
        queue_manager.log(f"กำลังเปิดหน้าต่าง YouTube Studio: {url}", "info")
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        # ตรวจสอบการล็อกอิน Google
        if "accounts.google.com" in page.url or "signin" in page.url:
            raise Exception("ยังไม่ได้เข้าสู่ระบบ Google / YouTube! กรุณากดปุ่ม 'ล็อกอิน: YouTube' ที่เมนูด้านบนก่อน")

        queue_manager.log("กำลังเริ่มกระบวนการอัปโหลด YouTube Shorts...", "info")

        # 1. กดปุ่ม สร้าง (Create) หรือ อัปโหลด
        create_btn = page.locator('#create-icon, button[aria-label="Create"], button[aria-label="สร้าง"], [aria-label="Upload videos"]').first
        if await create_btn.count() > 0:
            await create_btn.click()
            await page.wait_for_timeout(1000)

            upload_menu = page.locator('tp-yt-paper-item:has-text("Upload videos"), tp-yt-paper-item:has-text("อัปโหลดวิดีโอ")').first
            if await upload_menu.count() > 0:
                await upload_menu.click()
                await page.wait_for_timeout(1500)

        # 2. ใส่ไฟล์วิดีโอใน input file
        file_input = page.locator('input[type="file"]').first
        if await file_input.count() == 0:
            raise Exception("ไม่พบช่องอัปโหลดของ YouTube Studio")

        await file_input.set_input_files(video_path)
        queue_manager.log(f"กำลังส่งไฟล์ {os.path.basename(video_path)} ไปยัง YouTube...", "info")
        
        # รอให้หน้าต่างแก้ไขข้อมูลวิดีโอ (Metadata Editor) ปรากฏ
        try:
            await page.wait_for_selector('#textbox, #title-textarea', timeout=25000)
        except Exception:
            queue_manager.log("รอฟอร์มข้อมูล YouTube นานกว่าปกติ กำลังดำเนินการต่อ...", "warning")

        await page.wait_for_timeout(3000)

        # 3. ใส่ชื่อคลิป (Title) - ตรวจสอบให้มี #Shorts
        title_text = caption.split("\n")[0] if caption else os.path.splitext(item['filename'])[0]
        if "#shorts" not in title_text.lower():
            title_text = f"{title_text} #Shorts"
        title_text = title_text[:95]  # จำกัดความยาวไม่เกิน 100 ตัวอักษร

        queue_manager.log(f"กำลังใส่ชื่อคลิป YouTube Shorts: {title_text}", "info")
        title_box = page.locator('#title-textarea #textbox, #textbox[aria-label*="ชื่อ"], #textbox[aria-label*="Title"], div#textbox').first
        if await title_box.count() > 0:
            await title_box.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await title_box.fill(title_text)
            await page.wait_for_timeout(1000)

        # 4. ใส่คำอธิบายคลิป (Description) พร้อมพิกัดสินค้า
        full_desc = caption
        if product:
            full_desc += f"\n\n🛒 พิกัดสินค้าในคลิป / สั่งซื้อได้ที่: {product}"
        full_desc += "\n\n#Shorts #YouTubeShorts"

        desc_box = page.locator('#description-textarea #textbox, #textbox[aria-label*="คำอธิบาย"], #textbox[aria-label*="Description"]').first
        if await desc_box.count() > 0:
            await desc_box.click()
            await desc_box.fill(full_desc)
            await page.wait_for_timeout(1000)

        # 5. เลือกตัวเลือกเด็ก "ไม่ใช่ วิดีโอนี้ไม่ได้สร้างมาเพื่อเด็ก" (Not made for kids)
        queue_manager.log("กำลังกำหนดกลุ่มเป้าหมาย (ไม่ได้สร้างมาเพื่อเด็ก)...", "info")
        not_for_kids = page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"], [name="VIDEO_MADE_FOR_KIDS_NOT_MFK"], #not-made-for-kids').first
        if await not_for_kids.count() > 0:
            await not_for_kids.scroll_into_view_if_needed()
            await not_for_kids.click(force=True)
            await page.wait_for_timeout(1000)
        else:
            not_kids_text = page.locator('text="No, it\'s not made for kids", text="ไม่ใช่ วิดีโอนี้ไม่ได้สร้างมาเพื่อเด็ก"').first
            if await not_kids_text.count() > 0:
                await not_kids_text.scroll_into_view_if_needed()
                await not_kids_text.click(force=True)
                await page.wait_for_timeout(1000)

        # 6. กด ถัดไป (Next) จนกระทั่งถึงขั้นตอนกำหนดระดับการแชร์ (Visibility)
        queue_manager.log("กำลังดำเนินการไปยังขั้นตอนกำหนดการเปิดเผย (Visibility)...", "info")
        for step in range(5):
            # ตรวจสอบว่าถึงหน้าเลือก Public หรือยัง
            public_radio = page.locator('tp-yt-paper-radio-button[name="PUBLIC"], [name="PUBLIC"]').first
            if await public_radio.count() > 0 and await public_radio.is_visible():
                queue_manager.log("เข้าสู่หน้าเลือกการเปิดเผย (Visibility) เรียบร้อยแล้ว", "info")
                break

            next_btn = page.locator('#next-button, ytcp-button#next-button').first
            if await next_btn.count() > 0 and await next_btn.is_visible():
                # ตรวจสอบว่าปุ่ม enable หรือยัง
                for _ in range(10):
                    if await next_btn.is_enabled():
                        break
                    await page.wait_for_timeout(500)

                await next_btn.click()
                queue_manager.log(f"กด ถัดไป (Next) ขั้นตอนที่ {step + 1}...", "info")
                await page.wait_for_timeout(2000)
            else:
                await page.wait_for_timeout(1500)

        # 7. เลือกระดับการแชร์เป็น "สาธารณะ" (Public)
        public_radio = page.locator('tp-yt-paper-radio-button[name="PUBLIC"], [name="PUBLIC"]').first
        if await public_radio.count() > 0:
            await public_radio.scroll_into_view_if_needed()
            await public_radio.click(force=True)
            queue_manager.log("เลือกเผยแพร่แบบ 'สาธารณะ' (Public) เรียบร้อยแล้ว", "info")
            await page.wait_for_timeout(1500)
        else:
            public_text = page.locator('tp-yt-paper-radio-button:has-text("สาธารณะ"), tp-yt-paper-radio-button:has-text("Public")').first
            if await public_text.count() > 0:
                await public_text.scroll_into_view_if_needed()
                await public_text.click(force=True)
                queue_manager.log("เลือกเผยแพร่แบบ 'สาธารณะ' (Fallback) เรียบร้อยแล้ว", "info")
                await page.wait_for_timeout(1500)

        # 8. ตรวจสอบให้แน่ใจว่าไฟล์วิดีโออัปโหลดขึ้นเซิร์ฟเวอร์เสร็จสมบูรณ์
        queue_manager.log("กำลังตรวจสอบสถานะการอัปโหลดไฟล์ไปยัง YouTube...", "info")
        for _ in range(45):  # รอสูงสุด 90 วินาที
            done_indicator = page.locator('span:has-text("Upload complete"), span:has-text("อัปโหลดเสร็จสมบูรณ์"), span:has-text("การตรวจสอบเสร็จสิ้น"), span:has-text("Checks complete")').first
            pub_btn = page.locator('#done-button, ytcp-button#done-button').first
            
            if await done_indicator.count() > 0 and await done_indicator.is_visible():
                queue_manager.log("ไฟล์วิดีโออัปโหลดถึงเซิร์ฟเวอร์ YouTube เสร็จสมบูรณ์แล้ว!", "success")
                break
            if await pub_btn.count() > 0 and await pub_btn.is_enabled():
                break
            await page.wait_for_timeout(2000)

        # 9. กดปุ่ม เผยแพร่ (Publish / Done)
        publish_btn = page.locator('#done-button, ytcp-button#done-button').first
        if await publish_btn.count() > 0 and await publish_btn.is_visible():
            for _ in range(15):
                if await publish_btn.is_enabled():
                    break
                await page.wait_for_timeout(1000)

            await publish_btn.scroll_into_view_if_needed()
            await publish_btn.click()
            queue_manager.log("กดปุ่มเผยแพร่ (Publish) YouTube Shorts เรียบร้อยแล้ว!", "success")
        else:
            fallback_pub = page.locator('button:has-text("เผยแพร่"), button:has-text("Publish"), ytcp-button:has-text("เผยแพร่"), ytcp-button:has-text("Publish")').first
            if await fallback_pub.count() > 0:
                await fallback_pub.click()
                queue_manager.log("กดปุ่มเผยแพร่ (Publish fallback) เรียบร้อยแล้ว!", "success")
            else:
                raise Exception("ไม่พบปุ่มเผยแพร่บน YouTube Studio")

        # 9.1 ดักจับป๊อปอัปยืนยันการเผยแพร่ เช่น "เผยแพร่เลย" (Publish anyway) กรณี YouTube กำลังตรวจสอบลิขสิทธิ์/คุณภาพ
        await page.wait_for_timeout(2000)
        confirm_selectors = [
            'ytcp-confirmation-dialog #confirm-button',
            'ytcp-button#confirm-button',
            'button:has-text("เผยแพร่เลย")',
            'ytcp-button:has-text("เผยแพร่เลย")',
            'button:has-text("Publish anyway")',
            'ytcp-button:has-text("Publish anyway")',
            'tp-yt-paper-dialog #confirm-button',
            '#confirm-button'
        ]
        for sel in confirm_selectors:
            c_btn = page.locator(sel).first
            if await c_btn.count() > 0 and await c_btn.is_visible():
                queue_manager.log("⚡ พบหน้าต่างยืนยันการตรวจสอบ กำลังกด 'เผยแพร่เลย' (Publish anyway)...", "info")
                await c_btn.click()
                await page.wait_for_timeout(2000)
                break

        # 10. รอ YouTube ยืนยันการเผยแพร่อย่างเป็นทางการ (ป้องกันการปิดแท็บขณะกำลังส่งคำขอซึ่งทำให้ค้างเป็น Draft)
        queue_manager.log("กำลังรอ YouTube ยืนยันผลการเผยแพร่...", "info")
        published_confirmed = False
        for _ in range(35):  # รอสูงสุด 70 วินาที
            # เช็คซ้ำกรณีหน้าต่างยืนยัน "เผยแพร่เลย" ปรากฏขึ้นมาระหว่างประมวลผล
            for sel in confirm_selectors:
                c_btn = page.locator(sel).first
                if await c_btn.count() > 0 and await c_btn.is_visible():
                    queue_manager.log("⚡ กดปุ่มยืนยัน 'เผยแพร่เลย' (Publish anyway)...", "info")
                    await c_btn.click()
                    await page.wait_for_timeout(2000)
                    break

            share_dialog = page.locator('ytcp-video-share-dialog, ytcp-post-publish-dialog').first
            close_btn = page.locator('ytcp-video-share-dialog #close-button, ytcp-button#close-button, button[aria-label="Close"], button[aria-label="ปิด"]').first

            if await share_dialog.count() > 0 and await share_dialog.is_visible():
                published_confirmed = True
                queue_manager.log("🎉 YouTube ยืนยันการเผยแพร่คลิปเป็นสาธารณะ (Public) เรียบร้อยแล้ว!", "success")
                if await close_btn.count() > 0 and await close_btn.is_visible():
                    await close_btn.click()
                    await page.wait_for_timeout(1500)
                break

            uploads_dialog = page.locator('ytcp-uploads-dialog').first
            if await uploads_dialog.count() == 0:
                published_confirmed = True
                queue_manager.log("🎉 หน้าต่างอัปโหลดปิดแล้ว วิดีโอได้รับการเผยแพร่เรียบร้อย!", "success")
                break

            await page.wait_for_timeout(2000)

        if not published_confirmed:
            # ตรวจสอบว่ายังมีหน้าต่าง dialog ค้างอยู่หรือไม่
            for sel in confirm_selectors:
                c_btn = page.locator(sel).first
                if await c_btn.count() > 0 and await c_btn.is_visible():
                    await c_btn.click()
                    await page.wait_for_timeout(3000)
                    published_confirmed = True
                    break

            if not published_confirmed:
                raise Exception("YouTube ยังไม่ยืนยันการเผยแพร่วิดีโอ หรือค้างอยู่ที่หน้าต่างตรวจสอบ")

        return True

automation = MultiPlatformAutomation()
