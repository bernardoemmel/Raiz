# Armazenamento dos dados: sair dos Releases

Os Releases do GitHub viraram o banco de dados da Raíz. Em 17/11/2026 eram **354 GB em 12 Releases**:

| Release | Visibilidade | Arquivos | Tamanho |
|---|---|---:|---:|
| `dados-privados-checkpoints` | rascunho (privado) | 801 | 160,7 GB |
| `dados-privados` | rascunho (privado) | 796 | 70,7 GB |
| `historico-2026-11-12` a `-17` (6) | rascunho (privado) | 1.986 | 120,8 GB |
| `dados` | **público** | 113 | 2,3 GB |
| `insumos`, `busca`, `calendario` | **público** | 9 | 0,08 GB |

O histórico cresce ~30 GB por dia, e o `dados-privados-checkpoints` já tem 801 dos 1.000 arquivos que o GitHub
aceita num Release. Os downloads do Release `dados` falham com 403 quando muitos jobs baixam ao mesmo tempo.

**O que está público hoje (conferido em 17/11):** só a projeção básica (`cod_imovel`, município, UF e
`situacao_basica`), os resumos por município, as geometrias com apenas o CAR, os polígonos de projetos de
carbono (registros públicos) e o calendário. Não há CPF, CNPJ, nome nem tabelas pagas nos Releases públicos.
Os dados completos estão em rascunhos, que só abrem com credencial de escrita no repositório. O risco que fica
é humano: um clique em "Publish release" num desses rascunhos exporia o arquivo completo de um repositório público.

## Nova arquitetura

```
                          ┌──────────────────────────────┐
  processar-estados.yml   │ balde PRIVADO (S3/R2)        │  só com chave (Actions e servidor)
  lote-*.yml, vigilância ─▶  dados/            completo  │  raiz_<UF>.tar.gz, estados.json, controles, fichas
  (ArmazemBalde)          │  dados/historico/  retratos  │  um objeto por retrato (sem limite de arquivos)
                          │  dados-checkpoints/          │  checkpoints dos jobs
                          └──────────────┬───────────────┘
                                         │ _publicar_aberto(uf): projeção básica, lista positiva
                                         ▼
          fase 1: Release público `dados` (igual a hoje)  ──▶  site (baixar-dados.mjs)
          fase 2: balde PÚBLICO + RAIZ_PUBLICO_URL_BASE   ──▶  site (RAIZ_DADOS_URL)
```

- **O contrato não muda.** `ArmazemBalde` (`raiz/executor/armazem_balde.py`) é uma subclasse do `ArmazemRelease`
  que troca só o transporte (listar, baixar, subir, conferir que o privado é privado). Nomes de arquivo,
  `estados.json`, `publicar(uf)`, `_publicar_aberto(uf)`, `sincronizar_aberto`, `defasados_no_aberto`, fichas
  Croissant e travas por UF são os mesmos. O reprocessamento estado a estado
  ([`reprocessamento-progressivo.md`](reprocessamento-progressivo.md)) roda igual nos dois destinos: o estado só
  troca no público quando o publicador dele termina.
- **Travas:** continuam sendo refs git no repositório de código (não guardam dados), com o sufixo do balde. Assim
  um job antigo no Release e um job novo no balde nunca disputam a mesma trava durante a troca.
- **Privacidade conferida a cada processo:** o balde privado falha fechado se responde a uma leitura sem
  credencial, se é o mesmo balde do aberto ou se o endereço público aponta para ele. O aberto só aceita a lista
  positiva de `publicacao_aberta.py`, como hoje.
- **Histórico por CAR:** no balde, cada retrato é um objeto imutável (`If-None-Match: *`) em
  `historico/UF/município/hash.json.gz`, o formato que `raiz/aprendizado/transporte.py` já usava para S3. Acabam os
  Releases diários.
- **Escolha por variável**, sem mudar código:

| Variável | Fase 0 (hoje) | Fase 1 | Fase 2 |
|---|---|---|---|
| `RAIZ_DADOS_PRIVADOS_URL` (variável do repositório) | `release-github://…/dados-privados` | `s3://raiz-privado/dados` | `s3://raiz-privado/dados` |
| `RAIZ_ARMAZEM_URL` | `release-github://…/dados` | igual | `s3://raiz-publico/dados` |
| `RAIZ_PUBLICO_URL_BASE` | — | — | `https://<domínio público>/dados` |
| `RAIZ_S3_ENDPOINT` (variável) | — | `https://<conta>.r2.cloudflarestorage.com` | igual |
| `RAIZ_S3_ACCESS_KEY_ID`, `RAIZ_S3_SECRET_ACCESS_KEY` (segredos) | — | chave do R2 | igual |

Os workflows que já leem `vars.RAIZ_DADOS_PRIVADOS_URL` (processar-estados, lotes, dossiê, triagem, vigilância,
publicar-dados/metadados) recebem também `RAIZ_S3_*`. Sem essas variáveis tudo segue no Release.

Módulos que ainda só falam com Release (ex.: `scripts/migrar_dados_privados.py`, `scripts/aliviar_dados_privados.py`,
`restauracao_retomada.py`, `quantis_lote.py`) recebem `None` de `destino_privado()` quando o privado está no balde e
**falham fechados**: nunca gravam dado completo num lugar público. Eles migram depois, um por vez, para
`arquivo_privado_configurado()`.

## Onde guardar: custo para ~354 GB

| Opção | Guardar | Baixar | Custo/mês (354 GB) | Observação |
|---|---|---|---|---|
| **Cloudflare R2** (recomendado) | US$ 0,015/GB | **grátis** | **~US$ 5,2** (~R$ 28) | S3 compatível; balde público com domínio próprio para o site; 10 GB grátis |
| Backblaze B2 | US$ 6,95/TB | grátis até 3× o guardado | ~US$ 2,5 | Download acima de 3×/mês é pago; o Actions baixa muito |
| Google Cloud Storage | ~US$ 0,02–0,035/GB | US$ 0,12/GB para a internet | ~US$ 8 + download | Conta Google já existe (Earth Engine), mas cada GB baixado é pago |

Preços de lista em nov/2026 (comparativos de [tech-insider](https://tech-insider.org/cloudflare-r2-vs-s3-vs-backblaze-b2-2026)
e [nubbo](https://nubbo.app/articles/backblaze-b2-pricing-and-free-tier/)); confirmar na página oficial ao criar a conta.
O R2 vence porque os jobs e o site baixam os mesmos pacotes muitas vezes por dia, e no R2 isso não custa nada.
Com política de retenção (abaixo), o volume ativo deve cair bem abaixo de 354 GB.

## Plano de migração

Nada é apagado do GitHub até o fundador decidir, depois da validação.

1. **Criar o balde e a chave** (Bernardo, uma vez, ~5 min):
   1. Em <https://dash.cloudflare.com>, entrar ou criar conta → **R2 Object Storage** → ativar (pede cartão; o uso
      até 10 GB é grátis).
   2. **Create bucket** → nome `raiz-privado` → localização automática. Não ligar "Public access".
   3. **Manage R2 API Tokens** → **Create API token** → permissão **Object Read & Write**, só o balde
      `raiz-privado` → criar. Anotar *Access Key ID*, *Secret Access Key* e o endpoint
      `https://<id-da-conta>.r2.cloudflarestorage.com`.
   4. No GitHub do repositório: **Settings → Secrets and variables → Actions**:
      - *Secrets*: `RAIZ_S3_ACCESS_KEY_ID` e `RAIZ_S3_SECRET_ACCESS_KEY`;
      - *Variables*: `RAIZ_S3_ENDPOINT` e `RAIZ_BALDE_PRIVADO_URL` = `s3://raiz-privado/dados`.
2. **Copiar** (automático): Actions → *Migrar Releases para o balde privado* → fase `plano` (mostra o que vai
   copiar), depois `copiar`. Quatro jobs em paralelo (dados-privados, checkpoints, histórico, públicos). Cada asset
   é baixado pela API autenticada, conferido contra o SHA-256 do GitHub, enviado e conferido de novo no balde. O
   histórico é aberto pacote a pacote e cada retrato vira um objeto (o nome do retrato é o próprio hash). Pode
   rodar de novo quantas vezes precisar: só copia o que falta ou mudou.
3. **Verificar**: fase `verificar` grava `migracao/verificado-<grupo>.json` no balde e falha se faltar algo.
4. **Trocar** (um clique, reversível): com o processamento parado entre duas rodadas, rodar `copiar` mais uma
   vez e então criar a variável `RAIZ_DADOS_PRIVADOS_URL` = `s3://raiz-privado/dados`. A próxima rodada lê e grava
   no balde. Voltar = apagar a variável. A projeção pública continua no Release `dados` (fase 1), então o site não
   muda.
5. **Observar uma semana**: rodadas publicando no balde, site atualizando estado a estado, nenhum 403.
6. **Fase 2 (site)**: criar o balde `raiz-publico` com acesso público por domínio próprio, definir
   `RAIZ_ARMAZEM_URL=s3://raiz-publico/dados`, `RAIZ_PUBLICO_URL_BASE` e, no build do site, `RAIZ_DADOS_URL` com o
   mesmo endereço; rodar `sincronizar_aberto` para cada UF (o público é refeito a partir do privado, sem recalcular).
7. **Retirar os Releases** (decisão do fundador, irreversível): só depois de 2 a 6 com sucesso. Primeiro os
   rascunhos de histórico e checkpoints, depois `dados-privados`. O Release público `dados` sai por último, quando
   o site já lê do balde.

## Retenção (proposta, a decidir)

O volume vem quase todo de cópias repetidas: 160 GB de checkpoints e ~30 GB/dia de retratos. Proposta, aplicada
como regra de ciclo de vida do R2 e só depois da migração validada: checkpoints com mais de 14 dias e sem estado
em andamento saem; retratos ficam (são o aprendizado da Raíz), mas podem ir para a classe *Infrequent Access* do
R2 (US$ 0,01/GB) depois de 30 dias.
