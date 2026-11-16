import type { Geo } from "../../../compartilhado/dados"
import type { IdOpcao, NivelInteresse, PapelNoLote } from "../../../compartilhado/pedidos/tipos"

export interface FazendaNoMapa {
  cod_imovel: string
  cod_ibge: string
  lon: number
  lat: number
  papel: PapelNoLote
  interesse: NivelInteresse
  trocou?: string | null
  opcao?: IdOpcao
  geometria?: Geo["features"][number]["geometry"] | null
}

/** O mesmo CAR pode participar de mais de uma alternativa, sem perder a associação com cada lote. */
export function geometriasDosLotes(geos: (Geo | null)[], fazendas: FazendaNoMapa[]): Geo {
  const porCar = new Map<string, FazendaNoMapa[]>()
  for (const fazenda of fazendas) {
    const lista = porCar.get(fazenda.cod_imovel) ?? []
    lista.push(fazenda)
    porCar.set(fazenda.cod_imovel, lista)
  }
  const vistos = new Set<string>()
  return {
    type: "FeatureCollection",
    features: geos.flatMap((geo) => geo?.features ?? []).flatMap((feature) => {
      const car = String(feature.properties.cod_imovel)
      if (vistos.has(car)) return []
      vistos.add(car)
      return (porCar.get(car) ?? []).map((fazenda) => ({
        ...feature,
        properties: propriedadesDaFazenda(fazenda),
      }))
    }),
  }
}

export function propriedadesDaFazenda(fazenda: FazendaNoMapa) {
  return {
    id: `${fazenda.opcao ?? "lote"}:${fazenda.cod_imovel}`,
    cod: fazenda.cod_imovel,
    opcao: fazenda.opcao ?? "barata",
    papel: fazenda.papel === "lote" ? 1 : 0,
    interesse: fazenda.interesse,
    recusou: fazenda.interesse === "recusou" ? 1 : 0,
    trocou: !!fazenda.trocou,
  }
}

export function coordenadaValida(fazenda: FazendaNoMapa) {
  return Number.isFinite(fazenda.lon) && Number.isFinite(fazenda.lat) && Math.abs(fazenda.lon) <= 180 && Math.abs(fazenda.lat) <= 90
}

/** Inclui os extremos do polígono: enquadrar só os centros corta fazendas grandes na borda da tela. */
export function limitesDoLote(desenho: Geo, fazendas: FazendaNoMapa[]): [number, number, number, number] | null {
  let oeste = Infinity, sul = Infinity, leste = -Infinity, norte = -Infinity
  const incluir = (lon: number, lat: number) => {
    if (!Number.isFinite(lon) || !Number.isFinite(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 90) return
    oeste = Math.min(oeste, lon)
    leste = Math.max(leste, lon)
    sul = Math.min(sul, lat)
    norte = Math.max(norte, lat)
  }
  const percorrer = (coordenadas: unknown): void => {
    if (!Array.isArray(coordenadas)) return
    if (typeof coordenadas[0] === "number" && typeof coordenadas[1] === "number") incluir(coordenadas[0], coordenadas[1])
    else coordenadas.forEach(percorrer)
  }
  desenho.features.forEach((feature) => percorrer(feature.geometry.coordinates))
  fazendas.filter(coordenadaValida).forEach((fazenda) => incluir(fazenda.lon, fazenda.lat))
  return Number.isFinite(oeste) ? [oeste, sul, leste, norte] : null
}
