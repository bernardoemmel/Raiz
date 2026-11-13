# Rodada 12 — evidências e integração do motor

Trabalho em andamento em 12/11/2026 (horário de Brasília). Previsões da rodada 11
continuam imutáveis. Implementações e fontes abaixo ainda precisam ser integradas
ao recálculo dos três lotes; não são resultados novos do Pará.

## VCS 5511: reprodução contábil

[Registro público](https://registry.verra.org/verra/public/program/VCS/projects/5511),
planilha `VCS5511_BrazilARR_ExPost_20260303.xlsx`, aba `VCUs`, células F4, I4, G4,
J4, E14 e G14; relatório AENOR de abril de 2026. Janela 18/08/2022–31/05/2025.
SHA256, fonte, período e licença estão em `rodada12_referencias.json`.

| Etapa | Denominador | Desconto |
|---|---|---|
| Linha de base | ganho bruto de 329.303,66 t | 16,57553% |
| Incerteza | adicional após linha de base, 274.719,833 t | 4,81216% |
| Vazamento | quantidade absoluta | 0 t |
| Reserva histórica | adicional após incerteza, 261.499,875 t | 12% |

Resultado com entradas arredondadas: **230.119,890 t**, dentro de 230.120 ±1 t.
A planilha com precisão completa informa 230.119,897 t. O cenário contábil
`verificado_5511` identifica os 69,88% históricos. Para planejamento novo, mantém
reserva mínima de 20% e explicita o resultado de 209.199,900 t com as demais
entradas iguais. `conservador_plantio_pasto` preserva 57% como premissa agregada.
Nenhum cenário contábil libera comercialização ou substitui salvaguardas.

O projeto verificado contém 14.097,2 ha de eucalipto e 2.843,4 ha de restauração
nativa. Sua contabilidade não valida uma curva de plantio nativo na Amazônia.

## Mombak: janela inicial do plantio

[Isometric, projeto 84R7](https://registry.isometric.com/project/prj_1KA95092G1S093EM),
relatório 350Solutions v1.2 de 06/11/2026, publicado em 12/11/2026:

| Sítio | Área | Período | Remoção verificada antes da reserva | Por hectare |
|---|---:|---|---:|---:|
| Vale do Candiru | 768,5 ha | 30/04/2024–11/08/2026 | 20.255,66 t | 26,3574 t/ha |
| Três Irmãos | 259,5 ha | 28/09/2023–11/08/2026 | 8.372,55 t | 32,2642 t/ha |

O ajuste inicial usa os dois acumulados, não os vintages rateados por área-mês.
É uma aproximação regional pela idade do projeto, sem inventário por coorte.
Preserva estoque no ano 7 e total no ano 40, e mantém a incerteza explícita do
modelo: dois sítios não sustentam quantis empíricos regionais. A curva ajustada e
as diferenças anterior/ajustada ficam versionadas, rotuladas **“estimativa regional,
não medida na fazenda”**, sem alegar validação independente.

O relatório informa aproximadamente 1.667 mudas/ha. A mitigação do gado usa 462 e
156 cabeças a 0,228 t/cabeça; essas emissões foram excluídas pelo verificador por
materialidade. O fator arredondado dá 105,336 e 35,568 t; o documento arredonda
105,35 e 35,57 t. Não se descontam novamente das remoções publicadas.

## Regeneração e linha de base

- [Cardoso et al., Dryad](https://doi.org/10.5061/dryad.6t1g1jxdp): CC0, 126 parcelas,
  16 municípios e 74 observações comparáveis ao satélite. Downloads da página
  retornaram 403 e da API 401 neste ambiente; metadados e hashes estão acessíveis.
  O validador está implementado, mas o erro real por idade **ainda não foi calculado**.
  Faz junção espacial estrita com a malha IBGE e exclui municípios inteiros do
  ajuste e dos resíduos usados nos intervalos. Alvo: biomassa aérea em Mg/ha,
  sem convertê-la silenciosamente em crédito líquido.
- [Zenodo 15120870](https://zenodo.org/records/15120870): **CC BY 4.0** confirmada;
  idade de regeneração tropical, 30 m, referência 2023. Não é idade futura do pasto.
- `restauracao_linha_base.py`: médias ponderadas em blocos espaciais, máscara fixa,
  controles previamente elegíveis e pesos pysyncon estimados apenas no pré-plantio.
  Mudanças no pós não alteram os pesos nem o hash do treinamento.
- `infra/scpi`: processo isolado de servidor, GPL-3.0-only, sem importação pelo
  pacote `raiz` e excluído do sdist. Intervalo nominal de 80% não é apresentado
  como quantis P10/P90. Validado em painel sintético; dados reais continuam pendentes.

## Ainda por concluir nesta rodada

Implementados e integrados no cenário explícito `central_r12`: forma inicial de
plantio amazônico, Fundo Clima por tranche fixa de referência, preço de US$ 59,20,
arrendamento SFX de R$ 842,83 (“Censo 2017 corrigido”), provisão de certidão conjunta
e georreferenciamento sobre a área integral disponível. Uma certidão por CAR sem
contagem de matrículas é somente provisão mínima; escopo topográfico fica pendente.
Taxas Verra entram uma vez por projeto, com abatimento do adiantamento de emissão.
A faixa de mudas é orçamento separado: não somar novamente ao custo SFB que já
inclui implantação. R11 permanece cenário histórico explícito.

CVXPY dimensiona dívida por ICSD e conta reserva. Sem caixa no primeiro período
após a carência, juros positivos tornam impossível dívida positiva: retorna zero,
sem capitalizar juros escondidos fora do prazo contratado. O motor anual declara
sua aproximação; o módulo também aceita fluxos mensais.

PuLP/NetworkX alocam UA sem duplicar capacidade entre origens, guardando lotação
antes/depois. Encontrar vizinha não zera mais vazamento na R12: exige documentos
com hash e revisão humana, capacidade seca e rastreio. O exemplo VCS 3743 reproduz
2.500 UA em três destinos; sua capacidade regional histórica não é medição do mês
seco destas fazendas. Sensibilidade de 12% da área/150 km nunca vira desconto de
crédito automaticamente. Credibilidade calcula e divulga peso local/coorte;
sem inventário local o peso é zero, nunca se inventam parcelas.

Validação focada em 13/11 UTC (12/11 Brasília): **67 testes passaram**. Ainda faltam
sensibilidade com nova seleção, referências ecológicas no produto,
recálculo/publicação privada e comparação final dos três lotes, suíte integral,
PR e merge. O Dryad continua sem download acessível neste ambiente; não há MAE
real calculado nem controle sintético real sem painel pré/pós disponível.
