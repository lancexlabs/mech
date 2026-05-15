from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import json
import os
import hashlib
import uuid

app = FastAPI()

# License storage file
LICENSE_FILE = "licenses.json"

class LicenseGenerate(BaseModel):
    client_name: str
    client_email: str
    duration_days: int = 30
    hardware_id: str

class LicenseVerify(BaseModel):
    license_key: str
    hardware_id: str

def load_licenses():
    if os.path.exists(LICENSE_FILE):
        with open(LICENSE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_licenses(licenses):
    with open(LICENSE_FILE, 'w') as f:
        json.dump(licenses, f, indent=2)

def generate_license_key():
    return str(uuid.uuid4()).upper().replace('-', '')[:20]

@app.post("/api/license/generate")
async def generate_license(data: LicenseGenerate):
    licenses = load_licenses()
    
    license_key = generate_license_key()
    issued_date = datetime.now()
    expiry_date = issued_date + timedelta(days=data.duration_days)
    
    license_data = {
        "license_key": license_key,
        "client_name": data.client_name,
        "client_email": data.client_email,
        "hardware_id": data.hardware_id,
        "issued_date": issued_date.isoformat(),
        "expiry_date": expiry_date.isoformat(),
        "duration_days": data.duration_days,
        "is_active": True
    }
    
    licenses[license_key] = license_data
    save_licenses(licenses)
    
    return license_data

@app.post("/api/license/verify")
async def verify_license(data: LicenseVerify):
    licenses = load_licenses()
    
    if data.license_key not in licenses:
        raise HTTPException(status_code=401, detail="Invalid license key")
    
    license_data = licenses[data.license_key]
    expiry_date = datetime.fromisoformat(license_data["expiry_date"])
    
    if expiry_date < datetime.now():
        raise HTTPException(status_code=401, detail="License expired")
    
    if license_data["hardware_id"] != data.hardware_id and license_data["hardware_id"] != "*":
        raise HTTPException(status_code=401, detail="Hardware ID mismatch")
    
    days_left = (expiry_date - datetime.now()).days
    
    return {
        "valid": True,
        "client_name": license_data["client_name"],
        "expiry_date": license_data["expiry_date"],
        "days_left": days_left
    }

@app.get("/api/license/status")
async def get_license_status(license_key: str):
    licenses = load_licenses()
    
    if license_key not in licenses:
        raise HTTPException(status_code=404, detail="License not found")
    
    license_data = licenses[license_key]
    expiry_date = datetime.fromisoformat(license_data["expiry_date"])
    
    return {
        "license_key": license_key,
        "client_name": license_data["client_name"],
        "expiry_date": license_data["expiry_date"],
        "is_expired": expiry_date < datetime.now(),
        "days_left": max(0, (expiry_date - datetime.now()).days)
    }