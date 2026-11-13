/** Páginas sem JavaScript, montadas com os mesmos agregados públicos do painel. Só roda no build. */
import fs from "node:fs"
import path from "node:path"
import { num } from "./dados/colunas"
import type { Estados, FunilMunicipio } from "./dados/tipos"
import { mascarar } from "./privacidade"
import { malhasPublicas, urlMalhaIbge, type MalhasMapa } from "./dados/malhas-mapa"

interface Catalogo {
  estados: Estados
  municipios: FunilMunicipio[]
  arquivos: Record<string, string[]>
}
interface Opcoes {
  saida: string
  /** Base pública do painel, inclusive quando o plugin monta produtor/. */
  base: string
  siteUrl?: string
  produtor?: boolean
  catalogo?: Catalogo
  malhas?: MalhasMapa
}

const REPO = "https://github.com/bernardoemmel/Raiz"
const REGRAS = "Apta no funil: sem problema, área de carbono maior que zero e no máximo 5 ha desmatados depois de 2016. A indicação de matrícula exige também cobertura de pelo menos 50% do CAR por parcela particular do SIGEF com matrícula. Pequenas fazendas são agrupadas; não são excluídas pelo tamanho."
const LIMITE = "São estimativas e triagens com dados públicos, sujeitas à data e à cobertura de cada fonte. Aptidão não é crédito de carbono certificado, garantia de receita, autorização para intervir na terra ou comprovação de propriedade."
const PRIVACIDADE = "Nome, CPF, CNPJ e contato do dono não aparecem na ficha de prospecção. O contato passa pela Raíz. O site aberto publica agregados, CAR, contorno e situação básica (apto, com pendência ou não apto); a ficha completa exige conta de cliente e créditos pagos, com limites de consulta. O aceite não pode ser presumido a partir da presença no mapa."
const numero = (n: number) => new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(Number.isFinite(n) ? n : 0)
/** Nomes de lugares são texto; nunca podem criar HTML, links ou quebrar a tabela. */
const md = (s: string) => mascarar(String(s)).replace(/[\r\n]+/g, " ").replace(/([\\`*_[\]<>|])/g, "\\$1")
type Indicador = "imoveis" | "sem_problema" | "aptas_carbono" | "ha_carbono" | "aptas_com_matricula" | "ha_carbono_matricula"
const semContagem = (m: FunilMunicipio) => num(m.linha, "imoveis") === null
const soma = (ms: FunilMunicipio[], campo: Indicador) => {
  const valores = ms.map((m) => semContagem(m) ? null : num(m.linha, campo))
  return valores.some((v) => v === null) ? null : valores.reduce<number>((total, v) => total + v!, 0)
}
const protegido = (m: FunilMunicipio) => {
  const imoveis = num(m.linha, "imoveis")
  return m.linha.dados_suprimidos === "true" || (imoveis !== null && imoveis < 5)
}
const disponivel = (valor: number | null) => valor === null ? "Ainda não publicado" : numero(valor)
// Sem contagem conhecida não é possível confirmar o grupo mínimo de cinco imóveis para publicar suas medidas.
const indicador = (m: FunilMunicipio, campo: Indicador) => protegido(m) ? "Suprimido" : disponivel(semContagem(m) ? null : num(m.linha, campo))
const totalPublico = (ms: FunilMunicipio[]) => {
  if (ms.some(protegido)) return "Os totais deste recorte foram suprimidos porque incluem grupos com menos de cinco imóveis."
  const imoveis = soma(ms, "imoveis"), aptos = soma(ms, "aptas_carbono"), hectares = soma(ms, "ha_carbono")
  if (imoveis === null || aptos === null || hectares === null)
    return `Há medidas ainda não publicadas neste recorte. Imóveis: ${disponivel(imoveis)}. Aptos no funil: ${disponivel(aptos)}. Área de carbono nas fazendas aptas (ha): ${disponivel(hectares)}.`
  return `${numero(imoveis)} imóveis, ${numero(aptos)} aptos no funil e ${numero(hectares)} ha de área de carbono nas fazendas aptas.`
}
/** O funil usa zero como padrão de cálculo. Só publicar um indicador opcional se a fonte trouxer um número. */
const indicadorOpcional = (m: FunilMunicipio, coluna: string, rotulo: string) => {
  const valor = num(m.linha, coluna)
  return valor === null || protegido(m) || semContagem(m) ? "" : `| ${rotulo} | ${numero(valor)} |\n`
}

export function paginasAgentes(opcoes: Opcoes): void {
  const { saida, produtor, catalogo } = opcoes
  const base = `/${opcoes.base.replace(/^\/+|\/+$/g, "")}/`.replace(/^\/\//, "/")
  const url = new URL(opcoes.siteUrl || base, "https://bernardoemmel.github.io/")
  if (!url.pathname.endsWith("/")) url.pathname += "/"
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("RAIZ_SITE_URL precisa ser uma URL HTTP(S)")
  const absoluto = (p: string) => new URL(p, url).href
  const link = (p: string) => produtor ? `../${p}` : base + p
  const gravar = (p: string, texto: string) => {
    const arq = path.join(saida, p)
    fs.mkdirSync(path.dirname(arq), { recursive: true })
    fs.writeFileSync(arq, texto.trim() + "\n", "utf8")
  }
  const htmlCanonico = path.join(saida, "index.html")
  if (fs.existsSync(htmlCanonico)) {
    const canonico = absoluto(produtor ? "produtor/" : "").replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    const anterior = fs.readFileSync(htmlCanonico, "utf8").replace(/\s*<link\b[^>]*rel=["']canonical["'][^>]*>/gi, "")
    fs.writeFileSync(htmlCanonico, anterior.replace("</head>", `<link rel="canonical" href="${canonico}" />\n</head>`))
  }
  if (produtor) {
    gravar("index.md", `# Raíz: ficha da sua fazenda

A ficha apresenta a área da fazenda, quanto pode voltar a ser mata, a situação no funil e o que ainda precisa ser conferido. O município permite comparar a fazenda com outras da mesma região.

O selo bronze indica uma área achada no CAR; prata indica título conferido; ouro indica que o dono aceitou. Um selo não representa crédito de carbono emitido.

${REGRAS}

${PRIVACIDADE}

${LIMITE}

Este documento geral não contém uma ficha individual nem pressupõe o aceite de qualquer dono. A ficha completa exige conta de cliente, créditos pagos e conexão com a Raíz; o parâmetro \`car\` não libera os dados no site estático.

- [Consultar fichas na área de clientes](${link("#/prospeccao")})
- [Explorar os dados públicos](${link("index.md")})
- [Entender a reserva e a conexão](${link("servico.md")})
- [Fontes](${link("fontes.md")})`)
    return
  }

  // Defesa adicional: nem um catálogo antigo pode anunciar CSV por imóvel como download aberto.
  const estados = catalogo?.estados.estados.filter((e) => catalogo.arquivos[e.uf]?.includes(`resumo_${e.uf}.csv`)) ?? []
  const municipios = catalogo?.municipios.filter((m) => /^\d{7}$/.test(m.cod_ibge) && estados.some((e) => e.uf === m.uf)) ?? []
  const origem = catalogo?.estados.pasta === "amostra" ? "amostra do repositório" : "dados disponíveis neste build"
  const cobertura = estados.length
    ? `Esta publicação reúne ${numero(estados.length)} estados e ${numero(municipios.length)} municípios com resumo. ${totalPublico(municipios)} Origem: ${origem}.`
    : "Esta publicação não inclui tabelas do motor. Não é possível informar cobertura ou somar áreas neste build."
  const atualizado = catalogo?.estados.gerado_em ? `\nData do manifesto dos dados: ${md(catalogo.estados.gerado_em)}.\n` : ""
  const linksEstados = estados.map((e) => `- [${md(e.nome)} (${e.uf})](${link(`dados/estados/${e.uf}.md`)}): ${numero(e.municipios)} de ${numero(e.municipios_ibge)} municípios processados; ${e.completo ? "cobertura completa" : "cobertura parcial"}.`).join("\n")
  gravar("index.md", `# Raíz: onde dá para restaurar

${cobertura}
${atualizado}
O mapa mostra agregados e a situação básica de cada imóvel para estudar áreas de restauração. É possível buscar pelo nome ou código IBGE do município e pelo CAR. Crédito, TIR, risco, certidão com IA, terra comprometida, valor e histórico detalhado ficam na ficha completa com créditos pagos. Pequenas fazendas continuam na busca para compor grupos.

${REGRAS}

${LIMITE}

## Estados nesta publicação

${linksEstados || "Nenhuma tabela publicada neste build."}

## Próximos passos

- [Abrir o mapa](${link("")})
- [Prospectar terras na área de clientes](${link("#/prospeccao")})
- [Catálogo de dados](${link("dados/index.md")})
- [Serviço, conexão e reserva](${link("servico.md")})
- [Ficha do produtor](${link("produtor/index.md")})
- [Privacidade](${link("privacidade.md")})
- [Fontes](${link("fontes.md")})`)
  gravar("dados/index.md", `# Catálogo público da Raíz

${cobertura}
${atualizado}
${linksEstados || "Nenhuma tabela publicada neste build."}

Os resumos abaixo são calculados a partir das tabelas desta publicação. A cobertura do manifesto pode incluir municípios sem resumo; os totais não incluem esses municípios até que um resumo ou uma lista de imóveis esteja disponível.

${LIMITE}

[Regras e fontes](${link("fontes.md")})

[Voltar ao Brasil](${link("index.md")})`)

  const datasets: object[] = []
  for (const e of estados) {
    const ms = municipios.filter((m) => m.uf === e.uf).sort((a, b) => a.municipio.localeCompare(b.municipio, "pt-BR"))
    const arquivos = catalogo!.arquivos[e.uf].filter((f) => f === `resumo_${e.uf}.csv`)
    const resumo = arquivos.includes(`resumo_${e.uf}.csv`) ? `resumo_${e.uf}.csv` : null
    // O JSON-LD aponta ao resumo do estado; a página do estado lista todas as tabelas sem inflar o HTML inicial.
    const fontes = resumo ? [resumo] : []
    gravar(`dados/estados/${e.uf}.md`, `# ${md(e.nome)} (${e.uf}): dados da Raíz

Cobertura do manifesto: ${numero(e.municipios)} de ${numero(e.municipios_ibge)} municípios processados. ${e.completo ? "Estado completo na lista do IBGE." : "A cobertura ainda é parcial."}
${e.atualizado_em ? `\nAtualização do estado: ${md(e.atualizado_em)}.\n` : ""}${e.versao ? `\nVersão dos dados: ${md(e.versao)}.\n` : ""}
Há ${numero(ms.length)} resumos disponíveis. ${totalPublico(ms)}

## Municípios

| Município | Código IBGE | Imóveis | Aptos | Área de carbono apta (ha) |
|---|---|---:|---:|---:|
${ms.map((m) => `| [${md(m.municipio)}](${link(`dados/municipios/${m.cod_ibge}.md`)}) | ${m.cod_ibge} | ${indicador(m, "imoveis")} | ${indicador(m, "aptas_carbono")} | ${indicador(m, "ha_carbono")} |`).join("\n")}

## Tabelas disponíveis

${arquivos.map((f) => `- [${f}](${link(`amostra/${f}.gz`)}): CSV comprimido com gzip, sem colunas pessoais.`).join("\n")}

${LIMITE}

[Ver o estado no mapa](${link(`#/estado/${e.uf}`)})

[Fontes](${link("fontes.md")})

[Catálogo](${link("dados/index.md")})`)
    datasets.push({
      "@type": "Dataset", "@id": absoluto(`dados/estados/${e.uf}.md#dataset`),
      name: `Raíz: dados processados do CAR e do funil em ${e.nome}`,
      description: `${e.municipios} de ${e.municipios_ibge} municípios processados; ${e.completo ? "cobertura completa" : "cobertura parcial"}. ${LIMITE}`,
      url: absoluto(`dados/estados/${e.uf}.md`), inLanguage: "pt-BR",
      spatialCoverage: { "@type": "Place", name: `${e.nome}, Brasil` },
      creator: { "@id": absoluto("#organizacao") },
      ...(e.versao ? { version: e.versao } : {}),
      ...(e.atualizado_em && !Number.isNaN(Date.parse(e.atualizado_em)) ? { dateModified: new Date(e.atualizado_em).toISOString() } : {}),
      measurementTechnique: "Cruzamento do CAR com fontes ambientais públicas e regras do funil da Raíz.",
      variableMeasured: ["Código do município (IBGE)", "Imóveis no CAR", "Área em hectares", "Aptidão no funil"],
      usageInfo: absoluto("fontes.md"), isAccessibleForFree: true,
      distribution: fontes.map((f) => ({ "@type": "DataDownload", name: f, contentUrl: absoluto(`amostra/${f}.gz`), encodingFormat: "application/gzip" })),
    })
    for (const m of ms) {
      gravar(`dados/municipios/${m.cod_ibge}.md`, `# ${md(m.municipio)} (${e.uf}): funil da Raíz

Código IBGE: ${m.cod_ibge}. Origem do resumo: ${m.origem === "resumo" ? "tabela do estado" : "soma dos imóveis do município"}.

| Indicador | Resultado |
|---|---:|
| Imóveis analisados | ${indicador(m, "imoveis")} |
| Imóveis sem problema no funil | ${indicador(m, "sem_problema")} |
| Imóveis aptos para carbono | ${indicador(m, "aptas_carbono")} |
| Área de carbono nas fazendas aptas (ha) | ${indicador(m, "ha_carbono")} |
${indicadorOpcional(m, "tco2_ano_aptas", "Potencial estimado de carbono nas aptas (tCO₂/ano)")}| Aptos com indicação de matrícula | ${indicador(m, "aptas_com_matricula")} |
| Área de carbono das aptas com matrícula (ha) | ${indicador(m, "ha_carbono_matricula")} |
${indicadorOpcional(m, "frente_assentamento_agrupado", "Imóveis na frente de assentamentos para agrupar")}
Indicadores opcionais sem valor na tabela de origem não são exibidos. Ausência de informação não significa zero.

${protegido(m) ? "Os números deste grupo foram suprimidos no site aberto. As fazendas continuam disponíveis na busca da área de clientes, sem exclusão pelo tamanho." : ""}

${REGRAS}

${LIMITE}

[Abrir o município no mapa](${link(`#/municipio/${m.cod_ibge}`)})

[Tabelas e atualização do estado](${link(`dados/estados/${e.uf}.md`)})

[Fontes](${link("fontes.md")})`)
    }
  }
  gravar("servico.md", `# Serviço da Raíz: conexão e reserva

A Raíz ajuda a identificar e agrupar fazendas para restauração a partir de uma meta, uma região e restrições do cliente. As opções de lote comparam custo, risco e proximidade. Pequenas fazendas podem entrar em grupos.

O interesse do dono precisa ser registrado: sem contato, contatado, interessado, aceite de fase 1 e contrato firme são situações diferentes. A Raíz conduz o contato; o cliente não recebe dados pessoais dos donos.

## Consulta de fichas

O agregado e a situação básica por imóvel são abertos. A ficha completa por CAR exige conta de cliente e créditos pagos. O valor dos planos vem da configuração comercial do serviço autenticado. Reabrir uma ficha desbloqueada não cobra novamente. "Pedir contato" registra um pedido na Raíz para tratamento posterior.

## Conexão por hectare

A conexão é cobrada sobre os hectares do grupo que assinou o contrato. O valor depende da proposta. Os números usados pelo simulador são premissas, não uma tabela comercial confirmada. Consulte a proposta antes de contratar.

## Reserva do grupo

Quando o grupo está pronto, a reserva dá exclusividade por prazo definido na proposta. O valor pago é abatido da conexão quando o contrato fecha. Sem contrato ao fim do prazo, as fazendas voltam à base. Uma fazenda não pode participar de duas reservas simultâneas.

Sem conexão com a Raíz, o site mostra agregados e a camada básica publicada. Não efetiva contato, reserva ou cobrança real. Essas operações dependem do serviço autenticado e da proposta aceita.

[Explorar o mapa](${link("")})

[Entender o fluxo completo](${REPO}/blob/main/docs/cena-alvo.md)

[Privacidade](${link("privacidade.md")})`)
  gravar("privacidade.md", `# Privacidade na Raíz

${PRIVACIDADE}

Os documentos públicos em Markdown mostram agregados de municípios e estados. Eles não listam nomes, contatos, coordenadas de fazendas, Plus Codes ou registros privados de aceite. Não há páginas públicas dos pedidos ou reservas de um cliente.

O CAR é um cadastro ambiental e não comprova propriedade. Permitir a leitura por robôs não concede consentimento em nome de um dono nem altera as licenças das fontes.

[Fontes e termos](${link("fontes.md")})

[Voltar ao Brasil](${link("index.md")})`)
  gravar("fontes.md", `# Fontes e interpretação dos dados da Raíz

O CAR vem do SICAR/SFB; os embargos, do Ibama; PRODES, terras indígenas, unidades de conservação e hidrografia usam fontes públicas como INPE/TerraBrasilis, FUNAI e MMA/CNUC; a indicação de matrícula usa SIGEF/INCRA. O IBGE fornece códigos e limites de referência. Uso da terra e fogo incluem MapBiomas. O mapa base usa OpenStreetMap, distribuído por Protomaps.

As versões e a disponibilidade variam por estado e tabela. Consulte o catálogo e a atualização de cada estado, sem assumir que um arquivo ausente significa valor zero. O momento do build não é a data de observação de todas as fontes.

Os limites territoriais são simplificados para visualização e não definem propriedade nem demarcação legal. Onde a base TerraBrasilis ainda não contém um município publicado, todos os municípios de sua UF são substituídos juntos pela mesma edição da Malha Municipal Digital do IBGE, sob CC BY 4.0. A generalização altera os vetores originais. As demais UFs conservam sua fonte anterior; a edição abaixo não se aplica ao Brasil inteiro.
${Object.entries(malhasPublicas(opcoes.malhas)).sort(([a], [b]) => a.localeCompare(b)).map(([uf, m]) => `\n- ${uf}: [IBGE, Malha Municipal Digital ${m.ano}](${urlMalhaIbge(uf, m.ano)}), simplificada. SHA-256 do ZIP de origem: ${m.sha256}.`).join("") || "\nNenhuma substituição por UF registrada nesta publicação."}

[Condições técnicas e legais da edição 2025, p. 6–9](https://www.ibge.gov.br/biblioteca/visualizacao/livros/liv102268.pdf).

${REGRAS}

${LIMITE}

Cada fonte mantém seus termos e sua licença. A permissão de leitura por robôs não concede uma licença única sobre todos os dados.

- [Fontes e licenças detalhadas](${REPO}/blob/main/NOTICE.md)
- [Contrato das colunas](${REPO}/blob/main/docs/colunas.md)
- [Regras do funil](${REPO}/blob/main/front/compartilhado/dados/funil.ts)
- [Catálogo desta publicação](${link("dados/index.md")})`)

  const service = {
    "@type": "Service", "@id": absoluto("#servico"), name: "Conexão de grupos de fazendas para restauração",
    description: "Identificação e agrupamento de áreas, busca do interesse dos donos e conexão por hectare contratado. O site aberto mostra agregados e situação básica; a ficha exige conta e créditos pagos. A contratação depende do serviço autenticado e de proposta.",
    provider: { "@id": absoluto("#organizacao") }, areaServed: { "@type": "Country", name: "Brasil" },
    serviceType: "Conexão para restauração", url: absoluto("servico.md"), termsOfService: absoluto("servico.md"),
    offers: [
      { "@type": "Offer", "@id": absoluto("#oferta-conexao"), name: "Conexão por hectare contratado", description: "Valor definido em proposta, calculado sobre os hectares do grupo que assinou. Não há preço comercial fixado nesta página.", url: absoluto("servico.md"), itemOffered: { "@id": absoluto("#servico") } },
      { "@type": "Offer", "@id": absoluto("#oferta-reserva"), name: "Reserva do grupo", description: "Exclusividade por prazo e valor definidos na proposta; reserva abatida da conexão quando o contrato fecha. Depende de grupo pronto e serviço autenticado.", url: absoluto("servico.md"), itemOffered: { "@id": absoluto("#servico") } },
    ],
  }
  const schema = { "@context": "https://schema.org", "@graph": [{ "@type": "Organization", "@id": absoluto("#organizacao"), name: "Raíz", url: absoluto("") }, service, ...datasets] }
  const serializado = JSON.stringify(schema).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026")
  const html = path.join(saida, "index.html")
  if (fs.existsSync(html)) {
    const anterior = fs.readFileSync(html, "utf8").replace(/\s*<script id="raiz-dados-estruturados" type="application\/ld\+json">[\s\S]*?<\/script>/g, "")
    fs.writeFileSync(html, anterior.replace("</head>", `<script id="raiz-dados-estruturados" type="application/ld+json">${serializado}</script>\n</head>`))
  }
}
