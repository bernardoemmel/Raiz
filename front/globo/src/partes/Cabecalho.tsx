import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { Search, X } from "lucide-react"
import { useSessao } from "../sessao"
import { linkCalendario, linkNovoPedido, linkPedidos, linkProspeccao } from "../rota"
import { Busca } from "./Busca"
import { IconeRaiz, User } from "./Icones"
import "./Cabecalho.css"

const MENU = [
  { id: "fazendas", rotulo: "Áreas", href: linkProspeccao },
  { id: "pedidos", rotulo: "Pedidos", href: linkPedidos },
  { id: "calendario", rotulo: "Calendário", href: linkCalendario },
  { id: "acerto", rotulo: "Acerto", href: "#/acerto" },
]

interface Props {
  atual: string
  linkMapa?: string
  modoMapa?: boolean
  aoAbrirPedido?: () => void
  pedidoAberto?: boolean
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

/** Os três passos da cena-alvo, abertos pelo menu "Como funciona" sem sair do mapa. */
const PASSOS = [
  { titulo: "Faça o pedido", texto: "Diga quantos créditos ou hectares precisa, em que região e com quais regras de terra e de desmatamento." },
  { titulo: "O mapa monta o lote", texto: "A Raíz cruza o CAR, o satélite e o título de cada fazenda e junta as melhores, as pequenas inclusive, em um lote." },
  { titulo: "Confira e reserve", texto: "Cada fazenda tem uma ficha com a fonte e a data de cada medida. Nada é inventado: o que falta aparece como pendência." },
]

/** Barra verde comum a todas as telas: marca, menu principal, busca, pedido e conta. */
export function Cabecalho({ atual, linkMapa = "#/", modoMapa = false, aoAbrirPedido, pedidoAberto = false }: Props) {
  const sessao = useSessao()
  const celular = useMediaQuery("(max-width: 700px)")
  const compacto = useMediaQuery("(max-width: 1180px)")
  const [buscaAberta, setBuscaAberta] = useState(false)
  const [comoFunciona, setComoFunciona] = useState(false)
  const comoDialogo = useRef<HTMLDialogElement>(null)
  const cabecalho = useRef<HTMLElement>(null)
  const menu = useRef<HTMLDetailsElement>(null)
  const buscaDialogo = useRef<HTMLDialogElement>(null)
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
    if (comoFunciona) comoDialogo.current?.showModal()
    else comoDialogo.current?.close()
  }, [comoFunciona])
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
  const marca = <><IconeRaiz tamanho={22} /><span>Raíz</span></>
  const abrirComo = () => { fecharMenu(); setComoFunciona(true) }

  return (
    <header ref={cabecalho} className={`topo topo-v2${modoMapa ? " topo-v2-mapa" : ""}`}>
      <a className="pular-conteudo" href="#conteudo" onClick={(e) => {
        e.preventDefault()
        const principal = document.querySelector("main")
        if (principal) { principal.tabIndex = -1; principal.focus(); principal.scrollIntoView({ block: "nearest" }) }
      }}>Pular para o conteúdo</a>
      <a className="marca marca-desktop" href={linkMapa} aria-label="Raíz, abrir mapa">{marca}</a>
      {!compacto && <nav className="topo-principal" aria-label="Menu do site">
        <a href={linkMapa} aria-current={atual === "mapa" ? "page" : undefined}>Mapa</a>
        <a href={linkProspeccao} aria-current={atual === "fazendas" ? "page" : undefined}>Áreas</a>
        <button type="button" onClick={abrirComo} aria-haspopup="dialog">Como funciona</button>
        <a href={sessao ? linkPedidos : "#/entrar"} aria-current={atual === "pedidos" ? "page" : undefined}>{sessao ? "Seus pedidos" : "Entrar"}</a>
      </nav>}
      <div className="topo-espaco" />
      {!celular && <Busca atalho={false} />}
      {celular && <button ref={botaoBusca} type="button" className="topo-icone" aria-label="Buscar CAR, município ou estado" aria-haspopup="dialog" onClick={() => setBuscaAberta(true)}><Search size={20} aria-hidden="true" /></button>}
      {aoAbrirPedido ? <button type="button" className="topo-acao" onClick={aoAbrirPedido} aria-expanded={pedidoAberto}>{pedidoAberto ? "Pedido aberto" : "Fazer pedido"}</button> : <a className="topo-acao" href={linkNovoPedido}>Fazer pedido</a>}
      <details className="topo-conta" ref={menu}>
        <summary className={celular ? "marca" : "topo-icone"} aria-label={celular ? "Raíz, abrir menu e conta" : "Abrir menu e conta"}>{celular ? marca : <User size={20} aria-hidden="true" />}</summary>
        <div className="topo-menu">
          <nav aria-label="Principal">
            <a href={linkMapa} aria-current={atual === "mapa" ? "page" : undefined} onClick={fecharMenu}>Mapa</a>
            {MENU.map((m) => <a key={m.id} href={m.href} aria-current={atual === m.id ? "page" : undefined} onClick={fecharMenu}>{m.rotulo}</a>)}
            <button onClick={abrirComo}>Como funciona</button>
            {/* Áreas ainda sem conteúdo ficam visíveis, mas não abrem uma tela vazia. */}
            {["Projetos agrupados", "Minha cadeia", "Carteira"].map(nome => <span key={nome} aria-disabled="true">{nome} <small>Em breve</small></span>)}
            <a href={sessao ? linkPedidos : "#/entrar"} onClick={fecharMenu}>{sessao ? "Seus pedidos" : "Entrar"}</a>
          </nav>
        </div>
      </details>
      <dialog ref={buscaDialogo} className="topo-dialogo topo-dialogo-busca" aria-labelledby="titulo-busca-v2" onCancel={e => { e.preventDefault(); fecharBusca() }} onClose={e => { if (!e.currentTarget.open) setBuscaAberta(false) }}>
        <div className="topo-dialogo-cabeca"><h2 id="titulo-busca-v2">Buscar no mapa</h2><button className="topo-icone" type="button" onClick={fecharBusca} aria-label="Fechar busca"><X size={20} aria-hidden="true" /></button></div>
        {celular && <Busca atalho={false} aoEscolher={fecharBusca} />}
      </dialog>
      <dialog ref={comoDialogo} className="topo-dialogo topo-dialogo-como" aria-labelledby="titulo-como-funciona" onCancel={() => setComoFunciona(false)} onClose={() => setComoFunciona(false)}>
        <div className="topo-dialogo-cabeca"><h2 id="titulo-como-funciona">Como funciona</h2><button className="topo-icone" type="button" onClick={() => setComoFunciona(false)} aria-label="Fechar"><X size={20} aria-hidden="true" /></button></div>
        <ol className="como-passos">{PASSOS.map((p, i) => <li key={p.titulo}><span className="como-numero" aria-hidden="true">{i + 1}</span><div><h3>{p.titulo}</h3><p>{p.texto}</p></div></li>)}</ol>
        <p className="como-nota">Fazendas pequenas nunca ficam de fora: a Raíz as agrupa em um mesmo projeto.</p>
        <a className="topo-acao" href={linkNovoPedido} onClick={() => setComoFunciona(false)}>Fazer um pedido</a>
      </dialog>
    </header>
  )
}
