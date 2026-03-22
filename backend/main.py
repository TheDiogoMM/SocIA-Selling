"""
main.py — Servidor FastAPI para SocIA Selling (Social AI Selling).
Sessão Multi-Perfil e Integração Supabase.
"""
import sys
import os
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

# Ajuste para o Vercel encontrar módulos em /backend
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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
_active_searches: set[str] = set()

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

class SessionIdPayload(BaseModel):
    username: str
    sessionid: str

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
    
    # Tenta restaurar se não estiver em memória
    cl = await ig.get_or_restore_client(username)
    
    return {
        "logged_in": cl is not None,
        "is_searching": username in _active_searches,
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

@app.post("/api/login/sessionid")
async def login_sessionid(payload: SessionIdPayload):
    try:
        result = await ig.try_login_by_sessionid(payload.username, payload.sessionid)
        if result.get("ok"):
            try: await manager.broadcast({"event": "login_status", **result})
            except: pass
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}

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
    cl = await ig.get_or_restore_client(payload.profile)
    if not cl: raise HTTPException(401, "Insta off")
    ok = await dm.send_manual_dm(cl, lead_id, payload.text, payload.profile)
    return {"ok": ok}

@app.post("/api/leads/ai-mode")
async def set_ai_mode(payload: AIModePayload):
    await db.set_lead_ai_mode(payload.lead_id, payload.ai_mode)
    return {"ok": True}

@app.post("/api/search")
async def search_leads(payload: SearchPayload):
    cl = await ig.get_or_restore_client(payload.profile)
    if not cl: raise HTTPException(401, "Insta off - Re-autenticação necessária")

    async def run_search_logic():
        loop = asyncio.get_event_loop()
        leads = []
        # Tenta sanitizar a query na lógica central
        query = payload.query.strip().strip("@").strip("#")
        
        settings = await db.get_all_settings(payload.profile)
        kws_str = settings.get("search_keywords", "")
        kws = [k.strip() for k in kws_str.split(",") if k.strip()] if kws_str else None
        
        # Busca o plano ativo para servir de contexto para a IA
        ai_context = await db.get_active_plan_text(payload.profile)
        
        logger.info(f"Iniciando busca para {payload.profile}. TIPO: {payload.type}, QUERY: {query}")
        leads = []
        stats = {"total_vistos": 0}
        try:
            if payload.type == 'hashtag':
                tags = [t.strip().strip("#") for t in query.split(',') if t.strip().strip("#")]
                if not tags: return 0, stats
                leads, stats = await loop.run_in_executor(None, lambda: search_by_multiple_hashtags(cl, tags, payload.max_results, kws))
            elif payload.type == 'username':
                user = await loop.run_in_executor(None, lambda: search_by_username(cl, query))
                if user: leads = [user]
                stats = {"total_vistos": 1 if user else 0}
            elif payload.type == 'similar':
                leads, stats = await loop.run_in_executor(None, lambda: search_similar_accounts(cl, query, payload.max_results, kws, ai_context))
            
            logger.info(f"Busca brutas retornou {len(leads)} leads. Stats: {stats}")
            
            count = 0
            for l in leads:
                try:
                    if await db.upsert_lead(l, payload.profile):
                        count += 1
                except Exception as e:
                    logger.error(f"Erro ao salvar lead {l.get('username')}: {e}")
            
            return count, stats
        except Exception as e:
            logger.error(f"Erro na lógica de busca: {e}")
            raise e

    # No Vercel, evitamos background tasks para hashtag/similar pois elas morrem "infinitamente"
    is_vercel = os.getenv("VERCEL") or os.getenv("VERCEL_ENV")
    if payload.type == 'username' or is_vercel:
        try:
            # No Vercel, o limite é 10 segundos para funções Hobby.
            # Como cada similar/hashtag agora busca user_info individualmente (lento), 
            # precisamos limitar bastante a quantidade no Vercel para não dar timeout.
            if is_vercel and payload.type != 'username':
                payload.max_results = min(payload.max_results, 4) if payload.type == 'similar' else min(payload.max_results, 6)
            
            count, stats = await run_search_logic()
            return {"ok": True, "count": count, "stats": stats, "message": f"Busca concluída: {count} leads."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Localmente: Hashtags/Similar rodam em background
    async def background_search():
        _active_searches.add(payload.profile)
        try:
            count, stats = await run_search_logic()
            await manager.broadcast({"event": "search_done", "profile": payload.profile, "new": count, "stats": stats})
        except Exception as e:
            await manager.broadcast({"event": "search_error", "profile": payload.profile, "error": str(e)})
        finally:
            _active_searches.discard(payload.profile)

    asyncio.create_task(background_search())
    return {"ok": True, "message": "Busca iniciada em segundo plano."}

@app.post("/api/automation/start")
async def start_auto(payload: AutomationPayload):
    try:
        logger.info(f"Iniciando automação para {payload.profile} com {len(payload.lead_ids)} leads.")
        cl = await ig.get_or_restore_client(payload.profile)
        if not cl:
            logger.warning(f"Falha ao obter cliente para {payload.profile}")
            raise HTTPException(401, "Insta off - Re-autenticação necessária")
        
        ok = dm.start_automation(cl, payload.profile, payload.lead_ids)
        return {"ok": ok}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Erro CRÍTICO em start_auto: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}

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
    try:
        content = await file.read()
        text = ""
        if file.filename.endswith(".pdf"):
            text = extract_text_from_pdf(content)
        elif file.filename.endswith(".md") or file.filename.endswith(".txt"):
            text = extract_text_from_markdown(content)
        
        if text:
            await db.add_plan(profile, file.filename, text)
            return {"ok": True, "filename": file.filename}
        return {"ok": False, "error": "Não foi possível extrair texto do arquivo."}
    except Exception as e:
        logger.error(f"Erro no upload: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/plans")
async def get_plans(profile: str):
    return await db.get_plans(profile)

@app.post("/api/plans/{plan_id}/activate")
async def activate_plan(profile: str, plan_id: str):
    await db.activate_plan(profile, plan_id)
    return {"ok": True}

@app.delete("/api/plans/{plan_id}")
async def delete_plan(plan_id: str):
    await db.delete_plan(plan_id)
    return {"ok": True}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
