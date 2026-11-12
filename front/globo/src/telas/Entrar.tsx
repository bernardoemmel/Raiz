import { Mail } from "lucide-react"
import { useEffect, useState } from "react"
import { avisarSessao, pedidos } from "../pedidos"
import { Cabecalho } from "../partes/Cabecalho"
import { Estado } from "../partes/Estado"
import { AvisoExemplo } from "../partes/pedido/AvisoExemplo"
import { linkPedidos } from "../rota"

const CHAVE_VOLTA = "raiz.volta"
const guardarVolta = (v: string | null) => {
  try {
    if (v) sessionStorage.setItem(CHAVE_VOLTA, v)
    else sessionStorage.removeItem(CHAVE_VOLTA)
  } catch {
    // sem sessionStorage: depois de entrar, vai para Meus pedidos
  }
}
const lerVolta = () => {
  try {
    return sessionStorage.getItem(CHAVE_VOLTA)
  } catch {
    return null
  }
}

/**
 * Entrar sem senha: a pessoa diz o e-mail, recebe um link e entra ao abrir. Com o token na rota (#/entrar/<token>), a
 * tela confirma e volta para onde a pessoa ia.
 */
export function Entrar({ token, volta }: { token: string | null; volta?: string }) {
  const [email, setEmail] = useState("")
  const [estado, setEstado] = useState<{ tipo: "parado" | "mandando" | "mandado" | "erro"; link?: string; erro?: string }>({ tipo: "parado" })
  const [confirmando, setConfirmando] = useState<string | null>(token ? "confirmando" : null)

  useEffect(() => {
    if (volta && volta !== "#/entrar") guardarVolta(volta)
  }, [volta])

  useEffect(() => {
    if (!token) return
    let vivo = true
    pedidos.confirmar(token).then(
      () => {
        if (!vivo) return
        const destino = lerVolta() ?? linkPedidos
        guardarVolta(null)
        avisarSessao()
        location.hash = destino
      },
      (e: Error) => vivo && setConfirmando(e.message),
    )
    return () => {
      vivo = false
    }
  }, [token])

  async function mandar(e: React.FormEvent) {
    e.preventDefault()
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return setEstado({ tipo: "erro", erro: "Confira o e-mail: falta o @ ou o domínio." })
    setEstado({ tipo: "mandando" })
    try {
      const r = await pedidos.entrar(email.trim())
      setEstado({ tipo: "mandado", link: r.link_exemplo })
    } catch (err) {
      setEstado({ tipo: "erro", erro: (err as Error).message })
    }
  }

  return (
    <div className="tela-pedidos">
      <Cabecalho atual="pedidos" />
      <main className="pagina pagina-estreita">
        <h1>Entrar na Raíz</h1>
        {token ? (
          confirmando === "confirmando" ? (
            <Estado tipo="carregando" titulo="Conferindo o link" />
          ) : (
            <Estado tipo="erro" titulo="Este link não serve mais.">
              <p>{confirmando} Peça outro abaixo.</p>
              <a href="#/entrar">Pedir outro link</a>
            </Estado>
          )
        ) : estado.tipo === "mandado" ? (
          <div className="entrar-pronto">
            <p className="frase">
              <Mail size={20} aria-hidden="true" /> Mandamos um link para <strong>{email.trim()}</strong>. Abra no mesmo
              aparelho para entrar. Não precisa de senha.
            </p>
            {estado.link && (
              <>
                <AvisoExemplo ativo />
                <p>Sem back-end, nenhum e-mail sai. Abra o link por aqui:</p>
                <a className="botao principal" href={estado.link}>
                  Abrir o link de entrada
                </a>
              </>
            )}
            <p className="legenda-frase">
              Não chegou? Confira a caixa de spam ou <button type="button" className="link" onClick={() => setEstado({ tipo: "parado" })}>use outro e-mail</button>.
            </p>
          </div>
        ) : (
          <form className="formulario" onSubmit={mandar} noValidate>
            <p className="frase">Para pedir lotes de fazendas e acompanhar a busca de interesse dos donos. Sem senha: mandamos um link para o seu e-mail.</p>
            <label className="campo">
              <span>Seu e-mail</span>
              <input
                type="email"
                inputMode="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-invalid={estado.tipo === "erro"}
                aria-describedby={estado.tipo === "erro" ? "entrar-erro" : undefined}
              />
            </label>
            {estado.tipo === "erro" && (
              <p id="entrar-erro" className="erro-campo" role="alert">
                {estado.erro}
              </p>
            )}
            <button className="botao principal" type="submit" disabled={estado.tipo === "mandando"}>
              {estado.tipo === "mandando" ? "Mandando" : "Mandar o link"}
            </button>
          </form>
        )}
      </main>
    </div>
  )
}
