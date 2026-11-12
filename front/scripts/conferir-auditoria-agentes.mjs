import assert from "node:assert/strict"

/** Catálogo e texto para agentes apresentam agregados e o portão pago; a camada básica é validada no smoke Pages. */
export function conferirConteudoPublico(texto, identificador) {
  assert(!/\b[A-Z]{2}[-. ]?\d{7}[-. ]?(?:[A-F0-9][.]?){32}\b/i.test(texto),
    `${identificador}: um código CAR individual apareceu na publicação aberta.`)
  for (const [, destino] of texto.matchAll(/\[[^\]]*\]\(([^\s)]+)\)/g))
    conferirCaminhoPublico(new URL(destino, "https://raiz.invalid/").pathname, identificador)
}

/** Downloads completos continuam fechados; CSV básico e geometria projetada são permitidos. */
export function conferirCaminhoPublico(caminho, identificador) {
  const legivel = decodeURIComponent(caminho)
  assert(!/(?:^|\/)(?:car_[^/]*|imoveis_\d{7}\.csv[^/]*|(?:filtros|certidoes|desenvolvedor|ficha)_\d{7}[^/]*|fichas)(?:\/|$)/i.test(legivel),
    `${identificador}: download ou ficha individual anunciado no conteúdo público: ${legivel}`)
}

/** Portão do CI. WebMCP e ARD ficam no relatório, mas não são recursos exigidos do produto. */
export function conferirAuditoriaAgentes(lhr) {
  assert(!lhr.runtimeError, `Lighthouse falhou: ${JSON.stringify(lhr.runtimeError)}`)
  const categoria = lhr.categories?.["agentic-browsing"]
  assert(categoria?.auditRefs.length, "A categoria oficial agentic-browsing não rodou.")
  for (const { id } of categoria.auditRefs) {
    assert(lhr.audits?.[id], `A auditoria ${id} não entregou resultado.`)
    assert.notEqual(lhr.audits[id].scoreDisplayMode, "error", `A auditoria ${id} falhou ao executar; consulte o relatório.`)
  }
  const aplicavel = (id, modo) => {
    assert(categoria.auditRefs.some((a) => a.id === id), `${id} não foi executada nesta categoria.`)
    const auditoria = lhr.audits[id]
    assert.equal(auditoria.scoreDisplayMode, modo, `${id} precisa ser aplicável e entregar uma medição válida.`)
    return auditoria
  }
  assert.equal(aplicavel("llms-txt", "binary").score, 1, "llms.txt não passou nas recomendações do Lighthouse.")
  assert.equal(aplicavel("agent-accessibility-tree", "binary").score, 1, "A árvore de acessibilidade tem barreiras para os agentes.")
  const cls = aplicavel("cumulative-layout-shift", "numeric")
  // Faixa boa de CLS no Core Web Vitals e alvo p10 padrão do Lighthouse:
  // https://web.dev/articles/cls#what_is_a_good_cls_score
  assert(Number.isFinite(cls.numericValue) && cls.numericValue >= 0 && cls.numericValue <= 0.1,
    `CLS precisa estar na faixa boa (0 a 0,1); medido: ${cls.numericValue}.`)
  assert(Number.isFinite(cls.score) && cls.score >= 0.9, "A nota de estabilidade visual do Lighthouse precisa ser pelo menos 0,9.")
  return categoria
}
