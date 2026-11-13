import { useSessao } from "../sessao"
import { linkCalendario, linkPedidos, linkProspeccao } from "../rota"
import { Busca } from "./Busca"
import { IconeRaiz, User } from "./Icones"

const MENU = [
  { id: "mapa", rotulo: "Mapa" },
  { id: "pedidos", rotulo: "Pedidos" },
  { id: "calendario", rotulo: "Calendário" },
  { id: "fazendas", rotulo: "Fazendas" },
  { id: "acerto", rotulo: "Acerto" },
  { id: "agrupados", rotulo: "Projetos agrupados" },
  { id: "carteira", rotulo: "Carteira" },
  { id: "cadeia", rotulo: "Minha cadeia" },
]

export function Cabecalho({ atual, linkMapa = "#/" }: { atual: string; linkMapa?: string }) {
  const sessao = useSessao()
  return (
    <header className="topo">
      <a className="pular-conteudo" href="#conteudo" onClick={(e) => {
        e.preventDefault()
        const principal = document.querySelector("main")
        if (principal) { principal.tabIndex = -1; principal.focus(); principal.scrollIntoView({ block: "nearest" }) }
      }}>Pular para o conteúdo</a>
      <a className="marca" href={linkMapa}>
        <IconeRaiz />
        Raíz
      </a>
      <nav aria-label="Principal">
        <ul className="menu">
          {MENU.map((m) =>
            m.id === "mapa" || m.id === "pedidos" || m.id === "calendario" || m.id === "fazendas" || m.id === "acerto" ? (
              <li key={m.id} className="menu-ativo">
                <a href={m.id === "mapa" ? linkMapa : m.id === "calendario" ? linkCalendario : m.id === "fazendas" ? linkProspeccao : m.id === "acerto" ? "#/acerto" : linkPedidos} aria-current={atual === m.id ? "page" : undefined}>
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
        <Busca />
        <a className="avatar" href={sessao ? linkPedidos : "#/entrar"} title={sessao ? `Seus pedidos (${sessao.email})` : "Entrar"} aria-label={sessao ? "Seus pedidos" : "Entrar"}>
          <User size={20} aria-hidden="true" />
        </a>
      </div>
    </header>
  )
}
