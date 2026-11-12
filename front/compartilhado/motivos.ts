/**
 * Por que a fazenda é (ou não é) apta, item por item, com o número que decide. As regras são as do motor
 * (docs/colunas.md e motor.resumo); o texto diz o limite usado. Serve à ficha do painel e à ficha do produtor
 * ("motivos específicos de não apto", E9 passo 11).
 */

import type { Imovel } from "./dados/tipos"
import { fmtHa } from "./formato"

export interface Motivo {
  id: string
  ok: boolean
  /** frase curta, afirmativa quando ok */
  texto: string
  /** o número e a regra */
  detalhe: string
  /** este item sozinho tira a fazenda do funil? */
  bloqueia: boolean
}

export function motivos(i: Imovel): Motivo[] {
  const lista: Motivo[] = [
    {
      id: "embargo",
      ok: i.embargo_ha <= 1,
      texto: i.embargo_ha <= 1 ? "Sem embargo do Ibama" : "Tem embargo do Ibama",
      detalhe: `${fmtHa(i.embargo_ha)} embargados (limite: 1 ha)`,
      bloqueia: true,
    },
    {
      id: "ti",
      ok: i.ti_ha <= 1,
      texto: i.ti_ha <= 1 ? "Fora de terra indígena" : "Sobrepõe terra indígena",
      detalhe: `${fmtHa(i.ti_ha)} em terra indígena (limite: 1 ha)`,
      bloqueia: true,
    },
    {
      id: "desmate2020",
      ok: (i.desm_pos2020_ha ?? 0) <= 1,
      texto: (i.desm_pos2020_ha ?? 0) <= 1 ? "Sem desmatamento depois de 2020" : "Desmatamento depois de 2020",
      detalhe: `${fmtHa(i.desm_pos2020_ha ?? 0)} no PRODES desde 2021 (limite: 1 ha)`,
      bloqueia: true,
    },
    {
      id: "alerta",
      ok: i.alerta_pos2020_ha <= 1,
      texto: i.alerta_pos2020_ha <= 1 ? "Sem alerta de desmatamento depois de 2020" : "Alerta de desmatamento depois de 2020",
      detalhe:
        i.alerta_pos2020_ha <= 1
          ? `${fmtHa(i.alerta_pos2020_ha)} em alertas do MapBiomas (limite: 1 ha)`
          : `${fmtHa(i.alerta_pos2020_ha)} em alertas do MapBiomas${i.alerta_ultimo_ano ? `, o último em ${i.alerta_ultimo_ano}` : ""}`,
      bloqueia: true,
    },
    {
      id: "desmate2016",
      ok: (i.desm_pos2016_ha ?? 0) <= 5,
      texto: (i.desm_pos2016_ha ?? 0) <= 5 ? "Pouco ou nenhum desmate nos últimos 10 anos" : "Desmate nos últimos 10 anos",
      detalhe: `${fmtHa(i.desm_pos2016_ha ?? 0)} desmatados no PRODES desde 2016 (limite para carbono: 5 ha)`,
      bloqueia: true,
    },
    {
      id: "alem",
      ok: i.carbono_ha > 0,
      texto: i.carbono_ha > 0 ? "Tem área aberta além da reserva legal onde a mata volta sozinha" : "Sem área para a mata voltar além da reserva legal",
      detalhe: `${fmtHa(i.alem_RL_ha)} abertos além da reserva legal; ${fmtHa(i.pasto_ate1km_ha ?? 0)} de pasto a até 1 km de floresta`,
      bloqueia: true,
    },
  ]
  if (i.uc_ha > 1)
    lista.push({
      id: "uc",
      ok: false,
      texto: "Sobrepõe unidade de conservação",
      detalhe: `${fmtHa(i.uc_ha)} em UC: conferir a categoria (proteção integral ou uso sustentável)`,
      bloqueia: false,
    })
  if (i.deficit_RL_ha > 1)
    lista.push({
      id: "reserva",
      ok: false,
      texto: "Falta reserva legal",
      detalhe: `${fmtHa(i.deficit_RL_ha)} de reserva legal a recompor (${i.pct_RL ?? "—"}% do imóvel); não impede o carbono na área além da reserva`,
      bloqueia: false,
    })
  if (i.app_desmatada_ha > 1)
    lista.push({
      id: "app",
      ok: false,
      texto: "Beira de rio aberta (APP)",
      detalhe: `${fmtHa(i.app_recompor_ha ?? i.app_desmatada_ha)} de APP a recompor pela regra da escadinha`,
      bloqueia: false,
    })
  if (i.eudr_ok !== null)
    lista.push({
      id: "eudr",
      ok: i.eudr_ok,
      texto: i.eudr_ok ? "Passa na regra europeia (sem desmate depois de 2020)" : "Não passa na regra europeia",
      detalhe: "Regulamento europeu contra desmatamento (EUDR): corte em 31/12/2020",
      bloqueia: false,
    })
  if (i.credito_rural_ok !== null)
    lista.push({
      id: "credito",
      ok: i.credito_rural_ok,
      texto: i.credito_rural_ok ? "Pode ter crédito rural" : "Crédito rural travado",
      detalhe: "Sem embargo, terra indígena ou unidade de conservação",
      bloqueia: false,
    })
  if (i.filtro_territorial && i.filtro_territorial !== "ok")
    lista.push({
      id: "territorial",
      ok: false,
      texto: i.filtro_territorial === "bloqueio" ? "Bloqueio territorial" : "Atenção territorial",
      detalhe:
        "Quilombo, terra indígena da FUNAI em qualquer fase ou UC de proteção integral sobre o imóvel. O funil do motor ainda não tira o imóvel por isso: conferir antes do contrato.",
      bloqueia: false,
    })
  return lista
}
