# Passagem — Lote e números

## Entrega de 12/11/2026: cálculo e salvaguardas da rodada 11

Área: `raiz/lote.py`, `raiz/lote_relatorio.py`, `raiz/restauracao*.py`, `raiz/regras/`, testes e documentação.
Sem alteração na API, no MCP ou no código do front. Exceção autorizada pelo fundador: o teste de complementos
passa a exigir arquivos obrigatórios, excluir `certidoes_` e aceitar novos arquivos de uma linha por imóvel.
O workflow novo é a infraestrutura necessária para rodar o pedido no Actions.

- Modelo `restauracao-2026d`: reserva contra reversão nunca abaixo de 20%; inclui hash do código e premissas.
  O ICVCM 9.4(a)(5)(i) prevê essa alternativa; 9.4(a)(5)(ii) também permite ajuste proporcional ao risco.
  A Raíz adota o piso conservador solicitado. Não é uma afirmação de piso universal obrigatório em qualquer padrão.
- Preço mínimo por fazenda para TIR de 12% e 15%, projeto e alavancada, dívida pelo ICSD; corrigida participação do
  dono no período de duas fases. Fluxo do lote e preço por fazenda são conferidos separadamente.
- Três alternativas do mesmo solver: barata, segura e compacta. A compacta não reaplica bônus genérico de vazamento
  sobre créditos que já foram calculados líquidos. Pequenas continuam candidatas, sem corte por tamanho.
- Sobreposição jurisdicional confirmada bloqueia seleção; situação desconhecida permanece potencial, sem liberar
  venda. Camada opcional `jurisdicional_<mun>.csv` e função espacial `cruzar_jurisdicional` com fonte/vigência.
  Lei 15.042, art. 43 §§6,7,11,13: falta comprovar exclusão e período para não contar duas vezes.
- Território tradicional exige CLPI custeada pelo desenvolvedor e partilha comprovada: mínimo 50% para remoção,
  70% para REDD+ de mercado (art. 47). Ausência de consentimento não é autorização.
- Decisões e risco: JSONL com critério textual, versão e ID estável; revisão humana por protocolo persistente
  em SQLite (`pedir_revisao_humana`). A revisão não libera crédito automaticamente. A API para esses pedidos
  não foi alterada, conforme divisão de trabalho.
- Falta de dado de pasto não gera crédito sobre a área livre inteira: situação `pendente_pasto`, sem afirmar que
  a fazenda não tem potencial. Não confundir informação ausente com área zero observada.
- O lote recusa mistura de previsões antigas com fluxos do modelo atual. Fixtures históricas permanecem no git;
  o teste do lote recalcula uma cópia temporária antes de comparar.

## Execução e publicação

`.github/workflows/lote-para.yml`, comando `python -m raiz.restauracao_rodada`: congela os IDs e hashes dos pacotes
`raiz_PA.tar.gz` e `raiz_geo_PA.tar.gz` do Release `dados`, distribui 144 municípios por 15 jobs, confere versões e
cobertura, monta as três opções e publica pacotes imutáveis por execução. O ponteiro `lote_PA_central_r11.json` sobe
por último. Não substitui os pacotes originais do motor e não grava dados grandes no git.

Inspeção inicial: 144 municípios e 345.870 imóveis no pacote publicado; sem tabelas de desenvolvedor e terra,
APP pela escadinha presente em 81 municípios. Usa somente dados congelados; não executa downloads geográficos novos.
Piloto de Nova Esperança do Piriá: 880 imóveis reais calculados, três opções e todos os arquivos gerados localmente.
Execução integral/publicação: **pendente de rodar o workflow depois do merge do código**. Esta passagem será atualizada
com URL da execução, hashes e números quando a publicação terminar.

## Comparação com o real

O snapshot publicado de Nova Esperança ainda coincide com a exportação antiga: 222.694 tCO2/ano e 40.325,22 ha de
pasto. O documento `docs/teste-real-2026-11-12.md` relata a coleta atualizada com 209.708 tCO2/ano e 37.736 ha.
São fontes/coleções distintas, não medições de crescimento realizado. Não aplicar um fator de 5,8% à captura.
O relatório identifica a fonte efetivamente usada, compara por CAR e guarda hashes; o registro de previsões é
imutável por modelo e entradas. A publicação de uma coleta mais recente permanece dependente do fluxo de dados.

## Ecologia regional: fontes verificadas e pendências

O fundador confirmou ausência de inventário próprio e autorizou estimativa regional ou pendência quando as fontes
abertas não bastarem. `ecologia_PA.json` contém, por fazenda, os horizontes 3/5/10/15, bioma, método, versão,
fontes e licenças, com o rótulo **“estimativa regional, não medida na fazenda”**. Nesta rodada os quantis de árvores
e espécies ficam nulos com justificativa; nulo não é zero. O modelo ecológico `ecologia-2026b` inclui hash do código
e do YAML; os arquivos publicados são imutáveis por execução para confrontar com inventário futuro.

| Fonte pública examinada | Licença dos dados | Resultado da auditoria |
|---|---|---|
| [IFN/SFB, set/2025](https://dados.florestal.gov.br/dataset/ifn-dap-10-por-uf_disp-set2025) | CC-BY, versão não indicada no portal | Há microdados regionais, mas sem vínculo de idade e método de restauração; DAP10 e regenerantes têm esforços distintos. |
| [Rozendaal 2019, DANS](https://doi.org/10.17026/dans-xh8-gh92) | CC0-1.0; artigo NC apenas citado | Riqueza padronizada em 25 fustes, sem densidade absoluta. Seis sítios usam DAP10; falta confirmar a correspondência S1/S2 para o recorte brasileiro. Não usar como riqueza total por fazenda. |
| [Poorter 2021 / 2ndFOR](https://github.com/dylancraven/MultiDimensional_Recovery) | CC-BY-2.0 no repositório | Recuperação relativa dos atributos; não fornece diretamente árvores/ha ou espécies absolutas por fazenda. |
| [Giles 2024, Zenodo](https://doi.org/10.5281/zenodo.13970371) | CC-BY-4.0 | Candidato de densidade de fustes e riqueza por 100 fustes. CSV v1 tem 514 linhas/22 sítios, distinto das 448 parcelas/24 sítios do artigo. Protocolos misturam DAP, diâmetro basal e áreas aninhadas; o artigo/suplemento diverge sobre 1/3 sítios DAP10. Não incorporados quantis sem harmonização. |
| [MapBiomas, vegetação secundária](https://brasil.mapbiomas.org/downloads/assets-no-google-earth-engine/) | CC-BY, versão não explicitada na brochura oficial | Falta vincular pixels à coorte do projeto. A idade da vegetação existente não se aplica ao pasto que será restaurado; `sec_idade_media` atual vem do YbYrá, não do MapBiomas. A restauração futura começa na idade zero. |
| [Pacto pela Restauração da Mata Atlântica](https://doi.org/10.1177/1940082917697265) | Artigo CC-BY-NC-3.0, somente referência | Protocolo de medição; sem distribuição aberta por idade para gerar quantis. Não foram incorporados texto, código ou coeficientes NC. |
| [Rede de Sementes do Xingu](https://www.sementesdoxingu.org.br/restauracao-ecologica/) e [Freitas 2018](https://repositorio.unb.br/handle/10482/32438) | Licença aberta dos microdados não confirmada | Monitoramento e estudo de 72 áreas/1–10 anos; mistura de espécies semeadas e mudas iniciais não mede sobrevivência futura ou riqueza estabelecida. |

Os SHA256 dos dados candidatos baixados e as referências de licença ficam no YAML. **Pendências:** harmonizar
protocolos e parcelas, identificar árvores distintas de fustes, obter coortes abertas para plantio/semeadura,
vincular idade espacial à área restaurada e validar quantis. Não converter médias/desvios dos artigos nem metas
normativas em P10/P50/P90. A referência SMA/SP de regenerantes permanece separada, sem ser previsão para o Pará.

## Validação

Testes específicos de reserva, preço, salvaguardas, três opções, comparação, persistência e workflow.
Ruff global conferido. A contagem final de testes e links do CI serão registrados na entrega da execução integral.
