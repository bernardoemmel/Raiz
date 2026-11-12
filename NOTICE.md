# Código e dados de terceiros

| O quê | Onde é usado | Licença | Origem |
|---|---|---|---|
| Desenho do serviço de agentes: checkpointer aberto no início do serviço e retomada do grafo pelo thread_id quando há pausa pendente (reescrito, sem copiar código) | `raiz/api.py`, `raiz/agentes/memoria.py` | MIT, Copyright (c) 2024 Joshua Carroll | https://github.com/JoshuaC215/agent-service-toolkit |
| Leitura paginada do calendário de divulgação do IBGE (API v3, page/nextPage, tipo_id 1), reescrita sem polars | `raiz/coleta/ppm.py` | MIT, PYield | https://pypi.org/project/pyield/ |
| Desenho da fila de coleta: até 200 unidades por rodada, nova tentativa, disjuntor quando mais de 15% está sujo e reconciliação completa mensal (desenho, sem código copiado) | `raiz/coleta/fila.py` | MIT, osm-geoparquet (nfhl.py) | osm-geoparquet |
| Regras da escadinha do art. 61-A (`faixa_rio_consolidada`) e do teto do art. 61-B (`limite_61b`), reescritas | `motor/raiz_estado.py`, `motor/raiz_app.py` | MIT, Copyright (c) 2022 GeoOne | https://github.com/OpenGeoOne/GeoCAR |
| Componente do globo (`cobe-globe.tsx`, `cobe-globe-demo.tsx`), copiado sem alterar | `front/globo/src/components/` | licença do autor a confirmar antes de publicar; a biblioteca `cobe` 2.0.1 é MIT | especificação "Cobe Globe — ProfitizeBuild"; https://github.com/shuding/cobe |

Dados públicos lidos pelo motor (cada um com seus termos): SICAR/SFB, Ibama, INPE TerraBrasilis (PRODES),
INCRA (SIGEF, quilombolas), FUNAI, MMA/CNUC (via geobr/Ipea), MapBiomas (cobertura, Fogo, Alerta), YbYrá-BR
(Source Cooperative), Global Pasture Watch (OpenGeoHub), JRC TMF v1.2025 (espelho COG na Source Cooperative,
epoch/jrc-tmf; dado do Joint Research Centre da Comissão Europeia, reempacotado sem alterar valores), causas da
perda de floresta WRI/Google DeepMind v1.2 (Zenodo 15366671, CC BY 4.0).

Dependências usadas sem copiar código: `i_overlay` (MIT/Apache-2.0) e `serde_json` (MIT/Apache-2.0) no teste `motor/iovbench/`.

Extensão `nativo/raiz_iov` (Rust, sem código copiado): `i_overlay` (MIT/Apache-2.0), `pyo3` (MIT/Apache-2.0),
`numpy`/rust-numpy (BSD-2), `ndarray` (MIT/Apache-2.0), `rayon` (MIT/Apache-2.0). A conta da área segue o teste do
fundador em `motor/iovbench/` (EvenOdd, contorno externo menos buracos).

## Catala (compilador, runtime Python e biblioteca padrão)

- Origem: https://github.com/CatalaLang/catala, versão 1.3.0 (pacote `catala` do opam), Inria e contribuidores.
- Licença: Apache-2.0. Inclui o `dates.py` da biblioteca Dates_calc (Inria, Apache-2.0).
- Uso: `raiz/regras/gerado/` tem o runtime Python (`catala_runtime.py`, `dates.py`) e os módulos da biblioteca padrão
  gerados pelo compilador, copiados por `raiz regras gerar`. Mudança feita: os imports absolutos viraram relativos
  (`from catala_runtime import *` para `from .catala_runtime import *`, `import dates` para `from . import dates`),
  e cada arquivo gerado ganhou uma linha de cabeçalho dizendo de onde veio. As regras em `raiz/regras/catala/` são
  próprias da Raíz.

## Extensão spatial do DuckDB

- Origem: https://github.com/duckdb/duckdb-spatial (MIT), baixada de extensions.duckdb.org em tempo de execução, não
  copiada para o repositório. Usa GEOS (LGPL-2.1, como biblioteca), PROJ (MIT) e GDAL (MIT).
