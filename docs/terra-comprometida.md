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

As duas bases secundárias entram na coleta diária como **indício**: sozinhas deixam o imóvel em
`risco_sobreposicao` (nunca `ja_comprometida`); com o KML oficial e ativo da Verra, o imóvel vira `ja_comprometida`
e o indício não conta a mesma terra de novo. Elas cobrem o que o registro deixa de fora (KML ilegível, projeto só com
"Other", registro fora do ar). Cada uma é baixada de endereço fixo e conferida por checksum (InfoAmazonia: commit
`350f832`, sha256 dos quatro arquivos do shapefile; Zenodo: md5 e tamanho publicados). Arquivo mudou = coleta da
fonte vira `indisponivel`, nunca terra livre.

**Limite amplo.** Projetos agrupados e programas (ex.: VCS3380, VCS3713, VCS4137, VCS4849, VCS5184) publicam uma
"área geográfica" de milhões de hectares. Estar dentro dela não é compromisso. Limite acima de 1 milhão de ha fica
com `limite_amplo = true` no parquet, sai do cruzamento por CAR e do pacote do motor, e aparece em
`limites_amplos` no manifesto.

**Onde a tarefa lê os limites.** O `processar-estados.yml` baixa `comprometida_limites.parquet` e
`comprometida_cobertura.json` do Release `insumos` para `motor/cache/comprometida/`. Antes não baixava, e a tarefa
marcava todo imóvel como `nao_verificado`. A tarefa continua folha do grafo: coleta nova refaz só ela, município por
município; o funil dos prontos não muda (o `projetos_carbono.tar.gz` não entra na versão do funil, então
`projeto_carbono_ha` só muda num município reprocessado; a resposta certa para o comprador está em
`status_sobreposicao`).

O pacote manual de 16/11 (`pacote_limites_carbono_leve.zip`, 389 polígonos de 227 projetos) serviu para conferir a
coleta automática; não entra no git nem no Release (a InfoAmazonia e a Verra não declaram licença de redistribuição).
A tabela CAR × projeto do Pará (Zenodo 23929936) também não é publicada: o cruzamento geométrico já a reproduz.

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
