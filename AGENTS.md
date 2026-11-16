# Instruções para agentes (Codex e outros)

Este repositório é construído por agentes de IA. As regras são as mesmas para qualquer agente e estão em
[`CLAUDE.md`](CLAUDE.md): leia esse arquivo inteiro antes de começar e siga como se fosse escrito para você.

Resumo do que não pode faltar:
- Português do Brasil em tudo que o fundador lê.
- Norte do produto: `docs/cena-alvo.md`. Roteiro: `docs/plano-por-etapa.md` (marque "feito" o que entregar).
- Contrato de dados: `docs/colunas.md`; dados grandes nunca entram no git; Release `dados` só contém agregados e CAR/situação básica. Camadas completas ficam no arquivo privado autenticado (`docs/dados-publicados.md`).
- Nunca descartar fazenda por tamanho; CPF e CNPJ sempre mascarados; segredos só em variáveis de ambiente.
- Licenças: sem AGPL, EUPL, SSPL, BSL ou NC; registrar código de terceiros em `NOTICE.md`.
- Testes (iguais ao CI): `uv run ruff check raiz testes scripts migracoes`, `uv run ruff format --check raiz testes scripts migracoes` e `uv run pytest -q` antes de abrir o PR.

## Continuidade obrigatória do processamento

- Nenhum agente ou outro chat pode desativar o workflow **Processar estados (motor)**, cancelar seus runs/jobs
  ou interromper os workflows de processamento de lotes. Somente uma ordem posterior e explícita do fundador
  autoriza uma interrupção. Revisão, publicação, manutenção, troca de branch e limpeza não são autorização.
- Manter até **15 jobs de processamento no total**, somando motor, lotes e catálogo, pela admissão atômica
  compartilhada. O teto não é de 15 por workflow. Usar várias UFs e as fatias dos estados grandes em paralelo.
- Uma falha de publicação não autoriza descartar resultados, marcas ou retratos já calculados. Preservar o
  progresso no arquivo privado autenticado e retomar de hashes e versões conferidos; nunca usar artifacts
  públicos para os dados completos. Não apagar uma trava apenas porque passou tempo.
