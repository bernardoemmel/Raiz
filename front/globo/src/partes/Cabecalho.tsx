import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { Search, X } from "lucide-react"
import { useSessao } from "../sessao"
import { linkCalendario, linkNovoPedido, linkPedidos, linkProspeccao } from "../rota"
import { Busca } from "./Busca"
import { IconeRaiz, User } from "./Icones"
import "./Cabecalho.css"

const MENU = [
  { id: "pedidos", rotulo: "Pedidos", href: linkPedidos },
  { id: "calendario", rotulo: "Calendário", href: linkCalendario },
  { id: "fazendas", rotulo: "Fazendas", href: linkProspeccao },
  { id: "acerto", rotulo: "Acerto", href: "#/acerto" },
]

interface Props {
  atual: string
  linkMapa?: string
  modoMapa?: boolean
  aoAbrirPedido?: () => void
  pedidoAberto?: boolean
  filtros?: ReactNode
}

function useMediaQuery(consulta: string) {
  const [ativa, setAtiva] = useState(() => window.matchMedia(consulta).matches)
  useEffect(() => {
    const media = window.matchMedia(consulta)
    const atualizar = () => setAtiva(media.matches)
    media.addEventListener("change", atualizar)
    atualizar()
    return () => media.removeEventListener("change", atualizar)
  }, [consulta])
  return ativa
}

/** Navegação comum; no mapa, todos os controles flutuam sem roubar área da cartografia. */
export function Cabecalho({ atual, linkMapa = "#/", modoMapa = false, aoAbrirPedido, pedidoAberto = false, filtros }: Props) {
  const sessao = useSessao()
  const celular = useMediaQuery("(max-width: 700px)")
  const compacto = useMediaQuery("(max-width: 1180px)")
  const [buscaAberta, setBuscaAberta] = useState(false)
  const [secao, setSecao] = useState<"Minha cadeia" | "Carteira" | null>(null)
  const cabecalho = useRef<HTMLElement>(null)
  const menu = useRef<HTMLDetailsElement>(null)
  const buscaDialogo = useRef<HTMLDialogElement>(null)
  const servicoDialogo = useRef<HTMLDialogElement>(null)
  const botaoBusca = useRef<HTMLButtonElement>(null)

  useLayoutEffect(() => {
    const dialogo = buscaDialogo.current
    if (buscaAberta && celular) {
      dialogo?.showModal()
      dialogo?.querySelector<HTMLInputElement>("input")?.focus()
    }
    else if (dialogo?.open) dialogo.close()
  }, [buscaAberta, celular])
  useEffect(() => {
    if (secao) servicoDialogo.current?.showModal()
    else servicoDialogo.current?.close()
  }, [secao])
  useEffect(() => {
    const fecharMenu = (evento: PointerEvent) => {
      if (menu.current?.open && !menu.current.contains(evento.target as Node)) menu.current.open = false
    }
    const teclado = (evento: KeyboardEvent) => {
      if (evento.key === "Escape" && menu.current?.open) {
        menu.current.open = false
        menu.current.querySelector("summary")?.focus()
      }
      const alvo = evento.target as HTMLElement
      if (evento.key !== "/" || /INPUT|TEXTAREA|SELECT/.test(alvo.tagName) || alvo.isContentEditable) return
      evento.preventDefault()
      if (celular) setBuscaAberta(true)
      else cabecalho.current?.querySelector<HTMLInputElement>(".busca input")?.focus()
    }
    document.addEventListener("pointerdown", fecharMenu)
    window.addEventListener("keydown", teclado)
    return () => {
      document.removeEventListener("pointerdown", fecharMenu)
      window.removeEventListener("keydown", teclado)
    }
  }, [celular])

  const fecharBusca = () => { buscaDialogo.current?.close(); setBuscaAberta(false); botaoBusca.current?.focus() }
  const fecharMenu = () => { if (menu.current) menu.current.open = false }
  const abrirSecao = (nome: "Minha cadeia" | "Carteira") => { fecharMenu(); setSecao(nome) }
  const marca = <><IconeRaiz tamanho={22} /><span>Raíz</span></>

  return (
    <header ref={cabecalho} className={`topo topo-v2${modoMapa ? " topo-v2-mapa" : ""}`}>
      <a className="pular-conteudo" href="#conteudo" onClick={(e) => {
        e.preventDefault()
        const principal = document.querySelector("main")
        if (principal) { principal.tabIndex = -1; principal.focus(); principal.scrollIntoView({ block: "nearest" }) }
      }}>Pular para o conteúdo</a>
      <a className="marca marca-desktop" href={linkMapa} aria-label="Raíz, abrir mapa">{marca}</a>
      {!celular && <Busca atalho={false} />}
      {!compacto && filtros && <div className="topo-filtros" aria-label="Filtros do mapa">{filtros}</div>}
      <div className="topo-espaco" />
      {!compacto && <nav className="topo-atalhos" aria-label="Área de trabalho">
        <button className="topo-pilula" onClick={() => abrirSecao("Minha cadeia")}>Minha cadeia</button>
        <button className="topo-pilula" onClick={() => abrirSecao("Carteira")}>Carteira</button>
      </nav>}
      {celular && <button ref={botaoBusca} type="button" className="topo-icone" aria-label="Buscar CAR, município ou estado" aria-haspopup="dialog" onClick={() => setBuscaAberta(true)}><Search size={20} aria-hidden="true" /></button>}
      {aoAbrirPedido ? <button type="button" className="topo-acao" onClick={aoAbrirPedido} aria-expanded={pedidoAberto}>{pedidoAberto ? "Pedido aberto" : "Fazer pedido"}</button> : <a className="topo-acao" href={linkNovoPedido}>Fazer pedido</a>}
      <details className="topo-conta" ref={menu}>
        <summary className={celular ? "marca" : "topo-icone"} aria-label={celular ? "Raíz, abrir menu e conta" : "Abrir menu e conta"}>{celular ? marca : <User size={20} aria-hidden="true" />}</summary>
        <div className="topo-menu">
          <nav aria-label="Principal">
            <a href={linkMapa} aria-current={atual === "mapa" ? "page" : undefined} onClick={fecharMenu}>Mapa</a>
            {MENU.map((m) => <a key={m.id} href={m.href} aria-current={atual === m.id ? "page" : undefined} onClick={fecharMenu}>{m.rotulo}</a>)}
            <span aria-disabled="true">Projetos agrupados <small>Em construção</small></span>
            <button onClick={() => abrirSecao("Minha cadeia")}>Minha cadeia</button>
            <button onClick={() => abrirSecao("Carteira")}>Carteira</button>
            <a href={sessao ? linkPedidos : "#/entrar"} onClick={fecharMenu}>{sessao ? "Seus pedidos" : "Entrar"}</a>
          </nav>
          {compacto && filtros && <section className="topo-menu-filtros" aria-label="Filtros do mapa"><h2>Filtros do mapa</h2>{filtros}</section>}
        </div>
      </details>
      <dialog ref={buscaDialogo} className="topo-dialogo topo-dialogo-busca" aria-labelledby="titulo-busca-v2" onCancel={e => { e.preventDefault(); fecharBusca() }} onClose={e => { if (!e.currentTarget.open) setBuscaAberta(false) }}>
        <div className="topo-dialogo-cabeca"><h2 id="titulo-busca-v2">Buscar no mapa</h2><button className="topo-icone" type="button" onClick={fecharBusca} aria-label="Fechar busca"><X size={20} aria-hidden="true" /></button></div>
        {celular && <Busca atalho={false} aoEscolher={fecharBusca} />}
      </dialog>
      <dialog ref={servicoDialogo} className="topo-dialogo" aria-labelledby="titulo-servico-v2" onCancel={() => setSecao(null)} onClose={() => setSecao(null)}>
        <div className="topo-dialogo-cabeca"><h2 id="titulo-servico-v2">{secao}</h2><button className="topo-icone" type="button" onClick={() => setSecao(null)} aria-label="Fechar"><X size={20} aria-hidden="true" /></button></div>
        <p>Esta área ainda está em construção. Você pode consultar os lotes, acompanhar seus pedidos e abrir os documentos disponíveis em Pedidos.</p>
        <a className="botao principal" href={linkPedidos} onClick={() => setSecao(null)}>Ver pedidos</a>
      </dialog>
    </header>
  )
}
