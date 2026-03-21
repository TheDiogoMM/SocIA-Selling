"""
dm_manager.py — Controla o envio de DMs, modo IA e modo manual para SocIA Selling.
Suporte a múltiplos perfis simultâneos.
"""
import asyncio
import logging
import random
from instagrapi import Client
from database import (
    add_message, update_lead_status, set_lead_ai_mode,
    get_lead, get_setting, update_summary, get_all_settings
)
from ai_handler import generate_reply, summarize_conversation

logger = logging.getLogger(__name__)

# Fila de tarefas de automação por perfil
_automation_tasks: dict[str, asyncio.Task] = {}
_running_profiles: set[str] = set()
_broadcast_fn = None

def set_broadcast(fn):
    global _broadcast_fn
    _broadcast_fn = fn

async def _notify(event: str, data: dict):
    if _broadcast_fn:
        await _broadcast_fn({"event": event, **data})

def is_running(username: str):
    return username in _running_profiles

async def send_initial_dm(cl: Client, lead_id: str, profile_username: str) -> bool:
    lead = await get_lead(lead_id)
    if not lead: return False

    settings = await get_all_settings(profile_username)
    template = settings.get("initial_script", "Olá {nome}!")
    
    nome = (lead.get("full_name") or lead.get("username", "")).split()[0]
    message = template.replace("{nome}", nome).replace("{username}", lead.get("username", ""))

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: cl.direct_send(message, user_ids=[int(lead["instagram_id"])]))
        await add_message(lead_id, "bot", message)
        await update_lead_status(lead_id, "contatado")
        await _notify("dm_sent", {"lead_id": lead_id, "text": message, "profile": profile_username})
        return True
    except Exception as e:
        logger.error(f"Erro DM @{lead['username']} ({profile_username}): {e}")
        return False

async def send_manual_dm(cl: Client, lead_id: str, text: str, profile_username: str) -> bool:
    lead = await get_lead(lead_id)
    if not lead: return False
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: cl.direct_send(text, user_ids=[int(lead["instagram_id"])]))
        await add_message(lead_id, "bot", text)
        await _notify("dm_sent", {"lead_id": lead_id, "text": text, "profile": profile_username})
        return True
    except Exception as e:
        logger.error(f"Erro manual DM ({profile_username}): {e}")
        return False

async def handle_incoming_reply(cl: Client, lead_id: str, text: str, profile_username: str):
    lead = await get_lead(lead_id)
    if not lead: return

    await add_message(lead_id, "lead", text)
    await update_lead_status(lead_id, "respondeu")
    await _notify("reply_received", {"lead_id": lead_id, "text": text, "profile": profile_username})

    # Inteligência de Status
    positive_signals = ["quero", "interesse", "como funcion", "valor", "preço", "me conta"]
    if any(sig in text.lower() for sig in positive_signals):
        await update_lead_status(lead_id, "qualificado")

    # IA Automática
    if lead.get("ai_mode", True):
        await asyncio.sleep(random.uniform(20, 60))
        settings = await get_all_settings(profile_username)
        system_prompt = settings.get("system_prompt", "")
        kb_text = settings.get("knowledge_base_text", "")
        
        reply_text = await generate_reply(system_prompt, lead.get("raw_messages", []), lead, kb_text)
        if reply_text:
            await send_manual_dm(cl, lead_id, reply_text, profile_username)

async def automation_loop(cl: Client, profile_username: str, lead_ids: list[str]):
    global _running_profiles
    _running_profiles.add(profile_username)
    await _notify("automation_started", {"profile": profile_username, "total": len(lead_ids)})

    settings = await get_all_settings(profile_username)
    daily_limit = int(settings.get("daily_limit", 20))
    
    sent_count = 0
    for lead_id in lead_ids:
        if profile_username not in _running_profiles: break
        if sent_count >= daily_limit: break

        lead = await get_lead(lead_id)
        if not lead or lead["status"] != "descoberto": continue

        if await send_initial_dm(cl, lead_id, profile_username):
            sent_count += 1
            await _notify("progress", {"profile": profile_username, "sent": sent_count, "total": len(lead_ids)})
        
        await asyncio.sleep(random.uniform(40, 100))

    # Monitoramento contínuo de respostas
    while profile_username in _running_profiles:
        try:
            loop = asyncio.get_event_loop()
            threads = await loop.run_in_executor(None, lambda: cl.direct_threads(amount=10))
            for thread in threads:
                if not thread.messages: continue
                last_msg = thread.messages[0]
                if str(last_msg.user_id) == str(cl.user_id): continue
                
                # Procura lead no Supabase
                from database import get_all_leads
                relevant_leads = await get_all_leads(profile_username)
                for lead in relevant_leads:
                    if lead["instagram_id"] == str(last_msg.user_id):
                        last_saved = lead["raw_messages"][-1] if lead["raw_messages"] else None
                        if not last_saved or last_saved["text"] != last_msg.text:
                            await handle_incoming_reply(cl, lead["id"], last_msg.text, profile_username)
                        break
        except Exception as e:
            logger.error(f"Erro polling {profile_username}: {e}")
        
        await asyncio.sleep(60)

    _running_profiles.discard(profile_username)
    await _notify("automation_stopped", {"profile": profile_username})

def start_automation(cl: Client, profile_username: str, lead_ids: list[str]):
    if profile_username in _running_profiles: return False
    task = asyncio.create_task(automation_loop(cl, profile_username, lead_ids))
    _automation_tasks[profile_username] = task
    return True

def stop_automation(profile_username: str):
    if profile_username in _running_profiles:
        _running_profiles.remove(profile_username)
