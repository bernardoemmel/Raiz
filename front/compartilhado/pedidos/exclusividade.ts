/**
 * Exclusividade (cena-alvo, item 7): fazenda reservada por outro cliente some de toda busca, mapa, lista e ficha até o
 * prazo vencer ou o contrato fechar. Com o back-end, quem esconde é o servidor; na amostra, esta camada esconde as
 * reservadas da resposta de exemplo. A ficha do produtor não passa por aqui: o dono sempre vê a própria fazenda.
 */

import type { FonteDeDados } from "../dados/fonte"
import { reservadaPorOutro } from "./exemplo"

export function semReservadasPorOutros(f: FonteDeDados, reservada: (cod_imovel: string) => boolean = reservadaPorOutro): FonteDeDados {
  return {
    ...f,
    async imoveis(cod) {
      const lista = await f.imoveis(cod)
      return lista ? lista.filter((i) => !reservada(i.cod_imovel)) : null
    },
    imovel: async (cod_imovel) => (reservada(cod_imovel) ? null : f.imovel(cod_imovel)),
    ficha: async (cod_imovel) => (reservada(cod_imovel) ? null : f.ficha(cod_imovel)),
    certidoes: async (cod_imovel) => (reservada(cod_imovel) ? [] : f.certidoes(cod_imovel)),
    async buscar(q, sinal) {
      const r = await f.buscar(q, sinal)
      const imoveis = r.imoveis.filter((i) => !reservada(i.cod_imovel))
      if (r.imoveis.length && !imoveis.length && !r.municipios.length)
        return { ...r, imoveis, situacao: "nao_encontrado", mensagem: "Nenhum imóvel disponível com este código." }
      return { ...r, imoveis }
    },
    geo: {
      ...f.geo,
      async camada(cod, camada) {
        const g = await f.geo.camada(cod, camada)
        if (!g || camada !== "imoveis") return g
        return { ...g, features: g.features.filter((x) => !reservada(String(x.properties.cod_imovel))) }
      },
    },
  }
}
