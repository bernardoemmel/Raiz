# Instruções para agentes (Codex e outros)

Este repositório é construído por agentes de IA. As regras são as mesmas para qualquer agente e estão em
[`CLAUDE.md`](CLAUDE.md): leia esse arquivo inteiro antes de começar e siga como se fosse escrito para você.

Resumo do que não pode faltar:
- Português do Brasil em tudo que o fundador lê.
- Norte do produto: `docs/cena-alvo.md`. Roteiro: `docs/plano-por-etapa.md` (marque "feito" o que entregar).
- Contrato de dados: `docs/colunas.md`; dados grandes ficam no Release `dados`, nunca no git (`docs/dados-publicados.md`).
- Nunca descartar fazenda por tamanho; CPF e CNPJ sempre mascarados; segredos só em variáveis de ambiente.
- Licenças: sem AGPL, EUPL, SSPL, BSL ou NC; registrar código de terceiros em `NOTICE.md`.
- Testes (iguais ao CI): `uv run ruff check raiz testes scripts migracoes`, `uv run ruff format --check raiz testes scripts migracoes` e `uv run pytest -q` antes de abrir o PR.
