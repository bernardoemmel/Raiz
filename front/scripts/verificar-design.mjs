#!/usr/bin/env node
/**
 * Verificador de design da Raíz (guias v1, item 1.4, e v2, item 8). Roda no build e nos testes e
 * falha se achar:
 *   - box-shadow diferente de none;
 *   - borda esquerda colorida;
 *   - degradê de enfeite (linear, radial ou conic; repeating-linear-gradient de textura pode);
 *   - text-transform: uppercase fora da classe .rot no analista;
 *   - cor fora das paletas (base.css, cores.ts e :root de globo/src/raiz.css);
 *   - a fonte Inter, além de Familjen/Atkinson no analista;
 *   - emoji, travessão, seta ou ponto médio fora de um rótulo mono .rot.
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
const PONTO_MEDIO = /·/
const FONTE_V1 = /Familjen(?: Grotesk|-grotesk)|Atkinson(?: Hyperlegible(?: Next)?|-hyperlegible(?:-next)?)/i
const ANALISTA = (arquivo) => arquivo.startsWith("globo/")

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
    return { texto: s, linha: linhaDe(fonte, ini), inicio: ini, fim: i }
  }
  while (i < n) {
    const c = fonte[i]
    const d = fonte[i + 1]
    if (c === "/" && d === "/") {
      const ini = i
      while (i < n && fonte[i] !== "\n") i++
      codigo += " ".repeat(i - ini)
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
      codigo += fonte.slice(r.inicio, r.fim).replace(/[^\n]/g, " ")
      ultimoSignificativo = c
      continue
    }
    // </a> e /> fecham JSX, não expressão regular.
    if (c === "/" && d !== ">" && /[(,=:[!&|?{};+\-*%>~^]|^$|return$/.test(ultimoSignificativo)) {
      // expressão regular: vai até a barra que fecha (fora de [...])
      const ini = i
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
      codigo += fonte.slice(ini, i).replace(/[^\n]/g, " ")
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

function regrasDeTexto(texto, linha, arquivo, problemas, rotuloMono = false) {
  if (EMOJI.test(texto)) problemas.push({ arquivo, linha, regra: "emoji em texto da interface", trecho: texto })
  if (TRAVESSAO.test(texto)) problemas.push({ arquivo, linha, regra: "travessão em texto da interface", trecho: texto })
  if (SETA.test(texto)) problemas.push({ arquivo, linha, regra: "seta em texto da interface", trecho: texto })
  if (!rotuloMono && PONTO_MEDIO.test(texto)) problemas.push({ arquivo, linha, regra: '"A · B" com ponto médio', trecho: texto })
  if (/\bInter\b/.test(texto) && /font|fonte/i.test(texto))
    problemas.push({ arquivo, linha, regra: "fonte Inter", trecho: texto })
}

/** Blocos e seletores por posição: a exceção de .rot nunca vale para a linha ou o arquivo inteiro. */
function blocosCss(fonte) {
  const blocos = []
  const pilha = []
  let inicio = 0
  let aspa = ""
  for (let i = 0; i < fonte.length; i++) {
    const c = fonte[i]
    if (aspa) {
      if (c === "\\") i++
      else if (c === aspa) aspa = ""
      continue
    }
    if (c === '"' || c === "'") { aspa = c; continue }
    if (c === "{") {
      const bloco = { seletor: fonte.slice(inicio, i).trim(), inicio: i + 1, fim: fonte.length }
      blocos.push(bloco)
      pilha.push(bloco)
      inicio = i + 1
    } else if (c === "}") {
      const bloco = pilha.pop()
      if (bloco) bloco.fim = i
      inicio = i + 1
    } else if (c === ";") inicio = i + 1
  }
  return blocos
}

function blocoEm(blocos, pos) {
  return blocos.findLast((bloco) => bloco.inicio <= pos && pos < bloco.fim)
}

function seletorRotulo(seletor = "") {
  // A classe deve estar no elemento selecionado, não em um ancestral/irmão ou dentro de :not/:is.
  const semFuncoes = seletor.replace(/:[\w-]+\([^()]*\)/g, ":funcao").replace(/\[[^\]]*\]/g, "")
  return semFuncoes.split(",").every((parte) => /\.rot(?![\w-])/.test(parte.trim().split(/[\s>+~]+/).at(-1) ?? ""))
}

/** Intervalos de elementos com classe literal .rot ou do componente que sempre renderiza .rot. */
function rotulosJsx(fonte, codigo = fonte) {
  const intervalos = []
  const pilha = []
  let i = 0
  while (i < fonte.length) {
    if (codigo[i] !== "<" || !/[A-Za-z/]/.test(fonte[i + 1] ?? "")) { i++; continue }
    const inicio = i
    let aspa = ""
    let chaves = 0
    i++
    while (i < fonte.length) {
      const c = fonte[i]
      if (aspa) {
        if (c === "\\") i++
        else if (c === aspa) aspa = ""
      } else if (c === '"' || c === "'" || c === "`") aspa = c
      else if (c === "{") chaves++
      else if (c === "}") chaves--
      else if (c === ">" && chaves === 0) break
      i++
    }
    i++
    const tag = fonte.slice(inicio, i)
    const nome = /^<\/?([A-Za-z][\w.]*)/.exec(tag)?.[1]
    if (!nome) continue
    if (tag.startsWith("</")) {
      const indice = pilha.findLastIndex((item) => item.nome === nome)
      if (indice >= 0) {
        for (const item of pilha.splice(indice)) if (item.rot) intervalos.push([item.inicio, i])
      }
    } else {
      const classe = /\bclass(?:Name)?\s*=\s*(?:"([^"]*)"|'([^']*)'|\{\s*"([^"]*)"\s*\}|\{\s*'([^']*)'\s*\})/.exec(tag)
      const rot = nome === "RotuloMono" || Boolean(classe && classe.slice(1).some((valor) => valor?.split(/\s+/).includes("rot")))
      if (/\/\s*>$/.test(tag)) {
        if (rot) intervalos.push([inicio, i])
      } else pilha.push({ nome, rot, inicio })
    }
  }
  return intervalos
}

const dentroDeRotulo = (intervalos, pos) => intervalos.some(([inicio, fim]) => inicio <= pos && pos < fim)

function verificarCss(arquivo, fonte, problemas) {
  const s = semComentariosCss(fonte)
  const donoDaCor = DONOS_DA_COR.some((d) => arquivo.endsWith(d))
  const blocos = blocosCss(s)
  let pos = 0
  s.split("\n").forEach((l, k) => {
    const linha = k + 1
    const p = (regra) => problemas.push({ arquivo, linha, regra, trecho: l.trim() })
    if (/box-shadow\s*:/.test(l) && !/box-shadow\s*:\s*none\b/.test(l)) p("box-shadow diferente de none")
    if (/border-left(-color)?\s*:/.test(l) && !/border-left\s*:\s*(0|none)\b/.test(l)) p("borda esquerda colorida")
    if (/border-inline-start(-color)?\s*:/.test(l) && !/:\s*(0|none)\b/.test(l)) p("borda esquerda colorida")
    if (/(?<!repeating-)(linear|radial|conic)-gradient\(/.test(l)) p("degradê de enfeite")
    for (const m of l.matchAll(/text-transform\s*:\s*uppercase/g))
      if (!ANALISTA(arquivo) || !seletorRotulo(blocoEm(blocos, pos + m.index)?.seletor)) p("text-transform: uppercase")
    if (!donoDaCor) {
      const cores = [...l.matchAll(new RegExp(COR_ESCRITA.source, "g"))]
      const nome = /:/.test(l) && CORES_POR_NOME.exec(l.split(":").slice(1).join(":"))
      if (nome) cores.push({ index: l.indexOf(nome[1]) })
      if (cores.some((m) => arquivo !== "globo/src/raiz.css" || blocoEm(blocos, pos + m.index)?.seletor !== ":root"))
        p("cor fora das variáveis")
    }
    if (/font-family[^;]*\bInter\b/.test(l) || /fontsource[^"']*inter/i.test(l)) p("fonte Inter")
    if (ANALISTA(arquivo) && FONTE_V1.test(l)) p("fonte v1 no analista")
    for (const conteudo of l.matchAll(/content\s*:\s*["']([^"']*)["']/g))
      regrasDeTexto(conteudo[1], linha, arquivo, problemas, ANALISTA(arquivo) && seletorRotulo(blocoEm(blocos, pos + conteudo.index)?.seletor))
    pos += l.length + 1
  })
}

function verificarTs(arquivo, fonte, problemas) {
  const { codigo, textos } = separarTs(fonte)
  const rotulos = ANALISTA(arquivo) ? rotulosJsx(fonte, codigo) : []
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
    if (ANALISTA(arquivo) && FONTE_V1.test(t.texto))
      problemas.push({ arquivo, linha: t.linha, regra: "fonte v1 no analista", trecho: t.texto })
    regrasDeTexto(t.texto, t.linha, arquivo, problemas, dentroDeRotulo(rotulos, t.inicio))
  }
  // texto solto no JSX (fora das strings): o que sobrou no código depois de tirar comentários e strings
  let pos = 0
  codigo.split("\n").forEach((l, k) => {
    for (const [rx, regra] of [
      [EMOJI, "emoji em texto da interface"],
      [TRAVESSAO, "travessão em texto da interface"],
      [SETA, "seta em texto da interface"],
    ])
      if (rx.test(l)) problemas.push({ arquivo, linha: k + 1, regra, trecho: l.trim() })
    for (const m of l.matchAll(/·/g))
      if (!dentroDeRotulo(rotulos, pos + m.index)) problemas.push({ arquivo, linha: k + 1, regra: '"A · B" com ponto médio', trecho: l.trim() })
    pos += l.length + 1
    if (/boxShadow\s*:/.test(l)) problemas.push({ arquivo, linha: k + 1, regra: "box-shadow diferente de none", trecho: l.trim() })
    if (/textTransform\s*:/.test(l)) problemas.push({ arquivo, linha: k + 1, regra: "text-transform: uppercase", trecho: l.trim() })
  })
}

function verificarHtml(arquivo, fonte, problemas) {
  const s = fonte.replace(/<!--[\s\S]*?-->/g, "")
  s.split("\n").forEach((l, k) => {
    const linha = k + 1
    // A barra do navegador segue o chão V2 no analista e a mata V1 no produtor.
    const corTema = ANALISTA(arquivo) ? "#0D1311" : "#1D6B44"
    if (COR_ESCRITA.test(l) && !new RegExp(`name="theme-color"\\s+content="${corTema}"`, "i").test(l))
      problemas.push({ arquivo, linha, regra: "cor fora das variáveis", trecho: l.trim() })
    if (ANALISTA(arquivo) && FONTE_V1.test(l)) problemas.push({ arquivo, linha, regra: "fonte v1 no analista", trecho: l.trim() })
    const texto = l.replace(/<[^>]*>/g, " ")
    regrasDeTexto(texto, linha, arquivo, problemas)
    for (const m of l.matchAll(/(?:content|alt|title|aria-label)="([^"]*)"/g)) regrasDeTexto(m[1], linha, arquivo, problemas)
  })
}

function verificarPacote(arquivo, fonte, problemas) {
  if (ANALISTA(arquivo) && FONTE_V1.test(fonte))
    problemas.push({ arquivo, linha: 1, regra: "fonte v1 no analista", trecho: "dependência de fonte v1 no package.json" })
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
    console.error(`\nVerificador de design: ${problemas.length} problema(s). Ver docs/design/guia-front-v2.md, item 8, e guia-front-v1.md, item 1.`)
    process.exit(1)
  }
  console.log("Verificador de design: nenhum problema.")
}
