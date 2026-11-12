/**
 * Leitor de CSV (RFC 4180: aspas, vírgula e quebra de linha dentro de aspas, CRLF). Devolve uma linha por registro,
 * como objeto { coluna: valor }, sempre pelo NOME da coluna: o motor pode acrescentar colunas (docs/colunas.md) e
 * quem lê não pode depender da posição.
 */

export type Linha = Record<string, string>

export function lerCsv(texto: string): { colunas: string[]; linhas: Linha[] } {
  const registros: string[][] = []
  let campo = ""
  let registro: string[] = []
  let aspas = false
  const t = texto.charCodeAt(0) === 0xfeff ? texto.slice(1) : texto
  for (let i = 0; i < t.length; i++) {
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
      campo = ""
      if (registro.length > 1 || registro[0] !== "") registros.push(registro)
      registro = []
    } else campo += c
  }
  if (campo !== "" || registro.length) {
    registro.push(campo)
    registros.push(registro)
  }
  const [cabecalho = [], ...resto] = registros
  const colunas = cabecalho.map((c) => c.trim())
  const linhas = resto.map((r) => {
    const l: Linha = {}
    colunas.forEach((c, i) => (l[c] = r[i] ?? ""))
    return l
  })
  return { colunas, linhas }
}

/** Escreve CSV com as colunas pedidas (aspas só quando precisa). */
export function escreverCsv(colunas: string[], linhas: Record<string, unknown>[]): string {
  const cel = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v)
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
  }
  return [colunas.join(","), ...linhas.map((l) => colunas.map((c) => cel(l[c])).join(","))].join("\n") + "\n"
}
