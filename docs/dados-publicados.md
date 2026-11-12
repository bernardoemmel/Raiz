# Dados publicados: aberto e pago

Os dados grandes ficam fora do git. Existem dois contratos separados: uma
projeção pública para o mapa e os agregados; e o resultado completo do motor,
acessível somente por processos autorizados do servidor.

## O que é aberto

O Release `dados` distribui o contrato `publico_basico`, versão 1:

| Arquivo | Conteúdo permitido |
|---|---|
| `estados.json` | Cobertura por UF, municípios, datas, versões e endereços dos pacotes públicos |
| `raiz_<UF>.tar.gz` | Resumos por município e `imoveis_basicos_<IBGE>.csv` com `cod_imovel`, `cod_ibge`, `municipio`, `uf`, `situacao_basica` |
| `raiz_geo_<UF>.tar.gz` | Geometria do CAR com apenas `cod_imovel` e `geometry` |

As situações abertas são `apto`, `com_pendencia` e `nao_apto`. São uma triagem,
não certidão de domínio nem garantia de elegibilidade. Municípios e estados
mantêm agregados; valores de grupos pequenos são suprimidos para evitar a
reconstrução de uma ficha. Nenhuma fazenda é retirada por ser pequena.

A lista positiva está em `raiz/executor/publicacao_aberta.py`. Colunas, tabelas
e arquivos novos ficam privados até revisão. As geometrias abertas não carregam
atributos financeiros, históricos ou de risco. A amostra e os testes do site
seguem o mesmo contrato.

O front baixa somente esse contrato para `dados/publicos/`. O download rejeita
manifesto antigo, pacote com campos pagos e destino compartilhado com o espelho
privado. O build e o servidor de desenvolvimento também aplicam a lista positiva.
Sem dados básicos publicados, o site mostra cobertura indisponível; não busca
arquivos antigos completos como alternativa.

## O que é pago e permanece privado

Por imóvel: certidão lida por IA, cadeia e pendências detalhadas da terra,
comprometimento conhecido, sobreposições detalhadas, valor e créditos P10/P50/P90,
TIR, risco, restauração estimada, uso e perdas ao longo dos anos. A ausência de
nome ou CPF não torna esses derivados públicos.

O arquivo completo preserva CSV, GeoParquet, camadas internas, controle de
retomada, versões do motor e histórico de vigilância. Cada ficha é montada no
back-end, com fonte, referência temporal e data de corte de cada medida; falta
de dado continua explícita. O servidor exige identidade, liberação paga e limites
contra extração em massa. PDF e comparação passam pelas mesmas verificações.
Nunca são fornecidos nome, CPF ou contato do dono.

## Armazenamento privado e publicação

O destino desta migração é o Release **não publicado** `dados-privados` de
`bernardoemmel/Raiz` (ID 443383695). É um draft autenticado: **não publicar esse
Release**. A credencial de implantação não permitiu criar um repositório privado;
o código também aceita migrar para um Release de repositório privado no futuro.
O servidor confere `repo.private` ou `release.draft` antes de cada leitura e
escrita. Se o draft virar público, a operação falha.

```dotenv
RAIZ_ARMAZEM_URL=release-github://bernardoemmel/Raiz/dados
RAIZ_DADOS_PRIVADOS_URL=release-github://bernardoemmel/Raiz/dados-privados
RAIZ_DADOS_PRIVADOS_TOKEN=<somente no ambiente do servidor>
```

O token deve poder ler o Release privado. Os jobs de publicação usam credencial
com escrita, separada da credencial de leitura do back-end quando possível.
No Actions do próprio repositório, `github.token` permite manter o draft sem
expor token no navegador. Nunca usar variável `VITE_` para esse segredo.

O executor grava primeiro o pacote completo no destino privado; somente depois
projeta e valida os arquivos abertos. Travas por UF e por manifesto preservam
publicações concorrentes. Os nomes canônicos privados (`raiz_<UF>`, `raiz_geo_<UF>`,
`raiz_camadas_<UF>`, controles e `estados.json`) permitem retomar a coleta e carregar
o banco. Snapshots históricos usam nomes imutáveis e não substituem o canônico.
A vigilância por CAR e os cálculos completos do lote também usam armazenamento
privado. Não enviar esses conteúdos como artifacts ou caches de Actions públicos.

## Arquivos históricos encontrados

Inventário inicial do Release `dados`, antes da troca (12/11/2026):

- `raiz_<UF>.tar.gz`: AC, AP, GO, MA, MG, PA, RO, RR e TO. Contêm o motor completo
  e camadas exclusivas, como ficha, desenvolvedor, terra, certidões, regularização,
  filtros, MapBiomas e histórico. Devem ser substituídos pela projeção aberta.
- `raiz_camadas_<UF>.tar.gz`: AC, AP, GO, MA, MG, RO, RR e TO. Somente privados.
- `raiz_geo_<UF>.tar.gz`: AC, AP, GO, MA, MG, PA, RO, RR e TO. O original é
  preservado; o público é reconstruído pela lista positiva de geometria e CAR.
- `raiz_controle_<UF>.json`: AC, AM, AP, GO, MA, MG, MS, MT, PA, RO, RR e TO.
  Controle detalhado de execução fica privado.
- `estados.json`: substituído pelo manifesto básico sem referências a camadas pagas.
- `URTX.kml`: arquivo fora do contrato aberto; preservado no privado, sem republicação automática.

O inventário completo relaciona cada asset e cada membro, colunas, tamanho,
SHA-256 e ID do GitHub. Novos Releases publicados também entram na varredura.
O resultado remoto da migração e os comprovantes serão registrados nesta seção
após a execução verificada; inventário local não comprova remoção do público.

## Migração verificável do histórico

`scripts/migrar_dados_privados.py` inventaria todos os Releases **publicados** e seus assets, inclusive arquivos
históricos fora do manifesto atual. Drafts são excluídos da origem para não copiar o próprio backup de novo. A fase
`inventariar` baixa os originais para uma pasta fora do git, confere tamanho e SHA256 informado pelo GitHub e registra
caminho, tamanho, SHA256 e cabeçalho/esquema de cada membro de pacote. Não grava valores de linhas nem extrai tar no
filesystem; links, dispositivos e caminhos que escapam do pacote são recusados.

O snapshot completo é privado. Arquivos do motor, certidões, caminho da terra, regularização, estimativas de
restauração/crédito, ficha, MapBiomas, séries e camadas internas não viram públicos pela simples remoção de nomes ou
CPF. A projeção aberta é separada, definida em `raiz/executor/publicacao_aberta.py`: CSV básico com CAR, município,
UF e situação básica; geometria com CAR; resumos permitidos com supressão de grupos pequenos. Arquivos desconhecidos
ficam privados até revisão. Nunca substituir o snapshot pela projeção reduzida.

As fases são separadas e repetíveis, sem sobrescrever backups existentes:

```bash
uv run python scripts/migrar_dados_privados.py inventariar --origem bernardoemmel/Raiz --diretorio /tmp/raiz-migracao
uv run python scripts/migrar_dados_privados.py copiar --destino bernardoemmel/Raiz --tag dados-privados --diretorio /tmp/raiz-migracao
uv run python scripts/migrar_dados_privados.py verificar --destino bernardoemmel/Raiz --tag dados-privados --diretorio /tmp/raiz-migracao
uv run python scripts/migrar_dados_privados.py remover --destino bernardoemmel/Raiz --tag dados-privados --diretorio /tmp/raiz-migracao
```

`copiar` e `remover` são **dry-run** sem `--executar`. O repositório e o Release de destino devem ser criados
explicitamente. O destino precisa ser um repositório privado **ou um Release draft**, conferido novamente antes de
cada operação. O draft nunca deve ser publicado. Um Release draft é encontrado pela listagem autenticada e pelo ID;
a rota de Release por tag pode responder 404 mesmo para uma credencial autorizada.

Os backups recebem nomes imutáveis `historico-<release_id>-<asset_id>-<nome>`. `copiar --executar` baixa de novo cada
backup, confere o SHA256 e exige HTTP 404 no endereço de download sem cabeçalho de autenticação. Essa verificação
deve rodar no GitHub Actions ou em ambiente sem proxy que injete credenciais: o proxy do ambiente de desenvolvimento
não comprova anonimato. `verificar` repete as provas e grava `backup-verificado.json`.

A remoção gera primeiro `plano-remocao.json` para revisão. `remover --executar` reconfere **todos** os backups antes do
primeiro DELETE e recusa alterações de fingerprint da origem, assets novos ou mudança na lista de Releases
publicados. Cada DELETE usa o ID original e nova leitura de metadados; o progresso fica em
`remocao-progresso.json`. Se o original já tiver sido removido, ele não é apagado outra vez. A publicação da projeção
aberta acontece separadamente, após a cópia integral validada. Preserve também `inventario.json` e
`backup-verificado.json` no armazenamento privado para reconstruir o histórico.

Inventário local inicial em 12/11/2026: um Release publicado (`dados`, ID 442821475), 40 assets e cerca de 1,21 GB.
Foram encontrados 3.249 membros de camadas pagas, 365 CSV completos do motor, 365 arquivos de geometria básica,
9 resumos e 23 arquivos de controle ou formatos sem allowlist. Esses números descrevem a leitura daquele instante;
novas rodadas podem trocar assets. O inventário e os hashes atualizados ficam fora do git, em `/tmp/raiz-migracao/`.
