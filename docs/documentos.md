# Documentos (`raiz/documentos/`)

Quatro partes, um comando só (`python -m raiz.documentos --help`):

1. **Leitor de certidão de matrícula**: lê o PDF pela API da Anthropic, confere com o `certidoes_<mun>.csv` do motor e
   diz se a matrícula está **conferida**, **divergente** ou **cancelada**.
2. **Busca de registros e editais**: Verra, SFB, Ideflor-Bio e Diário Oficial da União, uma vez por semana, com a lista
   do que apareceu de novo.
3. **Documentos gerados** (docxtpl): folha de 3 páginas para o dono, relatório do lote com faixa P10 a P90 e checklist
   do edital.
4. **Aprendizado**: cada leitura fica guardada com a versão do modelo; quando a certidão real confirma ou desmente, isso
   vira gabarito e o placar mostra o acerto por modelo e versão.

Regra que vale para tudo: nome e CPF nunca vão para log, treino ou repositório (ver "Privacidade" abaixo).

## Instalar e configurar

```bash
pip install -r raiz/documentos/requirements.txt
cp .env.example .env    # preencha ANTHROPIC_API_KEY (e FIRECRAWL_API_KEY, se tiver)
```

| Variável | Para quê | Padrão |
|---|---|---|
| `ANTHROPIC_API_KEY` | leitura de certidão e edital | obrigatória para ler (sem ela, só leitura manual) |
| `RAIZ_MODELO_DOCUMENTO` | modelo que lê | `claude-opus-5-5` |
| `RAIZ_ESFORCO_DOCUMENTO` | esforço do modelo (`low` a `max`) | `high` |
| `FIRECRAWL_API_KEY` | Verra e Diário Oficial quando o acesso direto falha | sem |
| `RAIZ_DOCUMENTOS_DIR` | armazém, saídas e documentos | `dados/documentos/` (fora do git) |
| `RAIZ_DOCUMENTOS_ENTRADA` | onde estão as saídas do motor (separadas por `:`) | `motor/saida`, `dados/estados`, `dados/amostra` |
| `RAIZ_CONTATO` | como o dono fala com a Raíz (folha do dono) | frase genérica |

O back-end (`raiz/config.py`, outro branch) escolheu Sonnet 5.5 para documentos; aqui o padrão é Opus 5.5, porque ler a
cadeia de uma matrícula pede atenção. Os dois ficam gravados em cada leitura e o placar compara: para trocar, basta
`RAIZ_MODELO_DOCUMENTO=claude-sonnet-5-5`.

## 1. Certidão de matrícula

```bash
python -m raiz.documentos certidao ler certidao.pdf --imovel PA-1504950-0E3B...    # uma certidão
python -m raiz.documentos certidao lote pasta_de_pdfs/ --municipio 1504950          # todas da pasta + saída
python -m raiz.documentos certidao reconferir 12                                    # motor ou regra nova, sem pagar outra leitura
python -m raiz.documentos certidao saida 1504950                                    # matricula_<mun>.csv para o front
python -m raiz.documentos certidao ler certidao.pdf --manual leitura.json           # leitura feita por gente (modelo "humano")
```

**Como lê.** O PDF vai inteiro para o modelo (texto ou imagem: certidão escaneada também serve; acima de 30 MB vai pela
Files API e é apagado logo depois). A resposta vem em saída estruturada (`certidao/esquema.py`): cartório (nome, CNS,
comarca), matrícula (número, livro, CNM, origem, situação declarada), imóvel (município, área e unidade, SNCR, CAR,
georreferenciamento), partes **só por rótulo** (P1, P2...), todos os atos na ordem (abertura, R e AV, com natureza,
quem transmite e quem recebe, o que cancela, página) e a confiança. A reserva do servidor fica ligada: se o modelo
recusar, a própria API refaz num modelo de reserva, e o nome dele fica gravado.

**O código decide** (`certidao/regras.py` e `certidao/conferencia.py`, versionados pelo hash dos dois arquivos):

- área em hectares (ha, m², alqueire paulista 2,42, mineiro e goiano 4,84, baiano 9,68, do norte 2,72; tarefa e braça
  pedem confirmação);
- ônus ativos = ônus que nenhum ato posterior cancelou; graves = penhora, arresto, sequestro, indisponibilidade, ação
  judicial e bloqueio;
- cadeia de donos mascarada (rótulo, tipo e documento mascarado) com as quebras: alguém transmite sem ter aparecido
  antes como dono;
- encerramento, cancelamento ou transporte para outra matrícula = **cancelada** (com a matrícula de destino).

| Situação | Quando |
|---|---|
| conferida | certidão ativa e bate com o SIGEF do motor: mesmo cartório (CNS), mesmo número e área da matrícula pelo menos a da parcela SIGEF dentro do CAR (tolerância de 10% e 1 ha) |
| divergente | outro cartório, número que o motor não liga ao imóvel, área menor que a parcela, matrícula fora do certidoes_<mun>.csv ou matrícula bloqueada |
| cancelada | a certidão diz que a matrícula foi encerrada, cancelada ou transportada |
| revisar | o arquivo não deixa conferir (ilegível ou não é certidão): pedir outra cópia |

Cada motivo tem gravidade: **reprova** (decide a situação), **confirmar** (gente olha, sem mudar a situação: quebra de
cadeia, ônus grave, contrato averbado, CNS ausente, origem pouco clara no Pará pelos Provimentos 13/2006 e 02/2010 da
CGJ-PA, título público acima de 2.500 ha, georreferenciamento não averbado) ou **info** (ônus comum, certidão com mais
de 30 dias, certidão que não é de inteiro teor).

**Saída** (contrato em `docs/colunas.md`): `matricula_<mun>.csv`, uma linha por imóvel, com `matricula_conferida`, a
coluna que o selo "Matrícula conferida" do front já lê (`front/compartilhado/titulo.ts`), e
`matricula_conferencia_<mun>.csv`, uma linha por matrícula.

## 2. Busca semanal de registros e editais

```bash
python -m raiz.documentos busca semanal                 # todas as fontes
python -m raiz.documentos busca semanal --fontes sfb,dou
```

| Fonte | Como lê | O que volta como "mudou" |
|---|---|---|
| Verra (VCS, Brasil) | API antiga do registro (`uiapi`); o registro novo só abre no navegador, então vai pelo Firecrawl | a situação do projeto (ex.: Under development → Registered) |
| SFB | API do portal gov.br (`++api++`): editais em licitação, cada um com a data de modificação, e busca por edital, chamada pública, concessão e restauração | a data de modificação da página do edital |
| Ideflor-Bio | links de edital, aviso, resultado e concessão nas páginas de licitações e de concessão | — (link novo = novo) |
| Diário Oficial da União | busca do in.gov.br por frases (concessão florestal, restauração florestal, crédito de carbono, Cota de Reserva Ambiental...) | — |

Na primeira rodada de cada fonte tudo vira **linha de base** e não entra como novidade: a lista começa a valer na semana
seguinte. A lista sai em `dados/documentos/busca/novidades_<data>.md` e `.csv`. O resumo do Diário Oficial passa pela
tranca de nomes (pregoeiro, signatário); título e órgão, que são institucionais, só pela máscara de CPF/CNPJ.

**Toda semana sozinho:** o workflow `.github/workflows/busca-semanal.yml` roda segunda às 8h23 (Brasília), guarda o
estado no Release `busca`, mostra a lista no resumo do workflow e abre uma issue com a etiqueta `busca-semanal` quando
aparece coisa nova. O segredo `FIRECRAWL_API_KEY` (opcional) abre a Verra e o Diário Oficial quando o acesso direto
falha. Sem GitHub, um cron no servidor faz o mesmo: `python -m raiz.documentos busca semanal`.

Para acrescentar uma página, ponha em `raiz/documentos/busca/fontes.json`, em `paginas`: `{"nome", "url", "palavras"}`.
O Firecrawl entra só pela API hospedada: o código dele é AGPL e não pode ser instalado na Raíz.

## 3. Documentos gerados

```bash
python -m raiz.documentos gerar folha PA-1504950-0E3B... --pdf
python -m raiz.documentos gerar lote --municipio 1504950 --grupo G12 --pdf          # grupo_id do desenvolvedor_<mun>.csv
python -m raiz.documentos gerar lote --municipio 1504950 --frente carbono --nome "Piriá 1"
python -m raiz.documentos gerar edital https://.../edital.pdf --municipio 1504950 --frente carbono --pdf
python -m raiz.documentos modelos                                                    # reconstrói os .docx de modelo
```

Os dados vêm pelo nome das colunas de `imoveis`, `filtros`, `ficha`, `terra`, `desenvolvedor` e `matricula` de cada
município (o que existir). CAR que cruza divisa aparece no arquivo de outro município: passe `--municipio` do arquivo.

- **Folha do dono (3 páginas, sempre)**: 1) como está a terra (área, mata, pasto, o que pode voltar a ser mata, reserva
  legal que falta) e o que pode render, em faixa, com a regra escrita e o aviso de que é estimativa; 2) a situação da
  terra (o mesmo selo do front, agora com a conferência da certidão), até 5 pontos de atenção e até 7 documentos que
  vão ser pedidos, com o aviso de não mandar documento pessoal por mensagem; 3) próximos passos, o direito de dizer não,
  dados pessoais (LGPD), contato e glossário. Imóvel pequeno lê que entra junto com os vizinhos. Sem nome nem CPF.
- **Relatório do lote**: resumo (imóveis por porte, áreas, títulos), carbono e receita por ano em P10, P50 e P90 em duas
  contas lado a lado, **soma** (todos errando para o mesmo lado) e **carteira** (20.000 sorteios com correlação 0,5
  entre imóveis, normal de dois lados ajustada a cada P10/P50/P90, preço comum a todos), tabela por imóvel, riscos de
  título e as versões usadas. As faixas por imóvel vêm da ficha do produto (`carbono_tco2_ano_p10/_p50/_p90`) e, sem
  ela, da mesma regra provisória do back-end (faixas-2026a: 0,6 e 1,4 vezes o P50; R$ 40, 75 e 120 por tonelada).
- **Checklist do edital**: o modelo lê o edital (PDF ou página) e devolve prazos e requisitos, cada um ligado a um
  critério quando fala do imóvel (CAR ativo, sem embargo, sem desmatamento depois de 2008 ou 2020, matrícula regular,
  SIGEF, fora de TI e UC, área mínima ou máxima, bioma, UF, município, reserva legal...). O código avalia cada critério
  com os dados do motor; a área mínima vale para o lote somado, que é como as pequenas entram juntas. Saem os prazos com
  quantos dias faltam, os requisitos com a situação no lote e, por imóvel, o que atende e o que falta.

Os modelos ficam em `raiz/documentos/gerados/modelos/*.docx` e podem ser abertos no Word, desde que os campos `{{ }}` e
as linhas `{%tr %}` e `{%p %}` continuem inteiros; quem muda o texto deve mudar também `construir_modelos.py` (o teste
confere que os dois batem). PDF sai pelo LibreOffice, se estiver instalado no servidor.

## 4. Aprendizado

```bash
python -m raiz.documentos aprendizado fila                                   # o que gente precisa conferir primeiro
python -m raiz.documentos aprendizado marcar 12 --fonte cartorio --confirma --campo area_ha=290 --campo onus_ativos=0
python -m raiz.documentos aprendizado marcar 13 --fonte onr --real cancelada  # a certidão real desmente
python -m raiz.documentos aprendizado placar                                 # acerto por modelo e versão do prompt
python -m raiz.documentos aprendizado exportar pasta/                        # CSV no formato da E8
```

- Cada leitura grava: modelo pedido e modelo que respondeu, versão do prompt (hash do texto e do esquema), do esquema,
  das regras e do leitor, tokens, custo estimado, sha256 do PDF e o resultado já limpo. A leitura **nunca muda** (gatilho
  no banco) e tem um hash da linha que prova isso; ler de novo cria outra linha.
- Gabarito: a situação real e os campos conferidos (área, CNS, número, ônus ativos, ônus graves, transmissões, quebra de
  cadeia). Corrigir = marcar de novo; vale o último.
- Duas previsões aprendem com a mesma certidão: a do **leitor** (`titulo_matricula_situacao`) e a do **motor**, que
  disse que a matrícula do SIGEF vale para o imóvel (`motor_matricula_valida`). O motor só ganha gabarito de leitura
  confirmada por gente ou feita por gente.
- `exportar` grava `previsoes_documentos.csv` e `gabaritos_documentos.csv` com as colunas de `aprendizado.previsao` e
  `aprendizado.gabarito`; `exportar --banco` registra direto no PostgreSQL (`RAIZ_BANCO_URL`), um lote congelado por
  leitura, e pode rodar de novo sem repetir linha. Data de corte = emissão da certidão (sem ela, o dia anterior à
  leitura); horizonte de 30 dias (validade da certidão). O acerto aparece em `aprendizado.previsao_contra_gabarito`.

## Privacidade

1. O prompt proíbe nome de pessoa, RG, endereço e CPF inteiro; o esquema não tem campo de nome (só órgão público e
   banco podem ter o nome da instituição; para qualquer outra parte o campo é zerado no código).
2. Todo CPF e CNPJ é mascarado (`***.456.789-**`, `**.345.678/****-**`) com as mesmas regras do front e do back-end; o
   documento de uma parte nunca volta inteiro, nem com dígito errado.
3. Os textos livres (resumo de ato, observação, resumo do Diário Oficial) passam por uma tranca de nomes que troca por
   `[nome]` qualquer sequência de palavras com cara de nome próprio que não seja vocabulário de registro, lugar ou
   instituição. Erra para o lado de apagar.

O PDF da certidão não é copiado: só o sha256 fica. A tela mostra arquivo pelo sha256, nunca pelo nome do arquivo
(nome de arquivo costuma ter o nome do dono). `dados/documentos/` está no `.gitignore`. Os testes conferem que, mesmo
com um modelo que desobedece e escreve nome e CPF, nada disso chega ao armazém.

## Testes

```bash
pip install pytest
python -m pytest testes/ -q
```

Sem rede e sem chave: o cliente da API é simulado (`raiz/documentos/simulacao.py`, certidão e edital fictícios) e os
dados são os da `dados/amostra/`. O teste das 3 páginas da folha roda quando o LibreOffice está instalado.

## Limites conhecidos

- **Verra**: o registro migrou para uma plataforma nova que só abre no navegador; sem `FIRECRAWL_API_KEY` a fonte aparece
  como "não deu para consultar". Quando a Verra publicar a API nova, trocar `verra.api` em `fontes.json`.
- **Diário Oficial**: o portal às vezes recusa conexão de fora do Brasil; o Firecrawl (com localização Brasil) cobre.
  Diário Oficial do Pará (onde o Ideflor-Bio publica) ainda não entra: acrescentar em `paginas` quando houver busca
  pública estável.
- **CNS**: muita certidão não imprime o CNS do cartório; aí a conferência é pelo número e pede confirmação.
- **Selo prata no back-end**: a máscara já vem de `raiz/privacidade.py`, mas a carga (`raiz/carga.py`) ainda não lê o
  `matricula_<mun>.csv`; enquanto isso o `matricula_conferida` não chega ao `selo_prata` de `raiz/terra.py` nem ao
  caminho `matricula_conferida` do pedido de lote. Falta pôr `matricula` nas tabelas da carga e do contrato.
- **ONR**: quando o convênio sair (E5 passo 9), as certidões podem chegar pelo Monitor Registral e entrar em
  `certidao lote` sem passo manual.
