/** Correção local do MapLibre 6.15.0 (BSD-3-Clause; origem e licença em NOTICE.md).
 *
 * O renderizador cria um Sky transparente mesmo sem céu no estilo e compila seu programa WebGL.
 * O fragment shader mistura somente sky-color e horizon-color: se ambos têm alfa zero, não há
 * pixel visível a desenhar. Pular só esse draw preserva céu visível, neblina, atmosfera e o mapa.
 * A transformação vale para todo build/dev; não consulta Lighthouse, navegador ou ambiente de CI.
 */
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

const VERSAO = '6.15.0'
const SHA256 = '41198b23679a7d8892183408bbef2eabdc74745beb90261f6be0f660b7aeb2fd'
const ANTES = 'function BN(e,t){let n=t.context,r=n.gl,{sky:i,pixelRatio:a}=t.data,o=mM(i,t.transform,a)'
const DEPOIS = 'function BN(e,t){let n=t.context,r=n.gl,{sky:i,pixelRatio:a}=t.data;'
  + 'if(i["sky-color"].a===0&&i["horizon-color"].a===0)return;let o=mM(i,t.transform,a)'

/** Recusa atualizações do fornecedor até conferir novamente o código, o hash e o comportamento. */
export function corrigirCeuTransparente(codigo: string, versao: string): string {
  if (versao !== VERSAO || createHash('sha256').update(codigo).digest('hex') !== SHA256 || codigo.split(ANTES).length !== 2)
    throw new Error('MapLibre diferente de 6.15.0 conferido: revise a correção do céu transparente antes de atualizar.')
  return codigo.replace(ANTES, DEPOIS)
}

export function maplibreCeuTransparente() {
  let licenca: string | undefined
  return {
    name: 'raiz-maplibre-ceu-transparente',
    enforce: 'pre' as const,
    // No desenvolvimento, a biblioteca também passa por este carregador em vez de escapar pelo prebundle.
    config: () => ({ optimizeDeps: { exclude: ['maplibre-gl'] } }),
    load(id: string) {
      const arquivo = id.split('?')[0]
      if (!arquivo.replaceAll('\\', '/').endsWith('/maplibre-gl/dist/maplibre-gl.mjs')) return null
      const pacote = JSON.parse(readFileSync(resolve(dirname(arquivo), '../package.json'), 'utf8'))
      // Antes da normalização do Vite: os bytes conferidos são idênticos no dev e no build.
      const code = corrigirCeuTransparente(readFileSync(arquivo, 'utf8'), pacote.version)
      licenca = readFileSync(resolve(dirname(arquivo), '../LICENSE.txt'), 'utf8')
      return { code, map: null }
    },
    generateBundle(this: { emitFile(arquivo: { type: 'asset'; fileName: string; source: string }): unknown }) {
      if (licenca) this.emitFile({ type: 'asset', fileName: 'licencas/maplibre-gl.txt', source: licenca })
    },
  }
}
