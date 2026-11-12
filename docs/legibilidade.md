# Medidor de legibilidade

Toda mensagem ao dono sai com uma nota de legibilidade. A nota fica guardada junto da mensagem, com a versão do
medidor, para comparar depois com o que o dono entendeu no teach-back do aceite.

## Onde a nota aparece

- Mensagens do aceite pelo WhatsApp: coluna `legibilidade` de `pessoal.mensagem_saida`, também em
  `GET /mensagens/pendentes`. Quem aprova vê a nota antes de mandar.
- Avisos da vigilância ao cliente: campo `legibilidade` de cada aviso.
- No terminal:

```bash
raiz legibilidade modelos
```

```bash
echo "Pela nossa estimativa, 12 hectares podem voltar a ser mata." | raiz legibilidade medir
```

## O que é medido

A contagem de letras, palavras, sílabas e frases é a do ALT (legibilidade.com), copiada do código aberto dele (MIT).
Com essa contagem saem três versões do Flesch para o português. Todas ficam guardadas, porque cada uma tem um uso:

| Versão | Fórmula | Para quê |
|---|---|---|
| ALT | 226 − 1,04 × palavras por frase − 72 × sílabas por palavra | Bate com o site legibilidade.com |
| Martins (1996, USP) | 248,835 − 1,015 × palavras por frase − 84,6 × sílabas por palavra | A mais citada no Brasil. Faixas: 75 a 100 muito fácil, 50 a 75 fácil, 25 a 50 difícil, abaixo de 25 muito difícil |
| LanguageTool | 206,84 − 1,02 × palavras por frase − 60 × sílabas por palavra | A mesma conta do corretor que vai rodar antes de cada envio (E9, passo 2). Nível de 0 a 6 nos cortes dele |

Flesch mais alto é mais fácil. Também saem os índices do ALT em anos de estudo (Flesch-Kincaid, Gunning Fog, ARI,
Coleman-Liau) e o resultado do ALT, que é a média dos quatro: abaixo de 13 é legibilidade alta, de 13 a 17 média,
acima de 17 baixa.

## Antes de contar

O texto é lido como se fala: "R$ 1.200" vira "mil e duzentos reais", "12/11/2026" vira "doze de novembro de dois mil e
vinte e seis", "12,5%" vira "doze vírgula cinco por cento" e "art." vira "artigo". Sem isso o ALT conta "1.200" como
palavra sem sílaba e o ponto do milhar como fim de frase. `raiz legibilidade medir --cru` mostra a contagem do ALT sem
essa preparação.

## Revisor de estilo (LanguageTool)

Com o servidor próprio do LanguageTool no ar, cada mensagem também leva os avisos de estilo e legibilidade dele:
frase longa, parágrafo difícil, pleonasmo ("subiu para cima"), prolixidade ("a geração de" → "gerar"). Ortografia e
gramática ficam de fora (o nome da Raíz e as siglas não são erro). O texto vai só para o servidor da Raíz.

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d revisor
```

Depois, `RAIZ_LANGUAGETOOL_URL=http://localhost:8010` no `.env`. Sem ele, a nota sai só com o medidor. Com o servidor
fora do ar, a nota diz o erro e a mensagem segue para aprovação: quem aprova decide. Os avisos aparecem em
`raiz legibilidade medir` e ficam em `legibilidade.languagetool` de cada mensagem.

## O que ainda falta

- Palavra complexa (Gunning Fog): o ALT usa as 5.000 palavras mais comuns de uma lista da Linguateca, sem licença
  clara. Sem ela, conta como complexa a palavra com 4 sílabas ou mais. Com uma lista aberta, basta apontar
  `RAIZ_PALAVRAS_COMUNS` para o arquivo (uma palavra por linha, da mais comum para a menos comum).
- Nota mínima para mandar: o portão (E9, passo 3) calibra com 30 cartas reais. Até lá, o teste só barra modelo novo com
  Martins abaixo de 50 ou mais de 15 palavras por frase.
