import type { EvidenciaCompromisso, TerraComprometidaDados } from "../../../compartilhado/prospeccao"
import { dataTerra } from "../prospeccao"
import { Medida } from "./MedidaTerra"

const nomes: Record<string, string> = {
  sobreposicao_confirmada: "Sobreposição confirmada nas fontes consultadas", indicio: "Indício de sobreposição", sem_sobreposicao_identificada: "Sem sobreposição identificada nas fontes consultadas", nao_verificado: "Ainda não verificado",
  poligono_oficial: "Polígono oficial", poligono_secundario: "Polígono de fonte secundária", catalogo_sem_geometria: "Catálogo sem geometria", contexto_jurisdicional: "Contexto jurisdicional",
  projeto_carbono: "Projeto de carbono", concessao_florestal: "Concessão florestal", concessao_restauracao: "Concessão de restauração", programa_jurisdicional: "Programa jurisdicional",
  ativo: "Ativo", em_validacao: "Em validação", retirado: "Retirado", inativo: "Inativo", desconhecido: "Situação não informada",
  consultado: "Consultada", parcial: "Cobertura parcial", indisponivel: "Indisponível", brasil: "Brasil", uf: "Estado", bbox: "Recorte geográfico", projeto: "Projeto",
  verra: "Verra", berkeley: "Berkeley", sfb_concessoes: "Serviço Florestal Brasileiro", ideflor_concessoes: "IDEFLOR", art_jurisdicional: "ART", limites_pesquisa: "Limites de pesquisa",
}
const nome = (valor: string) => nomes[valor] ?? valor.replaceAll("_", " ")
function Fonte({ url, texto }: { url: string | null; texto: string }) {
  return url?.startsWith("https://") ? <a href={url} target="_blank" rel="noreferrer">{texto}</a> : <>{texto}</>
}
function Evidencia({ dado, contexto = false }: { dado: EvidenciaCompromisso; contexto?: boolean }) {
  return <li>
    <strong>{nome(dado.tipo)}: {dado.registro} {dado.objeto_id}</strong>
    <p>{nome(dado.situacao)}. Certeza: {nome(dado.certeza)}.</p>
    {!contexto && <Medida dado={dado.area} />}
    {!contexto && (dado.situacao === "retirado" || dado.situacao === "inativo") && <p>Área histórica informativa; não compõe a sobreposição atual.</p>}
    <p className="legenda-frase">Fonte: <Fonte url={dado.fonte_url} texto={nome(dado.fonte_id)} />. {dado.data_referencia ? `Referência: ${dataTerra(dado.data_referencia)}.` : "Data da fonte não informada."} Observada em {dataTerra(dado.observado_em)}.</p>
    {(dado.inicio || dado.fim) && <p className="legenda-frase">Início: {dataTerra(dado.inicio)}. Fim: {dataTerra(dado.fim)}.</p>}
  </li>
}
export function TerraComprometida({ dado }: { dado?: TerraComprometidaDados }) {
  return <section className="compromissos-terra" aria-labelledby="compromissos-titulo">
    <h2 id="compromissos-titulo">Terra comprometida</h2>
    <p className="frase">{nome(dado?.situacao ?? "nao_verificado")}</p>
    <p>{dado?.aviso || "Ausência de sobreposição nas fontes consultadas não comprova terra livre. Polígonos confirmam interseção com o registro observado, não exclusividade de carbono."}</p>
    {dado && <>
      <dl className="grade-terra"><div><dt>Interseção com registros oficiais ativos</dt><dd><Medida dado={dado.area_confirmada} /></dd></div><div><dt>Área com indícios</dt><dd><Medida dado={dado.area_indicio} /></dd></div></dl>
      <h3>Evidências no perímetro</h3>
      {dado.evidencias.length ? <ul className="grupos-prospeccao">{dado.evidencias.map((e) => <Evidencia key={`${e.fonte_id}-${e.objeto_id}`} dado={e} />)}</ul> : <p>Nenhuma evidência territorial associada nas fontes consultadas. Confira a cobertura abaixo.</p>}
      {!!dado.contexto_jurisdicional.length && <><h3>Contexto estadual</h3><p>Programa jurisdicional não compromete automaticamente cada CAR e não entra na área de sobreposição.</p><ul className="grupos-prospeccao">{dado.contexto_jurisdicional.map((e) => <Evidencia key={`${e.fonte_id}-${e.objeto_id}`} dado={e} contexto />)}</ul></>}
      <h3>Cobertura das fontes</h3>
      {dado.cobertura.length ? <ul className="grupos-prospeccao">{dado.cobertura.map((c, i) => <li key={`${c.fonte_id}-${c.recorte}-${i}`}>
        <strong><Fonte url={c.url} texto={nome(c.fonte_id)} /></strong><p>{nome(c.estado)}. Escopo: {nome(c.escopo)}, {c.recorte}.</p>
        <p className="legenda-frase">{c.data_referencia ? `Referência: ${dataTerra(c.data_referencia)}.` : "Data da fonte não informada."} Consultada em {dataTerra(c.consultado_em)}. Licença: {c.licenca}.</p>
      </li>)}</ul> : <p>Cobertura ainda não informada. Não é possível concluir que a terra esteja livre de compromissos.</p>}
    </>}
  </section>
}
