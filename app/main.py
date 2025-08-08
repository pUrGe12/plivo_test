# app/main.py
import os
from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from app.db import database, users, create_tables_if_not_exist
from app.models import RegisterRequest, LoginRequest, TokenResponse
from app.auth import hash_password, verify_password, create_access_token, decode_token
from sqlalchemy import select
import httpx
import asyncio

HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
API_MODEL = os.getenv("HF_MODEL", "Salesforce/blip-image-captioning-base")

app = FastAPI()

origins = [
    "https://plivo-test-front-nve5dd0d4-j44ys-projects.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# create tables if missing (useful on startup)
create_tables_if_not_exist()

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# Auth helpers
async def get_user_by_email(email: str):
    query = users.select().where(users.c.email == email)
    return await database.fetch_one(query)

async def get_user_by_id(uid: int):
    query = users.select().where(users.c.id == uid)
    return await database.fetch_one(query)

def require_auth(token: str = Depends(lambda authorization: authorization)):
    # This dependency is used in endpoints manually (we'll parse headers manually below)
    return

# Routes
@app.post("/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    existing = await get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    hashed = hash_password(req.password)
    query = users.insert().values(email=req.email, password_hash=hashed)
    row_id = await database.execute(query)
    user = {"id": row_id, "email": req.email}
    token = create_access_token({"sub": row_id, "email": req.email})
    return {"token": token, "user": user}

@app.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = await get_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return {"token": token, "user": {"id": user["id"], "email": user["email"]}}

# helper to extract and validate Authorization header
from fastapi import Request
async def get_current_user(request: Request):
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = auth.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid auth header")
    token = parts[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await get_user_by_id(payload.get("sub"))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@app.post("/upload")
async def upload_image(file: UploadFile = File(...), current=Depends(get_current_user)):
    # file: UploadFile
    contents = await file.read()
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (8MB limit)")
    if not HUGGINGFACE_API_TOKEN:
        raise HTTPException(status_code=500, detail="HUGGINGFACE_API_TOKEN not configured")

    hf_url = f"https://api-inference.huggingface.co/models/{API_MODEL}"

    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_TOKEN}",
        "Content-Type": "application/octet-stream",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(hf_url, headers=headers, content=contents)

    if resp.status_code != 200:
        # forward error text
        raise HTTPException(status_code=500, detail=f"Hugging Face API error: {resp.status_code} - {resp.text}")

    hf_json = resp.json()

    # Normalize caption out of common HF model outputs:
    caption = None
    if isinstance(hf_json, dict) and "generated_text" in hf_json:
        caption = hf_json["generated_text"]
    elif isinstance(hf_json, list) and len(hf_json) and isinstance(hf_json[0], dict):
        # some models return [{generated_text:...}] or [{caption:...}]
        first = hf_json[0]
        caption = first.get("generated_text") or first.get("caption") or first.get("label")
    elif isinstance(hf_json, str):
        caption = hf_json
    else:
        caption = str(hf_json)[:1000]

    return {"success": True, "caption": caption, "raw": hf_json}

@app.get("/me")
async def me(current=Depends(get_current_user)):
    return {"id": current["id"], "email": current["email"], "created_at": str(current["created_at"])}
