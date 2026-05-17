"""MECHTRACK — Complete Backend with On-Demand WhatsApp Bridge
Port: 4321
Run: python app.py
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response as FastAPIResponse
from starlette.middleware.cors import CORSMiddleware
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
import subprocess
import signal
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging

logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
load_dotenv()

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

# In-memory job store (with persistence)
jobs_db: Dict[str, Dict] = {}
job_counter = 1

# Bridge process management
bridge_process = None
bridge_pid = None

# In-memory QR store (pushed from PC bridge)
whatsapp_qr_store = {"qr": None, "updated_at": None}

# ============================================================
# PERSISTENCE HELPERS
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
    return f"MECH-{parts[0]}-{parts[1]}-{parts[2]}"


LICENSE_PRICES = {1: 999, 3: 2999, 6: 4999, 12: 7999}

# Built-in demo / test keys
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
    """Generate a new license key"""
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

        return {
            "success": True,
            "license_key": key,
            "client_name": data.client_name,
            "client_email": data.client_email,
            "expiry_date": expiry.isoformat(),
            "duration_months": data.duration_months,
            "price": price,
            "message": f"License generated for {data.client_name}",
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to generate license: {str(e)}")


@app.post("/api/license/verify")
async def verify_license(data: LicenseVerify):
    """Verify a license key"""
    try:
        key = data.license_key.strip().upper()
        licenses = load_licenses()

        if key in licenses:
            lic = licenses[key]
            try:
                expiry = datetime.fromisoformat(lic["expiry_date"])
                days_left = (expiry - datetime.now()).days
            except (KeyError, ValueError) as e:
                return {"valid": False, "message": f"License data corrupted: {str(e)}"}

            if expiry < datetime.now():
                return {"valid": False, "message": f"License expired on {expiry.strftime('%Y-%m-%d')}"}

            return {
                "valid": True,
                "license_key": key,
                "client_name": lic.get("client_name", "Unknown"),
                "client_email": lic.get("client_email", ""),
                "expiry_date": lic.get("expiry_date", ""),
                "days_left": days_left,
                "message": f"License valid for {days_left} more days",
            }

        if key in DEMO_KEYS:
            demo = DEMO_KEYS[key]
            return {
                "valid": True,
                "license_key": key,
                "client_name": demo["client_name"],
                "client_email": "",
                "expiry_date": (datetime.now() + timedelta(days=demo["days"])).isoformat(),
                "days_left": demo["days"],
                "message": "Demo license valid",
            }

        return {"valid": False, "message": "Invalid license key"}
    except Exception as e:
        raise HTTPException(500, f"License verification failed: {str(e)}")


@app.get("/api/licenses")
async def get_all_licenses():
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
    try:
        licenses = load_licenses()
        now = datetime.now()
        active = 0
        total_revenue = 0

        for lic in licenses.values():
            try:
                if "expiry_date" in lic:
                    expiry = datetime.fromisoformat(lic["expiry_date"])
                    if expiry > now:
                        active += 1
                else:
                    active += 1
                total_revenue += lic.get("price", 0)
            except (KeyError, ValueError):
                continue

        return {
            "total": len(licenses),
            "active": active,
            "expired": len(licenses) - active,
            "revenue": total_revenue,
        }
    except Exception as e:
        return {"total": 0, "active": 0, "expired": 0, "revenue": 0, "error": str(e)}

# ============================================================
# WHATSAPP HELPERS
# ============================================================

async def bridge_health() -> Dict:
    """Check WhatsApp bridge health"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE}/health")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


async def send_whatsapp(phone: str, message: str) -> bool:
    """Send a message via WhatsApp bridge (Render)"""
    if not WHATSAPP_ENABLED:
        print("⚠️ WhatsApp disabled via env")
        return False

    try:
        clean = re.sub(r"\D", "", phone)
        if len(clean) == 10:
            clean = "91" + clean
        elif len(clean) == 12 and clean.startswith("91"):
            pass
        else:
            print(f"⚠️ Invalid phone number format: {phone}")
            return False

        print(f"📱 Sending WhatsApp to {clean} via {WHATSAPP_BRIDGE}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Check bridge health first
            try:
                h = await client.get(f"{WHATSAPP_BRIDGE}/health", timeout=10.0)
                health_data = h.json()
                print(f"🔍 Bridge health: {health_data}")
                if h.status_code != 200 or not health_data.get("ready"):
                    print(f"⚠️ WhatsApp bridge not ready — status: {health_data}")
                    return False
            except Exception as he:
                print(f"⚠️ Bridge health check failed: {he}")
                return False

            # Send message
            r = await client.post(
                f"{WHATSAPP_BRIDGE}/send-message",
                json={"phone": clean, "message": message},
                timeout=60.0
            )
            print(f"📤 Send result: {r.status_code} — {r.text}")
            return r.status_code == 200

    except Exception as e:
        print(f"⚠️ Failed to send WhatsApp: {e}")
        return False

# ============================================================
# WHATSAPP BRIDGE MANAGEMENT - ON DEMAND
# ============================================================

async def wait_for_bridge(port=4322, timeout=30):
    """Wait for bridge to be ready"""
    start = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start) < timeout:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"http://localhost:{port}/health")
                if r.status_code == 200:
                    return True
        except:
            pass
        await asyncio.sleep(1)
    return False


@app.post("/whatsapp/start-bridge")
async def start_whatsapp_bridge():
    """Start the WhatsApp bridge process on demand"""
    global bridge_process, bridge_pid

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE}/health")
            if r.status_code == 200:
                await client.post(f"{WHATSAPP_BRIDGE}/reset")
                return {"success": True, "message": "Bridge already running, reset initiated", "already_running": True}
    except:
        pass

    if bridge_process and bridge_process.poll() is None:
        try:
            bridge_process.terminate()
            await asyncio.sleep(1)
        except:
            pass

    script_dir = os.path.dirname(os.path.abspath(__file__))
    bridge_script = os.path.join(script_dir, "whatsapp-bridge.js")

    if not os.path.exists(bridge_script):
        return {"success": False, "error": f"Bridge script not found at {bridge_script}"}

    try:
        if sys.platform == "win32":
            bridge_process = subprocess.Popen(
                ["node", bridge_script],
                cwd=script_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            bridge_process = subprocess.Popen(
                ["node", bridge_script],
                cwd=script_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
        bridge_pid = bridge_process.pid
        print(f"✅ Started WhatsApp bridge (PID: {bridge_pid})")

        ready = await wait_for_bridge(4322, 30)

        if ready:
            return {"success": True, "message": "Bridge started successfully", "pid": bridge_pid}
        else:
            return {"success": False, "error": "Bridge started but not responding"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/whatsapp/stop-bridge")
async def stop_whatsapp_bridge():
    """Stop the WhatsApp bridge process"""
    global bridge_process, bridge_pid

    try:
        if bridge_process and bridge_process.poll() is None:
            if sys.platform == "win32":
                bridge_process.terminate()
            else:
                os.kill(bridge_pid, signal.SIGTERM)
            try:
                bridge_process.wait(timeout=5)
            except:
                pass
            bridge_process = None
            bridge_pid = None
            print("✅ WhatsApp bridge stopped")
            return {"success": True, "message": "Bridge stopped"}
        else:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(f"{WHATSAPP_BRIDGE}/disconnect")
            except:
                pass
            return {"success": True, "message": "Bridge disconnected"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/whatsapp/connect-on-demand")
async def whatsapp_connect_on_demand():
    """Start bridge for QR connection"""
    result = await start_whatsapp_bridge()
    return result


@app.get("/whatsapp/bridge-status")
async def whatsapp_bridge_status():
    """Check bridge process status"""
    global bridge_process, bridge_pid

    bridge_running = False
    if bridge_process and bridge_process.poll() is None:
        bridge_running = True

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE}/health")
            if r.status_code == 200:
                data = r.json()
                return {
                    "process_running": bridge_running,
                    "bridge_ready": data.get("ready", False),
                    "bridge_connecting": data.get("connecting", False),
                    "pid": bridge_pid
                }
    except:
        pass

    return {
        "process_running": bridge_running,
        "bridge_ready": False,
        "bridge_connecting": False,
        "pid": bridge_pid
    }

# ============================================================
# WHATSAPP ENDPOINTS
# ============================================================

@app.get("/whatsapp-status")
async def whatsapp_status():
    try:
        info = await bridge_health()
        return {
            "connected": info.get("ready", False),
            "bridge_running": info.get("status") == "ok",
            "details": info,
        }
    except Exception as e:
        return {"connected": False, "bridge_running": False, "error": str(e)}


@app.get("/whatsapp/status/simple")
async def whatsapp_simple_status():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE}/status")
            if r.status_code == 200:
                data = r.json()
                return {
                    "ready": data.get("ready", False),
                    "connecting": data.get("connecting", False),
                }
    except Exception:
        pass
    return {"ready": False, "connecting": False}


@app.post("/whatsapp/push-qr")
async def push_qr(request: Request):
    """Receives QR from PC bridge and stores in memory — called by whatsapp-bridge.js"""
    global whatsapp_qr_store
    try:
        body = await request.json()
        whatsapp_qr_store["qr"] = body.get("qr")
        whatsapp_qr_store["updated_at"] = datetime.now().isoformat()
        whatsapp_qr_store["tunnel_url"] = body.get("tunnel_url")   # Cloudflare tunnel URL
        print(f"✅ QR received from bridge at {whatsapp_qr_store['updated_at']}")
        if whatsapp_qr_store.get("tunnel_url"):
            print(f"🌐 Bridge tunnel: {whatsapp_qr_store['tunnel_url']}")
        return {"success": True, "message": "QR stored successfully"}
    except Exception as e:
        raise HTTPException(500, f"Failed to store QR: {str(e)}")


@app.get("/whatsapp/qr")
async def whatsapp_qr():
    """Returns QR from memory store (pushed by PC bridge via Cloudflare Tunnel)"""
    try:
        if whatsapp_qr_store["qr"]:
            return {
                "qr": whatsapp_qr_store["qr"],
                "ready": False,
                "message": "QR ready to scan",
                "updated_at": whatsapp_qr_store["updated_at"],
                "tunnel_url": whatsapp_qr_store.get("tunnel_url")
            }
        return {
            "qr": None,
            "ready": False,
            "message": "QR not yet generated — make sure bridge is running on your PC"
        }
    except Exception as e:
        return {"qr": None, "ready": False, "message": str(e)}


@app.get("/whatsapp/qr-info")
async def whatsapp_qr_info():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{WHATSAPP_BRIDGE}/qr-info")
            if r.status_code == 200:
                return r.json()
            return {"qr_available": False, "is_connected": False, "is_connecting": False}
    except Exception as e:
        return {
            "qr_available": whatsapp_qr_store["qr"] is not None,
            "is_connected": False,
            "is_connecting": False,
            "error": str(e),
        }


@app.post("/whatsapp/disconnect")
async def whatsapp_disconnect():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{WHATSAPP_BRIDGE}/disconnect")
            return {"success": r.status_code == 200}
    except Exception:
        return {"success": False}


@app.post("/whatsapp/test-send")
async def test_send_whatsapp(request: Request):
    """Direct test — send a WhatsApp message to any number"""
    try:
        body = await request.json()
        phone = body.get("phone", "")
        message = body.get("message", "🔧 MechTrack test message!")

        if not phone:
            return {"success": False, "error": "Phone number required"}

        print(f"🧪 Test send to {phone}")
        result = await send_whatsapp(phone, message)
        return {
            "success": result,
            "phone": phone,
            "bridge_url": WHATSAPP_BRIDGE,
            "message": "Sent!" if result else "Failed — check Railway logs"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/whatsapp/bridge-url")
async def get_bridge_url():
    """Check what bridge URL is configured"""
    return {
        "bridge_url": WHATSAPP_BRIDGE,
        "whatsapp_enabled": WHATSAPP_ENABLED
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{WHATSAPP_BRIDGE}/reset")
            if r.status_code == 200:
                return {"success": True, "message": "Bridge reset, QR generating..."}
            return {"success": False, "message": "Bridge returned error"}
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
            raise ValueError("Phone number must be at least 10 digits")
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
            raise ValueError(f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}")
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

        asyncio.create_task(
            send_whatsapp(data.customer_phone, build_message(job, "intake"))
        )

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
        asyncio.create_task(
            send_whatsapp(job["customer_phone"], build_message(job, msg_type, data.message))
        )

        return {"success": True, "status": data.status, "message": "Status updated"}
    except Exception as e:
        raise HTTPException(500, f"Failed to update status: {str(e)}")


@app.get("/stats")
async def get_stats():
    try:
        vals = list(jobs_db.values())
        return {
            "total": len(vals),
            "active": sum(1 for j in vals if j["status"] != "delivered"),
            "ready": sum(1 for j in vals if j["status"] == "ready"),
            "waiting_parts": sum(1 for j in vals if j["status"] == "waiting_parts"),
            "delivered": sum(1 for j in vals if j["status"] == "delivered"),
        }
    except Exception as e:
        return {"total": 0, "active": 0, "ready": 0, "waiting_parts": 0, "delivered": 0, "error": str(e)}

# ============================================================
# GENERAL HEALTH & UTILITY
# ============================================================

@app.get("/")
async def root():
    try:
        info = await bridge_health()
        return {
            "status": "✅ MechTrack API Running",
            "shop_name": SHOP_NAME,
            "whatsapp_connected": info.get("ready", False),
            "version": "2.0.0",
            "port": 4321,
            "jobs_count": len(jobs_db),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "⚠️ Running with errors", "error": str(e)}


@app.get("/ping")
async def ping():
    return {"pong": True, "timestamp": datetime.now().isoformat(), "port": 4321, "status": "alive"}


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/jobs/backup")
async def backup_jobs():
    try:
        save_jobs_to_disk()
        return {"success": True, "message": "Jobs backed up successfully", "count": len(jobs_db)}
    except Exception as e:
        raise HTTPException(500, f"Backup failed: {str(e)}")


@app.get("/jobs/export")
async def export_jobs():
    try:
        return {
            "export_date": datetime.now().isoformat(),
            "total_jobs": len(jobs_db),
            "jobs": list(jobs_db.values()),
        }
    except Exception as e:
        raise HTTPException(500, f"Export failed: {str(e)}")

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 50)
    print("🔧 MechTrack API Server")
    print("=" * 50)
    print(f"🏪 Shop    : {SHOP_NAME}")
    print(f"📍 API     : http://localhost:4321")
    print(f"📊 Docs    : http://localhost:4321/docs")
    print(f"📱 Bridge  : {WHATSAPP_BRIDGE}")
    print(f"💾 Jobs    : {JOBS_FILE}")
    print(f"📋 License : {LICENSE_FILE}")
    print("=" * 50 + "\n")
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=4321,
        reload=True,
        reload_includes=["*.py"],
        reload_excludes=["*.json", "*.txt", "*.log"],
    )
