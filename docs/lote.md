# Dossiê executivo do lote por município

O que o Bot Agro montava na mão para Paragominas em 17/11/2026 (4 lotes, 17 imóveis, cerca de 13 mil ha) agora sai
automático: `raiz dossie lote --municipio <IBGE>` lê o que o processamento já calculou, aplica os filtros abaixo e
grava o dossiê em Markdown, PDF, Word e JSON. Código: `raiz/dossie_lote.py`. Regras e limiares:
`raiz/regras/padroes/dossie_lote.yaml` (a versão vai gravada no dossiê).

O dossiê **não muda a ciência do funil**: não recalcula floresta, restauração, terra nem previsões. Só filtra, agrupa
e formata. Nenhum imóvel sai por tamanho: pequenas entram no lote mais próximo.

## Como rodar

```
uv run raiz dossie lote --municipio 1505502 --pasta saida/PA --modo normal
uv run raiz dossie lote --municipio 1505502 --modo estrito --enviar   # baixa o estado do arquivo privado
```

`--limites` aponta para um `comprometida_limites.parquet`; sem ele, usa o do Release `insumos` em cache. Os arquivos
saem em `dados/documentos/dossie/` (fora do git). Com `--enviar`, vão para o arquivo privado.
No Actions: workflow **Dossiê executivo do lote** (`.github/workflows/dossie-lote.yml`), com o código do município e o
modo; baixa só o município do arquivo privado e os limites do Release `insumos`, e o dossiê vai só para o arquivo
privado (sem artifact nem código de fazenda no log).

## Modos

| Caso | estrito | normal |
|---|---|---|
| Sobreposição real com limite oficial de projeto de carbono | sai | ressalva forte |
| Sobreposição com limite secundário (InfoAmazonia, Zenodo etc.) | sai | ressalva forte, "a conferir" |
| Mais de 10% do CAR em gleba federal não destinada (CNFP/SFB) | sai | ressalva forte |
| Posse sem matrícula nem SIGEF | sai | ressalva forte |
| Dentro de KML regional (agrupado ou acima de 500 mil ha) | ressalva média | ressalva média |
| Só certificado no SIGEF, sem registro | ressalva média: pedir inteiro teor | igual |
| Limite de projeto a menos de 100 m, sem cruzar | ressalva leve | ressalva leve |

Em qualquer modo saem: desmatamento PRODES desde 2016, alerta MapBiomas, embargo Ibama, embargo ICMBio, LDI/SEMAS,
terra indígena, UC de proteção integral e de uso sustentável, quilombo, assentamento e os caminhos da terra que não
originam com particular (pública sem destinação, terra indígena ou tradicional, assentamento). A tolerância é 0,01 ha
(100 m², ruído de borda). Coluna que não existe nos dados não filtra nada e aparece no dossiê como "não disponível nos
dados: conferir" (hoje é o caso de embargo ICMBio e LDI/SEMAS no Pará).

## Carbono

Cruza o CAR com todos os limites do `comprometida_limites.parquet` (KML oficial da Verra, InfoAmazonia,
Renoster/CarbonPlan, GeoPackage Zenodo do Pará, lista CAR × REDD+ e os 19 projetos Verra "Other"). Situações
retirado, encerrado, inativo, cancelado e rejeitado não contam.

- **KML regional** nunca exclui. É regional o projeto da lista `agrupados_regionais` (VCS4137, VCS5184, VCS3380,
  VCS3713, VCS4849), o limite marcado `limite_suspeito`/`limite_amplo` ou acima de 500 mil ha. O dossiê diz "risco de
  sobreposição a conferir" e mostra a distância até a instância pública conhecida do mesmo projeto (polígono não
  regional de qualquer fonte), ou "sem instância pública".
- **Cruzamento real** (área acima da tolerância): exclusão no estrito, ressalva forte no normal, com o projeto, os ha
  e a fração do CAR.
- **Divisa** a menos de 100 m sem cruzar, ou cruzamento abaixo de 1 ha (desencontro de borda entre bases): ressalva leve.
- `projeto_carbono_ha` do dossiê é o maior entre o do motor e o cruzamento com limite oficial: não sai mais zero quando
  o polígono cruza.

## Matrícula

Vem do caminho da terra (`raiz/terra.py`): sem parcela no SIGEF, vale a cobertura de matrícula da tabela de imóveis
(`matricula_ha`), e a falta de SIGEF não vira posse. Imóvel só certificado no SIGEF (posse ou titulação, sem registro)
ganha a ressalva "pedir inteiro teor".

## Lotes

Por vizinhança do centróide do CAR: o maior imóvel apto ainda solto abre um lote e entram todos a até 12 km dele. Imóveis
sem ressalva forte formam lotes entre si e vêm primeiro; os de ressalva forte (só no modo normal) formam lotes à parte,
para a ressalva de um não derrubar a prontidão do lote inteiro. Os
lotes vão por ha restaurável (previsão de restauração; sem ela, a área aberta restaurável do motor). O dossiê detalha
os 4 maiores e soma o resto como "potencial adicional no município". A prontidão do lote é a do pior imóvel: baixa com
ressalva forte, média com ressalva média ou leve, alta sem ressalva.

## O que o dossiê traz

1. Título "[Município]: N lotes de restauração para avaliação".
2. Oferta (imóveis lidos, aptos, ha, modo, versão da regra).
3. Tabela | Lote | Imóveis | ha restauráveis | Raio / centro | Principais ressalvas | Prontidão |.
4. Checklist das conferências em dado público (o que foi cruzado e o que faltou nos dados).
5. Validação humana: proprietários, cartório (inteiro teor ≤ 30 dias, cadeia dominial, CNIB), outros desenvolvedores
   (Carbonext e demais), certidões e campo.
6. Potencial adicional no município.
7. Anexo dos CARs por lote: código, ha, ha restaurável, matrícula e observações.

Só o código público do CAR e números: nada de nome, CPF ou CNPJ.

## Conferência em Paragominas (17/11/2026)

Dados reais (geo do Release `dados`, CNFP 2025, SIGEF e limites do Release `insumos`):

| CAR | ha | Gleba federal (CNFP) | Carbono | Matrícula |
|---|---|---|---|---|
| D4386947 | 1.094 | 0% (gleba Croatá mais próxima a ~11 km) | dentro do regional VCS4137; VCS4681 a 1,1 km | 100% em parcela SIGEF registrada |
| CE800C8A | 1.266 | 0% | regional VCS4137; divisa a 34 m do VCS4681 (leve) | 100% em parcela SIGEF registrada |
| A5BAFA27 | 3.260 | – | cruza VCS4681 (YBYRÁ) em ~1.469 ha, 45% do CAR: sai no estrito, forte no normal | matrícula |
| A79C0259 | 3.154 | – | regional VCS4137; divisa a 69 m do VCS1953 (leve) | matrícula |

A informação de "~47–53% na gleba Croatá" para D4386947 e CE800C8A não se confirma no CNFP 2025 (shapefile completo
do SFB, publicado em 26/06/2026, sem recorte por UF e com todos os tipos): as glebas Croatá (A-1, A-2, A-3, A-5, A-6,
A-7; tipo B, federal, INCRA) ficam a 11 km ou mais dos dois, e o SIGEF mostra os dois 100% em parcela particular
registrada. Em Paragominas, quem tem a faixa citada é outro CAR: **0A690BF4** (1.121 ha, 53% em Croatá) e
**011CEC9E** (1.614 ha, 30%). Os dois passam do limiar de 10% e o dossiê já os trata como gleba federal (fora no
estrito, ressalva forte no normal) quando o processamento tem o CNFP.
