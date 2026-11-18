"""
deteccao.py — Visão computacional da cartela adesiva (OpenCV)
------------------------------------------------------------------
Mesma lógica testada em laboratório (versão 1.0), com melhorias da versão 1.1:

  1. Verificação de qualidade da imagem ANTES de contar:
     - nitidez (foto borrada?)
     - brilho (foto escura ou estourada?)
     - área amarela visível (algo tampando a cartela?)
     Leituras reprovadas são marcadas como "inválidas" e não entram no gráfico.

  2. Filtro de formato corrigido: a proporção comprimento/largura agora é
     medida com um retângulo que gira junto com o inseto (minAreaRect).
     Na versão 1.0 o limite mínimo era 1.0, o que deixava passar qualquer
     formato.

Todos os valores de ajuste estão no início do arquivo, com comentários.
"""

import cv2
import numpy as np

VERSAO_ALGORITMO = "1.1"

# ---------------------------------------------------------------------------
# AJUSTES DA CARTELA
# ---------------------------------------------------------------------------
AMARELO_MIN = np.array([15, 45, 45])     # faixa de cor da cartela (HSV)
AMARELO_MAX = np.array([50, 255, 255])

# ---------------------------------------------------------------------------
# AJUSTES DO "INSETO" (calibrados para a resolução 1024x768 do laboratório)
# ---------------------------------------------------------------------------
AREA_MINIMA = 80          # pixels
AREA_MAXIMA = 700         # pixels
PROPORCAO_MINIMA = 1.2    # inseto alongado: comprimento / largura
PROPORCAO_MAXIMA = 3.2
SOLIDEZ_MINIMA = 0.60     # quão "cheio" é o contorno (0 a 1)
MARGEM_BORDA = 6          # ignora objetos encostados na borda da cartela

# ---------------------------------------------------------------------------
# AJUSTES DE QUALIDADE DA FOTO
# Os valores medidos são salvos no banco: usem os dados reais para ajustar.
# ---------------------------------------------------------------------------
NITIDEZ_MINIMA = 10.0          # variância do Laplaciano (valor conservador: calibrar com os dados)
BRILHO_MINIMO = 40             # média de 0 a 255
BRILHO_MAXIMO = 235
FRACAO_AMARELO_MINIMA = 0.15   # a cartela deve ocupar pelo menos 15% da foto

# Níveis de alerta (escala EXPERIMENTAL, não é limiar agronômico oficial)
LIMITE_BAIXO = 3
LIMITE_ATENCAO = 10


def definir_nivel(contagem):
    if contagem <= LIMITE_BAIXO:
        return "BAIXO"
    if contagem <= LIMITE_ATENCAO:
        return "ATENÇÃO"
    return "RISCO"


def mascara_amarela(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mascara = cv2.inRange(hsv, AMARELO_MIN, AMARELO_MAX)
    kernel = np.ones((7, 7), np.uint8)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, kernel)
    return mascara


def avaliar_qualidade(frame, mascara):
    """Mede a qualidade da foto e diz se ela pode ser usada na contagem."""
    cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    nitidez = float(cv2.Laplacian(cinza, cv2.CV_64F).var())
    brilho = float(cinza.mean())
    fracao_amarelo = float(np.count_nonzero(mascara)) / mascara.size

    problemas = []
    if nitidez < NITIDEZ_MINIMA:
        problemas.append("imagem borrada")
    if brilho < BRILHO_MINIMO:
        problemas.append("imagem escura")
    if brilho > BRILHO_MAXIMO:
        problemas.append("imagem clara demais")
    if fracao_amarelo < FRACAO_AMARELO_MINIMA:
        problemas.append("cartela pouco visível")

    return {
        "nitidez": round(nitidez, 1),
        "brilho": round(brilho, 1),
        "fracao_amarelo": round(fracao_amarelo, 3),
        "valida": len(problemas) == 0,
        "motivo": ", ".join(problemas),
    }


def recortar_cartela(frame, mascara):
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return frame
    maior = max(contornos, key=cv2.contourArea)
    if cv2.contourArea(maior) < 5000:
        return frame
    x, y, w, h = cv2.boundingRect(maior)
    m = 10
    x, y = max(0, x - m), max(0, y - m)
    w = min(frame.shape[1] - x, w + 2 * m)
    h = min(frame.shape[0] - y, h + 2 * m)
    return frame[y:y + h, x:x + w]


def mascara_insetos(cartela):
    gray = cv2.cvtColor(cartela, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8)).apply(gray)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k)
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k)
    realce = cv2.addWeighted(tophat, 0.4, blackhat, 1.0, 0)
    _, mascara = cv2.threshold(realce, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    k3 = np.ones((3, 3), np.uint8)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, k3, iterations=1)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, k3, iterations=1)
    return mascara


def detectar(cartela):
    mascara = mascara_insetos(cartela)
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    alt, larg = cartela.shape[:2]
    detectados = []

    for c in contornos:
        area = cv2.contourArea(c)
        if area < AREA_MINIMA or area > AREA_MAXIMA:
            continue

        x, y, w, h = cv2.boundingRect(c)
        if w < 5 or h < 5:
            continue
        if (x < MARGEM_BORDA or y < MARGEM_BORDA or
                x + w > larg - MARGEM_BORDA or y + h > alt - MARGEM_BORDA):
            continue

        # Proporção medida com retângulo girado (funciona com inseto inclinado)
        (_, _), (rw, rh), _ = cv2.minAreaRect(c)
        if min(rw, rh) == 0:
            continue
        proporcao = max(rw, rh) / min(rw, rh)
        if proporcao < PROPORCAO_MINIMA or proporcao > PROPORCAO_MAXIMA:
            continue

        area_hull = cv2.contourArea(cv2.convexHull(c))
        if area_hull == 0 or area / area_hull < SOLIDEZ_MINIMA:
            continue

        detectados.append((x, y, w, h))

    return sorted(detectados, key=lambda d: (d[1], d[0]))


def desenhar(cartela, detectados, contagem, nivel, qualidade):
    marcada = cartela.copy()
    for i, (x, y, w, h) in enumerate(detectados, start=1):
        cv2.rectangle(marcada, (x, y), (x + w, y + h), (0, 0, 255), 2)
        y1, y2 = max(0, y - 28), max(22, y)
        cv2.rectangle(marcada, (x, y1), (x + 36, y2), (0, 0, 255), -1)
        cv2.putText(marcada, str(i), (x + 8, y2 - 7),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

    cab = 90
    h, w = marcada.shape[:2]
    saida = np.full((h + cab, w, 3), 255, dtype=np.uint8)
    saida[cab:, :] = marcada

    if qualidade["valida"]:
        linha1 = f"Possiveis cigarrinhas: {contagem}"
        linha2 = f"Nivel: {nivel.replace('Ç', 'C').replace('Ã', 'A')}"
        cor = (0, 80, 0)
    else:
        linha1 = "Leitura descartada"
        linha2 = qualidade["motivo"].encode("ascii", "ignore").decode()
        cor = (0, 0, 200)

    cv2.putText(saida, linha1, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, cor, 2)
    cv2.putText(saida, linha2, (20, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.7, cor, 2)
    return saida


def processar(frame):
    """Função principal: recebe a foto e devolve o resultado completo."""
    mascara = mascara_amarela(frame)
    qualidade = avaliar_qualidade(frame, mascara)
    cartela = recortar_cartela(frame, mascara)
    detectados = detectar(cartela)
    contagem = len(detectados)
    nivel = definir_nivel(contagem) if qualidade["valida"] else "INVÁLIDA"
    imagem_marcada = desenhar(cartela, detectados, contagem, nivel, qualidade)

    return {
        "contagem": contagem,
        "nivel": nivel,
        "imagem_marcada": imagem_marcada,
        **qualidade,
    }
