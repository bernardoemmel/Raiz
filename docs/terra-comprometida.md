# Terra já comprometida: fontes, geometria e certeza

A camada é privada e pertence à ficha paga. Cruza o polígono do CAR com limites
de projetos e concessões; guarda fonte, identificador público, data da fonte
quando disponível e data da consulta. Não coleta nomes, documentos ou contatos
dos proprietários. O catálogo versionado fica em
`raiz/terra_comprometida_fontes.json`.

| Fonte | Uso | Limitação |
|---|---|---|
| [Berkeley Carbon Trading Project](https://gspp.berkeley.edu/berkeley-carbon-trading-project/offsets-database), v2026-08 | Descoberta de projetos brasileiros dos registros ACR, ART, CAR, Gold Standard, Isometric e Verra | Catálogo sem limites; um registro no estado não comprova compromisso do CAR |
| [Verra Registry](https://verra.org/registry/overview/) | Consulta pública por ID e documento explicitamente classificado como limite KML | Sem contornar autenticação; ausência de KML ou falha da fonte fica como cobertura parcial/indisponível |
| [Serviço Florestal Brasileiro](https://www.gov.br/florestal/pt-br/assuntos/concessoes-e-monitoramento/concessoes-florestais-em-andamento) | Interseção de UMFs com concessões federais | Nem todos os contratos têm geometria; concessão não comprova exclusividade de carbono |
| [ART](https://artredd.org/art-september-2026-newsletter/) e `geo.redd_programa` | Contexto jurisdicional dos programas REDD+ | Não soma área comprometida individual nem afirma vínculo contratual de cada CAR |
| [Base científica de limites](https://doi.org/10.5281/zenodo.11459391), CC BY 4.0 | Polígonos secundários do Brasil, incluindo EcoRegistry | Indício, nunca confirmação automática; pontos são excluídos; status atual desconhecido |
| [InfoAmazonia, "Carbono sujo"](https://github.com/InfoAmazonia/unid_geojornalismo/tree/main/2025_06-carbono_sujo) (2025) | Limites de 111 projetos na Amazônia (Verra e Cercarbono), a partir dos KML dos registros | Indício; status da época da reportagem; repositório sem licença declarada: uso interno com crédito, sem redistribuir o bruto; CNPJ e empresa nunca são lidos |
| [REDD+ no Pará](https://doi.org/10.5281/zenodo.23929936), Paim, West & Silva, CC BY 4.0 (nov/2026) | Limites de 24 projetos REDD+ no Pará (linhas "KML Projeto") | Indício; sem status atual; os recortes de sobreposição com CAR, SIGEF e glebas não são lidos |

Na verificação de desenvolvimento, Berkeley continha 433 projetos brasileiros,
219 de florestas e uso da terra, incluindo 206 VCS. Foi possível consultar o
projeto público Verra 665 e seu KML. O índice científico inclui 34 polígonos
Verra, seis EcoRegistry e um ponto ACR, descartado do cálculo de área. Esses
achados comprovam acesso às fontes, não uma coleta nacional concluída. As fontes
mudam e cada execução registra sua própria cobertura. Não existe promessa de
cobertura integral de todos os registros.

## Como interpretar a ficha

- **Sobreposição confirmada:** interseção com limite oficial de objeto ativo,
  com fonte e data de consulta. Confirma a sobreposição, não a titularidade ou a
  exclusividade contratual do carbono.
- **Indício:** interseção com polígono secundário ou evidência insuficiente para
  confirmar o compromisso atual. Exige diligência.
- **Sem sobreposição identificada:** nenhuma interseção nas fontes e recortes
  efetivamente consultados. Não é certidão de terra livre.
- **Não verificado:** sem geometria do CAR, sem cobertura suficiente ou sem
  fontes consultadas. Áreas desconhecidas permanecem `null`, não zero.

O cálculo usa a união das interseções, em hectares na projeção métrica SIRGAS 2000 (EPSG:5880); áreas de indício
excluem a área já confirmada para não contar a mesma terra duas vezes. Programas
jurisdicionais são mostrados separadamente, com área individual `null`. Datas de
registro, início e término de projeto não substituem a data da geometria.
Uma fonte parcial que omite um projeto não apaga sua evidência anterior;
retirada/inatividade explícita muda o estado. A alteração fica no histórico.

## Fontes secundárias e o caso YBYRÁ (17/11/2026)

O imóvel PA-1505502-A5BAFA27 (Paragominas) tem ~1.469 ha (45% do CAR) dentro do YBYRÁ REDD+ (VCS4681, registrado
na Verra, um KML oficial "Project Boundary"). Três bases independentes confirmam: o KML da Verra, a InfoAmazonia e o
GeoPackage REDD+ do Pará (que lista o próprio CAR com 1.458 ha). A Raíz marcava `projeto_carbono_ha = 0` por dois
motivos, ambos corrigidos:

1. **A coleta nunca terminou.** Em 16/11, um KML de outro projeto trazia prefixo XML sem declaração (`gx:`), o
   leitor levantava `ParseError` (não é `ValueError`) e o workflow caía depois de 22 min, sem publicar nada. Sem o
   Release `insumos`, o motor não tinha mapa nenhum e todo imóvel saía com 0. Agora o KML é relido sem os prefixos;
   o que continuar ilegível vira "projeto sem geometria" e a fila segue.
2. **O primeiro erro parava a Verra inteira.** Qualquer projeto com problema próprio (sem polígono, fora do Brasil)
   encerrava a fila. Agora só falhas da fonte (rede, 429, 5xx, com 3 tentativas e espera) contam, e a fila para
   depois de 5 seguidas. Há pausa de 0,5 s entre chamadas.

Na conferência com a coleta real (17/11) apareceram mais três falhas do mesmo tipo, também corrigidas: um polígono
inválido do SFB (Amapá UMF IV) fazia sumirem todas as 22 UMFs; um polígono da base científica (Zenodo 11459391)
derrubava a base inteira; e um KML com anel em laço (VCS1382) virava coleção com linha. Agora cada geometria é
consertada e fica só a parte com área; o que não tiver área sai sozinho, sem levar o resto junto.

As duas bases secundárias entram na coleta diária como **indício**: sozinhas deixam o imóvel em
`risco_sobreposicao` (nunca `ja_comprometida`); com o KML oficial e ativo da Verra, o imóvel vira `ja_comprometida`
e o indício não conta a mesma terra de novo. Elas cobrem o que o registro deixa de fora (KML ilegível, projeto só com
"Other", registro fora do ar). Cada uma é baixada de endereço fixo e conferida por checksum (InfoAmazonia: commit
`350f832`, sha256 dos quatro arquivos do shapefile; Zenodo: md5 e tamanho publicados). Arquivo mudou = coleta da
fonte vira `indisponivel`, nunca terra livre.

**Filtro de sanidade do tamanho.** Projetos agrupados e programas publicam uma "área geográfica" enorme (VCS3380 e
VCS4137 têm ~210 milhões de ha; VCS4796, VCS5117, VCS5938 passam de 10 milhões). Estar dentro dela não é
compromisso. Mas há REDD grande de verdade (VCS1811, ~909 mil ha, confirmado por três bases). Por isso dois degraus,
e cada caso sai no log da coleta e no manifesto:

| Área do limite | Coluna no parquet | Efeito |
|---|---|---|
| até 500 mil ha | — | normal |
| mais de 500 mil ha | `limite_suspeito` | só indício: imóvel dentro fica `risco_sobreposicao`, nunca `ja_comprometida`; fora do pacote do motor; lista `limites_suspeitos` |
| mais de 5 milhões de ha | `limite_amplo` | inválido como limite: fora de todo cruzamento e do motor; lista `limites_amplos` |

**Municípios prontos recebem o status novo sem refazer o funil.** `projeto_carbono_ha` é calculado dentro do
funil e só muda quando o município é reprocessado. A resposta que vale para o comprador é a tarefa `comprometida`
(folha do grafo, depende só do funil): a versão dela mudou neste conserto (`comprometida-2026b`), então o
`processar-estados.yml` põe todos os estados prontos na fila de manutenção e o executor refaz só
`comprometida_<mun>.csv`, município por município. Coletas diárias seguintes entram pela assinatura dos limites
(externa da tarefa) quando o estado roda de novo. Para refazer na mão, sem funil: `raiz comprometida baixar` e
`raiz comprometida recalcular`.

**Onde a tarefa lê os limites.** O `processar-estados.yml` baixa `comprometida_limites.parquet` e
`comprometida_cobertura.json` do Release `insumos` para `motor/cache/comprometida/`. Antes não baixava, e a tarefa
marcava todo imóvel como `nao_verificado`. A tarefa continua folha do grafo: coleta nova refaz só ela, município por
município; o funil dos prontos não muda (o `projetos_carbono.tar.gz` não entra na versão do funil, então
`projeto_carbono_ha` só muda num município reprocessado; a resposta certa para o comprador está em
`status_sobreposicao`).

### Pacote manual de limites (16/11/2026): o que já estava, o que entrou

O `pacote_limites_carbono_leve.zip` (389 polígonos de 227 projetos; Verra, InfoAmazonia, Renoster, GeoPackage do Pará,
SFB e Berkeley, mais a lista CAR × REDD+ do Pará) não entra no git nem no Release: a InfoAmazonia e a Verra não declaram
licença de redistribuição, e o pacote é para análise interna. Como indício adicional, cada fonte dele foi comparada com
o que a coleta automática já faz:

| Fonte do pacote | Já na coleta automática? | Tratamento |
|---|---|---|
| Verra, KML "Project Boundary" (167 geometrias, 157 projetos) | Sim (`verra`) | oficial; o pacote não substitui nem acrescenta |
| Verra, KML só como "Other" (25 geometrias, **19 projetos**; 10 não aparecem em nenhuma outra fonte) | **Não** | **entra agora, como indício** (abaixo) |
| InfoAmazonia, "Carbono sujo" (111 projetos) | Sim (`infoamazonia_carbono`, #146) | indício, já integrada |
| GeoPackage REDD+ do Pará, Zenodo 23929936 (24 projetos) | Sim (`para_redd_zenodo`, #146) | indício, já integrado |
| Renoster, Zenodo 11459391 (40 geometrias no Brasil) | Sim (`limites_pesquisa`) | indício, já integrado |
| SFB, concessões federais (22 UMFs) | Sim (`sfb_concessoes`) | oficial, já integrado |
| Berkeley VROD v2026-08 | Sim (`berkeley`) | só catálogo, sem geometria |
| Lista CAR × REDD+ do Pará (5.479 CAR, 22 projetos) | Não é fonte: o cruzamento geométrico a reproduz | **vira conferência** (abaixo) |

**Verra com KML só como "Other".** O coletor da Verra só aceitava o documento do tipo "Project Boundary (KML File)".
Projeto sem ele, mas com `.kml` ou `.kmz` publicado como "Other", ficava só no catálogo, e o imóvel dentro dele saía
`livre`. Agora, quando não há "Project Boundary", os `.kml` e `.kmz` do projeto entram como `poligono_secundario`
(indício): sozinhos dão `risco_sobreposicao`, nunca `ja_comprometida`. Com "Project Boundary" presente, os "Other" são
ignorados. KMZ é lido na memória (zip com limite de tamanho, só o primeiro `.kml`); KMZ corrompido vira projeto sem
geometria, sem derrubar a fila. O filtro de tamanho (limite suspeito e amplo) vale para esses polígonos como para os
demais. Prioridade quando as fontes divergem: Verra oficial, depois Pará/Zenodo (nov/2026), InfoAmazonia (2025) e
Renoster (2024); o indício nunca conta de novo a área já confirmada.

**Conferência contra a lista CAR × REDD+ do Pará.** A lista (Zenodo 23929936, CC BY 4.0; CAR, projeto e hectares de
sobreposição) é independente do nosso cruzamento. `raiz comprometida conferir-pacote <lista.csv> --saida <saida/>
--lacunas lacunas.csv` compara, para cada CAR listado com 5 ha ou mais, o status de `comprometida_<mun>.csv`: concorda
quando é `ja_comprometida` ou `risco_sobreposicao`; é **lacuna** quando sai `livre` ou `nao_verificado` (limite que
falta na coleta, geometria do CAR diferente); município sem arquivo fica `sem_arquivo` (ainda não processado). Só saem
código do CAR, identificador do projeto e hectares. Rodar depois de cada coleta nova, nos estados do Pará já
processados, e olhar os `projetos_nas_lacunas`.

## No pedido de lote (o que o Bot Agro fazia na mão)

Em Paragominas o Bot Agro montou o lote cruzando carbono, matrícula e gleba pública à mão. Agora o pedido faz sozinho:

1. **Tira a terra já comprometida.** O índice do lote (`raiz/restauracao_catalogo.py`) lê `comprometida_<mun>.csv`
   e grava `status_sobreposicao`, `ja_comprometida`, `risco_sobreposicao`, `sobreposicao_ha`,
   `sobreposicao_indicio_ha` e `sobreposicao_projetos` (até 3 IDs públicos, ex.: VCS4681). A consulta
   (`raiz/restauracao_nacional.py`) tira `ja_comprometida` do lote (com o motivo na trilha de decisões) e conta em
   cada opção as marcadas com risco e as não verificadas. Imóvel sem status fica **nulo**, nunca `false`: não vira
   terra livre. A consulta diz `verificada`, `parcial` (com quantas faltaram) ou `nao_verificada`.
2. **Refaz a camada quando o pacote do estado não traz.** Antes de indexar cada UF, `completar_comprometida`
   (`raiz/restauracao_nacional_rodada.py`) refaz `comprometida_<mun>.csv` que falte ou seja de coleta velha, só com
   `geo_<mun>.parquet` e os limites do Release `insumos` (o `lote-nacional.yml` baixa os dois arquivos). Vale para o
   Pará histórico e estados processados antes da coleta, sem refazer o funil nem as previsões. Coleta nova muda a
   identidade da UF e reindexa sozinha. Sem limites, nada é escrito e o lote sai "não verificado".
3. **Entra a Verra "Other" e a lista CAR × REDD+ do Pará.** Projeto Verra sem "Project Boundary" usa os KML "Other"
   como indício (`risco_sobreposicao`); `raiz comprometida conferir-pacote` confere a camada contra a lista pública
   CAR × REDD+ do Pará (Zenodo 23929936) e lista os CAR que ela deixou passar (PR #151).
4. **Não apaga a matrícula.** Sem SIGEF no espelho, a etapa terra usa `matricula_ha`/`f_matricula` da tabela de
   imóveis em vez de gravar 0 e mandar tudo para posse (regra `caminho-terra-2026b`, PR #148).
5. **Filtra gleba federal não destinada.** O processamento baixa o Cadastro Nacional de Florestas Públicas do SFB
   uma vez (job `preparar` do `processar-estados.yml`, `raiz terra preparar-cnfp`, guardado no cache comum privado
   como `dados/terra_publica/cnfp_<UF>.parquet`). Antes ele nunca existia no Actions e só a "Gleba Pública" do SIGEF
   contava. Com 50% ou mais do CAR em gleba não destinada (CNFP tipo B/C) ou UC de domínio público, o caminho é
   `publica_sem_destinacao` e o imóvel não entra em lote. Posse ou assentamento com 5% ou mais nessa terra fica com
   `risco_terra` alto e o motivo escrito. Gleba **federal** acima de 10% do CAR tem critério próprio (seção abaixo). A assinatura do CNFP entra na versão da tarefa `terra`: só ela (e o que
   depende dela) refaz; o funil não.
6. **KML gigante não compromete ninguém.** Limite acima de 500 mil ha vira só indício; acima de 5 milhões de ha fica
   fora do cruzamento (tabela acima, PR #146).

Pequenas fazendas continuam no lote, agrupadas: nenhuma regra acima corta por tamanho.

## Gleba pública federal não destinada: critério de 10% (17/11/2026)

**Critério.** Mais de 10% do CAR em gleba pública **federal** não destinada (Cadastro Nacional de Florestas Públicas
do SFB, tipo B/C, `governo = FEDERAL`) tira o imóvel do lote ou o marca com ressalva, conforme o modo. Exatamente 10%
não passa. A fração é do próprio CAR: imóvel pequeno conta igual, ninguém sai por tamanho. Gleba estadual continua
como terra pública (caminho e risco da terra), mas não entra neste critério.

| Onde | Coluna / opção | Excluir (padrão) | Ressalva |
|---|---|---|---|
| Etapa terra (`raiz/terra.py`) | `terra_gleba_federal_ha` em `terra_<mun>.csv`; vazia sem CNFP (nunca 0) | — | — |
| Limiar | `gleba_federal_fracao: 0.10` em `raiz/regras/padroes/caminho_terra.yaml` | — | — |
| Lote nacional | pedido `gleba_federal: "excluir" \| "ressalva"` (`CamposPedido`) | sai do lote, com o motivo na trilha | fica, e a opção conta `marcadas_gleba_federal` |
| Triagem | `gleba_federal: {modo: trava}` na regra; `raiz triagem lote --gleba-federal ressalva` | `nao_segue` (nota até 30) | `com_ressalvas` |

O índice do lote grava `gleba_federal_ha`, `gleba_federal_fracao` e `gleba_federal` (nulo = não medido). A consulta
devolve `gleba_federal` com `situacao` (`medida`, `parcial`, `nao_medida`), `modo`, `acima_do_limiar` e
`nao_medidas`. O pacote "lote pronto" leva `gleba_federal_ressalva` e `gleba_federal_fracao` em `sobreposicao.csv`; a
triagem leva `gleba_federal_pct` no ranking. Sem medição nada é cortado e o texto diz "gleba federal não medida".

**Conferência com Paragominas (D4386947 e CE800C8A, 17/11/2026).** Com os polígonos do Release `dados`
(`raiz_geo_PA.tar.gz`) e o CNFP 2025: nenhuma gleba federal não destinada toca os dois CAR (0%), e o SIGEF do INCRA
mostra os dois 100% dentro de parcela particular registrada (Fazenda Santa Lucia, 1.266 ha; Fazenda Transprogresso II,
1.094 ha). Pelo critério, **os dois ficam no lote**. A base REDD+ do Pará (Zenodo 23929936) também não traz gleba
sobre eles. O teste `testes/test_gleba_federal.py::test_paragominas_d4386947_e_ce800c8a` refaz a conta quando os
arquivos estão na máquina (`RAIZ_TESTE_GEO_PARAGOMINAS`).

## Coletar e atualizar no servidor privado

Depois de aplicar as migrações, com o banco e o arquivo completo autenticado:

```bash
uv run --env-file .env raiz prospeccao atualizar-base
uv run --env-file .env raiz prospeccao coletar-compromissos
uv run --env-file .env raiz prospeccao coletar-compromissos --fonte verra --limite-verra 25
uv run --env-file .env raiz prospeccao coletar-compromissos --fonte limites_pesquisa
uv run --env-file .env raiz prospeccao verificar-buscas
```

A coleta padrão inclui Berkeley, ART e SFB. Verra é explícita e descobre IDs no
catálogo Berkeley; `--projeto-verra` limita projetos. Para continuar uma rodada,
use `--retomar-desde AAAA-MM-DD`: pula apenas coletas bem-sucedidas desde essa
data UTC. Uma rodada nova deve revisitar os projetos. Limites científicos são
opcionais: o GeoPackage regional tem cerca de 200 MB; a versão, licença,
tamanho e checksum publicado são conferidos antes da leitura. Não se executa
código da pesquisa nem se redistribui o arquivo bruto.

Cada coleta é persistida separadamente; falha posterior conserva as anteriores
e sinaliza pendência. O reindexador atualiza fichas de todas as UFs carregadas e
as próximas entradas do manifesto privado, sem recalcular o motor. A inclusão
de novos perímetros REDD+ também invalida o índice. `reindexar --forcar` permite
reconferir o banco. Ver [operação](operacao.md) para agendamento e proteção.

Dados brutos, polígonos e versões completas não pertencem ao Release público,
ao front estático ou a artefatos abertos de CI. Berkeley e a base científica
exigem atribuição; fontes sem licença expressa de redistribuição são usadas
como referência e análise privada, sem publicar documentos originais.

## No processamento, sem servidor (arquivo por município)

A mesma camada roda no processamento dos estados, sem banco, como tarefa própria do executor (`comprometida`, só
depende do funil e ninguém depende dela). Duas peças:

1. **Coleta diária** (`.github/workflows/coletar-comprometida.yml`, 04h23 de Brasília): `raiz comprometida coletar`
   baixa o KML oficial de cada projeto Verra brasileiro do catálogo Berkeley (floresta e uso da terra: ARR, REDD,
   IFM), os limites das concessões do SFB e, só como indício, a base científica do Zenodo, a InfoAmazonia e a base
   REDD+ do Pará. Publica no Release `insumos`:
   `comprometida_limites.parquet`, `comprometida_cobertura.json` (o que cada fonte cobriu e quando) e
   `projetos_carbono.tar.gz`, que o `processar-estados.yml` já baixa e o motor lê: com ele, `projeto_carbono_ha`
   deixa de sair sempre 0. Só entram nesse pacote limites oficiais e ativos da Verra, nunca indício nem concessão.
   Se nenhuma fonte cobrir, o workflow falha e o Release mantém a coleta anterior. Para pausar, desative o workflow.
2. **Status por CAR** (`raiz/comprometida/status.py`): `comprometida_<mun>.csv` (colunas em `docs/colunas.md`).
   `livre` só quando alguma fonte cobriu a área; sem fonte, `nao_verificado`. Reaproveita o cruzamento do servidor
   (`terra_comprometida.cruzar`): união das interseções em EPSG:5880, retirada e prazo encerrado não confirmam,
   indício desconta a área já confirmada.

Versão própria: a versão da tarefa junta o código de `status.py` e `terra_comprometida.py` com a assinatura da coleta.
Coleta nova ou regra nova refaz só esta tarefa, município por município (`raiz comprometida recalcular` ou o
executor); o funil dos municípios prontos não muda. A tarefa não passa por `raiz/funil/rodar.py`, que entra no hash
de todas as tarefas. No servidor, `raiz comprometida baixar` traz os arquivos do Release para `cache/comprometida/`.

**Público só agregado.** O Release `insumos` é aberto e guarda os limites coletados; o status por imóvel fica no
arquivo privado e fora da projeção aberta. O que pode ser público é a contagem por município e status
(`raiz comprometida resumo`). No mapa da área logada, a fazenda `ja_comprometida` fica em cinza.

**Licença dos limites.** Os KML da Verra e os limites do SFB não declaram licença de redistribuição (ver tabela
acima). Publicá-los no Release aberto `insumos` foi decisão do fundador, para o motor ler sem gancho novo; se a
decisão mudar, basta apagar os três arquivos do Release e pôr o `projetos_carbono.tar.gz` no armazém privado.
Os limites da InfoAmazonia (sem licença declarada, derivados dos KML dos registros) seguem a mesma decisão dos KML
da Verra. Berkeley, as duas bases do Zenodo (CC BY 4.0) e a InfoAmazonia levam atribuição no manifesto. O parquet publicado
traz só identificador, situação, UF e geometria dos limites: nada de CNPJ, empresa ou CAR. Fora do escopo: Gold Standard, averbação na matrícula
e cota vendida.

## Caminho da terra sem SIGEF no espelho (correção de 17/11/2026)

**O problema.** A etapa `terra` (raiz/terra.py) mede a sobreposição do CAR com o SIGEF do espelho
(`sigef/<UF>/<mun>.parquet`). O funil não depende desse arquivo: quando ele falta, o motor baixa o SIGEF pela caixa
do município e grava `matricula_ha`, `sigef_ha` e `f_matricula` na tabela de imóveis. A etapa de terra, sem o
arquivo, gravava **0** em todas as colunas `terra_sigef_*_ha`, e o 0 medido ganhava da coluna do motor. Resultado no
Pará: 98,8% dos imóveis viraram `posse_em_titulacao` e nenhum `privada_matricula`, embora o motor mostrasse quase
38 mil com matrícula; essas fazendas saíam do lote (só a privada com matrícula é pronta agora).

**A regra agora (caminho-terra-2026b).**

- Falta de SIGEF nunca apaga matrícula. Sem o SIGEF do espelho, `terra_sigef_*_ha` ficam **vazias** (nunca 0) e a
  nova coluna `terra_sigef_disponivel` fica `False`.
- Sem SIGEF medido, matrícula, posse e assentamento vêm da tabela de imóveis do motor (`matricula_ha`, ou
  `f_matricula × ha`; `sigef_ha`; `assentamento_ha`), a fonte mais confiável nesse caso. As camadas que não dependem
  do SIGEF (florestas públicas, UC, terras indígenas, quilombos, concessões) continuam medidas.
- `terra_fonte` ganha o valor `sobreposicao_sem_sigef` (camadas medidas, matrícula do motor), e o motivo da privada
  com matrícula diz "cobertura da tabela de imóveis do motor".
- Arquivos `terra_<mun>.csv` antigos (sem `terra_sigef_disponivel`) com todas as `terra_sigef_*_ha` em 0, num imóvel
  onde o motor achou SIGEF ou matrícula, são lidos como "SIGEF ausente", não como "sem matrícula".
- Com o SIGEF medido de verdade (`terra_sigef_disponivel = True`), a medida do espelho continua valendo.
- A etapa avisa no log quando um município rodou sem SIGEF e devolve `sem_sigef` no resumo.

**Reprocessamento.** Só a etapa `terra` (e o que lê a saída dela, se mudar) roda de novo: a versão da tarefa é o
hash de raiz/terra.py mais a versão da regra, que subiu para `caminho-terra-2026b`. O funil dos municípios prontos
não é refeito. Para refazer só a terra à mão: `raiz terra recalcular --ufs PA`.

**Teste.** `testes/test_terra.py` cobre o município da amostra (1504950) rodando sem SIGEF no espelho: antes da
correção, 880 de 880 imóveis saíam como posse; agora os 55 com matrícula em metade do CAR ou mais voltam a
`privada_matricula` e os 57 lotes de assentamento voltam a `assentamento`.
