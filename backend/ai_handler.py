"""
ai_handler.py — Integração com Google Gemini para resposta automática nas conversas.
Evoluído para incluir base de conhecimento (PDF/MD) para SocIA Selling.
"""
import logging
import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()
logger = logging.getLogger(__name__)

genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

_model = genai.GenerativeModel("gemini-1.5-flash")


async def generate_reply(
    system_prompt: str,
    conversation_history: list[dict],
    lead_info: dict,
    knowledge_base: str = ""
) -> str:
    """
    Gera uma resposta baseada no histórico da conversa e na base de conhecimento.
    """
    try:
        # Monta o contexto completo
        context = f"""
{system_prompt}

BASE DE CONHECIMENTO (Siga as instruções e scripts abaixo):
{knowledge_base if knowledge_base else "Nenhum arquivo de script adicional fornecido."}

Informações sobre o lead:
- Nome: {lead_info.get('full_name') or lead_info.get('username')}
- Username: @{lead_info.get('username')}
- Bio: {lead_info.get('bio', 'não disponível')}
- Seguidores: {lead_info.get('followers', 0)}

Histórico da conversa (mais recente por último):
"""
        for msg in conversation_history[-10:]:
            role_label = "Você (SocIA Selling)" if msg["role"] == "bot" else f"{lead_info.get('full_name') or lead_info.get('username')}"
            context += f"\n{role_label}: {msg['text']}"

        context += "\n\nContinue a conversa de forma natural como representante da SocIA Selling. Responda APENAS com o texto da próxima mensagem, sem explicações adicionais."

        response = await _model.generate_content_async(context)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Erro ao gerar resposta com Gemini: {e}")
        return ""


async def summarize_conversation(
    conversation_history: list[dict],
    lead_info: dict,
) -> str:
    """Gera um resumo conciso da conversa com o lead."""
    try:
        msgs_text = "\n".join(
            [f"{'Bot' if m['role'] == 'bot' else 'Lead'}: {m['text']}"
             for m in conversation_history]
        )
        prompt = f"""
Resuma em 2-3 frases a conversa abaixo com o profissional @{lead_info.get('username')}.
Inclua: interesse demonstrado, objeções levantadas e próximo passo sugerido.

Conversa:
{msgs_text}

Resumo:"""
        response = await _model.generate_content_async(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Erro ao gerar resumo: {e}")
        return "Resumo indisponível."
