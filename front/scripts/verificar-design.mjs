#!/usr/bin/env node
/**
 * Verificador de design do front da Raíz (docs/design/guia-front-v1.md, item 1.4). Roda no build e nos testes e
 * falha se achar:
 *   - box-shadow diferente de none;
 *   - borda esquerda colorida;
 *   - degradê de enfeite (linear, radial ou conic; repeating-linear-gradient de textura pode);
 *   - text-transform: uppercase;
 *   - cor fora das variáveis (só compartilhado/base.css e compartilhado/cores.ts podem escrever cor);
 *   - a fonte Inter;
 *   - emoji, travessão, seta ou "A · B" com ponto médio em texto da interface.
 * Comentários não contam. O componente do globo (globo/src/components/) foi copiado sem alterar e fica de fora.
 *
 * Uso: node front/scripts/verificar-design.mjs   (sai com código 1 e lista os problemas)
 */

import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const FRONT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")

const PASTAS = ["globo/src", "produtor/src", "compartilhado"]
const ARQUIVOS_SOLTOS = ["globo/index.html", "produtor/index.html", "globo/package.json", "produtor/package.json"]
const FORA = [/globo\/src\/components\//, /compartilhado\/testes\//, /node_modules/, /\/dist\//]
/** os únicos lugares com cor escrita */
const DONOS_DA_COR = ["compartilhado/base.css", "compartilhado/cores.ts"]

const COR_ESCRITA = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/
const CORES_POR_NOME =
  /(?:^|[\s:(,])(white|black|red|green|blue|gray|grey|orange|yellow|purple|pink|magenta|fuchsia|violet|brown|navy|teal|olive|maroon|silver|lime|aqua|cyan|indigo|beige|crimson|gold|khaki|salmon|tomato|coral)(?=[\s;),!]|$)/i
// © ® ™ são crédito e marca, não emoji (o guia pede "© OpenStreetMap" visível)
const EMOJI = /(?![\u00A9\u00AE\u2122])\p{Extended_Pictographic}/u
const TRAVESSAO = /[—–]/
const SETA = /[←-⇿⟰-⟿⤀-⥿⬀-⬏➜-➿]/
const PONTO_MEDIO = /\S\s·\s\S/

function listar(dir) {
  const saida = []
  if (!fs.existsSync(dir)) return saida
  for (const nome of fs.readdirSync(dir)) {
    const p = path.join(dir, nome)
    const st = fs.statSync(p)
    if (st.isDirectory()) saida.push(...listar(p))
    else if (/\.(css|ts|tsx|mjs|html)$/.test(nome)) saida.push(p)
  }
  return saida
}

const linhaDe = (texto, pos) => texto.slice(0, pos).split("\n").length

/** Separa um arquivo TypeScript em código (sem comentários) e textos (strings e template literals). */
export function separarTs(fonte) {
  let codigo = ""
  const textos = []
  let i = 0
  let ultimoSignificativo = ""
  const n = fonte.length
  const lerString = (aspa) => {
    const ini = i
    i++
    let s = ""
    while (i < n && fonte[i] !== aspa) {
      if (fonte[i] === "\\") {
        s += fonte[i] + (fonte[i + 1] ?? "")
        i += 2
        continue
      }
      if (aspa === "`" && fonte[i] === "$" && fonte[i + 1] === "{") {
        // expressão dentro do template: pula com contagem de chaves (strings internas viram texto também)
        let prof = 1
        i += 2
        while (i < n && prof > 0) {
          if (fonte[i] === "{") prof++
          else if (fonte[i] === "}") prof--
          else if (fonte[i] === '"' || fonte[i] === "'") {
            const r = lerString(fonte[i])
            textos.push(r)
            continue
          }
          i++
        }
        s += " "
        continue
      }
      s += fonte[i]
      i++
    }
    i++
    return { texto: s, linha: linhaDe(fonte, ini) }
  }
  while (i < n) {
    const c = fonte[i]
    const d = fonte[i + 1]
    if (c === "/" && d === "/") {
      while (i < n && fonte[i] !== "\n") i++
      continue
    }
    if (c === "/" && d === "*") {
      const fim = fonte.indexOf("*/", i + 2)
      const trecho = fonte.slice(i, fim < 0 ? n : fim + 2)
      codigo += trecho.replace(/[^\n]/g, " ")
      i = fim < 0 ? n : fim + 2
      continue
    }
    if (c === '"' || c === "'" || c === "`") {
      const r = lerString(c)
      textos.push(r)
      codigo += c + c
      ultimoSignificativo = c
      continue
    }
    // "/" depois de "<" é fecha-tag do JSX (</a>), não expressão regular
    if (c === "/" && /[(,=:[!&|?{};+\-*%>~^]|^$|return$/.test(ultimoSignificativo)) {
      // expressão regular: vai até a barra que fecha (fora de [...])
      let classe = false
      i++
      while (i < n) {
        if (fonte[i] === "\\") {
          i += 2
          continue
        }
        if (fonte[i] === "[") classe = true
        else if (fonte[i] === "]") classe = false
        else if (fonte[i] === "/" && !classe) break
        else if (fonte[i] === "\n") break
        i++
      }
      i++
      while (i < n && /[a-z]/.test(fonte[i])) i++
      codigo += "/r/"
      ultimoSignificativo = "/"
      continue
    }
    codigo += c
    if (!/\s/.test(c)) ultimoSignificativo = /[A-Za-z0-9_$]/.test(c) ? (/[A-Za-z]/.test(c) ? lerPalavra() : c) : c
    i++
  }
  function lerPalavra() {
    let j = i
    while (j > 0 && /[A-Za-z0-9_$]/.test(fonte[j - 1])) j--
    return fonte.slice(j, i + 1)
  }
  return { codigo, textos }
}

const semComentariosCss = (s) => s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))

function regrasDeTexto(texto, linha, arquivo, problemas) {
  if (EMOJI.test(texto)) problemas.push({ arquivo, linha, regra: "emoji em texto da interface", trecho: texto })
  if (TRAVESSAO.test(texto)) problemas.push({ arquivo, linha, regra: "travessão em texto da interface", trecho: texto })
  if (SETA.test(texto)) problemas.push({ arquivo, linha, regra: "seta em texto da interface", trecho: texto })
  if (PONTO_MEDIO.test(texto)) problemas.push({ arquivo, linha, regra: '"A · B" com ponto médio', trecho: texto })
  if (/\bInter\b/.test(texto) && /font|fonte/i.test(texto))
    problemas.push({ arquivo, linha, regra: "fonte Inter", trecho: texto })
}

function verificarCss(arquivo, fonte, problemas) {
  const s = semComentariosCss(fonte)
  const donoDaCor = DONOS_DA_COR.some((d) => arquivo.endsWith(d))
  s.split("\n").forEach((l, k) => {
    const linha = k + 1
    const p = (regra) => problemas.push({ arquivo, linha, regra, trecho: l.trim() })
    if (/box-shadow\s*:/.test(l) && !/box-shadow\s*:\s*none\b/.test(l)) p("box-shadow diferente de none")
    if (/border-left(-color)?\s*:/.test(l) && !/border-left\s*:\s*(0|none)\b/.test(l)) p("borda esquerda colorida")
    if (/border-inline-start(-color)?\s*:/.test(l) && !/:\s*(0|none)\b/.test(l)) p("borda esquerda colorida")
    if (/(?<!repeating-)(linear|radial|conic)-gradient\(/.test(l)) p("degradê de enfeite")
    if (/text-transform\s*:\s*uppercase/.test(l)) p("text-transform: uppercase")
    if (!donoDaCor && (COR_ESCRITA.test(l) || (/:/.test(l) && CORES_POR_NOME.test(l.split(":").slice(1).join(":")))))
      p("cor fora das variáveis")
    if (/font-family[^;]*\bInter\b/.test(l) || /fontsource[^"']*inter/i.test(l)) p("fonte Inter")
    const conteudo = /content\s*:\s*"([^"]*)"/.exec(l)
    if (conteudo) regrasDeTexto(conteudo[1], linha, arquivo, problemas)
  })
}

function verificarTs(arquivo, fonte, problemas) {
  const { codigo, textos } = separarTs(fonte)
  const donoDaCor = DONOS_DA_COR.some((d) => arquivo.endsWith(d))
  for (const t of textos) {
    if (!donoDaCor && COR_ESCRITA.test(t.texto))
      problemas.push({ arquivo, linha: t.linha, regra: "cor fora das variáveis", trecho: t.texto })
    if (/box-shadow\s*:\s*(?!none)/.test(t.texto))
      problemas.push({ arquivo, linha: t.linha, regra: "box-shadow diferente de none", trecho: t.texto })
    if (/^uppercase$/.test(t.texto.trim()) || /text-transform\s*:\s*uppercase/.test(t.texto))
      problemas.push({ arquivo, linha: t.linha, regra: "text-transform: uppercase", trecho: t.texto })
    if (/@fontsource(-variable)?\/inter\b/.test(t.texto))
      problemas.push({ arquivo, linha: t.linha, regra: "fonte Inter", trecho: t.texto })
    regrasDeTexto(t.texto, t.linha, arquivo, problemas)
  }
  // texto solto no JSX (fora das strings): o que sobrou no código depois de tirar comentários e strings
  codigo.split("\n").forEach((l, k) => {
    for (const [rx, regra] of [
      [EMOJI, "emoji em texto da interface"],
      [TRAVESSAO, "travessão em texto da interface"],
      [SETA, "seta em texto da interface"],
      [PONTO_MEDIO, '"A · B" com ponto médio'],
    ])
      if (rx.test(l)) problemas.push({ arquivo, linha: k + 1, regra, trecho: l.trim() })
    if (/boxShadow\s*:/.test(l)) problemas.push({ arquivo, linha: k + 1, regra: "box-shadow diferente de none", trecho: l.trim() })
    if (/textTransform\s*:/.test(l)) problemas.push({ arquivo, linha: k + 1, regra: "text-transform: uppercase", trecho: l.trim() })
  })
}

function verificarHtml(arquivo, fonte, problemas) {
  const s = fonte.replace(/<!--[\s\S]*?-->/g, "")
  s.split("\n").forEach((l, k) => {
    const linha = k + 1
    // a cor da barra do navegador precisa ser escrita; tem de ser a --mata
    if (COR_ESCRITA.test(l) && !/name="theme-color"\s+content="#1D6B44"/i.test(l))
      problemas.push({ arquivo, linha, regra: "cor fora das variáveis", trecho: l.trim() })
    const texto = l.replace(/<[^>]*>/g, " ")
    regrasDeTexto(texto, linha, arquivo, problemas)
    for (const m of l.matchAll(/(?:content|alt|title|aria-label)="([^"]*)"/g)) regrasDeTexto(m[1], linha, arquivo, problemas)
  })
}

function verificarPacote(arquivo, fonte, problemas) {
  if (/"@fontsource(-variable)?\/inter"/.test(fonte))
    problemas.push({ arquivo, linha: 1, regra: "fonte Inter", trecho: "dependência da Inter no package.json" })
}

export function verificar(raiz = FRONT) {
  const problemas = []
  const arquivos = [
    ...PASTAS.flatMap((d) => listar(path.join(raiz, d))),
    ...ARQUIVOS_SOLTOS.map((f) => path.join(raiz, f)).filter((f) => fs.existsSync(f)),
  ]
  for (const abs of arquivos) {
    const rel = path.relative(raiz, abs).split(path.sep).join("/")
    if (FORA.some((rx) => rx.test(rel))) continue
    if (rel === "scripts/verificar-design.mjs") continue
    const fonte = fs.readFileSync(abs, "utf8")
    if (rel.endsWith(".css")) verificarCss(rel, fonte, problemas)
    else if (rel.endsWith(".html")) verificarHtml(rel, fonte, problemas)
    else if (rel.endsWith("package.json")) verificarPacote(rel, fonte, problemas)
    else verificarTs(rel, fonte, problemas)
  }
  return problemas
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const problemas = verificar()
  if (problemas.length) {
    for (const p of problemas) console.error(`${p.arquivo}:${p.linha}  ${p.regra}  ${p.trecho.slice(0, 110)}`)
    console.error(`\nVerificador de design: ${problemas.length} problema(s). Ver docs/design/guia-front-v1.md, item 1.`)
    process.exit(1)
  }
  console.log("Verificador de design: nenhum problema.")
}
