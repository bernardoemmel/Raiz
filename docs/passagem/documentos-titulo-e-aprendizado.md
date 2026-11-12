# Passagem: documentos, título (E5) e aprendizado (E8)

Chat que cuidou de `raiz/documentos/`, do título (E5) e do aprendizado contínuo (E8). Parou por fim de cota em
12/11/2026, com o PR #35 aberto.

## O que este chat fez

- PR #24 (merge): `raiz/documentos/` — leitor de certidão de matrícula pela API da Anthropic, conferência com o
  `certidoes_<mun>.csv`, busca semanal de registros e editais, documentos docxtpl, aprendizado das leituras.
- PR #29 (merge): coluna "Situação" do E5 e do E8 em `docs/plano-por-etapa.md`.
- PR #35 (aberto, ver abaixo): E5 passos 1 a 8 e parte do E8, em quatro blocos:
  - regularização da posse (`raiz/titulo/regularizacao.py`), achados no formato do CFPB e confirmações
    (`raiz/titulo/achados.py`, `banco.py`, migração 0021);
  - memorial, planilha ODS, geometria D1 a D7 e nota de risco 1 a 5 (`memorial.py`, `planilha.py`,
    `geometria.py`, `nota.py`, `tarefa.py`);
  - cadeia dominial no Postgres (migração 0022, `raiz/documentos/certidao/cadeia.py`, `raiz/titulo/cadeia.py`),
    contexto e auditoria (`contexto.py`), localização da sede pelo WhatsApp (`sede.py`, `raiz/whatsapp.py`), laudo
    HTML/PDF (`laudo.py`, `modelos/laudo.html.j2`), WARC cifrado (`warc.py`), triagem (`triagem.py`);
  - E8: sorteio das conferências, Hájek e Olofsson (`raiz/aprendizado/sorteio.py`, migração 0023), calibração por
    UF e porte (`calibracao.py`), folds anuais (`folds.py`), campeão e desafiante (`campeao.py`, migração 0024).

## Onde parou

- PR #35 recebeu o merge da main (#39, #41), as migrações foram renumeradas (0021 a 0024, depois da
  `0020_alertas_operacao` da main) e o E8 local foi juntado. Falta: CI verde no PR e o merge.
- O pedido novo do fundador, **Calendário da Raíz**, não foi começado (nenhum arquivo).

## O que falta, em ordem

1. PR #35: se o CI falhar, ler o log (`checagens`), corrigir e empurrar; com verde, merge (squash). Se a main tiver
   migração nova com o mesmo número, renumerar as quatro deste PR em sequência (`revision` e `down_revision`) e
   atualizar os números citados em `docs/plano-por-etapa.md` (E5 passos 1 e 6, E8 passo 6).
2. Calendário da Raíz (pedido do fundador, texto completo na conversa de 12/11/2026): tabela de eventos no banco
   (tipo, data, prazo, UF/município, fonte com link, data da coleta, confiança; leilão ligado ao código do CAR, CPF/
   CNPJ sempre mascarado, nunca nome), coleta diária automática (Firecrawl, DOU e diários estaduais, sites
   oficiais; reaproveitar `raiz/documentos/busca/`), cruzamento de leilões e penhoras com CAR/SIGEF, marca "em
   leilão" no mapa e aviso a quem tem lote com a fazenda, rota `GET /eventos` (filtros tipo, estado, período) em
   `raiz/api.py`, feed `.ics`, ferramenta MCP `proximos_eventos` (não há servidor MCP no repositório: deixar a
   função pronta), aba "Calendário" no site com filtros, testes com páginas gravadas, atualizar o plano.
3. E8 que falta: folds para o motor e os outros modelos a partir do scd2 (`folds.como_estava`); sobrevivência do
   aceite (tempo até o aceite; lifelines é MIT); MCGrad e mapaccuracy só depois de conferir a licença; SQLMesh e
   Dagster (passos 1, 2 e 7) seguem trocados pelo executor próprio — decidir com o fundador antes de mexer.
4. E5 passo 9 (convênio ONR): o pedido está pronto em `docs/pedidos/onr-convenio.md`; o envio é do fundador.

## PRs abertos e branches sem merge

- PR #35, branch `claude/vibrant-knuth-qygs43` (tudo deste chat está nela).
- Branches locais `entrega-c`, `entrega-c-pronta`, `entrega-cd`, `e8-aprendizado`: já juntadas na do PR; não
  foram empurradas e podem ser apagadas.

## Actions

- O processamento dos estados ("Processar estados") roda sozinho e ocupa os executores; o CI dos PRs pode ficar
  na fila. Não cancelar. Conferir: aba Actions do repositório ou `mcp__github__actions_list` (list_workflow_runs).

## Decisões e cuidados

- Migrações: a main recebe migração de outros chats o tempo todo. Antes do merge, conferir
  `git ls-tree origin/main migracoes/versions/` e manter uma cabeça só (`uv run alembic heads`).
- O `capture_http` do warcio só grava se for importado antes do `requests` no processo: não serve aqui; o WARC é
  montado da resposta (`warc._registros`) e cifrado com `RAIZ_CHAVE_PESSOAL` (página do SIGEF traz nome).
- CAR "PE" (pendente) não segura a regularização; só ocupação e área limite a conferir seguram "pronta".
- Classes D3 a D7 são só pela sobreposição (IoU); área e afastamento ficam na mensagem.
- `normalizar_matricula` e `titulo.norm_matricula` (SQL) têm de dar o mesmo resultado; '5178.0' vira '5178',
  '5.000' é milhar e vira '5000'. Há teste comparando os dois.
- Testes de banco que dependem de hash da carga usam coluna `teste_marca` e datas próprias; o de triagem usa
  datas sorteadas porque o aprendizado só aceita linhas novas.
- Olofsson com fazendas muito grandes: estimativa sem viés, mas o intervalo cobre ~85%; o teste mede isso em 8
  réplicas.
- Folds: por padrão o treino usa gabarito observado até o corte; `--pelo-registro` também exige registrado até lá.
- Force push foi negado pelo classificador: usar merge comum.

## Testes desta parte

PostgreSQL com PostGIS local (ou o do CI) e:

```bash
export RAIZ_BANCO_URL_TESTE=postgresql+psycopg://raiz:raiz@localhost:55432/raiz_teste
```

```bash
uv run pytest -q testes/test_titulo.py testes/test_titulo_geometria.py testes/test_titulo_cadeia.py testes/test_titulo_laudo.py testes/test_sorteio.py testes/test_campeao.py testes/test_documentos_certidao.py testes/test_aceite.py
```

```bash
uv run ruff check raiz testes scripts migracoes && uv run raiz privacidade varrer && uv run python scripts/checar_licencas.py
```
