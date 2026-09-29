import os
import sys
import time
import subprocess
import threading
import asyncio
import uvicorn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_PROFILE = os.path.join(BASE_DIR, "browser_profiles", "shared_user_profile")
os.makedirs(SHARED_PROFILE, exist_ok=True)

def get_chrome_exe():
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

def open_browser():
    time.sleep(1.5)
    chrome_exe = get_chrome_exe()
    print(f"กำลังเปิด Google Chrome: {chrome_exe}")
    
    # เปิด Google Chrome เท่านั้น พร้อมพอร์ต 9222 เพื่อให้ทุกอย่างทำงานเป็นแท็บใหม่ในหน้าต่างนี้เสมอ
    cmd = [
        chrome_exe,
        "--remote-debugging-port=9222",
        f"--user-data-dir={SHARED_PROFILE}",
        "http://127.0.0.1:8000"
    ]
    try:
        subprocess.Popen(cmd)
    except Exception as e:
        print(f"ไม่สามารถเปิด Chrome โดยตรงได้ กำลังลองใช้คำสั่งเริ่มต้น: {e}")
        try:
            os.system(f'start chrome "http://127.0.0.1:8000"')
        except Exception:
            import webbrowser
            webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    print("=" * 60)
    print("  Multi-Platform Video Auto-Poster (Google Chrome Only)")
    print("=" * 60)
    print("กำลังเริ่มระบบและเปิด Google Chrome พร้อมโหมดแท็บเดียว...")
    
    # เปิด Chrome เฉพาะตอนเริ่มโปรเซสหลัก (ไม่เปิดซ้ำตอน reload โค้ด)
    if not os.environ.get("UVICORN_RELOAD"):
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        uvicorn.run(
            "app:app",
            host="127.0.0.1",
            port=8000,
            reload=True,
            reload_includes=["*.py", "*.html", "*.js"],
            reload_excludes=["uploads/*", "browser_profiles/*", "static/voice_samples/*", "data/*", "*.mp4", "*.png", "*.jpg", "*.mp3"],
            loop="asyncio.windows_events:ProactorEventLoop",
            log_level="info"
        )
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการรันเซิร์ฟเวอร์: {e}")
        input("กด Enter เพื่อออก...")
