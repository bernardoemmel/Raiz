# Avaliação de carbono, equidade e mudança de modelo

A suíte `testes/avaliacao_modelos/` verifica o procedimento com dados **sintéticos**. Ela não demonstra que a
Raíz já prevê carbono com acerto no campo. Ainda falta uma coorte independente com resultados reais maturados,
sorteios originais e cobertura por município/porte. Ausência dessa evidência reprova a avaliação privada;
não se preenche resultado real com previsão do próprio modelo.

## Previsão contra resultado

`raiz.avaliacao.metricas.crps` usa `properscoring.crps_ensemble`. Recebe todos os sorteios finitos, de igual peso,
da distribuição congelada e a medição real na **mesma unidade e horizonte**.
O backend Numba é obrigatório: o fallback quadrático de properscoring 0.1 é recusado para não alocar uma matriz
de 20.000 × 20.000 sorteios. Nenhum sorteio é descartado para acelerar a avaliação. O resultado tem a unidade do alvo;
menor é melhor. Penaliza tanto distância ao real quanto dispersão indevida. Não aceita NaN, infinito ou amostra
vazia e não interpreta três quantis como três sorteios. Uma distribuição realmente degenerada pode ter sorteios
iguais. Não se afirma que o P50 determinístico atual seja uma mediana empírica.

O placar existente de `aprendizado.acerto` calcula CRPS das previsões com faixa que também guardam
`distribuicao = {"tipo": "empirica", "sorteios": [...]}`. `crps_n` informa quantas foram avaliadas; quantis sem
sorteios continuam com WIS/cobertura e não recebem CRPS inventado. O número de previsões com gabarito pode ser
maior que `crps_n`. O portão privado usa exclusivamente distribuições completas.

O hash do registro agora inclui a distribuição, em JSON canônico. Trocar sorteios com a mesma versão deixa de
ser descartado silenciosamente como lote repetido: a unicidade do banco exige uma **nova versão**. Os registros
anteriores não são regravados. Lotes antigos sem distribuição preservam seus hashes. Lotes históricos que tinham
distribuição sob o hash antigo não provam sua integridade: `conferir_lote` reprova essa situação; o responsável pelo
arquivo deve conservar o original e produzir uma atestação adicional, nunca alterar a previsão passada.

## Origem móvel e treino

`raiz.avaliacao.tempo.avaliar` usa `sktime.split.ExpandingWindowSplitter` no calendário explícito de decisões.
Em cada origem só entrega ao callback observações cujo evento, conhecimento do resultado e disponibilidade das
entradas já ocorreram. A previsão recebe o corte e as datas futuras, sem os resultados futuros. Gabarito tardio
pode avaliar a previsão antiga; só entra em treino posterior ao seu registro. Horizonte é posição nesse calendário,
não quantidade de fazendas. Cada callback deve ajustar uma instância nova, com os retratos imutáveis descritos em
[aprendizado por tempo](../aprendizado-por-tempo.md). O executor não transforma bases atuais em passado histórico.

`classificador_balanceado` constrói uma Pipeline do imbalanced-learn: normalização e RandomOverSampler são
ajustados apenas no treino. `predict` preserva os casos e a prevalência do teste. Validação, conjunto cego e
cálculo de equidade nunca são reamostrados. Separar por tempo antes de `fit`; não ajustar hiperparâmetros no cego.

`variancia_floresta` usa o infinitesimal jackknife de forestci, com bootstrap e pelo menos 100 árvores; variância
negativa/não finita reprova. Mede incerteza da média estimada pela floresta, **não** a distribuição do resultado
futuro. Não serve sozinho para criar sorteios de CRPS. `caudas` usa mpl-probscale (pacote PyPI `probscale`) para
gráfico privado e quantis 1/50/99% do erro, além de P95 do erro absoluto. Mantém sinais e extremos. Esses
instrumentos não substituem o modelo em produção.

## Nunca descartar por tamanho

A política está em [infra/politica-avaliacao.json](../../infra/politica-avaliacao.json): limite inicial de **5 pontos
percentuais**, mínimo de 30 fazendas distintas por classe no ensaio real. São escolhas explícitas da Raíz, não
limites prescritos pelas referências. Pequena tem até 4 módulos fiscais; média, mais de 4 até 15; grande, mais de
15. Valores ausentes, zero ou negativos não viram automaticamente pequenas.

AIF360 calcula a diferença de taxas de seleção entre **cada par de classes**, separadamente por município e
aptidão. A magnitude acima do limite reprova, inclusive diferença favorável às pequenas. Classes ausentes ou
insuficientes também reprovam. Cada fazenda pesa igualmente dentro da classe; decisões repetidas não aumentam
sua cobertura nem seu peso. Aptidão deve ser definida antes da seleção, sem usar área total como substituto,
com a receita e a coorte fixadas no plano. Alterar aptidão ou remover uma fazenda muda o hash do denominador.

No CI, cenários contrafactuais passam por `filtrar` e pelo solver real das três opções: duas municipalidades,
duas faixas de aptidão, mesmo crédito/custo/área apta e total do CAR variado. Há incluídas e não incluídas.
A rotação balanceada de classes testa discriminação direta por porte; não estima chance na população real.
Esse teste usa mínimo de 12 casos por classe por ser sintético. Outro teste injeta diferença local que se anula
na média nacional e exige reprovação. O pytest normal inclui todos esses ensaios.

## Plano anterior à troca e prova cega

Os contratos JSON Schema estão em [esquemas/avaliacao](../esquemas/avaliacao/), derivados dos validadores
fechados de `raiz.avaliacao.contratos`. Campos novos não autorizados são rejeitados. Identificadores são UUIDs
opacos e hashes; não há nome, documento civil, endereço ou contato. A ligação privada entre UUID e CAR, se
necessária, fica fora do dossiê e do repositório, sob controle do responsável pelo dado.

O plano fixa antes do treino: versão anterior, receita candidata, tipos permitidos de mudança, hash das previsões
antigas, do conjunto cego, da coorte de inclusão, da política de equidade e do controle estável. Fixa também mínimo,
teto absoluto de CRPS e aumento máximo em cada subgrupo. O artefato treinado tem seu próprio hash nas previsões;
a receita candidata é que já deve existir antes do treino. Aprovação compara exatamente os mesmos casos, corte,
retratos de entrada, unidade e horizonte. Backtest pode ser emitido após o horizonte, mas antes de revelar o cego.

O gabarito registra UUID da amostra cega e do laboratório, procedimento e evidência por hash, medição, incerteza
padrão, datas de registro/revelação e controle associado. O controle estável conserva centro, desvio, tamanho e
hash da referência e multiplicador de limite definidos anteriormente. Exige controle do mesmo procedimento no
dia de cada medição. Um controle fora do limite invalida o ensaio; não se recalcula o limite com o novo resultado.
A revisão da independência do laboratório e da evidência original cabe ao custodiante, não a uma flag declarada
pelo próprio candidato. O hash compromete o conteúdo; não prova sozinho a veracidade das datas ou das medições.

A condição de retorno é fixa: qualquer subgrupo, equidade ou controle reprovado implica manter ou retornar à
versão anterior. Falta de dados também impede aprovação. O CLI não promove nem faz rollback no servidor:
ele produz a decisão verificável e conserva ambos os conjuntos de previsões, inclusive candidatos reprovados.
A ligação transacional desse portão com `campeao.promover` pertence a **Produto e regras**, conforme a passagem.

## Operar o arquivo privado

Instale as dependências de desenvolvimento travadas (`uv sync --frozen --all-extras`). O custodiante prepara o
plano e os hashes sem disponibilizar respostas cegas ao treino. Registre o plano enquanto `fixado_em` corresponde
ao relógio atual (tolerância de cinco minutos) e antes de `inicio_treino_em`:

```sh
uv run python scripts/avaliar_modelos.py dados/avaliacao/plano.json \
  --fixar-plano --arquivo-privado dados/avaliacao/arquivo
```

Após congelar as previsões candidatas, o custodiante revela e reúne o dossiê no esquema `ensaio.json`:

```sh
uv run python scripts/avaliar_modelos.py dados/avaliacao/ensaio.json \
  --arquivo-privado dados/avaliacao/arquivo
```

Sem recibo prévio do plano, com conteúdo alterado ou com qualquer reprovação, o comando termina com código 1.
O mesmo identificador de plano não pode ganhar outra tolerância. Arquivos novos usam criação exclusiva e modo
0600; os antigos nunca são substituídos. Isso não impede um administrador de disco de adulterar arquivos:
no servidor, usar armazenamento privado com retenção imutável, relógio confiável, papéis separados e backup.
O conjunto cego não fica acessível à conta de treino. Só o custodiante executa a avaliação com as respostas.
Nenhum dossiê, gráfico, sorteio, UUID individual ou resultado por fazenda deve ir ao Release, site ou artefato CI.
O stdout informa somente aprovação/ação ou motivo fechado de entrada inválida. Não imprimir `ValidationError.errors()`.

## Funil: só contrato de dados

`FunilFixo` registra a coorte por hash dos UUIDs e denominador inicial, conserva inelegíveis, desconhecidos,
recusas, ausência de resposta e perdas. Exige um registro por caso e consistência de elegibilidade. Trocar o
conjunto e reduzir o denominador falha, mesmo que as contagens voltem a fechar. As categorias seguem o princípio
de contabilizar todos os casos sorteados; não se declara uma taxa AAPOR RR1/RR3 sem definir elegibilidade e desenho.
Não há integração de contato, envio, coleta de telefone ou nome nesta entrega.

## Referências e limites

- [properscoring](https://github.com/properscoring/properscoring): Apache-2.0, CRPS empírico.
- [sktime, splitters](https://www.sktime.net/en/stable/api_reference/split.html): BSD-3-Clause.
- [AIF360, diferença de seleção](https://aif360.readthedocs.io/en/stable/modules/generated/aif360.sklearn.metrics.statistical_parity_difference.html): Apache-2.0.
- [FDA, princípios PCCP](https://www.fda.gov/medical-devices/artificial-intelligence-enabled-medical-devices/predetermined-change-control-plans-machine-learning-enabled-medical-devices-guiding-principles): mudanças previstas, protocolo e impacto.
- [ILAC P9:01/2024](https://ilac.org/publications-and-resources/ilac-policy-series/): ensaios de proficiência e comparações interlaboratoriais.
- [NIST SOP 30](https://www.nist.gov/system/files/documents/2019/05/13/sop-30-process-measurement-assurance-20190506.pdf): acompanhamento de desempenho com padrões de controle.
- [CONSORT](https://www.consort-statement.org/), [STROBE](https://www.strobe-statement.org/checklists/) e [AAPOR](https://aapor.org/standards-and-ethics/standard-definitions/): fluxo, denominadores e disposições documentados.
- [imbalanced-learn](https://imbalanced-learn.org/stable/common_pitfalls.html): MIT, vazamento se reamostrar antes da separação.
- [forestci](https://contrib.scikit-learn.org/forest-confidence-interval/): MIT; [mpl-probscale](https://matplotlib.org/mpl-probscale/): BSD-3-Clause.

FDA, ILAC e NIST inspiram o **formato do protocolo**. Esta entrega não é aprovação médica, acreditação laboratorial
ou certificação de carbono. CONSORT/STROBE/AAPOR não transformam um funil comercial em ensaio clínico ou amostra
representativa. As licenças foram conferidas nos pacotes travados; `scpi`, `scpi-pkg` e `vegan` são barrados no
wheel e no grafo de dependências distribuível, sem exceção por registro GPL no servidor.
