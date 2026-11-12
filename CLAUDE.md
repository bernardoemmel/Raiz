# Instruções para quem trabalha neste repositório

- Idioma: português do Brasil em tudo que o fundador lê (mensagens, commits, documentação, textos da interface).
- Construir o produto COMPLETO. Não cortar escopo por prazo do hackathon.
- Nunca descartar fazendas por tamanho: pequenas se agrupam; agrupar áreas pequenas é um dos valores da Raíz.
- CPF e CNPJ sempre mascarados; nunca nome ou CPF em dados de treino, logs ou arquivos do repositório.
- Licenças: evitar AGPL, EUPL, SSPL, BSL e qualquer licença não comercial (NC). GPL só em serviço no servidor,
  nunca embutido no produto distribuído. Ao copiar código de terceiros, registrar em `NOTICE.md`.
- Preferir ferramentas abertas: o objetivo é construir inteligência própria da Raíz, que aprende com os próprios
  acertos e erros (guardar cada previsão com a versão do modelo e comparar com o resultado real).
- O motor (`motor/`) é o contrato de dados: ler colunas pelo nome (`docs/colunas.md`) e tolerar colunas novas.
- Segredos só em variáveis de ambiente (`.env`, nunca no git). Dados grandes não entram no git.
- Roteiro de construção: `docs/plano-por-etapa.md`.
- Norte do produto: `docs/cena-alvo.md` (o cliente pede "1 milhão de créditos" e o mapa monta o melhor lote). Todo trabalho deve aproximar essa cena.
