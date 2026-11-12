/**
 * Privacidade no front: CPF e CNPJ sempre mascarados e nenhuma coluna pessoal chega à tela.
 *
 * As regras são as mesmas do back-end (raiz/privacidade.py): máscara ***.456.789-** e **.345.678/****-**, aceita o
 * CNPJ alfanumérico, e na dúvida a coluna sai ("é mais barato pedir uma coluna de volta do que tirar um CPF de um
 * backup"). O motor já entrega sem CPF, CNPJ ou nome; isto é a segunda tranca, para quando a fonte for a API.
 */

const soDigitos = (s: string) => s.replace(/\D/g, "")

export function cpfValido(cpf: string): boolean {
  const d = soDigitos(cpf)
  if (d.length !== 11 || d === d[0].repeat(11)) return false
  for (const n of [9, 10]) {
    let soma = 0
    for (let i = 0; i < n; i++) soma += Number(d[i]) * (n + 1 - i)
    if (((soma * 10) % 11) % 10 !== Number(d[n])) return false
  }
  return true
}

// CNPJ alfanumérico (IN RFB 2.229/2024): valor de cada caractere = código ASCII menos 48
const valorCnpj = (c: string) => c.charCodeAt(0) - 48

export function cnpjValido(cnpj: string): boolean {
  const s = cnpj.toUpperCase().replace(/[^0-9A-Z]/g, "")
  if (s.length !== 14 || !/^\d\d$/.test(s.slice(12)) || s === s[0].repeat(14)) return false
  const pesos: [number, number[]][] = [
    [12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]],
    [13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]],
  ]
  for (const [n, p] of pesos) {
    let soma = 0
    for (let i = 0; i < n; i++) soma += valorCnpj(s[i]) * p[i]
    const r = soma % 11
    if ((r < 2 ? 0 : 11 - r) !== Number(s[n])) return false
  }
  return true
}

export const mascaraCpf = (cpf: string) => {
  const d = soDigitos(cpf)
  return `***.${d.slice(3, 6)}.${d.slice(6, 9)}-**`
}

export const mascaraCnpj = (cnpj: string) => {
  const s = cnpj.toUpperCase().replace(/[^0-9A-Z]/g, "")
  return `**.${s.slice(2, 5)}.${s.slice(5, 8)}/****-**`
}

// bordas: não pega pedaço de número decimal (189.99087022873272) nem de código maior (o código do CAR tem 32
// caracteres hexadecimais, que podem conter 11 ou 14 dígitos seguidos)
const ANTES = String.raw`(?<![\w./-])`
const DEPOIS = String.raw`(?![\w]|\.\d|[/-]\w)`
const CPF_FMT = new RegExp(ANTES + String.raw`\d{3}\.\d{3}\.\d{3}-\d{2}` + DEPOIS, "g")
const CNPJ_FMT = new RegExp(ANTES + String.raw`[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}` + DEPOIS, "g")
const CPF_NU = new RegExp(ANTES + String.raw`\d{11}` + DEPOIS, "g")
const CNPJ_NU = new RegExp(ANTES + String.raw`[0-9A-Z]{12}\d{2}` + DEPOIS, "g")

/** Mascara todo CPF e CNPJ do texto: formatados sempre; sem pontuação, só se os dígitos verificadores batem. */
export function mascarar(texto: string): string {
  if (!texto) return texto
  return texto
    .replace(CNPJ_FMT, (m) => mascaraCnpj(m))
    .replace(CPF_FMT, (m) => mascaraCpf(m))
    .replace(CNPJ_NU, (m) => (cnpjValido(m) ? mascaraCnpj(m) : m))
    .replace(CPF_NU, (m) => (cpfValido(m) ? mascaraCpf(m) : m))
}

const PESSOAL = new RegExp(
  "cpf|cnpj|nome|^nom_|_nom_|e_?mail|telefone|celular|^fone|_fone|whats|endereco|endereço|logradouro|" +
    "^rg$|^rg_|_rg$|^nis|pis_pasep|titulo_eleitor|nasc|^mae|nome_mae|filiacao|^cep$|_cep$|propriet|dono|titular",
  "i",
)
// nomes de lugares e de áreas protegidas não são dado pessoal
const LUGAR = /munic|^uf$|estado|bioma|nome_uc|nome_ti|terra_ind|unidade|nome_projeto|camada/i

export function colunaPessoal(coluna: string): boolean {
  return PESSOAL.test(coluna) && !LUGAR.test(coluna)
}
