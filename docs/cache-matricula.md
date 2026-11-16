# Cache calibrado da matrícula

`certidao ler` e `certidao lote` reutilizam uma extração do mesmo PDF somente com corte
calibrado. A conferência contra CAR/SIGEF, as regras e a idade da certidão são refeitas
em cada uso. Troca do PDF, modelo, esforço, prompt, esquema ou leitor exige outra leitura.
Uma resposta de modelo de reserva não é reaproveitada para o modelo pedido.

Cada leitura guarda `escore_confianca`, `escore_versao` e a origem (API, manual ou
simulação) nos derivados imutáveis. O escore de 0 a 1 combina confiança declarada,
legibilidade e campos presentes; **não é probabilidade de acerto**. As decisões ficam
na tabela `cache_decisao` do SQLite dos documentos, com hash da calibração e sem o PDF.

A leitura também guarda `receita_hash`, calculado automaticamente dos arquivos de
extração, saneamento e escore, versão do Python e dependências Anthropic/PDF. Alterar
esses componentes exige reler, mesmo sem mudar a versão manual do pacote. Os cortes
guardam `calibrador_hash`, incluindo MAPIE, scikit-learn, NumPy, SciPy, código dos
gabaritos e parâmetros do controle de risco; alterar essa base exige recalibrar.
Leituras e relatórios antigos sem esses hashes não são aceitos no cache.

A calibração usa MAPIE (BSD-3), Learn Then Test, precisão mínima de 95%, confiança de
95% e correção de Bonferroni para cinco cortes fixos. Esses limites valem sob a hipótese
de que as matrículas conferidas representam a produção. Antes de conferir, sorteie
matrículas da população que será lida; não escolha só as difíceis ou fáceis. Uma mesma
matrícula conta uma vez por receita, mesmo que tenha vários PDFs ou tentativas.

O gabarito antigo `--confirma` confirma **somente a situação**. Para medir a qualidade
da extração inteira, alguém deve conferir todos os fatos extraídos contra o PDF e
registrar explicitamente a leitura correta ou incorreta:

```bash
uv run python -m raiz.documentos aprendizado marcar 42 --fonte conferencia_humana \
  --leitura-correta --amostra-aleatoria-cache
uv run python -m raiz.documentos aprendizado marcar 43 --fonte cartorio \
  --leitura-incorreta --amostra-aleatoria-cache
uv run python -m raiz.documentos aprendizado calibrar-cache
```

O relatório e os cortes ficam em `dados/documentos/cache-calibracao.json`, fora do git.
Só entram fontes `cartorio`, `onr` ou `conferencia_humana` com revisão integral da
amostra aleatória declarada. Leituras simuladas, humanas e revisões parciais não
calibram a qualidade do modelo. Não há corte pré-aprovado no repositório: com poucos
gabaritos ou erro excessivo, a saída diz `sem corte: continuar relendo`.

A calibração vence após 90 dias. Correção ou acréscimo de gabarito integral invalida o
relatório e exige recalibrar. Uma leitura desmentida por qualquer campo conferido não
é reutilizada. Arquivo ausente, inválido, vencido ou de outra receita faz o leitor
seguir com a API. O cache evita apenas nova extração, não substitui uma certidão atual.
Para auditoria ou releitura deliberada, use `--forcar-releitura`; para testar outro
relatório local, use `--calibracao-cache CAMINHO`.
