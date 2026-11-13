import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { corrigirCeuTransparente, maplibreCeuTransparente } from './vite-maplibre-ceu'

const original = readFileSync(new URL('../globo/node_modules/maplibre-gl/dist/maplibre-gl.mjs', import.meta.url), 'utf8')
const pacote = JSON.parse(readFileSync(new URL('../globo/node_modules/maplibre-gl/package.json', import.meta.url), 'utf8'))

describe('correção conferida do céu transparente do MapLibre', () => {
  it('recusa versão ou bytes diferentes dos que foram revisados', () => {
    expect(() => corrigirCeuTransparente(original, '6.16.0')).toThrow(/revise/)
    expect(() => corrigirCeuTransparente(`${original}\n`, pacote.version)).toThrow(/revise/)
    expect(() => corrigirCeuTransparente('outra biblioteca', pacote.version)).toThrow(/revise/)
  })

  it.each([[0, 0, false], [1, 0, true], [0, 1, true], [0.1, 0.2, true]])(
    'executa o drawSky real com alfa céu=%s/horizonte=%s: desenhar=%s', (ceu, horizonte, desenhar) => {
      const corrigido = corrigirCeuTransparente(original, pacote.version)
      // Executa a função real do pacote após o patch. Os dublês só observam GPU/uniforms sem WebGL no teste unitário.
      const inicio = corrigido.indexOf('function BN(e,t)')
      const fim = corrigido.indexOf('function VN(', inicio)
      expect(inicio).toBeGreaterThan(0)
      expect(fim).toBeGreaterThan(inicio)
      const chamadas: string[] = []
      const uniforms = () => { chamadas.push('uniforms'); return {} }
      const DepthMode = class { static ReadWrite = 1 }
      const drawSky = new Function('mM', 'CM', 'yM', 'SM', `${corrigido.slice(inicio, fim)};return BN`)(
        uniforms, DepthMode, { disabled: null }, { disabled: null },
      )
      const frame = {
        context: { gl: { LEQUAL: 1, TRIANGLES: 4 } }, transform: {},
        data: { pixelRatio: 1, sky: { 'sky-color': { a: ceu }, 'horizon-color': { a: horizonte } } },
        colorModeForRenderPass: () => null,
        useProgram: (nome: string) => { chamadas.push(nome); return { draw: () => chamadas.push('draw') } },
      }
      drawSky({}, frame)
      expect(chamadas).toEqual(desenhar ? ['uniforms', 'sky', 'draw'] : [])
    },
  )

  it('usa a mesma transformação no desenvolvimento', () => {
    const plugin = maplibreCeuTransparente()
    expect(plugin.enforce).toBe('pre')
    expect(typeof plugin.config).toBe('function')
    const config = plugin.config as () => { optimizeDeps: { exclude: string[] } }
    expect(config().optimizeDeps.exclude).toContain('maplibre-gl')
  })

  it('publica junto da biblioteca corrigida os avisos e a licença completos do fornecedor', () => {
    const plugin = maplibreCeuTransparente()
    const arquivo = fileURLToPath(new URL('../globo/node_modules/maplibre-gl/dist/maplibre-gl.mjs', import.meta.url))
    expect(plugin.load(arquivo)?.code).toContain('horizon-color"].a===0')
    const assets: { type: 'asset'; fileName: string; source: string }[] = []
    plugin.generateBundle.call({ emitFile: asset => assets.push(asset) })
    expect(assets).toHaveLength(1)
    expect(assets[0].fileName).toBe('licencas/maplibre-gl.txt')
    expect(assets[0].source).toContain('Copyright (c) 2023, MapLibre contributors')
    expect(assets[0].source).toContain('Redistribution and use in source and binary forms')
  })
})
