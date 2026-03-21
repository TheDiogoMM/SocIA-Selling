"""
main.py — Servidor FastAPI para SocIA Selling (Social AI Selling).
Sessão Multi-Perfil e Integração Supabase.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
import instagram_client as ig
import dm_manager as dm
from lead_finder import search_by_multiple_hashtags, search_by_username, search_similar_accounts
from file_processor import extract_text_from_pdf, extract_text_from_markdown

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
    async def broadcast(self, data: dict):
        for ws in self.active:
            try: await ws.send_text(json.dumps(data, ensure_ascii=False))
            except: pass

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validação de ambiente
    import os
    missing = [v for v in ["SUPABASE_URL", "SUPABASE_ANON_KEY", "GEMINI_API_KEY"] if not os.getenv(v)]
    if missing:
        logger.critical(f"VARIÁVEIS DE AMBIENTE AUSENTES: {', '.join(missing)}")
    
    dm.set_broadcast(manager.broadcast)
    logger.info("SocIA Selling Online.")
    yield

app = FastAPI(title="SocIA Selling", lifespan=lifespan)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# --- Models ---
class LoginPayload(BaseModel):
    username: str
    password: Optional[str] = None

class ManualDMPayload(BaseModel):
    lead_id: str
    text: str
    profile: str

class AIModePayload(BaseModel):
    lead_id: str
    ai_mode: bool

class SearchPayload(BaseModel):
    profile: str
    type: str  # 'hashtag', 'username', 'similar'
    query: str
    max_results: int = 10

class SettingsPayload(BaseModel):
    profile: str
    settings: dict

class AutomationPayload(BaseModel):
    profile: str
    lead_ids: list[str]

# --- Routes ---
@app.get("/")
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    return FileResponse(str(index)) if index.exists() else {"error": "Frontend missing"}

@app.get("/api/status")
async def get_status(username: str):
    # Tenta restaurar login se não estiver ativo
    if not ig.is_logged_in(username):
        await ig.try_login(username)
    
    return {
        "logged_in": ig.is_logged_in(username),
        "automation_running": dm.is_running(username),
        "stats": await db.get_stats(username),
    }

@app.post("/api/login")
async def login(payload: LoginPayload):
    try:
        result = await ig.try_login(payload.username, payload.password)
        try:
            await manager.broadcast({"event": "login_status", **result})
        except:
            pass
        return result
    except Exception as e:
        logger.error(f"Erro no login: {e}")
        return {"ok": False, "error": f"Erro interno no servidor: {str(e)}"}

@app.post("/api/logout")
async def logout(payload: LoginPayload):
    ig.logout(payload.username)
    return {"ok": True}

@app.get("/api/leads")
async def list_leads(profile: str, status: str = None):
    return await db.get_all_leads(profile, status)

@app.get("/api/leads/{lead_id}")
async def get_lead(lead_id: str):
    return await db.get_lead(lead_id)

@app.patch("/api/leads/{lead_id}/status")
async def update_status(lead_id: str, payload: dict):
    await db.update_lead_status(lead_id, payload["status"])
    return {"ok": True}

@app.post("/api/leads/{lead_id}/dm")
async def send_dm(lead_id: str, payload: ManualDMPayload):
    cl = ig.get_client(payload.profile)
    if not cl: raise HTTPException(401, "Insta off")
    ok = await dm.send_manual_dm(cl, lead_id, payload.text, payload.profile)
    return {"ok": ok}

@app.post("/api/leads/ai-mode")
async def set_ai_mode(payload: AIModePayload):
    await db.set_lead_ai_mode(payload.lead_id, payload.ai_mode)
    return {"ok": True}

@app.post("/api/search")
async def search_leads(payload: SearchPayload):
    cl = ig.get_client(payload.profile)
    if not cl: raise HTTPException(401, "Insta off")

    async def run_search():
        try:
            loop = asyncio.get_event_loop()
            leads = []
            if payload.type == 'hashtag':
                leads = await loop.run_in_executor(None, lambda: search_by_multiple_hashtags(cl, payload.query.split(','), payload.max_results))
            elif payload.type == 'username':
                user = await loop.run_in_executor(None, lambda: search_by_username(cl, payload.query))
                if user: leads = [user]
            elif payload.type == 'similar':
                leads = await loop.run_in_executor(None, lambda: search_similar_accounts(cl, payload.query, payload.max_results))
            
            count = 0
            for l in leads:
                if await db.upsert_lead(l, payload.profile): count += 1
            await manager.broadcast({"event": "search_done", "profile": payload.profile, "new": count})
        except Exception as e:
            logger.error(f"Erro na busca: {e}")
            await manager.broadcast({"event": "search_error", "profile": payload.profile, "error": str(e)})

    asyncio.create_task(run_search())
    return {"ok": True}

@app.post("/api/automation/start")
async def start_auto(payload: AutomationPayload):
    cl = ig.get_client(payload.profile)
    if not cl: raise HTTPException(401, "Insta off")
    ok = dm.start_automation(cl, payload.profile, payload.lead_ids)
    return {"ok": ok}

@app.post("/api/automation/stop")
async def stop_auto(payload: LoginPayload):
    dm.stop_automation(payload.username)
    return {"ok": True}

@app.get("/api/settings")
async def get_settings(profile: str):
    return await db.get_all_settings(profile)

@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    for k, v in payload.settings.items():
        await db.set_setting(payload.profile, k, str(v))
    return {"ok": True}

@app.post("/api/upload")
async def upload_file(profile: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    text = ""
    if file.filename.endswith(".pdf"):
        text = extract_text_from_pdf(content)
    elif file.filename.endswith(".md") or file.filename.endswith(".txt"):
        text = extract_text_from_markdown(content)
    
    if text:
        await db.set_setting(profile, "knowledge_base_text", text)
        return {"ok": True, "filename": file.filename}
    return {"ok": False, "error": "Formato não suportado"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
