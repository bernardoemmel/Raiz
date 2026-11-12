# Raíz

A Raíz acha, no Brasil inteiro, fazendas aptas a restauração, carbono, solo e metano usando só dados públicos,
checa o título da terra, pede o aceite do dono e liga a fazenda a quem paga (desenvolvedores de restauração,
empresas com meta FLAG, compradores de crédito, financiadores e governos). Também vende a checagem de título e
geolocalização como produto. Empresa AI First: o fundador opera com agentes de IA, e cada previsão é guardada
e comparada com o resultado real.

## O que já existe

**Motor de dados (`motor/`)**: funil por imóvel do CAR, município por município, para todos os estados.

| Script | O que faz |
|---|---|
| `raiz_estado.py` | funil principal: CAR (SICAR), embargos (Ibama), PRODES, TI, UC e hidrografia (TerraBrasilis), SIGEF (INCRA), MapBiomas, MapBiomas Alerta; reserva legal, APP (escadinha), frentes e carbono |
| `raiz_filtros.py` | quilombos (INCRA), terras indígenas da FUNAI em todas as fases, unidades de conservação do CNUC por grupo |
| `raiz_extras.py` | camadas exportadas do Earth Engine (`motor/gee/`): vegetação secundária, fogo, pasto, lavoura, TMF, causa da perda |
| `raiz_direto.py` | YbYrá e Global Pasture Watch lidos direto dos arquivos públicos, sem Earth Engine |
| `raiz_mapbiomas.py` | MapBiomas (cobertura, desmatamento, fogo, pasto) pela API da Plataforma, sem login e sem Earth Engine |
| `raiz_app.py` | aplica a escadinha da APP a municípios rodados antes dela |
| `raiz_ajustes.py` | ajustes da pesquisa (cenários de carbono etc.) por cima da saída |
| `mapbiomas_alerta.py` | API do MapBiomas Alerta (credenciais em variáveis de ambiente) |
| `iovbench/` | teste da interseção pelo iOverlay (Rust) contra o GEOS nos mesmos pares: 2,1x mais rápido em São Félix do Xingu e Altamira, mesma área |
| `fila*.sh` | filas que rodam o país inteiro, estado por estado, retomando de onde pararam |

Desempenho: cerca de 30 a 40 s por município com 3 municípios ao mesmo tempo (4 núcleos, 15 GB); Brasil inteiro em cerca de 2 dias.

**Amostra (`dados/amostra/`)**: resumo do Pará (144 municípios) e os imóveis de Nova Esperança do Piriá (PA).
Os dados completos não ficam no repositório (são grandes); o motor gera de novo.

**Documentação (`docs/`)**: `colunas.md` (o que cada coluna significa; é o contrato entre motor e produto) e
`plano-por-etapa.md` (o que construir, em que ordem, com horas estimadas).

## Rodar o motor

```bash
pip install -r requirements.txt
cd motor
python raiz_estado.py PA 1504950      # um município (código IBGE)
python raiz_estado.py PA              # o estado inteiro
python raiz_filtros.py PA
python raiz_direto.py PA
```

Saída em `motor/saida/<UF>/`. Para o MapBiomas Alerta, copie `.env.example` para `.env` e preencha.

## Etapas do produto

E1 coleta de dados públicos · E2 funil por imóvel · E3 conta de carbono e de dinheiro · E4 rebanho, metano e solo ·
E5 título e geolocalização · E6 quem compra · E7 agentes e operação · E8 aprendizado contínuo · E9 o que as pessoas veem.

Ferramentas de terceiros usadas: ver `NOTICE.md`.
