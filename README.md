# Monitoramento da Cigarrinha-do-milho — servidor na nuvem

Projeto de iniciação científica do Colégio Estadual do Campo Cerrado das Cinzas (Arapoti-PR).

A armadilha (ESP32-CAM) envia a foto da cartela adesiva para este servidor, que conta as possíveis
cigarrinhas com visão computacional (OpenCV), grava os dados no Supabase e exibe um painel web.

- `app.py` — servidor Flask (rotas e painel)
- `deteccao.py` — algoritmo de visão computacional
- `banco.py` — comunicação com o Supabase
- `painel.html` — página do painel
