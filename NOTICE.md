# Código e dados de terceiros

| O quê | Onde é usado | Licença | Origem |
|---|---|---|---|
| Regras da escadinha do art. 61-A (`faixa_rio_consolidada`) e do teto do art. 61-B (`limite_61b`), reescritas | `motor/raiz_estado.py`, `motor/raiz_app.py` | MIT, Copyright (c) 2022 GeoOne | https://github.com/OpenGeoOne/GeoCAR |
| Componente do globo (`cobe-globe.tsx`, `cobe-globe-demo.tsx`), copiado sem alterar | `front/globo/src/components/` | licença do autor a confirmar antes de publicar; a biblioteca `cobe` 2.0.1 é MIT | especificação "Cobe Globe — ProfitizeBuild"; https://github.com/shuding/cobe |

Dados públicos lidos pelo motor (cada um com seus termos): SICAR/SFB, Ibama, INPE TerraBrasilis (PRODES),
INCRA (SIGEF, quilombolas), FUNAI, MMA/CNUC (via geobr/Ipea), MapBiomas (cobertura, Fogo, Alerta), YbYrá-BR
(Source Cooperative), Global Pasture Watch (OpenGeoHub), JRC TMF v1.2025 (espelho COG na Source Cooperative,
epoch/jrc-tmf; dado do Joint Research Centre da Comissão Europeia, reempacotado sem alterar valores), causas da
perda de floresta WRI/Google DeepMind v1.2 (Zenodo 15366671, CC BY 4.0).

Dependências usadas sem copiar código: `i_overlay` (MIT/Apache-2.0) e `serde_json` (MIT/Apache-2.0) no teste `motor/iovbench/`.
