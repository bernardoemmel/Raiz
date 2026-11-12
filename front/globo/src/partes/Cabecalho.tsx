import type { Imovel } from "../../../compartilhado/dados"
import { Busca } from "./Busca"
import { IconePessoa, IconeRaiz } from "./Icones"

const MENU = [
  { id: "mapa", rotulo: "Mapa" },
  { id: "fazendas", rotulo: "Fazendas" },
  { id: "agrupados", rotulo: "Projetos agrupados" },
  { id: "carteira", rotulo: "Carteira" },
  { id: "cadeia", rotulo: "Minha cadeia" },
]

export function Cabecalho({ atual, imoveis, linkMapa = "#/" }: { atual: string; imoveis?: Imovel[] | null; linkMapa?: string }) {
  return (
    <header className="topo">
      <a className="marca" href={linkMapa}>
        <IconeRaiz />
        Raíz
      </a>
      <nav aria-label="Principal">
        <ul className="menu">
          {MENU.map((m) =>
            m.id === "mapa" ? (
              <li key={m.id}>
                <a href={linkMapa} aria-current={atual === "mapa" ? "page" : undefined}>
                  {m.rotulo}
                </a>
              </li>
            ) : (
              <li key={m.id}>
                <span aria-disabled="true" title="Em construção">
                  {m.rotulo}
                </span>
              </li>
            ),
          )}
        </ul>
      </nav>
      <div className="topo-dir">
        <Busca imoveis={imoveis} />
        <span className="avatar" title="Sua conta">
          <IconePessoa />
        </span>
      </div>
    </header>
  )
}
