/**
 * Leitor de CSV (RFC 4180: aspas, vírgula e quebra de linha dentro de aspas, CRLF). Devolve uma linha por registro,
 * como objeto { coluna: valor }, sempre pelo NOME da coluna: o motor pode acrescentar colunas (docs/colunas.md) e
 * quem lê não pode depender da posição.
 */

export type Linha = Record<string, string>

export function lerCsv(texto: string, opcoes: { colunas?: string[] } = {}): { colunas: string[]; linhas: Linha[] } {
  const t = texto.charCodeAt(0) === 0xfeff ? texto.slice(1) : texto
  const registros: string[][] = []
  // arquivo só com \r (Mac antigo): tudo pelo caminho com aspas, que entende qualquer quebra de linha
  const soCr = t.indexOf("\n") < 0 && t.indexOf("\r") >= 0
  let aspasEm = soCr ? 0 : t.indexOf('"')
  let i = 0
  while (i < t.length) {
    if (aspasEm >= 0 && aspasEm < i) aspasEm = t.indexOf('"', i)
    let fim = t.indexOf("\n", i)
    if (fim < 0) fim = t.length
    // caminho rápido: linha sem aspas é só separar nas vírgulas (quase todas as linhas do motor)
    if (!soCr && (aspasEm < 0 || aspasEm > fim)) {
      const linha = t.charCodeAt(fim - 1) === 13 ? t.slice(i, fim - 1) : t.slice(i, fim)
      if (linha !== "") registros.push(linha.split(","))
      i = fim + 1
      continue
    }
    i = registroComAspas(t, i, registros)
  }
  const [cabecalho = [], ...resto] = registros
  const colunas = cabecalho.map((c) => c.trim())
  // só as colunas pedidas viram campo do objeto (ler 345 mil imóveis do Pará só para o mapa fica 5 vezes mais rápido)
  const usar = opcoes.colunas ? colunas.map((c, k) => [c, k] as const).filter(([c]) => opcoes.colunas!.includes(c)) : colunas.map((c, k) => [c, k] as const)
  const linhas = resto.map((r) => {
    const l: Linha = {}
    for (const [c, k] of usar) l[c] = r[k] ?? ""
    return l
  })
  return { colunas, linhas }
}

/** um registro com aspas (vírgula, aspas ou quebra de linha dentro do campo), a partir de i; devolve onde o próximo começa */
function registroComAspas(t: string, i: number, registros: string[][]): number {
  let campo = ""
  const registro: string[] = []
  let aspas = false
  for (; i < t.length; i++) {
    const c = t[i]
    if (aspas) {
      if (c === '"') {
        if (t[i + 1] === '"') {
          campo += '"'
          i++
        } else aspas = false
      } else campo += c
    } else if (c === '"') aspas = true
    else if (c === ",") {
      registro.push(campo)
      campo = ""
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && t[i + 1] === "\n") i++
      registro.push(campo)
      if (registro.length > 1 || registro[0] !== "") registros.push(registro)
      return i + 1
    } else campo += c
  }
  registro.push(campo)
  registros.push(registro)
  return i
}

/** Escreve CSV com as colunas pedidas (aspas só quando precisa). */
export function escreverCsv(colunas: string[], linhas: Record<string, unknown>[]): string {
  const cel = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v)
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
  }
  return [colunas.join(","), ...linhas.map((l) => colunas.map((c) => cel(l[c])).join(","))].join("\n") + "\n"
}
