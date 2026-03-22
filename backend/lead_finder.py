"""
lead_finder.py — Busca de profissionais (SocIA Selling) com suporte a perfis específicos e similares.
"""
import asyncio
import logging
import random
from instagrapi import Client

logger = logging.getLogger(__name__)

ARCH_KEYWORDS = [
    "arquitet", "architect", "design de interior", "interior design",
    "decoraç", "projeto", "interiores", "ateliê", "studio arq"
]

from ai_handler import filter_profile_by_ai

def _is_professional(user, custom_keywords: list[str] = None) -> tuple[bool, str]:
    """Heurística para filtrar perfis profissionais."""
    bio = (user.biography or "").lower()
    full_name = (user.full_name or "").lower()
    reason = "ok"
    
    keywords = custom_keywords if custom_keywords else ARCH_KEYWORDS
    matched = [k.strip() for k in keywords if k.strip().lower() in bio or k.strip().lower() in full_name]
    has_keyword = len(matched) > 0
    
    # Critérios: Palavra-chave OU Instagram diz que é similar
    is_prof = (has_keyword or not custom_keywords) and user.follower_count >= 10 and not user.is_private
    
    if not is_prof:
        if user.is_private: reason = "privado"
        elif user.follower_count < 10: reason = "seguidores"
        elif not (has_keyword or not custom_keywords): reason = "palavras-chave"
        logger.info(f"Filtro: @{user.username} rejeitado: {reason}")
    else:
        logger.info(f"Filtro: @{user.username} ACEITO! (Seguidores: {user.follower_count}, Match: {', '.join(matched) if matched else 'Similaridade/Vazio'})")
        
    return is_prof, reason

def search_by_hashtag(cl: Client, hashtag: str, max_results: int = 20, keywords: list[str] = None) -> tuple[list[dict], dict]:
    """Busca leads por hashtag e filtra."""
    leads = []
    stats = {"total_vistos": 0, "privado": 0, "seguidores": 0, "palavras-chave": 0, "ai_rejeitado": 0}
    clean_tag = hashtag.strip("#")
    logger.info(f"Instagrapi: Buscando hashtag #{clean_tag}")
    try:
        medias = cl.hashtag_medias_v1(clean_tag, amount=max_results * 4) # Busca mais p/ filtrar
        seen_ids = set()
        for media in medias:
            if media.user.pk in seen_ids: continue
            seen_ids.add(media.user.pk)
            stats["total_vistos"] += 1
            try:
                user = cl.user_info(media.user.pk)
                is_prof, reason = _is_professional(user, keywords)
                if not is_prof:
                    if reason in stats: stats[reason] += 1
                    continue
                
                leads.append(_format_user(user))
                import time
                time.sleep(random.uniform(1.0, 2.5))
                if len(leads) >= max_results: break
            except: continue
    except Exception as e:
        logger.error(f"Erro hashtag #{hashtag}: {e}")
    return leads, stats

def search_by_username(cl: Client, username: str) -> dict | None:
    """Busca um perfil específico pelo username."""
    try:
        clean_user = username.strip().strip("@")
        logger.info(f"Instagrapi: Buscando ID para @{clean_user}")
        user_id = cl.user_id_from_username(clean_user)
        logger.info(f"Instagrapi: ID encontrado: {user_id}. Buscando info completa...")
        user = cl.user_info(user_id)
        formatted = _format_user(user)
        logger.info(f"Instagrapi: Perfil @{clean_user} encontrado e formatado.")
        return formatted
    except Exception as e:
        logger.error(f"Instagrapi: Erro ao buscar @{username}: {e}")
        return None

def search_similar_accounts(cl: Client, username: str, max_results: int = 20, keywords: list[str] = None, ai_context: str = None) -> tuple[list[dict], dict]:
    """Busca seguidores de contas semelhantes à fornecida, com filtro opcional de IA."""
    leads = []
    stats = {"total_vistos": 0, "privado": 0, "seguidores": 0, "palavras-chave": 0, "ai_rejeitado": 0}
    clean_user = username.strip().strip("@")
    logger.info(f"Buscando contas semelhantes a @{clean_user}")
    try:
        user_id = cl.user_id_from_username(clean_user)
        similar_users = cl.user_similar_accounts(user_id)
        logger.info(f"Instagram retornou {len(similar_users)} contas semelhantes para @{clean_user}")
        
        for user in similar_users:
            stats["total_vistos"] += 1
            try:
                # OBTEM INFO COMPLETA (BIO, SEGUIDORES)
                full_user = cl.user_info(user.pk)
                
                # Perfil profissional básico
                is_prof, reason = _is_professional(full_user, keywords)
                if not is_prof:
                    if reason in stats: stats[reason] += 1
                    continue
                
                formatted = _format_user(full_user)
                
                # Filtro de IA (Opcional)
                if ai_context:
                    import asyncio
                    is_match = asyncio.run(filter_profile_by_ai(formatted, ai_context))
                    if not is_match:
                        logger.info(f"IA: Perfil @{user.username} rejeitado pelo contexto.")
                        stats["ai_rejeitado"] += 1
                        continue
                
                leads.append(formatted)
                
                # Pequeno delay
                import time
                time.sleep(random.uniform(1.0, 2.5))
                
                if len(leads) >= max_results: break
            except Exception as e:
                logger.error(f"Erro ao processar similar @{user.username}: {e}")
                continue
    except Exception as e:
        logger.error(f"Erro perfis similares a @{username}: {e}")
    return leads, stats

def search_by_multiple_hashtags(cl: Client, hashtags: list[str], max_per_hashtag: int = 10, keywords: list[str] = None) -> tuple[list[dict], dict]:
    """Busca leads em múltiplas hashtags, removendo duplicatas."""
    all_leads = []
    seen_ids = set()
    global_stats = {"total_vistos": 0, "privado": 0, "seguidores": 0, "palavras-chave": 0, "ai_rejeitado": 0}
    
    for hashtag in hashtags:
        results, stats = search_by_hashtag(cl, hashtag, max_per_hashtag, keywords)
        for k in global_stats: global_stats[k] += stats.get(k, 0)
        
        for lead in results:
            if lead["instagram_id"] not in seen_ids:
                seen_ids.add(lead["instagram_id"])
                all_leads.append(lead)
    return all_leads, global_stats

def _format_user(user) -> dict:
    return {
        "instagram_id": str(user.pk),
        "username": user.username,
        "full_name": user.full_name or "",
        "bio": user.biography or "",
        "followers": user.follower_count,
        "following": user.following_count,
        "profile_pic_url": str(user.profile_pic_url) if user.profile_pic_url else "",
    }
