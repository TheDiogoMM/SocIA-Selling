"""
database.py — Integração com Supabase (PostgreSQL) para SocIA Selling.
Utiliza postgrest-py diretamente para evitar conflitos de dependências.
"""
import os
import json
import asyncio
import logging
from datetime import datetime
from postgrest import AsyncPostgrestClient
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Configuração do Supabase
URL: str = os.getenv("SUPABASE_URL")
KEY: str = os.getenv("SUPABASE_ANON_KEY")

# URL do PostgREST no Supabase
REST_URL = f"{URL}/rest/v1"

def get_client() -> AsyncPostgrestClient:
    if not URL or not KEY:
        raise ValueError("Configuração do Supabase ausente. Verifique as variáveis de ambiente no Vercel (SUPABASE_URL e SUPABASE_ANON_KEY).")
    return AsyncPostgrestClient(REST_URL, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})

# --- Settings ---

async def get_setting(profile: str, key: str) -> str:
    async with get_client() as client:
        res = await client.table("settings").select("*").eq("profile_username", profile).execute()
        if res.data:
            return res.data[0].get(key, "")
        return ""

async def set_setting(profile: str, key: str, value: str):
    data = {"profile_username": profile, key: value, "updated_at": "now()"}
    async with get_client() as client:
        await client.table("settings").upsert(data, on_conflict="profile_username").execute()

async def get_all_settings(profile: str) -> dict:
    async with get_client() as client:
        res = await client.table("settings").select("*").eq("profile_username", profile).execute()
        if res.data:
            return res.data[0]
        # Se não existir, cria vazio para evitar erros
        await client.table("settings").insert({"profile_username": profile}).execute()
        return {}

# --- Knowledge Plans ---

async def add_plan(profile: str, name: str, content: str):
    async with get_client() as client:
        # Se for o primeiro plano, marca como ativo
        plans = await get_plans(profile)
        is_active = len(plans) == 0
        await client.table("knowledge_plans").insert({
            "profile_username": profile,
            "name": name,
            "content": content,
            "is_active": is_active
        }).execute()

async def get_plans(profile: str) -> list[dict]:
    async with get_client() as client:
        res = await client.table("knowledge_plans").select("*").eq("profile_username", profile).order("created_at", desc=True).execute()
        return res.data

async def delete_plan(plan_id: str):
    async with get_client() as client:
        await client.table("knowledge_plans").delete().eq("id", plan_id).execute()

async def activate_plan(profile: str, plan_id: str):
    async with get_client() as client:
        # Desativa todos
        await client.table("knowledge_plans").update({"is_active": False}).eq("profile_username", profile).execute()
        # Ativa o selecionado
        await client.table("knowledge_plans").update({"is_active": True}).eq("id", plan_id).execute()

async def get_active_plan_text(profile: str) -> str:
    async with get_client() as client:
        res = await client.table("knowledge_plans").select("content").eq("profile_username", profile).eq("is_active", True).execute()
        return res.data[0]["content"] if res.data else ""

# --- Sessions (Cookies) ---

async def save_session(profile: str, session_data: dict):
    data = {
        "profile_username": profile,
        "session_data": session_data,
        "updated_at": "now()"
    }
    async with get_client() as client:
        await client.table("sessions").upsert(data, on_conflict="profile_username").execute()

async def load_session(profile: str) -> dict | None:
    async with get_client() as client:
        res = await client.table("sessions").select("session_data").eq("profile_username", profile).execute()
        return res.data[0]["session_data"] if res.data else None

# --- Leads ---

async def upsert_lead(data: dict, owner: str) -> str:
    data["owner_profile"] = owner
    try:
        async with get_client() as client:
            res = await client.table("leads").upsert(data, on_conflict="instagram_id").execute()
            if res.data:
                return res.data[0]["id"]
            else:
                logger.warning(f"Upsert de lead não retornou dados. Res: {res}")
                return None
    except Exception as e:
        logger.error(f"Erro ao fazer upsert do lead {data.get('username')}: {e}")
        return None

async def get_lead(lead_id: str) -> dict | None:
    async with get_client() as client:
        res = await client.table("leads").select("*").eq("id", lead_id).execute()
        return res.data[0] if res.data else None

async def get_all_leads(owner: str, status_filter: str = None) -> list:
    async with get_client() as client:
        query = client.table("leads").select("*").eq("owner_profile", owner)
        if status_filter:
            query = query.eq("status", status_filter)
        res = await query.order("created_at", desc=True).execute()
        return res.data

async def update_lead_status(lead_id: str, status: str):
    async with get_client() as client:
        await client.table("leads").update({"status": status}).eq("id", lead_id).execute()

async def set_lead_ai_mode(lead_id: str, ai_mode: bool):
    async with get_client() as client:
        await client.table("leads").update({"ai_mode": ai_mode}).eq("id", lead_id).execute()

async def add_message(lead_id: str, role: str, text: str):
    async with get_client() as client:
        res = await client.table("leads").select("raw_messages").eq("id", lead_id).execute()
        messages = res.data[0]["raw_messages"] if res.data else []
        
        messages.append({
            "role": role,
            "text": text,
            "timestamp": datetime.now().isoformat()
        })
        
        await client.table("leads").update({
            "raw_messages": messages
        }).eq("id", lead_id).execute()

async def update_summary(lead_id: str, summary: str):
    async with get_client() as client:
        await client.table("leads").update({"conversation_summary": summary}).eq("id", lead_id).execute()

async def get_stats(owner: str) -> dict:
    async with get_client() as client:
        stats = {}
        for status in ["descoberto", "contatado", "respondeu", "qualificado", "ignorado"]:
            res = await client.table("leads").select("id", count="exact").eq("owner_profile", owner).eq("status", status).execute()
            stats[status] = res.count if res.count is not None else 0
        res = await client.table("leads").select("id", count="exact").eq("owner_profile", owner).execute()
        stats["total"] = res.count if res.count is not None else 0
        return stats
