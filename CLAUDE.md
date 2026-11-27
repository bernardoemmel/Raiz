# Instruções para quem trabalha neste repositório

- Idioma: português do Brasil em tudo que o fundador lê (mensagens, commits, documentação, textos da interface).
- Norte do produto: `docs/cena-alvo.md`. O cliente pede "1 milhão de créditos" e o mapa monta três lotes. Pequenas fazendas entram agrupadas; nunca são descartadas por tamanho.
- A demo do hackathon é o site estático. Não acrescente serviço, workflow ou dependência que a demo não usa.
- API paga (Anthropic, Firecrawl ou outra) só com ordem explícita do fundador. Nenhum workflow pode receber essa chave.
- CPF e CNPJ sempre mascarados. Nunca grave nome ou documento de dono em dado de treino, log ou arquivo do repositório. Matrícula e código de cartório não entram na amostra pública.
- Licenças: sem AGPL, EUPL, SSPL, BSL e sem licença não comercial (NC). GPL só em serviço no servidor, nunca no produto distribuído. Código de terceiros entra em `NOTICE.md`.
- O motor (`motor/`) é o contrato de dados: ler colunas pelo nome (`docs/colunas.md`) e tolerar colunas novas.
- Segredos só em variáveis de ambiente (`.env`, nunca no git). Dados grandes não entram no git.
- Entrega: branch própria, PR para a `main`, sem push direto e sem force-push. Fora das áreas críticas, com o CI verde, quem abriu o PR faz o merge. Nunca desligue um check para conseguir mergear.
- Áreas críticas (`motor/`, `.github/`, dados publicados, publicação do site, migrações e estas regras; lista em `docs/politica-de-merge.md`): o check `aprovacao` só passa com o rótulo `aprovado-bernardo`, que só o fundador põe. Agente nunca põe nem tira esse rótulo.
- Não desligue o workflow **Processar estados (motor)** nem apague Release, branch remota ou dado já calculado. Uma falha de publicação não autoriza jogar fora o que já foi feito.
