"""
MechTrack Backend — Railway
WhatsApp Bridge runs separately on Render
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional, Dict
import uuid
import hashlib
import random
import string
import json
import os
import asyncio
import httpx
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ============================================================
# APP INIT
# ============================================================

app = FastAPI(title="MechTrack API", version="2.0.0")

# CORS - Allow all for testing
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

SHOP_NAME = os.getenv("SHOP_NAME", "MechTrack Workshop")
WHATSAPP_BRIDGE = os.getenv("WHATSAPP_BRIDGE_URL", "https://whatsapp-bridge-7n8j.onrender.com")
WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "true").lower() == "true"
LICENSE_FILE = "licenses.json"
JOBS_FILE = "jobs.json"

STATUS_LABELS = {
    "received": "✅ Vehicle Received",
    "diagnosing": "🔍 Under Diagnosis",
    "waiting_parts": "⏳ Waiting for Parts",
    "in_progress": "🔧 Work In Progress",
    "quality_check": "🔎 Quality Check",
    "ready": "🎉 Ready for Pickup",
    "delivered": "✔️ Delivered",
}
VALID_STATUSES = list(STATUS_LABELS.keys())

# In-memory storage
jobs_db: Dict[str, Dict] = {}
job_counter = 1

# WhatsApp QR storage
current_qr_code = None
qr_timestamp = None
qr_expiry = None

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
                logger.info(f"Loaded {len(jobs_db)} jobs from disk")
        except Exception as e:
            logger.error(f"Error loading jobs: {e}")
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
        logger.error(f"Error saving jobs: {e}")

# Load existing data
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
            "license_key_hash": hashlib.sha256(key.encode()).hexdigest(),
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
        logger.info("WhatsApp disabled")
        return False
    try:
        clean = re.sub(r"\D", "", phone)
        if len(clean) == 10:
            clean = "91" + clean
        elif len(clean) == 11 and clean.startswith("0"):
            clean = "91" + clean[1:]
        if len(clean) != 12 or not clean.startswith("91"):
            logger.warning(f"Invalid phone: {phone} -> {clean}")
            return False

        bridge = WHATSAPP_BRIDGE.rstrip("/")
        logger.info(f"Sending to {clean} via {bridge}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                h = await client.get(f"{bridge}/health", timeout=10.0)
                health = h.json()
                if not health.get("ready"):
                    logger.warning("Bridge not ready")
                    return False
            except Exception as e:
                logger.warning(f"Health check failed: {e}")
                return False

            r = await client.post(
                f"{bridge}/send-message",
                json={"phone": clean, "message": message},
                timeout=30.0
            )
            return r.status_code == 200
    except Exception as e:
        logger.error(f"send_whatsapp error: {e}")
        return False

# ============================================================
# WHATSAPP ENDPOINTS
# ============================================================

@app.get("/whatsapp/status")
async def whatsapp_status():
    """Check WhatsApp bridge status"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE.rstrip('/')}/health")
            data = r.json()
            return {
                "ready": data.get("ready", False),
                "connecting": data.get("connecting", False),
                "bridge_url": WHATSAPP_BRIDGE,
                "qr_available": current_qr_code is not None
            }
    except Exception as e:
        return {
            "ready": False,
            "connecting": False,
            "error": str(e),
            "bridge_url": WHATSAPP_BRIDGE,
            "qr_available": current_qr_code is not None
        }

@app.post("/whatsapp/push-qr")
async def push_qr(request: Request):
    """Receive QR from Render bridge"""
    global current_qr_code, qr_timestamp, qr_expiry
    try:
        body = await request.json()
        qr_data = body.get("qr")
        if qr_data:
            current_qr_code = qr_data
            qr_timestamp = datetime.now()
            qr_expiry = datetime.now() + timedelta(minutes=5)
            logger.info(f"QR received at {qr_timestamp}")
            return {"success": True, "timestamp": qr_timestamp.isoformat()}
        return {"success": False, "message": "No QR data"}
    except Exception as e:
        logger.error(f"QR push error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/whatsapp/qr")
async def get_qr_json():
    """JSON endpoint for QR"""
    global current_qr_code, qr_expiry
    
    if not current_qr_code:
        return {"qr": None, "ready": False, "message": "No QR available"}
    
    if qr_expiry and datetime.now() > qr_expiry:
        return {"qr": None, "ready": False, "expired": True, "message": "QR expired"}
    
    return {
        "qr": current_qr_code,
        "ready": False,
        "expires_at": qr_expiry.isoformat() if qr_expiry else None,
        "age_seconds": (datetime.now() - qr_timestamp).seconds if qr_timestamp else 0
    }

@app.get("/whatsapp/qr-info")
async def get_qr_info():
    """Get QR metadata without the actual QR code"""
    global current_qr_code, qr_timestamp, qr_expiry
    
    return {
        "available": current_qr_code is not None,
        "timestamp": qr_timestamp.isoformat() if qr_timestamp else None,
        "expires_at": qr_expiry.isoformat() if qr_expiry else None,
        "expired": qr_expiry and datetime.now() > qr_expiry if qr_expiry else False,
        "age_seconds": (datetime.now() - qr_timestamp).seconds if qr_timestamp else 0,
        "time_to_live": (qr_expiry - datetime.now()).seconds if qr_expiry and datetime.now() < qr_expiry else 0
    }

@app.post("/whatsapp/bridge-ready")
async def bridge_ready(request: Request):
    """Receive ready status from bridge"""
    try:
        body = await request.json()
        logger.info(f"Bridge ready: {body}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Bridge ready error: {e}")
        return {"success": False}

@app.post("/whatsapp/reset")
async def whatsapp_reset():
    """Reset bridge connection"""
    global current_qr_code, qr_timestamp, qr_expiry
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{WHATSAPP_BRIDGE.rstrip('/')}/reset")
            current_qr_code = None
            qr_timestamp = None
            qr_expiry = None
            logger.info("QR storage cleared")
            return {"success": True}
    except Exception as e:
        logger.error(f"Reset error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/whatsapp/test-send")
async def test_send(request: Request):
    """Test sending message"""
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
            "message": "Sent!" if result else "Failed"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/whatsapp/bridge-url")
async def get_bridge_url():
    return {"bridge_url": WHATSAPP_BRIDGE, "whatsapp_enabled": WHATSAPP_ENABLED}

@app.post("/whatsapp/disconnect")
async def whatsapp_disconnect():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{WHATSAPP_BRIDGE.rstrip('/')}/disconnect")
            return {"success": r.status_code == 200}
    except Exception:
        return {"success": False}

# ============================================================
# MESSAGE TEMPLATES
# ============================================================

def build_message(job: Dict, msg_type: str, update_msg: str = "") -> str:
    cost = f"₹{job['estimated_cost']:,.0f}" if job.get("estimated_cost") else "TBC"
    delivery = job.get("estimated_delivery") or "TBC"
    vehicle = f"{job.get('vehicle_make', '')} {job.get('vehicle_model', '')}".strip()

    if msg_type == "intake":
        return (
            f"🔧 *{SHOP_NAME}*\n"
            f"Hello *{job['customer_name']}*!\n\n"
            f"Vehicle received: {vehicle or job['vehicle_number']}\n"
            f"Job #{job['job_number']}\n"
            f"Complaint: {job['complaint']}\n"
            f"Estimate: {cost}\n"
            f"Delivery: {delivery}\n\n"
            f"We'll keep you updated! 🙏"
        )
    elif msg_type == "ready":
        final = f"₹{job['final_cost']:,.0f}" if job.get("final_cost") else cost
        return (
            f"🎉 *{SHOP_NAME}*\n"
            f"Hello *{job['customer_name']}*!\n\n"
            f"Your vehicle *{job['vehicle_number']}* is READY for pickup! 🚗\n"
            f"Total: {final}\n\n"
            f"Please visit our workshop. Thank you! 🙏"
        )
    else:
        label = STATUS_LABELS.get(job.get("status", ""), "Updated")
        return (
            f"🔧 *{SHOP_NAME}*\n"
            f"Hello *{job['customer_name']}*!\n\n"
            f"Job #{job['job_number']} - {job['vehicle_number']}\n"
            f"Status: *{label}*\n"
            f"Message: {update_msg}\n\n"
            f"Thank you! 🙏"
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
            raise ValueError(f"Invalid status: {v}")
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
        
        # Send WhatsApp notification
        asyncio.create_task(send_whatsapp(data.customer_phone, build_message(job, "intake")))
        
        return job
    except Exception as e:
        logger.error(f"Create job error: {e}")
        raise HTTPException(500, str(e))

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
        
        if data.diagnosis:
            job["diagnosis"] = data.diagnosis
        if data.work_done:
            job["work_done"] = data.work_done
        if data.parts_used:
            job["parts_used"] = data.parts_used
        if data.final_cost:
            job["final_cost"] = data.final_cost
        if data.estimated_delivery:
            job["estimated_delivery"] = data.estimated_delivery
            
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
        logger.error(f"Update status error: {e}")
        raise HTTPException(500, str(e))

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

@app.post("/jobs/backup")
async def backup_jobs():
    save_jobs_to_disk()
    return {"success": True, "count": len(jobs_db)}

@app.get("/jobs/export")
async def export_jobs():
    return {"export_date": datetime.now().isoformat(), "total": len(jobs_db), "jobs": list(jobs_db.values())}

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

@app.get("/debug")
async def debug():
    """Debug endpoint to check system status"""
    return {
        "status": "running",
        "time": datetime.now().isoformat(),
        "qr_available": current_qr_code is not None,
        "qr_expired": qr_expiry and datetime.now() > qr_expiry if qr_expiry else False,
        "bridge_url": WHATSAPP_BRIDGE,
        "whatsapp_enabled": WHATSAPP_ENABLED,
        "jobs_count": len(jobs_db)
    }

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 4321))
    print(f"\n{'='*50}")
    print(f"🔧 MechTrack API — {SHOP_NAME}")
    print(f"📱 Bridge: {WHATSAPP_BRIDGE}")
    print(f"🚪 Port: {port}")
    print(f"{'='*50}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
