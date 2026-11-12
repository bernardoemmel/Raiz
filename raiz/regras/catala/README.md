# Regras federais em Catala

Referência legal da Raíz para o Código Florestal (E2 passo 2): o texto dos arts. 4º, 12, 15, 61-A, 61-B, 67 e 68
(e do art. 19 do Decreto 7.830/2012), cada trecho seguido do código que o traduz. O Catala
([catala-lang.org](https://catala-lang.org), Apache-2.0) ainda não tem dialeto em português: as palavras-chave ficam
em inglês, os nomes e o texto em português.

| Arquivo | O que tem |
|---|---|
| `prologo.catala_en` | tipos (imóvel, vegetação, corpo d'água) |
| `codigo_florestal.catala_en` | texto da lei e regras: `ReservaLegal`, `FaixaApp`, `AppARecompor`, `LaudoFederal` |
| `testes/testes_federal.catala_en` | testes com imóveis reais do funil (município 1504950) e casos de cada artigo |
| `clerk.toml` | projeto do clerk (compilador e testes) |

## Como as peças conversam

- `raiz/regras/gerado/`: o Python gerado pelo Catala (não edite à mão; `ORIGEM.json` guarda o hash de cada fonte).
- `raiz/regras/referencia.py`: chama o código gerado com uma linha do motor (colunas de `docs/colunas.md`).
- `raiz/regras/federal.py` e `raiz/regras/parametros/federal.yaml`: o caminho vetorizado, para milhões de imóveis.
- `testes/test_regras_catala.py`: os 72 imóveis de teste e o Hypothesis conferem que Catala, motor e caminho
  vetorizado dão o mesmo número. Se alguém mudar um `.catala_en` sem gerar de novo, o teste `test_gerado_em_dia` falha.

## Mudar uma regra

1. Edite o `.catala_en` (texto da lei e código juntos) e, se mudar um número, a tabela `federal.yaml` com nova versão
   nomeada (`regras-2026c`...).
2. Gere e teste: `raiz regras gerar` (roda `clerk test` e `clerk build` e copia o Python).
3. `pytest testes/test_regras_catala.py testes/test_regras_federal.py`.

## Instalar o Catala (só quem edita as regras)

O CI e o servidor não precisam do compilador, só do Python gerado. Para editar:

```bash
apt-get install -y opam ocaml-nox libgmp-dev ninja-build m4 pkg-config
```

```bash
opam init --bare -n --disable-sandboxing && opam switch create catala ocaml-system && opam install -y catala
```

Leva uns 10 minutos em 4 núcleos. Atrás de proxy que bloqueia o GitHub, o opam baixa as fontes do cache
opam.ocaml.org.

## Leituras da Raíz que vale conferir com advogado

- Extremos das alíneas do art. 4º, I (10, 50, 200 e 600 m aparecem em duas alíneas): 10 m já é alínea b; 50 e 200 m
  vão para a faixa de cima; 600 m fica na alínea d.
- Arts. 12, §§ 4º e 5º: a redução a 50% só vale quando quem chama diz que o município ou o estado cumpre as condições;
  o motor usa 50% sempre, como cenário do lado da oferta (`pct_RL_alem`), e o laudo chama assim.
- Art. 67: o déficit continua medido (`deficit_ha`), mas o devido (`deficit_devido_ha`) é zero até 4 módulos fiscais.
- Art. 15: a floresta remanescente do motor já inclui a APP com floresta; só a APP conservada sem floresta soma à parte.
- A transcrição dos artigos precisa ser conferida contra o link arquivado da lei (pendente na tabela de parâmetros).
