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
   IFM), os limites das concessões do SFB e a base científica do Zenodo (só indício). Publica no Release `insumos`:
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
Berkeley e Zenodo (CC BY 4.0) levam atribuição no manifesto. Fora do escopo: Gold Standard, averbação na matrícula
e cota vendida.
