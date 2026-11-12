# Código e dados de terceiros

| O quê | Onde é usado | Licença | Origem |
|---|---|---|---|
| Desenho do serviço de agentes: checkpointer aberto no início do serviço e retomada do grafo pelo thread_id quando há pausa pendente (reescrito, sem copiar código) | `raiz/api.py`, `raiz/agentes/memoria.py` | MIT, Copyright (c) 2024 Joshua Carroll | https://github.com/JoshuaC215/agent-service-toolkit |
| Leitura paginada do calendário de divulgação do IBGE (API v3, page/nextPage, tipo_id 1), reescrita sem polars | `raiz/coleta/ppm.py` | MIT, PYield | https://pypi.org/project/pyield/ |
| Desenho da fila de coleta: até 200 unidades por rodada, nova tentativa, disjuntor quando mais de 15% está sujo e reconciliação completa mensal (desenho, sem código copiado) | `raiz/coleta/fila.py` | MIT, osm-geoparquet (nfhl.py) | osm-geoparquet |
| Regras da escadinha do art. 61-A (`faixa_rio_consolidada`) e do teto do art. 61-B (`limite_61b`), reescritas | `motor/raiz_estado.py`, `motor/raiz_app.py` | MIT, Copyright (c) 2022 GeoOne | https://github.com/OpenGeoOne/GeoCAR |

Dados públicos lidos pelo motor (cada um com seus termos): SICAR/SFB, Ibama, INPE TerraBrasilis (PRODES),
INCRA (SIGEF, quilombolas), FUNAI, MMA/CNUC (via geobr/Ipea), MapBiomas (cobertura, Fogo, Alerta), YbYrá-BR
(Source Cooperative), Global Pasture Watch (OpenGeoHub), JRC TMF, WRI.

Dependências usadas sem copiar código: `i_overlay` (MIT/Apache-2.0) e `serde_json` (MIT/Apache-2.0) no teste `motor/iovbench/`.
