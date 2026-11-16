# Triagem em lote para o desenvolvedor

Lista de códigos do CAR (CSV) -> **ranking** em CSV e PDF, com nota de 0 a 100, crédito líquido P50 por ha, custo por
crédito, TIR, caminho e risco da terra, embargo, TI/UC, desmatamento e alerta recentes, `status_sobreposicao` e **o
motivo de cada nota**. Aproxima a cena-alvo (`docs/cena-alvo.md`): o desenvolvedor chega com as fazendas que está
olhando e vê em minutos quais seguem. Fora do escopo: certidão e contato com o dono.

## Como rodar

No Actions (hoje): workflow **Triagem em lote para o desenvolvedor** (`triagem-desenvolvedor.yml`, disparo manual).
O resultado vai só para o arquivo privado, como `triagem_<nome>.csv` e `triagem_<nome>.pdf`. O repositório é aberto e
a página da execução mostra as entradas: a lista da empresa diz quais fazendas ela olha. Por isso prefira a entrada
privada:

```bash
uv run raiz triagem enviar-entrada lista.csv --nome entrada-empresa.csv
```

e dispare o workflow com `entrada_privada = entrada-empresa.csv` (ou `codigos`, visíveis na execução, para um teste).
Na máquina, com a pasta `saida/` do motor restaurada, ou baixando os estados do arquivo privado:

```bash
uv run raiz triagem lote --entrada lista.csv --pasta saida --saida triagem --nome empresa-1
```

A entrada aceita CSV com cabeçalho (`cod_imovel`, `car`, `codigo_car`...), uma coluna sem cabeçalho ou texto com códigos
separados por espaço. **Só o código é lido**: outras colunas do arquivo (nome, CPF) são ignoradas, e código fora do
padrão é contado, nunca repetido em log ou mensagem. Até 5.000 códigos por lista.

## A nota

Regra em `raiz/regras/padroes/triagem_desenvolvedor.yaml` (versão em cada linha do ranking; **premissas provisórias**,
a calibrar com a primeira carteira): custo por crédito 35% (US$ 8 vale 1, US$ 25 vale 0), TIR 25% (15% vale 1, 0% vale
0), crédito líquido P50 por ha até o fim do contrato 20% (150 t/ha vale 1, 20 vale 0) e terra 20% (risco baixo 1,
médio 0,6, alto 0,25). Parte sem dado sai da conta e o peso se reparte; sem custo e sem crédito, a fazenda fica
`sem_dados` (nunca zero).

**Travas**: embargo, terra indígena, UC de proteção integral, desmatamento depois de 2020, alerta no último ano,
`ja_comprometida` (projeto ou concessão, `docs/terra-comprometida.md`) e caminho da terra que não origina limitam a
nota a 30 e põem a fazenda em `nao_segue`. **Ressalva**: `risco_sobreposicao` tira de `recomendada`. A fazenda nunca
sai da lista, **nem por ser pequena**, e código que não está nos dados fica como `nao_encontrada`.

Faixas, na ordem do ranking: `recomendada` (nota >= 70, sem ressalva), `com_ressalvas`, `nao_segue`, `sem_dados`,
`nao_encontrada`; dentro de cada uma, a maior nota primeiro. O motivo mostra cada parte (ex.: "custo US$ 9,00 por
crédito (parte 0,94); TIR 14,0% ...; terra privada com matrícula, risco baixo. Trava: embargo ativo em 12,5 ha").

## Colunas do ranking

`posicao, cod_imovel, municipio, uf, faixa, nota, ha, pequena, restauracao_area_ha, credito_p50_tco2_ha,
custo_credito_usd, tir_pct, caminho_terra, risco_terra, embargo_ha, ti_uc, desmatamento_recente_ha, alerta_recente_ha,
status_sobreposicao, projeto_id, motivo, regra_versao, gerado_em`. Lidas pelo nome nas colunas do motor
(`docs/colunas.md`), com a mesma conta da oferta para o crédito (`raiz/pedidos/oferta.py`); `status_sobreposicao`
vem de `comprometida_<mun>.csv` e, sem ele, o motivo diz "sobreposição com projetos não verificada".

## API e MCP

A mesma função (`raiz.triagem_desenvolvedor.mcp.triar_codigos`) é o endpoint **`POST /triagem/desenvolvedor`**
(`raiz/api.py`, token operacional `RAIZ_API_TOKEN`, corpo `{"codigos_car": [...]}`, resposta com `linhas`, `resumo` e
`codigos_invalidos`) e a ferramenta **`triar_fazendas`** (`ferramentas()` e `executar()` no formato de
`raiz/prospeccao_mcp.py`, até 200 códigos por chamada). **A ferramenta ainda não está registrada em
`raiz/publica/servidor_mcp.py`**: escopo, preço e limite por empresa são decisão do fundador, porque a triagem usa os
dados completos de cada fazenda; o host passa o callback `autorizar` (conta paga, escopo, auditoria).
