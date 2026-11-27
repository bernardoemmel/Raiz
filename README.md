# Raíz

Quem compra crédito de restauração florestal no Brasil não sabe quais fazendas servem: a terra pode ter embargo, estar em terra indígena ou unidade de conservação, ter sido desmatada depois do corte legal, ou não ter título. A Raíz cruza só dados públicos e aponta, fazenda a fazenda, onde a mata pode voltar — e monta o lote.

**Demo:** [bernardoemmel.github.io/Raiz](https://bernardoemmel.github.io/Raiz/)

No mapa, abra **Fazer pedido** e peça 1 milhão de créditos no Pará. A Raíz devolve três lotes (o mais barato, o mais seguro e o mais compacto), agrupa as fazendas pequenas e simula o contato em ondas até o grupo pronto. Essa demonstração roda no navegador, sem back-end e sem dado pessoal.

## O problema

O comprador (desenvolvedor de projeto, empresa com meta de desmatamento, frigorífico, fundo) precisa de um volume de crédito e de terra regular. O Cadastro Ambiental Rural tem milhões de imóveis. Cruzar embargo do Ibama, terra indígena da FUNAI, unidade de conservação, desmatamento do INPE, reserva legal e matrícula do SIGEF, um por um, não cabe numa planilha. Fazenda pequena não pode ficar de fora: ela entra no grupo.

## Como funciona

Cada imóvel do CAR passa por um funil. Quem passa tem uma faixa de crédito, do pessimista ao otimista (P10, P50 e P90), com retorno e risco. Um pedido ("1 milhão de créditos no Pará, no cronograma do ProFloresta+") vira três lotes. O contato com os donos sai em ondas. Quando o grupo fecha, a reserva segura aquelas fazendas.

Fontes públicas: CAR/SICAR, Ibama, PRODES e DETER (INPE), SIGEF/INCRA, MapBiomas, FUNAI, CNUC, malha do IBGE. Nome, CPF e CNPJ do dono não entram. A amostra do repositório também não traz número de matrícula nem código de cartório.

Os números do site (27 estados, milhares de municípios, milhões de hectares) vêm do Release `dados`, calculado pelo motor. Este repositório não guarda essa base.

## Arquitetura

| Peça | Onde | Para quê |
|---|---|---|
| Site | `front/globo` (React, MapLibre) e `front/produtor` (ficha no celular) | a demo, publicada no GitHub Pages |
| Funil, crédito e lote | `motor/`, `raiz/restauracao/` e `raiz/lote/` | a conta, município a município |
| Uma API | `raiz/api.py` | o mesmo processo sobe o front, o pedido e a API `/v1` |
| Pipeline | `raiz/executor/` e o workflow Processar estados | baixa as fontes, retoma de onde parou e publica o Release |
| Nuvem, enxuta | `infra/docker-compose.yml` | PostGIS na própria máquina. Keycloak, observabilidade e o modelo local são arquivos à parte, para quando o servidor existir |

O site estático é o que está no ar. O back-end, o banco e o Docker ficam prontos para o passo seguinte; a demo não depende deles.

## Rodar a demo

É preciso Node 22.

```bash
cd front/globo
npm ci
npm run dev
```

O `predev` baixa o pacote público do Release `dados` (agregados e a situação básica de cada imóvel, sem dado pessoal). Abra o endereço que o Vite mostrar e use **Fazer pedido**.

Sem baixar o Release, o front usa `dados/amostra/` (Pará de verdade, dois municípios com a ficha completa). Para o build que o Pages publica:

```bash
# com os dados já em dados/publicos e a geometria em front/geo
RAIZ_DADOS=dados/publicos RAIZ_GEO=front/geo RAIZ_BASE=/Raiz/ front/scripts/construir-site.sh
```

## Rodar o back-end

Python 3.12 e [uv](https://docs.astral.sh/uv/). O banco é opcional para a demo.

```bash
uv sync
docker compose --env-file .env -f infra/docker-compose.yml up -d
uv run raiz banco migrar
uv run raiz carregar dados/amostra --data-corte 2026-11-12
uv run raiz api
```

A API sobe em `http://127.0.0.1:8000`. Rotas do mapa, do pedido e de `/v1` estão no mesmo processo. Segredos ficam no `.env` (há um `.env.example`); nada disso entra no git.

Testes do que mudou:

```bash
uv run ruff check raiz testes scripts migracoes
uv run ruff format --check raiz testes scripts migracoes
uv run pytest -q
cd front/globo && npm test
```

## Próximo passo, na nuvem

1. Um servidor com o `docker compose` do PostGIS e `uv run raiz api` atrás de HTTPS. O site deixa de simular o pedido e passa a gravar de verdade.
2. O workflow **Processar estados** continua publicando o Release `dados`. A malha do mapa passa a ser a do IBGE em toda UF publicada; o primeiro build depois disso leva uns 15 a 40 minutos (`docs/municipios.md`).
3. Login da empresa, cobrança e o contato com o dono entram nesse servidor. Até lá, a demo não chama API paga.

O que saiu nesta limpeza, e o que o fundador ainda precisa decidir, está no pull request.
