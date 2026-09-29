# 🚀 Multi-Platform Video Auto-Poster & AI Video Studio (Facebook Reels / TikTok / YouTube Shorts)

ระบบจัดการและสร้างวิดีโออัตโนมัติครบวงจร All-in-One: ควบคุมเบราว์เซอร์อัตโนมัติ (Playwright) เพื่อโพสต์คลิปสั้นลง **Facebook Reels**, **TikTok** และ **YouTube Shorts** พร้อมปักตะกร้าสินค้า รวมถึงสตูดิโอสร้างคลิปวิดีโอ AI อัจฉริยะ (AI Presenter Studio, Origin Story Documentary Studio และ AI Image Generator)

---

## ✨ ฟีเจอร์หลัก (Features)

### 1. 🤖 AI Video Studio & Documentary Creator
* **📜 สตูดิโอสารคดีสั้น & จุดกำเนิดสินค้า (Origin Story Studio):**
  - สร้างคลิปสั้นแนวประวัติศาสตร์/ต้นกำเนิดสุดน่าสนใจ (แบบ Full-bleed 9:16 เต็มจอ 100% ไร้กรอบดำ)
  - แอบปักตะกร้าสินค้าแบบ Soft-selling แนบเนียน เพิ่มยอดขายและผู้ติดตาม
  - ซูมภาพเปิดตัวแบบ Cinematic Ken Burns สวยงาม คมชัด ตัวหนังสือวางบนภาพสบายตา
* **🎙️ ระบบเสียงพากย์ AI รองรับทั้ง Gemini Voice & Edge Neural:**
  - รองรับเสียงจาก Gemini (`Charon`, `Fenrir`, `Puck`, `Aoede`, `Kore`) และ Edge Neural ภาษาไทย
  - มีปุ่ม **🔊 ฟังตัวอย่างเสียง** ให้กดเทสฟังเสียงแต่ละคนก่อนสร้างคลิปจริง
* **🎨 ระบบสร้างภาพ AI อัตโนมัติ (AI Image Generator):**
  - สั่งเจนรูปตามคีย์เวิร์ดทีละ 3 ภาพที่แตกต่างกัน สัดส่วน 9:16 เพื่อนำไปใช้ตัดต่อสารคดีได้ทันที
* **👩‍💼 AI Presenter Studio:**
  - สตูดิโอผู้ดำเนินรายการ AI ขยับปาก กะพริบตา โยกตัวตามเสียงพากย์จริง

### 2. 📲 Multi-Platform Cross-Posting & Browser Automation
* **🔵 Facebook Reels:** โพสต์ผ่าน Meta Business Suite พร้อมปักตะกร้าสินค้า/คอมเมนต์ลิงก์สินค้าอัตโนมัติ
* **🎵 TikTok:** โพสต์ผ่าน TikTok Creator Center พร้อมแคปชั่น แฮชแท็ก #fyp และลิงก์สินค้า
* **🔴 YouTube Shorts:** โพสต์ผ่าน YouTube Studio ตั้งค่าแท็ก #Shorts คำอธิบาย และการตั้งค่าเด็กให้อัตโนมัติ
* **โหมดเปิดแท็บเดียว (New Tab Mode):** ทุกการทำงานจะเปิดเป็นแท็บใหม่ใน Google Chrome ไม่เปิดหน้าต่างซ้ำซ้อน

---

## 🛠️ การติดตั้งและเริ่มต้นใช้งาน (Getting Started)

### 1. ความต้องการของระบบ (Requirements)
* Python 3.10 ขึ้นไป
* Google Chrome
* FFmpeg (ติดตั้งในระบบและตั้งค่า PATH แล้ว)

### 2. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. เริ่มต้นใช้งาน (Run Application)
ดับเบิลคลิกไฟล์:
```bash
run_app.bat
```
หรือรันผ่าน Terminal:
```bash
python run.py
```
> ระบบจะเปิดหน้า Web Dashboard ที่ `http://localhost:8000` ให้อัตโนมัติ

---

## 📖 โครงสร้างโปรเจกต์ (Project Structure)
```
fb-video-pin/
├── assets/                  # ฟอนต์ไทย, BGM, ธีม และกราฟิกสำหรับวิดีโอ
├── static/                  # สไตล์ชีท และไฟล์เสียงตัวอย่างพากย์ (Voice Samples)
├── templates/
│   └── index.html           # หน้า Web Dashboard ครบวงจร
├── uploads/                 # โฟลเดอร์เก็บวิดีโอและรูปภาพ (ถูก ignore ใน git)
├── ai_creator.py            # เอนจินสร้างวิดีโอ AI, สารคดีสั้น, Gemini TTS และ Ken Burns
├── automation.py            # Playwright Automation สำหรับ FB, TikTok, YouTube
├── queue_manager.py         # ตัวจัดการคิวงานโพสต์และการตั้งค่า
├── worker.py                # Background Worker ประมวลผลคิวโพสต์
├── app.py                   # FastAPI Web Server
├── run.py                   # สคริปต์เริ่มระบบและเปิด Chrome
├── requirements.txt         # รายการแพ็กเกจ Python
└── README.md
```

---

## 🔒 ความปลอดภัย (Security & Privacy)
* โฟลเดอร์ `browser_profiles/` (คุกกี้และเซสชันล็อกอิน) และ `data/config.json` (API Keys) ได้รับการตั้งค่าใน `.gitignore` เพื่อป้องกันการอัปโหลดข้อมูลส่วนตัวขึ้นสู่ GitHub สาธารณะโดยเด็ดขาด
