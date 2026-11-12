# Acerto do modelo no site

A rota `#/acerto` mostra as métricas reais do aprendizado por modelo, versão, alvo e horizonte. A comparação
usa previsões congeladas e gabaritos posteriores ao corte, com fonte e data. Separa previsões ao vivo de
reexecuções retrospectivas (`backtest`), sem somar seus casos nem afirmar validação prospectiva no backtest. O horizonte precisa ter terminado;
observações futuras e faixas inválidas ficam fora. A tela não apresenta um percentual geral nem elege uma versão
vencedora a partir de médias de populações diferentes. O portão de campeão/desafiante continua separado.

A interface mostra WIS, erro absoluto, cobertura da faixa de 80%, Brier, log score ou categorias corretas,
conforme o tipo previsto. Preserva zero observado e ausência de evidência como estados diferentes. Informa
número de comparações, imóveis distintos, período dos cortes, última observação e data do resumo. Menos de
30 imóveis recebe aviso de evidência inicial; esse aviso não representa um teste de significância estatística.

## Público e privado

`GET /acerto/resumo` usa o contrato `raiz.acerto.publico.v1`, construído por lista positiva em
`raiz/aprendizado/painel.py`. Um grupo precisa de pelo menos cinco imóveis **distintos** com observação válida.
Repetir a previsão de uma mesma fazenda não satisfaz o mínimo. Grupos pequenos não expõem nem nota nem contagem;
CAR, observações individuais, fontes textuais livres e qualquer campo extra são descartados.

`GET /acerto/placar`, o hub, o histórico e suas linhas continuam privados. Não se deve apontar o site para seus
arquivos, copiar o token operacional para o navegador ou publicar um pacote completo de aprendizado.

## Alimentação

Com `VITE_RAIZ_API`, o navegador consulta a nova rota agregada, sem token operacional. No Pages, lê
`acerto/placar.json`, sempre incluído pelo build, mesmo sem fonte configurada. Sem dados, o arquivo tem
`gerado_em: null` e `versoes: []`; a interface explica que a publicação ainda não está ligada, sem tentar uma
URL inexistente ou inventar acurácia.

No servidor com o banco de aprendizado, exportar somente o resumo:

```bash
uv run raiz aprendizado acerto-publico dados/acerto/placar.json
```

A variável de Actions `RAIZ_ACERTO_URL` pode apontar para o JSON agregado por HTTPS público (por exemplo, a rota
`/acerto/resumo` de um servidor já instalado). A publicação diária baixa o resumo e o reprojeta antes de gerar
o site. Falha de rede, esquema ou métricas interrompe o build; não transforma erro em zero. Um arquivo local
explícito pode ser indicado por `RAIZ_ACERTO_DADOS`. Dados de entrada e caches não entram no git.

Na inspeção de 12/11/2026, o Release público não anunciava um placar de acerto. O histórico privado já recebe
retratos de previsão; isso sozinho não comprova desempenho contra resultados reais. Nenhum número do benchmark
sintético nem da avaliação de intenção do assistente foi usado como acerto do motor. Não há servidor de produção
configurado nesta entrega, portanto a publicação inicial apresenta a ausência de comparações publicáveis.

## Verificação

Os testes Python cobrem nota conhecida, zero real, faixas inválidas, maturidade, fonte/data, separação de
horizontes/versões e privacidade. O parser do navegador revalida o contrato e descarta campos não permitidos.
`npm run test:acerto` verifica filtros, duas versões, zero observado, ausência, teclado, axe WCAG 2.1 AA,
1440/360 px e zero 404. A página também entra nas três medições fixas do portão Lighthouse mobile (mediana de desempenho e acessibilidade mínima de 90). Seus números são fixtures exclusivas do teste, sem dados reais individuais.
