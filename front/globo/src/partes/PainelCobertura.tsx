import { contarCobertura, type CoberturaMapa } from "../../../compartilhado/dados/cobertura-mapa"
import { fmtInt, plural, ufDoCodigo } from "../../../compartilhado/formato"

function Data({ valor }: { valor: string }) {
  return <time dateTime={valor}>{new Date(valor).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" })} (Brasília)</time>
}

export function PainelCobertura({ cobertura, uf }: { cobertura?: CoberturaMapa; uf?: string | null }) {
  if (!cobertura) return <p className="legenda-frase">A cobertura dos desenhos e a data de atualização ainda não foram informadas.</p>
  const n = contarCobertura(cobertura, uf)
  const comparacao = cobertura.novos_desde
  const novos = comparacao ? [...new Set(comparacao.municipios)].filter((cod) => !uf || ufDoCodigo(cod) === uf).length : null
  return (
    <section className="secao-painel" aria-labelledby="cobertura-titulo">
      <h2 id="cobertura-titulo">Cobertura do mapa</h2>
      <p>
        <strong>{plural(n.municipios, "município", "municípios")}{!uf && ` em ${plural(n.estados, "estado", "estados")}`}</strong>
        {n.municipios === 1 ? " tem" : " têm"} desenho das fazendas na base.
        {n.semDesenho > 0 && ` ${fmtInt(n.semDesenho)} ${n.semDesenho === 1 ? "ainda aguarda" : "ainda aguardam"} o desenho.`}
      </p>
      <p className="legenda-frase">
        {cobertura.acesso === "restrito" ? "Este mapa aberto mostra os agregados; os desenhos individuais exigem acesso pago." : "O mapa aberto mostra os limites do CAR e a situação básica da terra."}
        {" "}Ao aproximar, o fundo é o mosaico Sentinel-2 2016/2017, histórico. As imagens e análises detalhadas do imóvel ficam na ficha com acesso pago, quando disponíveis.
      </p>
      <p className="legenda-frase">
        Última atualização do mapa: {cobertura.gerado_em ? <Data valor={cobertura.gerado_em} /> : "data não informada"}.
        <br />
        Dados publicados no Release: {cobertura.dados_publicados_em ? <Data valor={cobertura.dados_publicados_em} /> : "data não informada"}.
      </p>
      <p className="novos-municipios">{novos === null || !comparacao ? "A comparação com a publicação anterior ainda não está disponível." : <><strong>{plural(novos, "município novo", "municípios novos")}</strong> desde a publicação de <Data valor={comparacao.anterior_em} />.</>}</p>
      <p className="legenda-frase">A publicação diária inclui os municípios novos do processamento.</p>
    </section>
  )
}
