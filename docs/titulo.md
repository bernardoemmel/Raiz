# Título (`raiz/titulo/`, E5)

A posse é o maior gargalo dos lotes: no primeiro lote, 623 de 702 fazendas estavam em posse. Este módulo diz, para
cada imóvel em posse ou lote de assentamento, **quão perto do título ele está e o que fazer primeiro**, e junta todo
achado de título (regularização e certidões) numa tabela só, com quem confirmou cada um.

## Regularização da posse

```bash
raiz titulo recalcular                 # regularizacao_<mun>.csv e achados_<mun>.csv que faltam ou mudaram de regra
raiz titulo resumo 1504950             # imóveis, hectares e tCO2/ano por classe
raiz titulo mutiroes 1504950           # vizinhas que só precisam do georreferenciamento, por grupo
```

O executor roda sozinho a tarefa `titulo` depois da `terra` (refaz quando a regra muda ou quando chegam certidões
conferidas). Regra em `raiz/regras/padroes/regularizacao.yaml`; colunas em `docs/colunas.md`.

| Classe | Quando | Próximo passo |
|---|---|---|
| em titulação | parcela em titulação no SIGEF (ou lote de assentamento titulado) | pedir ao dono o número do processo e acompanhar no INCRA ou no órgão de terras do estado |
| pronta para pedir | georreferenciamento certificado, uso antes de 22/07/2008 visto no satélite, sem impedimento nem pendência | pedir a titulação; falta só a declaração do dono |
| falta georreferenciamento | só falta certificar no SIGEF | contratar o georreferenciamento (profissional credenciado no INCRA) |
| pendente | embargo, desmatamento depois de 2020, CAR suspenso ou cancelado, ocupação sem prova no satélite, acima de 2.500 ha | resolver a primeira pendência |
| impedida | terra indígena, quilombo, UC de domínio público ou floresta pública a partir de 1 ha | fora da originação |

Na amostra de Nova Esperança do Piriá (880 imóveis): 75 em titulação, 3 prontos para pedir, **599 só com o
georreferenciamento faltando** (cerca de 157 mil tCO2/ano de potencial), 82 pendentes e 8 impedidos. O
georreferenciamento é a alavanca. `raiz titulo mutiroes 1504950` junta esses imóveis por grupo de vizinhas (grupo_id
do valor para quem restaura, pontos a até ~15 km): na amostra, 17 grupos; o maior tem 112 fazendas (111 pequenas,
5.855 ha, 26 mil tCO2/ano), o que um mesmo profissional certifica numa ida a campo.

Requisitos checados por dado público, cada um com a base legal e a fonte: fora de terra indígena e quilombo; fora de
UC de domínio público e floresta pública; georreferenciamento certificado; ocupação antes de 22/07/2008 (área aberta até
2008 no PRODES); área de até 2.500 ha; sem embargo; sem desmatamento depois de 2020; CAR ativo (CAR "pendente" no
SICAR não segura: só pede para ver a pendência). Os requisitos pessoais (sem outro imóvel, sem benefício anterior)
ficam sempre "conferir": a Raíz não usa CPF. Também saem a gratuidade (até 1 módulo fiscal) e, se a terra for
particular, a alternativa de usucapião (especial até 50 ha com 5 anos de uso; 10 anos com moradia ou produção).

**Base legal a conferir**: as citações da Lei 11.952/2009, da Lei 10.267/2001, da Lei 8.629/1993 e a lista dos órgãos
estaduais estão marcadas `conferido: false` no YAML. Antes de citar ao dono ou num contrato, o jurídico confere e muda
a marca (a versão da regra muda sozinha).

**Aprendizado**: a chance a priori de título em 12 meses (por classe) entra congelada em `aprendizado.previsao`
(modelo `regularizacao`, alvo `titulo_regularizado_12m`). `raiz titulo gabaritar` marca 1 quando a rodada seguinte põe o
imóvel em matrícula e 0 quando o prazo vence; com os gabaritos, as chances e os prazos do YAML se calibram.

**Onde aparece**: a classe vai na linha do imóvel (API e ficha), na oferta do pedido de lote (`regularizacao_classe`) e
no quadro "o que destrava o lote" do lote do ProFloresta+, que agora separa as fazendas em espera pela classe.

## Conferir a terra pela geometria

```bash
raiz titulo memorial memorial.pdf --cod-imovel PA-1504950-...        # lê, fecha e confere com o CAR e o SIGEF
raiz titulo memorial memorial.txt --cod-imovel ... --modelo --gravar # modelo só com nota baixa; achados no banco
raiz titulo planilha georref.ods --cod-imovel PA-1504950-...         # planilha ODS do georreferenciamento
raiz titulo conjunto-teste 1504950 --n 200                           # placar de regressão do leitor de memorial
```

- **Memorial** (`raiz/titulo/memorial.py`): regras em português leem vértices (código do SIGEF ou "M-01"),
  coordenadas geográficas ou UTM (fuso ou meridiano central), azimute ou rumo, distância, área e perímetro. A nota de
  confiança junta vértices com coordenada, lados completos, fechamento (1:5.000 ou melhor) e área declarada; abaixo
  de 80%, entra o modelo da Anthropic (só então) e, se continuar baixa, o achado pede revisão. Nome de confrontante
  nunca é guardado.
- **Geometria** (`raiz/titulo/geometria.py`): azimute e distância no elipsoide GRS80 (SIRGAS 2000), erro de
  fechamento, precisão 1:N e ajuste pela regra da bússola; comparação entre duas descrições da mesma terra na escala
  D1 a D7 (D1 coincide até a tolerância; D2 até 2 vezes; D3, D4 e D5 sobreposição de 95%, 90% e 70% ou mais; D6
  parcial; D7 não se sobrepõem), com as tolerâncias do INCRA: 0,50 m (limite artificial), 3,00 m (natural), 7,50 m
  (inacessível). O plano citava "classes D1 a D7" sem defini-las: a escala acima é a da Raíz.
- **CAR contra SIGEF**: a tarefa do município compara o polígono de cada CAR com a união das parcelas do SIGEF que o
  cobrem (tolerância de 7,50 m, porque o CAR é declarado) quando há `geo_<mun>.parquet` e o espelho do SIGEF.
- **Planilha ODS** (`raiz/titulo/planilha.py`): lida com zip e ElementTree; as colunas são achadas pelo nome do
  cabeçalho (código, longitude, latitude, sigma, tipo de limite, CNS, matrícula) e a validação confere o padrão do
  código, coordenadas, repetidos, precisão contra a tolerância do limite (LA 0,50 m, LN 3,00 m, vértice V 7,50 m) e o
  polígono. **O layout exato da planilha do SIGEF não foi conferido com um arquivo real**: o leitor avisa as colunas
  que não achou; conferir com a primeira planilha que chegar.
- **Conjunto de teste**: sorteia parcelas do SIGEF do espelho, escreve o memorial de cada uma nos dois estilos (SIGEF e
  antigo, por rumo) com um gerador próprio (o LFTools e o GeoPlanta são GPL e não entram) e mede o acerto do leitor.

## Nota de risco e decisão

`titulo_<mun>.csv` (regra em `raiz/regras/padroes/nota_titulo.yaml`): nota de 1 (título em ordem) a 5 (não segue) a
partir do caminho da terra e do risco (ou da classe da regularização, na posse), mais 1 por fase com achado que
reprova e ninguém confirmou (até 2), ônus grave e divergência geométrica (D5 +1, D6 +2); piso 5 com matrícula
cancelada e 4 com certidão divergente. Decisão: **aceitar** (nota até 2, nada a conferir), **aceitar com condições**
(até 3; as condições são os achados a confirmar e o motivo do risco da terra), **análise humana** (4) ou **recusar**
(5). Na amostra de Nova Esperança do Piriá: 719 aceitar com condições, 82 análise humana e 79 recusar (71 terra
pública sem destinação e 8 posses impedidas).

## Achados e confirmações

```bash
raiz titulo pendentes [--cod-imovel ...]                    # reprova ou confirmar, ainda sem confirmação
raiz titulo confirmar 123 --quem fundador --decisao confirmado --nota "visto no SIGEF"
```

Achado no formato do CFPB: registro (chave `car:<CAR>|sigef:<parcelas>|mat:<CNS>/<matrícula>`), regra, campo, valor,
situação, gravidade (reprova, confirmar, info) e fase (formato, geometria, coerência, referência, cadeia,
regularização). Os motivos de cada certidão lida em `raiz/documentos` entram com a fase certa. A carga grava em
`titulo.achado`; a confirmação (`titulo.confirmacao`) só recebe linhas novas, guarda o identificador do operador (nunca
nome) e vale para a mesma regra do mesmo imóvel enquanto o valor não mudar (`titulo.achado_vigente`).

## Matrícula conferida e selo prata

A conferência das certidões (`matricula_<mun>.csv`, de `raiz/documentos`) entra na carga como complemento do imóvel:
o caminho da terra dá risco baixo à matrícula conferida, a ficha sobe a etapa para título conferido (selo prata) e a
oferta usa o caminho `matricula_conferida`.
