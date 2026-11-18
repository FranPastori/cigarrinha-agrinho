"""
app.py — Servidor na nuvem do Monitoramento da Cigarrinha-do-milho
--------------------------------------------------------------------
Funcionamento:
  1. A armadilha (ESP32-CAM) ENVIA a foto para  POST /api/leitura
  2. O servidor confere a chave secreta, analisa a foto (deteccao.py)
     e guarda o resultado no Supabase (banco.py).
  3. O painel (página inicial "/") mostra os dados em tempo real,
     acessível por qualquer celular pelo link fixo do Render.

Rotas:
  /                     painel de monitoramento
  /api/leitura          recebe a foto da armadilha (POST)
  /api/status           última leitura (JSON)
  /api/historico        últimas leituras válidas para o gráfico (JSON)
  /api/exportar.csv     todas as leituras em planilha (para o relatório)
  /saude                teste rápido se o servidor está no ar
"""

import csv
import io
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request

import banco
from deteccao import VERSAO_ALGORITMO, processar, LIMITE_BAIXO, LIMITE_ATENCAO

PASTA = os.path.dirname(os.path.abspath(__file__))
# O painel.html pode estar em "templates/" ou na mesma pasta do app.py
PASTA_PAINEL = (os.path.join(PASTA, "templates")
                if os.path.exists(os.path.join(PASTA, "templates", "painel.html"))
                else PASTA)
app = Flask(__name__, template_folder=PASTA_PAINEL)

API_KEY = os.environ.get("API_KEY", "")
ARMADILHA_PADRAO = os.environ.get("ARMADILHA_PADRAO", "A01")
# Para não lotar o armazenamento gratuito (1 GB), a imagem de TODA leitura
# substitui a "última imagem", mas só uma a cada X minutos fica no histórico.
ARQUIVAR_A_CADA_MIN = int(os.environ.get("ARQUIVAR_A_CADA_MIN", "30"))
INTERVALO_ESPERADO_S = int(os.environ.get("INTERVALO_ESPERADO_S", "60"))
FUSO = ZoneInfo("America/Sao_Paulo")


def para_horario_local(iso):
    """Converte o horário do banco (UTC) para o horário de Brasília."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(FUSO)


def deve_arquivar(armadilha_id, agora_utc):
    ultima = banco.ultima_leitura_arquivada(armadilha_id)
    if not ultima:
        return True
    dt = datetime.fromisoformat(ultima.replace("Z", "+00:00"))
    return (agora_utc - dt).total_seconds() >= ARQUIVAR_A_CADA_MIN * 60


# ---------------------------------------------------------------------------
# Recebe a foto enviada pela armadilha
# ---------------------------------------------------------------------------
@app.post("/api/leitura")
def receber_leitura():
    if not API_KEY or request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"erro": "chave inválida"}), 401

    jpeg = request.get_data()
    if not jpeg:
        return jsonify({"erro": "nenhuma imagem recebida"}), 400

    frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"erro": "imagem inválida"}), 400

    armadilha = request.headers.get("X-Armadilha", ARMADILHA_PADRAO)
    try:
        rssi = int(request.headers.get("X-RSSI", ""))
    except ValueError:
        rssi = None

    resultado = processar(frame)
    _, marcada_jpg = cv2.imencode(".jpg", resultado["imagem_marcada"],
                                  [cv2.IMWRITE_JPEG_QUALITY, 80])
    marcada_jpg = marcada_jpg.tobytes()

    # "Última imagem": sempre substituída (aparece no painel)
    banco.enviar_imagem(f"ultima/{armadilha}_marcada.jpg", marcada_jpg)

    # Histórico: guarda original + marcada a cada ARQUIVAR_A_CADA_MIN minutos
    agora = datetime.now(timezone.utc)
    url_original = url_marcada = None
    if deve_arquivar(armadilha, agora):
        carimbo = agora.astimezone(FUSO).strftime("%Y%m%d_%H%M%S")
        base = f"historico/{armadilha}/{carimbo}"
        url_original = banco.enviar_imagem(f"{base}_original.jpg", jpeg)
        url_marcada = banco.enviar_imagem(f"{base}_marcada.jpg", marcada_jpg)

    registro = banco.salvar_leitura({
        "armadilha_id": armadilha,
        "contagem": resultado["contagem"],
        "nivel": resultado["nivel"],
        "valida": resultado["valida"],
        "motivo": resultado["motivo"] or None,
        "nitidez": resultado["nitidez"],
        "brilho": resultado["brilho"],
        "fracao_amarelo": resultado["fracao_amarelo"],
        "rssi": rssi,
        "versao_algoritmo": VERSAO_ALGORITMO,
        "imagem_original": url_original,
        "imagem_marcada": url_marcada,
    })

    return jsonify({
        "id": registro["id"],
        "contagem": resultado["contagem"],
        "nivel": resultado["nivel"],
        "valida": resultado["valida"],
        "motivo": resultado["motivo"],
    })


# ---------------------------------------------------------------------------
# Dados para o painel
# ---------------------------------------------------------------------------
@app.get("/api/status")
def status():
    armadilha = request.args.get("armadilha", ARMADILHA_PADRAO)
    linhas = banco.buscar_leituras(armadilha, limite=1)
    if not linhas:
        return jsonify({"existe": False})

    l = linhas[0]
    local = para_horario_local(l["criado_em"])
    segundos = (datetime.now(timezone.utc) - local).total_seconds()

    return jsonify({
        "existe": True,
        "armadilha": armadilha,
        "contagem": l["contagem"],
        "nivel": l["nivel"],
        "valida": l["valida"],
        "motivo": l["motivo"],
        "rssi": l["rssi"],
        "data_hora": local.strftime("%d/%m/%Y %H:%M:%S"),
        "segundos_desde": int(segundos),
        "online": segundos < INTERVALO_ESPERADO_S * 3,
        "imagem": f"{banco.SUPABASE_URL}/storage/v1/object/public/"
                  f"{banco.BUCKET}/ultima/{armadilha}_marcada.jpg?t={l['id']}",
        "versao_algoritmo": l["versao_algoritmo"],
    })


@app.get("/api/historico")
def historico():
    armadilha = request.args.get("armadilha", ARMADILHA_PADRAO)
    linhas = banco.buscar_leituras(armadilha, limite=40, somente_validas=True)
    linhas.reverse()
    return jsonify([
        {"hora": para_horario_local(l["criado_em"]).strftime("%H:%M"),
         "contagem": l["contagem"]}
        for l in linhas
    ])


@app.get("/api/exportar.csv")
def exportar_csv():
    """Baixa todas as leituras em CSV (abre no Excel / Google Planilhas)."""
    armadilha = request.args.get("armadilha")
    todas, offset, lote = [], 0, 1000
    while True:
        url = f"{banco.SUPABASE_URL}/rest/v1/{banco.TABELA}"
        params = {"select": "*", "order": "id.asc",
                  "limit": str(lote), "offset": str(offset)}
        if armadilha:
            params["armadilha_id"] = f"eq.{armadilha}"
        r = banco.requests.get(url, params=params, headers=banco._cabecalhos(), timeout=30)
        r.raise_for_status()
        parte = r.json()
        todas.extend(parte)
        if len(parte) < lote:
            break
        offset += lote

    colunas = ["id", "data_hora_local", "armadilha_id", "contagem", "nivel", "valida",
               "motivo", "nitidez", "brilho", "fracao_amarelo", "rssi",
               "versao_algoritmo", "imagem_original", "imagem_marcada"]
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=";")
    w.writerow(colunas)
    for l in todas:
        l["data_hora_local"] = para_horario_local(l["criado_em"]).strftime("%d/%m/%Y %H:%M:%S")
        w.writerow([l.get(c) for c in colunas])

    return Response(
        "﻿" + saida.getvalue(),  # ﻿: acentos corretos no Excel
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leituras_cigarrinha.csv"},
    )


@app.get("/saude")
def saude():
    return jsonify({"ok": True, "banco_configurado": banco.configurado(),
                    "versao_algoritmo": VERSAO_ALGORITMO})


@app.get("/")
def painel():
    return render_template("painel.html",
                           armadilha=ARMADILHA_PADRAO,
                           limite_baixo=LIMITE_BAIXO,
                           limite_atencao=LIMITE_ATENCAO)


if __name__ == "__main__":
    # Para testar no próprio computador: python app.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
