# 🔧 MechTrack — Mechanic Shop Management App
WhatsApp-powered vehicle service tracker. Admin panel only — customers get all updates on WhatsApp automatically.

---

## 📁 File Structure
```
mechanic-app/
├── supabase_schema.sql   ← Run in Supabase SQL Editor
├── main.py               ← FastAPI backend
├── admin.html            ← Admin panel (open in browser)
├── .env.example          ← Copy to .env and fill in values
└── README.md
```

---

## ⚙️ Setup — Step by Step

### 1. Supabase
1. Go to https://supabase.com → Create new project
2. Go to **SQL Editor** → paste & run `supabase_schema.sql`
3. Go to **Storage** → New bucket → name: `vehicle-images` → toggle **Public ON**
4. Go to **Settings → API** → copy:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` key (secret) → `SUPABASE_SERVICE_KEY`

### 2. Twilio WhatsApp
1. Sign up at https://www.twilio.com
2. Go to **Messaging → Try it out → Send a WhatsApp message**
3. Note your **Sandbox number** (e.g. `whatsapp:+14155238886`)
4. Copy from Twilio Console:
   - Account SID → `TWILIO_ACCOUNT_SID`
   - Auth Token → `TWILIO_AUTH_TOKEN`
5. For production: apply for a WhatsApp-approved sender number

### 3. Backend
```bash
pip install fastapi uvicorn python-dotenv httpx python-multipart

# Create .env file
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, TWILIO_* values

# Run
uvicorn main:app --reload --port 8000
```

### 4. Admin Panel
- Simply open `admin.html` in your browser
- Make sure the backend (`localhost:8000`) is running
- That's it! No build step needed.

---

## 📲 WhatsApp Messages Sent Automatically

| Event | Message Type |
|-------|-------------|
| New job created | Intake message with job number, vehicle, complaint, est. cost & delivery |
| Status → Diagnosing / In Progress / etc. | Status update with custom message |
| Status → Ready for pickup | Special "vehicle ready" message with final amount |
| Status → Delivered | Full invoice message with work done, parts, total |

---

## 🔄 Status Flow
```
received → diagnosing → waiting_parts → in_progress → quality_check → ready → delivered
```
Each status change sends a WhatsApp to the customer automatically.

---

## 🚀 Production Tips
- Deploy backend to **Railway / Render / EC2**
- Set `allow_origins` in CORS to your actual domain
- Use Supabase RLS with proper auth for security
- Get a dedicated WhatsApp Business number from Twilio
- Set `SHOP_NAME` in `.env` to your actual shop name
