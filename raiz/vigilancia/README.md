# Vigilância das fazendas e dos projetos (`raiz/vigilancia/`)

Todo dia, às 06:17 de Brasília, o GitHub Actions lê os alertas públicos, cruza com os polígonos do CAR publicados no
Release `dados` e com os polígonos dos projetos, e publica o resultado no Release `vigilancia`. Cada alerta é
guardado com a versão da regra que o gerou e pode ser marcado depois como verdadeiro ou falso. Perda dentro da área
de carbono de um projeto vira evento de perda com o prazo da Verra, rascunho do relatório de perda e aviso ao cliente.

## Fontes

| Fonte | O que traz | Como lê | Chave do alerta |
|---|---|---|---|
| MapBiomas Alerta | desmatamento validado em imagem de alta resolução, com o polígono e os CAR tocados | API GraphQL v2 com login (`MAPBIOMAS_ALERTA_EMAIL`, `MAPBIOMAS_ALERTA_SENHA`), janela de 35 dias pela data de publicação; só pede de novo se saiu publicação nova ou se a última releitura tem 7 dias | código do alerta |
| FIRMS | focos de calor do VIIRS 375 m, satélites NOAA-20 e NOAA-21 | arquivos públicos da América do Sul (48 h; 7 dias na primeira vez); com `FIRMS_MAP_KEY`, API de área | satélite, data e hora da passagem (os focos da mesma passagem no mesmo imóvel viram um alerta) |
| Embargos do Ibama | termos de embargo ativos, com polígono ou só o ponto | CSV dos dados abertos com pedido condicional (ETag); só cruza termo novo ou alterado | `SEQ_TAD` |
| DETER (INPE) | desmatamento, degradação e cicatriz de queimada, Amazônia e Cerrado | WFS do TerraBrasilis, janela de 45 dias (90 na primeira vez) | camada, classe, data da imagem e geometria (o `gid` muda quando o mês fecha) |
| PRODES (INPE) | desmatamento anual, Amazônia Legal e Cerrado | todo dia pergunta qual o último ano; quando sai ano novo, baixa o ano nos estados vigiados | `uuid` do polígono |

Fonte fora do ar não para as outras: fica registrada como erro em `fontes.json`, a rodada publica o que deu certo e
termina vermelha (o GitHub avisa por e-mail). Fonte sem credencial só avisa.

## O que vai para o Release `vigilancia`

O repositório é público, então o Release também é.

| Arquivo | Aberto ou cifrado | O que é |
|---|---|---|
| `alertas_AAAA-MM.parquet` | aberto | alertas de imóvel do mês em que a Raíz os viu (só dado público cruzado com o CAR) |
| `ibama_espelho.parquet` | aberto | `seq_tad`, hash, ativo, cancelado, desembargado (sem nome nem CPF/CNPJ) |
| `fontes.json`, `rodadas.jsonl` | aberto | situação de cada fonte e contagens de cada rodada |
| `privado.tar.gz.cifrado` | cifrado (Fernet, chave `RAIZ_VIGILANCIA_CHAVE`) | alertas de projeto, marcações, eventos do fundador, número fixo de cada evento de perda, rascunhos dos relatórios, KML, avisos e acerto |
| `entrada_*.cifrado` | cifrado | marcações e eventos feitos pela API, que a rodada seguinte junta e apaga |
| `vigilancia.json` | aberto | manifesto (sha256 de cada arquivo), sobe por último |

Sem a chave, a rodada roda, mas a parte privada não é guardada (o resumo da execução avisa).

## Rotas

As rotas já estão no back-end (`raiz/api.py`), com o mesmo token das outras (`RAIZ_API_TOKEN`):

```python
from raiz.vigilancia import api as vigilancia_api

app.include_router(vigilancia_api.roteador(), dependencies=seguro)
```

O servidor do back-end lê o estado da pasta `RAIZ_VIGILANCIA_DIR`; `python -m raiz.vigilancia baixar` traz o estado
publicado no Release (com `RAIZ_VIGILANCIA_CHAVE`, também a parte privada). `python -m raiz.vigilancia servir` sobe
só estas rotas, sem o resto do back-end, baixando o estado ao subir.

| Rota | Devolve |
|---|---|
| `GET /vigilancia/imovel/{cod_imovel}` | situação (`alerta`, `atencao`, `sem_alerta`), resumo (alertas em 30 dias, por fonte, embargo ativo, marcados), alertas com fonte, data, área, fração do imóvel, gravidade, confiança, versão da regra e marcação; `?desde=`, `?fonte=`, `?limite=`, `?geo=true` (GeoJSON) |
| `GET /vigilancia/projeto/{id}` | área de carbono, avisos sobre o polígono, situação, regra da Verra, eventos de perda (prazos, magnitude, imóveis do CAR tocados, avisos, links do relatório e do KML) e alertas do projeto |
| `GET /vigilancia/projeto/{id}/perdas/{perda_id}/relatorio?idioma=pt\|en` | rascunho do relatório de perda em Markdown |
| `GET /vigilancia/projeto/{id}/perdas/{perda_id}/kml` | KML da área afetada |
| `POST /vigilancia/projeto/{id}/perdas/{perda_id}/eventos` | `verra_avisada`, `relatorio_enviado`, `descoberta_informada` (com justificativa), `perda_descartada`, `perda_reaberta`, `nota` |
| `GET /vigilancia/avisos?estado=aguardando_aprovacao` | avisos ao cliente |
| `POST /vigilancia/avisos/{aviso_id}/eventos` | `aviso_aprovado`, `aviso_enviado`, `aviso_descartado` |
| `POST /vigilancia/alertas/{alerta_id}/marcacao` | `{verdadeiro, fonte: campo\|cliente\|imagem_nova\|fonte_oficial, quem, evidencia, observado_em}` |
| `GET /vigilancia/acerto` | acerto por fonte, estrato e versão da regra |
| `GET /vigilancia/saude` | última rodada, se está atrasada, situação de cada fonte |

As colunas saem pelo nome, com CPF/CNPJ mascarados e sem chave pessoal. O código do CAR pode vir com os pontos do
recibo e em qualquer caixa.

## Regra da Verra (perda em área de projeto)

Base: Verra, VCS Program, Registration and Issuance Process v4.4, seção 5.3.1: ao descobrir um evento de perda, o
proponente avisa a Verra por e-mail (registry@verra.org) em até **30 dias** e, se o projeto já emitiu VCU, entrega o
relatório de perda em até **2 anos** da descoberta; sem o relatório, o projeto não emite mais VCU (errata de
14/02/2023: vale também para os outros projetos do mesmo proponente). Modelo do relatório: Loss Event Report Template
v5.0 (é evento de perda quando a perda passa de **5%** das reduções e remoções já verificadas).

- Entra como candidata a perda todo alerta de desmatamento, degradação ou fogo na área de carbono do projeto
  (`classes_projeto`) com data igual ou depois do início do projeto. Embargo dentro do projeto aparece como alerta de
  gravidade alta, mas não abre evento sozinho. Alerta em aceiro e estrada (`classes_entorno`) só avisa.
- Alertas a até 500 m e 60 dias um do outro formam o mesmo evento. Cada evento ganha número fixo no formato da Verra
  (`URTX_LE1`); número dado nunca é reaproveitado.
- **Descoberta**: a data mais cedo entre a publicação pela fonte e a primeira leitura pela Raíz (conservador). O
  fundador pode informar outra com justificativa (`descoberta_informada`).
- **Contador de prazo**: aviso à Verra (`no_prazo`, `urgente` a 7 dias, `vencido`, `cumprido`) e relatório
  (`atencao` a 180 dias, `urgente` a 30, `vencido`, `cumprido`, `nao_obrigatorio` se o projeto não emitiu VCU).
- **Magnitude**: área por classe vezes o estoque por hectare (todo o estoque perdido: estimativa conservadora),
  dividido pelo total já verificado. Sem esses números (arquivo privado), a rota diz o que falta.
- **Rascunho do relatório**: seções 1.1 a 4 do modelo v5.0, em português (para conferir) e inglês (para entregar),
  com tabela de datas, centro de cada área afetada, KML, parâmetros monitorados, quantificação e lista dos alertas. O
  que a Raíz não sabe fica `[preencher]`.
- **Aviso ao cliente**: curto, na ordem fonte, fato, fazenda, prazo, o que fazer; um por marco (nova perda, perda
  confirmada, lembrete do aviso à Verra, prazo do relatório a 180 e 30 dias, prazo vencido); sempre nasce
  aguardando a aprovação do fundador.
- Situação do evento: `suspeita`, `confirmada` (algum alerta verdadeiro), `descartada` (todos falsos ou descartado
  pelo fundador) ou `relatada`.

## Alerta do pedido salvo (cena-alvo, passo 9)

O vigia do pedido (`raiz/pedidos/servico.py`, `vigiar`, rodado de hora em hora por `raiz pedidos ciclo`) usa
`raiz/vigilancia/pedidos.py` para saber o que aconteceu nas fazendas do lote e do grupo depois que o pedido foi salvo:

| Motivo | De onde vem |
|---|---|
| `desmatamento` | alerta de desmatamento ou degradação da vigilância diária (MapBiomas Alerta, DETER, PRODES) visto depois do pedido; fica de fora o que foi marcado falso, a borda e a linha de base |
| `embargo` | termo de embargo do Ibama novo e ainda ativo |
| `matricula_cancelada` | certidão lida que diz que a matrícula foi encerrada, cancelada ou transportada (`matricula_<mun>.csv` do leitor de certidões) |
| `bloqueio`, `caminho_terra`, `saiu_da_base` | o motor refez o município e a fazenda não passa mais no filtro do pedido |

Cada fato tem chave própria e nunca é avisado duas vezes. O aviso vai para o painel e o e-mail; com o grupo em
formação ou fechado, também por WhatsApp (simulado até haver enviador). "Lote melhorou" diz quais fazendas novas
entraram e se o dado delas é novo na base. Antes do vigia, o ciclo traz o estado publicado da vigilância (a parte
aberta basta; com `RAIZ_VIGILANCIA_CHAVE`, também as marcações).

## Aprendizado

Cada alerta é uma previsão congelada: nasce com a versão da regra (`vigilancia-2026.11a+<hash de regras.yaml>`), o
estrato (fonte e tipo) e a confiança daquele momento. A marcação diz se foi verdadeiro ou falso:

| Fonte da marcação | Quem marca |
|---|---|
| `campo` | alguém foi ao lugar |
| `cliente` | o dono ou o desenvolvedor do projeto confirmou ou desmentiu |
| `imagem_nova` | imagem posterior: automático quando o PRODES ou o MapBiomas Alerta confirma o DETER (ou o PRODES do ano, já lido, não mapeou desmatamento maior que 6,25 ha), ou quando a cicatriz de queimada do DETER confirma o foco de calor; ou alguém olhando imagem nova |
| `fonte_oficial` | a fonte voltou atrás: termo de embargo cancelado, alerta do MapBiomas rejeitado |

Vale a marcação humana mais recente; a automática só vale quando não há humana. A confiança de cada estrato é
Beta(a + verdadeiros, b + falsos), com a e b em `regras.yaml`. O acerto por versão da regra (precisão e nota de Brier)
mostra se uma regra nova é melhor que a velha. A marcação automática só confirma foco de calor (nunca desmente),
então os falsos do FIRMS vêm só de marcação humana; o acerto mostra de onde veio cada marcação.
`python -m raiz.vigilancia exportar-aprendizado PASTA` gera previsões e gabaritos no formato de `raiz/aprendizado`
(`aprendizado.previsao` e `aprendizado.gabarito`) para o back-end congelar com `registrar_lote`.

## Projetos

`projetos.yaml` tem só o que é público (o primeiro é a URTX, polígono `URTX.kml` do Release `dados`). O que é
comercial (código do cliente, total verificado, estoque por hectare, se já emitiu VCU, período de monitoramento) vem
de `RAIZ_PROJETOS_PRIVADO` (segredo do GitHub, texto YAML no mesmo formato), juntado pelo id. Projeto que só existe
no privado (grupo de fazendas pequenas de um cliente, pela lista de códigos do CAR) é vigiado igual e nunca aparece
aberto.

## Regras gerais

- Nenhuma fazenda sai por tamanho. Sobreposição pequena fica guardada; quando parece só diferença de traçado
  (borda: menos de 0,1 ha e menos de 1% do alerta e do imóvel), vai com gravidade baixa. Imóvel pequeno atingido em
  boa parte tem gravidade pela fração atingida, não pela área.
- Colunas lidas pelo nome (`docs/colunas.md`), tolerando coluna nova ou faltante.
- Privacidade: do CSV do Ibama só entram colunas sem nada pessoal; o CSV bruto é baixado em pasta temporária fora do
  cache e apagado. Todo texto passa pela máscara de CPF/CNPJ; marcação e evento guardam o papel de quem fez
  (fundador, cliente, campo), nunca nome. Segredos da URL (chave do FIRMS) saem das mensagens de erro.

## Linha de comando

```bash
pip install -r raiz/vigilancia/requisitos.txt
```

```bash
python -m raiz.vigilancia rodar --ufs PA
```

```bash
python -m raiz.vigilancia imovel PA-1507300-F293CD17...
```

```bash
python -m raiz.vigilancia projeto URTX
```

```bash
python -m raiz.vigilancia relatorio URTX URTX_LE1 --idioma en
```

```bash
python -m raiz.vigilancia marcar <alerta_id> falso --fonte campo --quem fundador --evidencia "pasto antigo"
```

```bash
python -m raiz.vigilancia evento perda URTX_LE1 verra_avisada --quem fundador --data 2026-11-13
```

Outros: `avisos`, `acerto`, `baixar` (traz o estado publicado), `chave` (gera a chave da parte privada), `servir`.
Testes: `python -m pytest raiz/vigilancia/testes` (sem rede); também rodam no `uv run pytest` do CI.

## Medido em 12/11/2026

Rodada do Pará inteiro (144 municípios) com FIRMS de 7 dias, DETER de 90 dias, PRODES 2025/2026 e todos os embargos
ativos: 222 s, pico de 1,9 GB de memória, 83.314 alertas em 38.685 imóveis e projetos. O MapBiomas Alerta não rodou
aqui por falta de credencial neste ambiente.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `regras.yaml`, `regras.py` | regras versionadas (fontes, tipos, confiança inicial, gravidade, marcação automática, Verra) |
| `fontes/` | um coletor por fonte, todos no mesmo formato de ocorrência |
| `poligonos.py` | polígonos e colunas de identificação do Release `dados`, por município, com cache pela versão |
| `projetos.py`, `projetos.yaml`, `kml.py` | cadastro e áreas dos projetos (KML ou GeoJSON, ou grupo de CAR) |
| `cruzamento.py` | alerta = ocorrência x alvo, com gravidade, borda, confiança e versão da regra |
| `aprendizado.py` | marcações, confiança por estrato, marcação automática, acerto e exportação |
| `perdas.py`, `relatorio.py`, `aviso.py` | regra da Verra, rascunho do relatório e KML, aviso ao cliente |
| `armazem.py`, `publicacao.py` | estado em arquivos e publicação no Release (privado cifrado) |
| `rodada.py`, `servico.py`, `api.py`, `servidor.py`, `__main__.py` | rodada diária, respostas das rotas, rotas, servidor avulso, linha de comando |

## Aviso inicial à Verra

O e-mail inicial é separado do relatório de perda. A rodada diária grava `<evento>_aviso_verra.eml` na pasta privada dos relatórios (publicada somente no pacote cifrado). As rotas `GET /vigilancia/projeto/{id}/perdas/{evento}/aviso-verra` e `/aviso-verra.eml` usam a autenticação existente e mostram as pendências. `python -m raiz.vigilancia aviso-verra URTX URTX_LE1 --saida /caminho/privado/aviso.eml` prepara sem enviar. Sem o estado privado, `--prazo-informado AAAA-MM-DD` prepara só um rascunho incompleto, marcado como prazo informado pelo operador. Preparação nunca registra `verra_avisada`. Ver `docs/pedidos/urtx-le1-aviso-verra.md`.
