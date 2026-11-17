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
- Entrega: ao terminar, puxe a main, resolva os conflitos, abra o PR e, com o CI verde, faça você mesmo o merge na main.
  Não precisa pedir permissão ao fundador nem esperar outra sessão. Nunca force-push na main.
- Main protegida: todo código entra por PR, com os checks do CI verdes (agentes, workflows, segredos, front,
  seguranca, testes_python, referencia_para, checagens, e2e, carga, mcp). Proibido push direto, force-push e apagar
  a main, inclusive para administradores. Não há review humano obrigatório: com o CI verde, quem abriu o PR faz o merge.
  Nunca desligue, pule ou marque como opcional um check para conseguir mergear; conserte o que falhou.
- Automações não gravam na main. Workflows publicam em Releases, tags de trava ou no Pages; se um workflow precisar
  mudar arquivo do repositório, ele abre um PR. O painel do `motor/README.md` não é mais regravado pelo Actions
  (a situação dos estados fica no `estados.json` do Release `dados`). Configuração da proteção: `docs/protecao-main.md`.
