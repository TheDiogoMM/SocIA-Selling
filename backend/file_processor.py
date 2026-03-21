"""
file_processor.py — Extração de texto de arquivos PDF e Markdown para SocIA Selling.
"""
import io
from pypdf import PdfReader

def extract_text_from_pdf(file_content: bytes) -> str:
    """Extrai todo o texto de um arquivo PDF."""
    try:
        reader = PdfReader(io.BytesIO(file_content))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        return f"Erro ao processar PDF: {e}"

def extract_text_from_markdown(file_content: bytes) -> str:
    """Lê conteúdo de um arquivo Markdown (que já é texto)."""
    try:
        return file_content.decode("utf-8").strip()
    except Exception as e:
        return f"Erro ao processar Markdown: {e}"
