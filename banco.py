"""
banco.py — Comunicação com o Supabase (banco PostgreSQL + armazenamento de imagens)
------------------------------------------------------------------------------------
Usa a API REST do Supabase diretamente (biblioteca "requests"), sem pacotes extras.
As chaves ficam em variáveis de ambiente configuradas no Render, nunca no código.
"""

import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
BUCKET = "imagens"
TABELA = "leituras"


def _cabecalhos(extra=None):
    h = {"apikey": SUPABASE_KEY}
    # Chaves antigas (service_role, começam com "eyJ") também vão no Authorization.
    if SUPABASE_KEY.startswith("eyJ"):
        h["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if extra:
        h.update(extra)
    return h


def configurado():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def enviar_imagem(caminho, jpeg_bytes):
    """Salva (ou substitui) uma imagem no bucket e devolve o link público."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{caminho}"
    r = requests.post(
        url,
        data=jpeg_bytes,
        headers=_cabecalhos({"Content-Type": "image/jpeg", "x-upsert": "true"}),
        timeout=30,
    )
    r.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{caminho}"


def salvar_leitura(dados):
    url = f"{SUPABASE_URL}/rest/v1/{TABELA}"
    r = requests.post(
        url,
        json=dados,
        headers=_cabecalhos({"Content-Type": "application/json",
                             "Prefer": "return=representation"}),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()[0]


def buscar_leituras(armadilha_id=None, limite=30, somente_validas=False, ordem="desc"):
    url = f"{SUPABASE_URL}/rest/v1/{TABELA}"
    params = {"select": "*", "order": f"id.{ordem}", "limit": str(limite)}
    if armadilha_id:
        params["armadilha_id"] = f"eq.{armadilha_id}"
    if somente_validas:
        params["valida"] = "eq.true"
    r = requests.get(url, params=params, headers=_cabecalhos(), timeout=20)
    r.raise_for_status()
    return r.json()


def ultima_leitura_arquivada(armadilha_id):
    """Última leitura que teve imagem guardada no histórico."""
    url = f"{SUPABASE_URL}/rest/v1/{TABELA}"
    params = {
        "select": "criado_em",
        "armadilha_id": f"eq.{armadilha_id}",
        "imagem_marcada": "not.is.null",
        "order": "id.desc",
        "limit": "1",
    }
    r = requests.get(url, params=params, headers=_cabecalhos(), timeout=20)
    r.raise_for_status()
    linhas = r.json()
    return linhas[0]["criado_em"] if linhas else None
