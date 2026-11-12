import type { Imovel } from "../../../compartilhado/dados"
import { DESMATES, FRENTES, TITULOS, type Filtros as F, type TituloId } from "../filtros"

export interface Camadas {
  secundaria: boolean
  alertas: boolean
  areas: boolean
  rios: boolean
}

interface Props {
  filtros: F
  mudar: (f: F) => void
  camadas: Camadas
  mudarCamadas: (c: Camadas) => void
  imoveis: Imovel[] | null | undefined
}

export function Filtros({ filtros, mudar, camadas, mudarCamadas, imoveis }: Props) {
  const semDado = !imoveis
  const alternarTitulo = (t: TituloId) =>
    mudar({ ...filtros, titulos: filtros.titulos.includes(t) ? filtros.titulos.filter((x) => x !== t) : [...filtros.titulos, t] })
  const temColuna = (c: string) => !!imoveis?.some((i) => i.linha[c] !== undefined && i.linha[c] !== "")
  const temFogo = temColuna("mb_fogo_2025_ha") || temColuna("anos_fogo")

  return (
    <aside className="painel filtros" aria-label="Filtros">
      {semDado && (
        <p className="aviso-filtro">
          Os filtros por fazenda ligam quando o motor entregar os imóveis deste município. Os números do funil já são
          do motor.
        </p>
      )}
      <fieldset disabled={semDado}>
        <legend>Frente</legend>
        <div className="fichas-chip">
          {FRENTES.map((f) => {
            const ok = !imoveis || f.disponivel(imoveis)
            return (
              <button
                key={f.id}
                type="button"
                className="chip"
                aria-pressed={filtros.frente === f.id}
                disabled={!ok}
                title={f.dica}
                onClick={() => mudar({ ...filtros, frente: f.id })}
              >
                {f.rotulo}
              </button>
            )
          })}
        </div>
      </fieldset>

      <fieldset disabled={semDado}>
        <legend>Título da terra</legend>
        {TITULOS.map((t) => (
          <label key={t.id} className="marcar" title={t.dica}>
            <input type="checkbox" checked={filtros.titulos.includes(t.id)} onChange={() => alternarTitulo(t.id)} />
            {t.rotulo}
          </label>
        ))}
      </fieldset>

      <fieldset disabled={semDado}>
        <legend>Sem desmatamento há</legend>
        <div className="fichas-chip">
          {DESMATES.map((d) => (
            <button
              key={d.id}
              type="button"
              className="chip"
              aria-pressed={filtros.semDesmate === d.id}
              title={d.dica}
              onClick={() => mudar({ ...filtros, semDesmate: filtros.semDesmate === d.id ? null : d.id })}
            >
              {d.rotulo}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>Tamanho</legend>
        <p className="texto-tamanho">
          Todas entram. Fazenda grande vira projeto sozinha; pequenas entram juntas num projeto agrupado.
        </p>
      </fieldset>

      <fieldset>
        <legend>Camadas do mapa</legend>
        <label className={"marcar" + (semDado ? " desligado" : "")}>
          <input
            type="checkbox"
            disabled={semDado}
            checked={camadas.secundaria}
            onChange={() => mudarCamadas({ ...camadas, secundaria: !camadas.secundaria })}
          />
          Mata que voltou sozinha
        </label>
        <label className={"marcar" + (semDado ? " desligado" : "")}>
          <input
            type="checkbox"
            disabled={semDado}
            checked={camadas.alertas}
            onChange={() => mudarCamadas({ ...camadas, alertas: !camadas.alertas })}
          />
          Alertas de desmatamento
        </label>
        <label className={"marcar" + (temFogo ? "" : " desligado")} title="O motor ainda não entrega os anos de fogo nesta amostra">
          <input type="checkbox" disabled={!temFogo} checked={false} onChange={() => undefined} />
          <span>
            Fogo (anos queimados)
            {!temFogo && <small>chega com o MapBiomas Fogo no motor</small>}
          </span>
        </label>
        <label className="marcar">
          <input type="checkbox" checked={camadas.rios} onChange={() => mudarCamadas({ ...camadas, rios: !camadas.rios })} />
          Rios e APP
        </label>
        <label className="marcar">
          <input type="checkbox" checked={camadas.areas} onChange={() => mudarCamadas({ ...camadas, areas: !camadas.areas })} />
          Terras indígenas e UCs
        </label>
        <label className="marcar desligado" title="Falta a lista de frigoríficos com localização">
          <input type="checkbox" disabled checked={false} onChange={() => undefined} />
          <span>
            Raio de 50 km do frigorífico
            <small>falta a lista de frigoríficos</small>
          </span>
        </label>
      </fieldset>
    </aside>
  )
}
