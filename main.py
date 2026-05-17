"""
MechTrack Backend — Railway
WhatsApp Bridge runs separately on Render
"""

from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional, Dict
import uuid, hashlib, random, string, json, os, asyncio, httpx, re
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging

logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
load_dotenv()

# ============================================================
# APP INIT
# ============================================================

app = FastAPI(title="MechTrack API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# CONFIGURATION
# ============================================================

SHOP_NAME        = os.getenv("SHOP_NAME", "MechTrack Workshop")
WHATSAPP_BRIDGE  = os.getenv("WHATSAPP_BRIDGE_URL", "https://whatsapp-bridge-7n8j.onrender.com")
WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "true").lower() == "true"
LICENSE_FILE     = "licenses.json"
JOBS_FILE        = "jobs.json"

STATUS_LABELS = {
    "received":      "✅ Vehicle Received",
    "diagnosing":    "🔍 Under Diagnosis",
    "waiting_parts": "⏳ Waiting for Parts",
    "in_progress":   "🔧 Work In Progress",
    "quality_check": "🔎 Quality Check",
    "ready":         "🎉 Ready for Pickup",
    "delivered":     "✔️ Delivered",
}
VALID_STATUSES = list(STATUS_LABELS.keys())

jobs_db: Dict[str, Dict] = {}
job_counter = 1

# ============================================================
# PERSISTENCE
# ============================================================

def load_jobs_from_disk():
    global jobs_db, job_counter
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r") as f:
                data = json.load(f)
                jobs_db = data.get("jobs", {})
                job_counter = data.get("job_counter", 1)
                print(f"✅ Loaded {len(jobs_db)} jobs from disk")
        except Exception as e:
            print(f"⚠️ Error loading jobs: {e}")
            jobs_db = {}
            job_counter = 1
    else:
        jobs_db = {}
        job_counter = 1

def save_jobs_to_disk():
    try:
        with open(JOBS_FILE, "w") as f:
            json.dump({
                "jobs": jobs_db,
                "job_counter": job_counter,
                "last_saved": datetime.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving jobs: {e}")

load_jobs_from_disk()

# ============================================================
# LICENSE HELPERS
# ============================================================

def load_licenses() -> Dict:
    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_licenses(licenses: Dict):
    with open(LICENSE_FILE, "w") as f:
        json.dump(licenses, f, indent=2)

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def generate_license_key() -> str:
    chars = string.ascii_uppercase + string.digits
    parts = ["".join(random.choices(chars, k=4)) for _ in range(3)]
    return f"MECH-{'-'.join(parts)}"

LICENSE_PRICES = {1: 999, 3: 2999, 6: 4999, 12: 7999}

DEMO_KEYS = {
    "MECH-DEMO-2024-001": {"client_name": "Demo Workshop", "days": 365},
    "MECH-TEST-0000-0001": {"client_name": "Test Garage", "days": 90},
}

# ============================================================
# LICENSE MODELS
# ============================================================

class LicenseGenerate(BaseModel):
    client_name: str
    client_email: str
    duration_months: int = 1

class LicenseVerify(BaseModel):
    license_key: str

# ============================================================
# LICENSE ENDPOINTS
# ============================================================

@app.post("/api/license/generate")
async def generate_license(data: LicenseGenerate):
    try:
        licenses = load_licenses()
        key = generate_license_key()
        issued = datetime.now()
        expiry = issued + timedelta(days=data.duration_months * 30)
        price = LICENSE_PRICES.get(data.duration_months, 999)
        licenses[key] = {
            "license_key": key,
            "license_key_hash": hash_key(key),
            "client_name": data.client_name,
            "client_email": data.client_email,
            "issued_date": issued.isoformat(),
            "expiry_date": expiry.isoformat(),
            "duration_months": data.duration_months,
            "price": price,
            "is_active": True,
            "created_at": issued.isoformat(),
        }
        save_licenses(licenses)
        return {"success": True, "license_key": key, "client_name": data.client_name,
                "expiry_date": expiry.isoformat(), "price": price}
    except Exception as e:
        raise HTTPException(500, f"Failed to generate license: {str(e)}")

@app.post("/api/license/verify")
async def verify_license(data: LicenseVerify):
    try:
        key = data.license_key.strip().upper()
        licenses = load_licenses()
        if key in licenses:
            lic = licenses[key]
            expiry = datetime.fromisoformat(lic["expiry_date"])
            days_left = (expiry - datetime.now()).days
            if expiry < datetime.now():
                return {"valid": False, "message": f"License expired on {expiry.strftime('%Y-%m-%d')}"}
            return {"valid": True, "license_key": key, "client_name": lic.get("client_name"),
                    "expiry_date": lic.get("expiry_date"), "days_left": days_left}
        if key in DEMO_KEYS:
            demo = DEMO_KEYS[key]
            return {"valid": True, "license_key": key, "client_name": demo["client_name"],
                    "days_left": demo["days"], "message": "Demo license"}
        return {"valid": False, "message": "Invalid license key"}
    except Exception as e:
        raise HTTPException(500, f"License verification failed: {str(e)}")

@app.get("/api/licenses")
async def get_all_licenses():
    return list(load_licenses().values())

@app.delete("/api/license/{license_key}")
async def delete_license(license_key: str):
    licenses = load_licenses()
    if license_key not in licenses:
        raise HTTPException(404, "License not found")
    del licenses[license_key]
    save_licenses(licenses)
    return {"success": True}

@app.get("/api/license/stats")
async def license_stats():
    licenses = load_licenses()
    now = datetime.now()
    active, revenue = 0, 0
    for lic in licenses.values():
        try:
            if datetime.fromisoformat(lic.get("expiry_date", "")) > now:
                active += 1
            revenue += lic.get("price", 0)
        except Exception:
            continue
    return {"total": len(licenses), "active": active, "expired": len(licenses) - active, "revenue": revenue}

# ============================================================
# WHATSAPP — SEND MESSAGE
# ============================================================

async def send_whatsapp(phone: str, message: str) -> bool:
    if not WHATSAPP_ENABLED:
        print("⚠️ WhatsApp disabled")
        return False
    try:
        clean = re.sub(r"\D", "", phone)
        if len(clean) == 10:
            clean = "91" + clean
        elif len(clean) == 11 and clean.startswith("0"):
            clean = "91" + clean[1:]
        if len(clean) != 12 or not clean.startswith("91"):
            print(f"⚠️ Invalid phone: {phone} → {clean}")
            return False

        bridge = WHATSAPP_BRIDGE.rstrip("/")
        print(f"📱 Sending to {clean} via {bridge}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Health check first
            try:
                h = await client.get(f"{bridge}/health", timeout=10.0)
                health = h.json()
                print(f"🔍 Bridge health: {health}")
                if not health.get("ready"):
                    print("⚠️ Bridge not ready — message not sent")
                    return False
            except Exception as e:
                print(f"⚠️ Health check failed: {e}")
                return False

            # Send message
            r = await client.post(
                f"{bridge}/send-message",
                json={"phone": clean, "message": message},
                timeout=60.0
            )
            print(f"📤 Result: {r.status_code} — {r.text}")
            return r.status_code == 200

    except Exception as e:
        print(f"⚠️ send_whatsapp error: {e}")
        return False

# ============================================================
# WHATSAPP ENDPOINTS
# ============================================================

@app.get("/whatsapp/status")
@app.get("/whatsapp/status/simple")
@app.get("/whatsapp-status")
async def whatsapp_status():
    """Check if WhatsApp bridge on Render is connected"""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE.rstrip('/')}/health")
            data = r.json()
            return {
                "connected": data.get("ready", False),
                "ready": data.get("ready", False),
                "connecting": data.get("connecting", False),
                "bridge_url": WHATSAPP_BRIDGE,
            }
    except Exception as e:
        return {"connected": False, "ready": False, "connecting": False, "error": str(e)}

@app.get("/whatsapp/bridge-url")
async def get_bridge_url():
    return {"bridge_url": WHATSAPP_BRIDGE, "whatsapp_enabled": WHATSAPP_ENABLED}

@app.post("/whatsapp/test-send")
async def test_send(request: Request):
    """Test sending a WhatsApp message"""
    try:
        body = await request.json()
        phone = body.get("phone", "")
        message = body.get("message", "🔧 MechTrack test message!")
        if not phone:
            return {"success": False, "error": "Phone number required"}
        result = await send_whatsapp(phone, message)
        return {
            "success": result,
            "phone": phone,
            "bridge_url": WHATSAPP_BRIDGE,
            "message": "Sent!" if result else "Failed — check Railway logs"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/whatsapp/disconnect")
async def whatsapp_disconnect():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{WHATSAPP_BRIDGE.rstrip('/')}/disconnect")
            return {"success": r.status_code == 200}
    except Exception:
        return {"success": False}

@app.post("/whatsapp/reset")
async def whatsapp_reset():
    """Reset bridge — clears session and generates new QR"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{WHATSAPP_BRIDGE.rstrip('/')}/reset")
            return {"success": r.status_code == 200, "message": "Bridge reset — new QR generating"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================
# MESSAGE TEMPLATES
# ============================================================

def build_message(job: Dict, msg_type: str, update_msg: str = "") -> str:
    cost = f"₹{job['estimated_cost']:,.0f}" if job.get("estimated_cost") else "To be confirmed"
    delivery = job.get("estimated_delivery") or "To be confirmed"
    vehicle = f"{job.get('vehicle_make') or ''} {job.get('vehicle_model') or ''}".strip()

    if msg_type == "intake":
        return (
            f"🔧 *{SHOP_NAME}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Hello *{job['customer_name']}*!\n\n"
            f"Your vehicle has been received at our workshop.\n\n"
            f"📋 *Job Details*\n"
            f"• Job No: *{job['job_number']}*\n"
            f"• Vehicle: {vehicle or job['vehicle_number']}\n"
            f"• Reg No: {job['vehicle_number']}\n"
            f"• Issue: {job['complaint']}\n\n"
            f"💰 Estimated Cost: {cost}\n"
            f"📅 Expected Delivery: {delivery}\n\n"
            f"We'll keep you updated! 🙏"
        )
    elif msg_type == "ready":
        final = f"₹{job['final_cost']:,.0f}" if job.get("final_cost") else "Please contact us"
        return (
            f"🎉 *{SHOP_NAME}* — Ready for Pickup!\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Hello *{job['customer_name']}*!\n\n"
            f"Your vehicle is *ready for pickup*! 🚗✨\n\n"
            f"📋 Job: *{job['job_number']}*\n"
            f"🚗 Vehicle: {job['vehicle_number']}\n"
            f"💰 Total Amount: {final}\n\n"
            f"📍 Please visit our workshop to collect your vehicle.\n\n"
            f"Thank you for your patience! 🙏"
        )
    else:
        label = STATUS_LABELS.get(job.get("status", ""), job.get("status", "Updated"))
        return (
            f"🔧 *{SHOP_NAME}* — Status Update\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Hello *{job['customer_name']}*!\n\n"
            f"📋 Job: *{job['job_number']}*\n"
            f"🚗 Vehicle: {job['vehicle_number']}\n"
            f"📍 Status: *{label}*\n\n"
            f"💬 {update_msg}\n\n"
            f"Thank you for choosing us! 🙏"
        )

# ============================================================
# JOB MODELS
# ============================================================

class JobCreate(BaseModel):
    customer_name: str
    customer_phone: str
    vehicle_number: str
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    complaint: str
    estimated_cost: Optional[float] = None
    estimated_delivery: Optional[str] = None
    assigned_mechanic: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("customer_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if len(re.sub(r"\D", "", v)) < 10:
            raise ValueError("Phone must be at least 10 digits")
        return v

class StatusUpdate(BaseModel):
    status: str
    message: str
    diagnosis: Optional[str] = None
    work_done: Optional[str] = None
    parts_used: Optional[str] = None
    final_cost: Optional[float] = None
    estimated_delivery: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(VALID_STATUSES)}")
        return v

# ============================================================
# JOB ENDPOINTS
# ============================================================

@app.post("/jobs")
async def create_job(data: JobCreate):
    global job_counter
    try:
        job_id = str(uuid.uuid4())
        job_number = f"JOB-{datetime.now().year}-{str(job_counter).zfill(4)}"
        job_counter += 1
        job = {
            "id": job_id,
            "job_number": job_number,
            "customer_name": data.customer_name,
            "customer_phone": data.customer_phone,
            "vehicle_number": data.vehicle_number.upper(),
            "vehicle_make": data.vehicle_make,
            "vehicle_model": data.vehicle_model,
            "complaint": data.complaint,
            "estimated_cost": data.estimated_cost,
            "estimated_delivery": data.estimated_delivery,
            "assigned_mechanic": data.assigned_mechanic,
            "notes": data.notes,
            "status": "received",
            "diagnosis": None,
            "work_done": None,
            "parts_used": None,
            "final_cost": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "updates": [],
        }
        jobs_db[job_id] = job
        save_jobs_to_disk()
        asyncio.create_task(send_whatsapp(data.customer_phone, build_message(job, "intake")))
        return job
    except Exception as e:
        raise HTTPException(500, f"Failed to create job: {str(e)}")

@app.get("/jobs")
async def get_jobs():
    return sorted(jobs_db.values(), key=lambda j: j["created_at"], reverse=True)

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(404, "Job not found")
    return jobs_db[job_id]

@app.patch("/jobs/{job_id}/status")
async def update_status(job_id: str, data: StatusUpdate):
    if job_id not in jobs_db:
        raise HTTPException(404, "Job not found")
    try:
        job = jobs_db[job_id]
        old_status = job["status"]
        job["status"] = data.status
        job["updated_at"] = datetime.now().isoformat()
        if data.diagnosis: job["diagnosis"] = data.diagnosis
        if data.work_done: job["work_done"] = data.work_done
        if data.parts_used: job["parts_used"] = data.parts_used
        if data.final_cost: job["final_cost"] = data.final_cost
        if data.estimated_delivery: job["estimated_delivery"] = data.estimated_delivery
        job["updates"].append({
            "old_status": old_status,
            "status": data.status,
            "message": data.message,
            "created_at": datetime.now().isoformat(),
        })
        save_jobs_to_disk()
        msg_type = "ready" if data.status == "ready" else "update"
        asyncio.create_task(send_whatsapp(job["customer_phone"], build_message(job, msg_type, data.message)))
        return {"success": True, "status": data.status}
    except Exception as e:
        raise HTTPException(500, f"Failed to update status: {str(e)}")

@app.get("/stats")
async def get_stats():
    vals = list(jobs_db.values())
    return {
        "total": len(vals),
        "active": sum(1 for j in vals if j["status"] != "delivered"),
        "ready": sum(1 for j in vals if j["status"] == "ready"),
        "waiting_parts": sum(1 for j in vals if j["status"] == "waiting_parts"),
        "delivered": sum(1 for j in vals if j["status"] == "delivered"),
    }

# ============================================================
# HEALTH & UTILITY
# ============================================================

@app.get("/")
async def root():
    return {
        "status": "✅ MechTrack API Running",
        "shop": SHOP_NAME,
        "bridge": WHATSAPP_BRIDGE,
        "jobs": len(jobs_db),
        "time": datetime.now().isoformat(),
    }

@app.get("/ping")
async def ping():
    return {"pong": True, "time": datetime.now().isoformat()}

@app.get("/health")
async def health():
    return {"status": "healthy", "time": datetime.now().isoformat()}

@app.post("/jobs/backup")
async def backup_jobs():
    save_jobs_to_disk()
    return {"success": True, "count": len(jobs_db)}

@app.get("/jobs/export")
async def export_jobs():
    return {"export_date": datetime.now().isoformat(), "total": len(jobs_db), "jobs": list(jobs_db.values())}

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    print(f"\n{'='*50}")
    print(f"🔧 MechTrack API — {SHOP_NAME}")
    print(f"📱 Bridge  : {WHATSAPP_BRIDGE}")
    print(f"{'='*50}\n")
    uvicorn.run("app:app", host="0.0.0.0", port=4321, reload=True)
