"""
MECHTRACK — Complete Backend with WhatsApp Integration
Port: 4321
Run: uvicorn app:app --reload --port 4321
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional, Dict, Any, List
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
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
load_dotenv()

# ============================================================
# OPTIONAL SUPABASE — comment out if not using
# ============================================================
# from supabase import create_client, Client
# supabase: Client = create_client(
#     os.getenv("SUPABASE_URL"),
#     os.getenv("SUPABASE_SERVICE_KEY")
# )

# ============================================================
# APP INIT
# ============================================================

app = FastAPI(
    title="MechTrack API",
    description="Mechanic Shop Management System with WhatsApp",
    version="2.0.0"
)

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
WHATSAPP_BRIDGE  = os.getenv("WHATSAPP_BRIDGE_URL", "http://localhost:4322")
WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "true").lower() == "true"
LICENSE_FILE     = "licenses.json"
JOBS_FILE        = "jobs.json"  # NEW: Persist jobs to disk

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

# In-memory job store (with persistence)
jobs_db: Dict[str, Dict] = {}
job_counter = 1

# ============================================================
# PERSISTENCE HELPERS (FIX: Jobs survive restart)
# ============================================================

def load_jobs_from_disk():
    """Load jobs from JSON file on startup"""
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
    """Save jobs to JSON file after each change"""
    try:
        with open(JOBS_FILE, "w") as f:
            json.dump({
                "jobs": jobs_db,
                "job_counter": job_counter,
                "last_saved": datetime.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving jobs: {e}")

# Load jobs on startup
load_jobs_from_disk()

# ============================================================
# LICENSE HELPERS (FIX: Better error handling)
# ============================================================

def load_licenses() -> Dict:
    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE, "r") as f:
                return json.load(f)
        except:
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
    return f"MECH-{parts[0]}-{parts[1]}-{parts[2]}"

LICENSE_PRICES = {1: 999, 3: 2999, 6: 4999, 12: 7999}

# Built-in demo / test keys that work even when the license file is empty
DEMO_KEYS = {
    "MECH-DEMO-2024-001": {"client_name": "Demo Workshop",  "days": 365},
    "MECH-TEST-0000-0001": {"client_name": "Test Garage",   "days": 90},
}

# ============================================================
# LICENSE MODELS
# ============================================================

class LicenseGenerate(BaseModel):
    client_name:     str
    client_email:    str
    duration_months: int = 1

class LicenseVerify(BaseModel):
    license_key: str

# ============================================================
# LICENSE ENDPOINTS (FIX: Better error handling)
# ============================================================

@app.post("/api/license/generate")
async def generate_license(data: LicenseGenerate):
    """Generate a new license key"""
    try:
        licenses = load_licenses()

        key         = generate_license_key()
        issued      = datetime.now()
        expiry      = issued + timedelta(days=data.duration_months * 30)
        price       = LICENSE_PRICES.get(data.duration_months, 999)

        licenses[key] = {
            "license_key":      key,
            "license_key_hash": hash_key(key),
            "client_name":      data.client_name,
            "client_email":     data.client_email,
            "issued_date":      issued.isoformat(),
            "expiry_date":      expiry.isoformat(),
            "duration_months":  data.duration_months,
            "price":            price,
            "is_active":        True,
            "created_at":       issued.isoformat(),
        }
        save_licenses(licenses)

        return {
            "success":        True,
            "license_key":    key,
            "client_name":    data.client_name,
            "client_email":   data.client_email,
            "expiry_date":    expiry.isoformat(),
            "duration_months": data.duration_months,
            "price":          price,
            "message":        f"License generated for {data.client_name}",
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to generate license: {str(e)}")


@app.post("/api/license/verify")
async def verify_license(data: LicenseVerify):
    """Verify a license key — checks file-based licenses first, then demo keys"""
    try:
        key      = data.license_key.strip().upper()
        licenses = load_licenses()

        # --- Check file-based licenses ---
        if key in licenses:
            lic = licenses[key]
            
            # FIX: Safe date parsing with error handling
            try:
                expiry = datetime.fromisoformat(lic["expiry_date"])
                days_left = (expiry - datetime.now()).days
            except (KeyError, ValueError) as e:
                return {"valid": False, "message": f"License data corrupted: {str(e)}"}

            if expiry < datetime.now():
                return {"valid": False, "message": f"License expired on {expiry.strftime('%Y-%m-%d')}"}

            return {
                "valid":       True,
                "license_key": key,
                "client_name": lic.get("client_name", "Unknown"),
                "client_email": lic.get("client_email", ""),
                "expiry_date": lic.get("expiry_date", ""),
                "days_left":   days_left,
                "message":     f"License valid for {days_left} more days",
            }

        # --- Fallback to built-in demo keys ---
        if key in DEMO_KEYS:
            demo = DEMO_KEYS[key]
            return {
                "valid":       True,
                "license_key": key,
                "client_name": demo["client_name"],
                "client_email": "",
                "expiry_date": (datetime.now() + timedelta(days=demo["days"])).isoformat(),
                "days_left":   demo["days"],
                "message":     "Demo license valid",
            }

        return {"valid": False, "message": "Invalid license key"}
    except Exception as e:
        raise HTTPException(500, f"License verification failed: {str(e)}")


@app.get("/api/licenses")
async def get_all_licenses():
    """Return all stored licenses"""
    try:
        return list(load_licenses().values())
    except Exception as e:
        raise HTTPException(500, f"Failed to load licenses: {str(e)}")


@app.delete("/api/license/{license_key}")
async def delete_license(license_key: str):
    try:
        licenses = load_licenses()
        if license_key not in licenses:
            raise HTTPException(404, "License not found")
        del licenses[license_key]
        save_licenses(licenses)
        return {"success": True, "message": "License deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to delete license: {str(e)}")


@app.get("/api/license/stats")
async def license_stats():
    """Get license statistics with safe error handling"""
    try:
        licenses = load_licenses()
        now = datetime.now()
        active = 0
        total_revenue = 0
        
        for l in licenses.values():
            try:
                # FIX: Safe date parsing
                if "expiry_date" in l:
                    expiry = datetime.fromisoformat(l["expiry_date"])
                    if expiry > now:
                        active += 1
                else:
                    active += 1  # Assume active if no expiry
                
                total_revenue += l.get("price", 0)
            except (KeyError, ValueError):
                # Skip corrupted entries
                continue
        
        return {
            "total":   len(licenses),
            "active":  active,
            "expired": len(licenses) - active,
            "revenue": total_revenue,
        }
    except Exception as e:
        # Return default stats instead of failing
        return {
            "total":   0,
            "active":  0,
            "expired": 0,
            "revenue": 0,
            "error": str(e)
        }

# ============================================================
# WHATSAPP HELPERS (FIX: Better error handling)
# ============================================================

async def bridge_health() -> Dict:
    """Check WhatsApp bridge /health — returns {} on failure"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE}/health")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


async def send_whatsapp(phone: str, message: str) -> bool:
    """Send a message via the local WhatsApp bridge"""
    if not WHATSAPP_ENABLED:
        return False

    try:
        clean = re.sub(r"\D", "", phone)
        if len(clean) == 10:
            clean = "91" + clean
        elif len(clean) == 12 and clean.startswith("91"):
            pass  # Already has country code
        else:
            print(f"⚠️ Invalid phone number format: {phone}")
            return False

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Confirm bridge is ready before sending
            h = await client.get(f"{WHATSAPP_BRIDGE}/health")
            if h.status_code != 200 or not h.json().get("ready"):
                print("⚠️ WhatsApp bridge not ready")
                return False

            r = await client.post(
                f"{WHATSAPP_BRIDGE}/send-message",
                json={"phone": clean, "message": message},
            )
            return r.status_code == 200
    except Exception as e:
        print(f"⚠️ Failed to send WhatsApp: {e}")
        return False

# ============================================================
# WHATSAPP ENDPOINTS
# ============================================================

@app.get("/whatsapp-status")
async def whatsapp_status():
    """Connection status used by the frontend sidebar"""
    try:
        info = await bridge_health()
        return {
            "connected":     info.get("ready", False),
            "bridge_running": info.get("status") == "ok",
            "details":       info,
        }
    except Exception as e:
        return {
            "connected": False,
            "bridge_running": False,
            "error": str(e)
        }


@app.get("/whatsapp/qr")
async def whatsapp_qr():
    """Proxy QR code from bridge to frontend"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE}/qr")
            if r.status_code == 200:
                return r.json()
            return {"qr": None, "success": False, "message": "Bridge returned an error"}
    except Exception as e:
        return {"qr": None, "success": False, "message": f"Cannot reach bridge: {e}"}


@app.post("/whatsapp/disconnect")
async def whatsapp_disconnect():
    """Tell bridge to log out"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{WHATSAPP_BRIDGE}/disconnect")
            return {"success": r.status_code == 200}
    except Exception:
        return {"success": False}


@app.get("/whatsapp-bridge-status")
async def whatsapp_bridge_status():
    """Detailed bridge diagnostic"""
    import socket
    def port_open(p):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("localhost", p))
        s.close()
        return result == 0

    running = port_open(4322)
    info    = {"port": 4322, "running": running,
               "status": "online" if running else "offline",
               "message": "Bridge running" if running else
                          "Bridge offline — start with: node whatsapp-bridge.js"}

    if running:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get("http://localhost:4322/health")
                if r.status_code == 200:
                    info["ready"]   = r.json().get("ready", False)
                    info["details"] = r.json()
        except Exception as e:
            info["ready"] = False
            info["error"] = str(e)

    return info

# ============================================================
# MESSAGE TEMPLATES
# ============================================================

def build_message(job: Dict, msg_type: str, update_msg: str = "") -> str:
    cost     = f"₹{job['estimated_cost']:,.0f}" if job.get("estimated_cost") else "To be confirmed"
    delivery = job.get("estimated_delivery") or "To be confirmed"
    vehicle  = f"{job.get('vehicle_make','') or ''} {job.get('vehicle_model','') or ''}".strip()

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
    customer_name:      str
    customer_phone:     str
    vehicle_number:     str
    vehicle_make:       Optional[str] = None
    vehicle_model:      Optional[str] = None
    complaint:          str
    estimated_cost:     Optional[float] = None
    estimated_delivery: Optional[str]   = None
    assigned_mechanic:  Optional[str]   = None
    notes:              Optional[str]   = None

    @field_validator("customer_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if len(re.sub(r"\D", "", v)) < 10:
            raise ValueError("Phone number must be at least 10 digits")
        return v


class StatusUpdate(BaseModel):
    status:             str
    message:            str
    diagnosis:          Optional[str]   = None
    work_done:          Optional[str]   = None
    parts_used:         Optional[str]   = None
    final_cost:         Optional[float] = None
    estimated_delivery: Optional[str]   = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}")
        return v

# ============================================================
# JOB ENDPOINTS (FIX: Persist jobs to disk)
# ============================================================

@app.post("/jobs")
async def create_job(data: JobCreate):
    global job_counter
    
    try:
        job_id     = str(uuid.uuid4())
        job_number = f"JOB-{datetime.now().year}-{str(job_counter).zfill(4)}"
        job_counter += 1

        job = {
            "id":                 job_id,
            "job_number":         job_number,
            "customer_name":      data.customer_name,
            "customer_phone":     data.customer_phone,
            "vehicle_number":     data.vehicle_number.upper(),
            "vehicle_make":       data.vehicle_make,
            "vehicle_model":      data.vehicle_model,
            "complaint":          data.complaint,
            "estimated_cost":     data.estimated_cost,
            "estimated_delivery": data.estimated_delivery,
            "assigned_mechanic":  data.assigned_mechanic,
            "notes":              data.notes,
            "status":             "received",
            "diagnosis":          None,
            "work_done":          None,
            "parts_used":         None,
            "final_cost":         None,
            "created_at":         datetime.now().isoformat(),
            "updated_at":         datetime.now().isoformat(),
            "updates":            [],
        }
        jobs_db[job_id] = job
        
        # Save to disk immediately
        save_jobs_to_disk()

        # Fire-and-forget WhatsApp notification
        asyncio.create_task(send_whatsapp(data.customer_phone, build_message(job, "intake")))

        return job
    except Exception as e:
        raise HTTPException(500, f"Failed to create job: {str(e)}")


@app.get("/jobs")
async def get_jobs():
    try:
        return sorted(jobs_db.values(), key=lambda j: j["created_at"], reverse=True)
    except Exception as e:
        raise HTTPException(500, f"Failed to retrieve jobs: {str(e)}")


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
        job["status"]     = data.status
        job["updated_at"] = datetime.now().isoformat()

        if data.diagnosis:          job["diagnosis"]          = data.diagnosis
        if data.work_done:          job["work_done"]          = data.work_done
        if data.parts_used:         job["parts_used"]         = data.parts_used
        if data.final_cost:         job["final_cost"]         = data.final_cost
        if data.estimated_delivery: job["estimated_delivery"] = data.estimated_delivery

        job["updates"].append({
            "old_status": old_status,
            "status":     data.status,
            "message":    data.message,
            "created_at": datetime.now().isoformat(),
        })
        
        # Save to disk
        save_jobs_to_disk()

        msg_type = "ready" if data.status == "ready" else "update"
        asyncio.create_task(send_whatsapp(job["customer_phone"], build_message(job, msg_type, data.message)))

        return {"success": True, "status": data.status, "message": "Status updated"}
    except Exception as e:
        raise HTTPException(500, f"Failed to update status: {str(e)}")


@app.get("/stats")
async def get_stats():
    try:
        vals = list(jobs_db.values())
        return {
            "total":         len(vals),
            "active":        sum(1 for j in vals if j["status"] != "delivered"),
            "ready":         sum(1 for j in vals if j["status"] == "ready"),
            "waiting_parts": sum(1 for j in vals if j["status"] == "waiting_parts"),
            "delivered":     sum(1 for j in vals if j["status"] == "delivered"),
        }
    except Exception as e:
        return {
            "total": 0,
            "active": 0,
            "ready": 0,
            "waiting_parts": 0,
            "delivered": 0,
            "error": str(e)
        }

# ============================================================
# GENERAL HEALTH
# ============================================================

@app.get("/")
async def root():
    try:
        info = await bridge_health()
        return {
            "status":             "✅ MechTrack API Running",
            "shop_name":          SHOP_NAME,
            "whatsapp_connected": info.get("ready", False),
            "version":            "2.0.0",
            "port":               4321,
            "jobs_count":         len(jobs_db),
            "timestamp":          datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "status": "⚠️ Running with errors",
            "error": str(e)
        }


@app.get("/ping")
async def ping():
    return {"pong": True, "timestamp": datetime.now().isoformat(), "port": 4321, "status": "alive"}


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# ============================================================
# ADDITIONAL UTILITY ENDPOINTS
# ============================================================

@app.post("/jobs/backup")
async def backup_jobs():
    """Manually trigger a backup of all jobs"""
    try:
        save_jobs_to_disk()
        return {"success": True, "message": "Jobs backed up successfully", "count": len(jobs_db)}
    except Exception as e:
        raise HTTPException(500, f"Backup failed: {str(e)}")


@app.get("/jobs/export")
async def export_jobs():
    """Export all jobs as JSON"""
    try:
        return {
            "export_date": datetime.now().isoformat(),
            "total_jobs": len(jobs_db),
            "jobs": list(jobs_db.values())
        }
    except Exception as e:
        raise HTTPException(500, f"Export failed: {str(e)}")

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 50)
    print("🔧 MechTrack API Server (FIXED VERSION)")
    print("=" * 50)
    print(f"🏪 Shop  : {SHOP_NAME}")
    print(f"📍 API   : http://localhost:4321")
    print(f"📊 Docs  : http://localhost:4321/docs")
    print(f"📱 Bridge: {WHATSAPP_BRIDGE}")
    print(f"💾 Jobs  : {JOBS_FILE}")
    print(f"📋 License: {LICENSE_FILE}")
    print("=" * 50 + "\n")
    uvicorn.run("app:app", host="0.0.0.0", port=4321, reload=True)