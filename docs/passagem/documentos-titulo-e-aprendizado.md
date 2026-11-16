# Passagem: documentos, título (E5), aprendizado (E8) e terra comprometida

Chat que cuidou de `raiz/documentos/`, do título (E5), de partes do aprendizado (E8) e, por último, da camada "já
comprometida" e da triagem em lote para o desenvolvedor. Atualizada em 16/11/2026, uma vez, no fim.

## O que este chat fez (PRs)

- #24 documentos: leitor de certidão, busca semanal, documentos docxtpl, aprendizado das leituras.
- #29 situação do E5 e do E8 no plano.
- #35 E5 passos 1 a 8 (regularização da posse, achados, memorial e geometria, nota, cadeia dominial, contexto, sede,
  laudo, WARC, triagem do título) e parte do E8 (sorteio, calibração, folds, campeão e desafiante). Mesclado.
- #126 **Terra já comprometida no processamento** (mesclado): `raiz/comprometida/` (coleta e status), workflow
  `coletar-comprometida.yml` (diário, publica no Release `insumos`), tarefa própria do executor `comprometida`
  (folha do grafo, versão própria, não passa por `raiz/funil/rodar.py`), `comprometida_<mun>.csv`, contorno cinza no
  mapa (`comprometidas` em `MapaBrasil`), `docs/terra-comprometida.md`, `docs/colunas.md`, `NOTICE.md`.
- #129 **Triagem em lote para o desenvolvedor** (este PR): `raiz/triagem_desenvolvedor/`, regra
  `raiz/regras/padroes/triagem_desenvolvedor.yaml`, `raiz triagem lote`, workflow `triagem-desenvolvedor.yml`,
  `POST /triagem/desenvolvedor`, ferramenta `triar_fazendas` (`mcp.py`), `docs/triagem-desenvolvedor.md`.

## Onde parou

Tudo entregue. Nada em andamento. Pendências abaixo são de decisão ou de uso real, não de código começado.

## O que falta, em ordem

1. **Fundador:** conferir a decisão de licença. Os limites da Verra e do SFB (sem licença de redistribuição declarada)
   vão ao Release aberto `insumos` por pedido seu (exceção registrada no `NOTICE.md`). Se não quiser, apagar os
   arquivos do Release e desativar `coletar-comprometida.yml`.
2. Rodar o workflow `coletar-comprometida.yml` uma vez à mão (`limite_verra` pequeno) e ver a cobertura de cada fonte
   no log; a coleta real não foi executada daqui. Depois, o `processar-estados.yml` já baixa o
   `projetos_carbono.tar.gz` do `insumos` (conferir `projeto_carbono_ha` diferente de 0 num estado).
3. Rodar a tarefa `comprometida` nos municípios prontos (`raiz comprometida baixar` e `raiz comprometida recalcular`,
   ou o executor): só ela muda; o funil não refaz.
4. Pedir ao chat Dados: (a) contagem por status e município em `COLUNAS_RESUMO` de
   `raiz/executor/publicacao_aberta.py` (público só agregado); (b) a área logada passar `comprometidas` (CAR com
   `ja_comprometida`) ao `MapaBrasil`, que hoje não recebe o conjunto.
5. Disparar o workflow `triagem-desenvolvedor.yml` uma vez com uma lista pequena em `entrada_privada` e conferir
   que baixa `raiz_<UF>.tar.gz` do arquivo privado e envia `triagem_<nome>.csv/.pdf`. Não foi rodado contra o arquivo
   real (sem o token). Se o nome dos assets ou o conteúdo dos pacotes for diferente, ajustar em
   `raiz triagem lote` (`raiz/cli.py`).
6. Decidir escopo, preço e limite do MCP e registrar `triar_fazendas` em `raiz/publica/servidor_mcp.py` (a função já
   está pronta; falta o callback `autorizar` do host).
7. Calibrar as premissas da nota da triagem (pesos e faixas em `triagem_desenvolvedor.yaml`) com a primeira carteira.
8. E8 que ficou: folds do motor e dos outros modelos a partir do scd2; sobrevivência do aceite (lifelines, MIT);
   MCGrad e mapaccuracy só depois de conferir a licença. E5 passo 9 (convênio ONR): envio é do fundador.

## PRs abertos e branches sem merge

Nenhum PR aberto deste chat depois do #129. Branches locais antigas (`entrega-*`, `e8-aprendizado`) já estão na main.

## Actions

- `coletar-comprometida.yml` roda sozinho às 04h23 de Brasília e publica no `insumos`: conferir na aba Actions.
- O processamento dos estados segue sozinho; não cancelar.
- O job `front` do CI às vezes cai no Lighthouse por 1 ponto (89 contra 90) sem relação com a mudança; uma reexecução
  resolveu.

## Decisões e cuidados

- `raiz/funil/rodar.py` entra no hash de TODAS as tarefas (`raiz/executor/tarefas.py`, `historico`): mexer nele refaz o
  funil de todos os municípios. Por isso a tarefa `comprometida` roda por função própria e não está em `TAREFAS`.
- `livre` só quando alguma fonte cobriu a área; coleta indisponível ou ausente é `nao_verificado`, nunca `livre`.
- O capture_http do warcio só grava se importado antes do `requests`: o WARC do título é montado da resposta.
- O varredor de CPF do CI recusa até CPF fictício literal em teste: usar `cpf_ficticio()`.
- Modelo de API em FastAPI com `from __future__ import annotations` precisa ficar no nível do módulo (dentro da
  função vira parâmetro de query e dá 422).
- Migrações: a main recebe número novo de outros chats o tempo todo; conferir `alembic heads` antes de mesclar.
- Falhas locais conhecidas e alheias a este trabalho (também na main): `test_armazem_release`, `test_rodadas_fontes`,
  `test_snapshot_publicacao`, `test_publicar_metadados`, `test_verificar_release_dados` (ambiente local).

## Testes desta parte

```bash
export RAIZ_BANCO_URL_TESTE=postgresql+psycopg://raiz:raiz@localhost:55432/raiz_teste
```

```bash
uv run pytest -q testes/test_comprometida.py testes/test_triagem_desenvolvedor.py testes/test_executor.py testes/test_titulo.py testes/test_titulo_cadeia.py testes/test_titulo_laudo.py testes/test_sorteio.py testes/test_campeao.py
```

```bash
uv run ruff check raiz testes scripts migracoes && uv run ruff format --check raiz testes scripts migracoes && uv run raiz privacidade varrer
```
