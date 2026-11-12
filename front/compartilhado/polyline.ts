/**
 * Perímetro em polyline (algoritmo de polilinha codificada, precisão de 6 casas, ~0,1 m), como pede o passo 3 do
 * E9: o contorno da fazenda viaja como texto curto dentro da ficha e vira desenho sem baixar o mapa.
 * Ordem dos pares: [longitude, latitude], como no GeoJSON.
 */

export function codificar(pontos: [number, number][], casas = 6): string {
  const fator = 10 ** casas
  let saida = ""
  let lat0 = 0
  let lon0 = 0
  const parte = (v: number) => {
    let n = v < 0 ? ~(v << 1) : v << 1
    let s = ""
    while (n >= 0x20) {
      s += String.fromCharCode((0x20 | (n & 0x1f)) + 63)
      n >>>= 5
    }
    return s + String.fromCharCode(n + 63)
  }
  for (const [lon, lat] of pontos) {
    const la = Math.round(lat * fator)
    const lo = Math.round(lon * fator)
    saida += parte(la - lat0) + parte(lo - lon0)
    lat0 = la
    lon0 = lo
  }
  return saida
}

export function decodificar(texto: string, casas = 6): [number, number][] {
  const fator = 10 ** casas
  const pontos: [number, number][] = []
  let i = 0
  let lat = 0
  let lon = 0
  const ler = () => {
    let resultado = 0
    let desloc = 0
    let b: number
    do {
      b = texto.charCodeAt(i++) - 63
      resultado |= (b & 0x1f) << desloc
      desloc += 5
    } while (b >= 0x20)
    return resultado & 1 ? ~(resultado >> 1) : resultado >> 1
  }
  while (i < texto.length) {
    lat += ler()
    lon += ler()
    pontos.push([lon / fator, lat / fator])
  }
  return pontos
}
