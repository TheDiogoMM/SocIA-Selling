"""
instagram_client.py — Autenticação dinâmica e persistência via Supabase para SocIA Selling.
"""
import logging
import asyncio
import os
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, TwoFactorRequired
from database import save_session, load_session

logger = logging.getLogger(__name__)

# Dicionário global para manter clientes ativos por username
_clients: dict[str, Client] = {}
_logged_in_users: set[str] = set()

def get_client(username: str) -> Client | None:
    return _clients.get(username)

def is_logged_in(username: str) -> bool:
    return username in _logged_in_users

async def try_login(username: str, password: str = None) -> dict:
    """
    Tenta login no Instagram. Se não houver senha, tenta usar a sessão do banco.
    """
    global _clients, _logged_in_users
    
    cl = Client()
    if os.path.exists('/tmp'):
        cl.settings_path = '/tmp/instagrapi_settings'
    
    cl.delay_range = [1, 3] # Reduzido para acelerar no Vercel
    cl.request_timeout = 7  # Timeout por requisição mais agressivo
    
    # 1. Tenta carregar sessão do Supabase
    session_data = await load_session(username)
    if session_data:
        try:
            cl.set_settings(session_data)
            _clients[username] = cl
            _logged_in_users.add(username)
            logger.info(f"Sessão de @{username} restaurada do Supabase.")
            return {"ok": True, "message": "Sessão restaurada", "username": username}
        except Exception as e:
            logger.warning(f"Sessão de @{username} inválida: {e}")

    # 2. Login com senha se fornecida
    if not password:
        return {"ok": False, "error": "Senha necessária para novo login", "username": username}

    try:
        loop = asyncio.get_event_loop()
        # Timeout para evitar que o Vercel mate o processo sem resposta (Hobby = 10s)
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: cl.login(username, password)),
            timeout=9.0
        )
        
        # Salva nova sessão no Supabase
        new_session = cl.get_settings()
        await save_session(username, new_session)
        
        _clients[username] = cl
        _logged_in_users.add(username)
        logger.info(f"Login de @{username} realizado com sucesso.")
        return {"ok": True, "message": "Login realizado com sucesso", "username": username}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Tempo limite do Vercel (10s) excedido no login.", "username": username}
    except TwoFactorRequired:
        return {"ok": False, "error": "2FA necessário", "username": username}
    except Exception as e:
        logger.error(f"Erro no login de @{username}: {e}")
        return {"ok": False, "error": str(e), "username": username}

async def try_login_by_sessionid(username: str, sessionid: str) -> dict:
    """
    Realiza login usando apenas o SessionID colado do navegador.
    """
    global _clients, _logged_in_users
    cl = Client()
    if os.path.exists('/tmp'):
        cl.settings_path = '/tmp/instagrapi_settings'
    
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: cl.login_by_sessionid(sessionid))
        
        actual_username = cl.username
        new_session = cl.get_settings()
        await save_session(actual_username, new_session)
        
        _clients[actual_username] = cl
        _logged_in_users.add(actual_username)
        return {"ok": True, "message": "Login por SessionID com sucesso", "username": actual_username}
    except Exception as e:
        logger.error(f"Erro no login por SessionID: {e}")
        return {"ok": False, "error": str(e), "username": username}

def logout(username: str):
    if username in _clients:
        try:
            _clients[username].logout()
        except:
            pass
        del _clients[username]
    if username in _logged_in_users:
        _logged_in_users.remove(username)
