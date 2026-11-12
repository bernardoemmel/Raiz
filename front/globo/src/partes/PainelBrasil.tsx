import type { FunilMunicipio } from "../../../compartilhado/dados"
import { fmtHa, fmtInt, UFS } from "../../../compartilhado/formato"
import { fraseDoBrasil, numerosDoBrasil } from "../../../compartilhado/funil-etapas"
import { linkMunicipio } from "../rota"
import { Estado } from "./Estado"

/** O Brasil na primeira tela: números do que a Raíz já leu e os municípios com mais área para restaurar. */
export function PainelBrasil({ municipios, comLista, carregando }: { municipios: FunilMunicipio[] | undefined; comLista: Set<string>; carregando: boolean }) {
  if (!municipios) return <Estado tipo="carregando" titulo="Lendo os municípios processados" />
  if (!municipios.length)
    return (
      <Estado tipo="vazio" titulo="Nenhum município processado ainda.">
        <p>O mapa mostra os municípios assim que o motor rodar o primeiro estado.</p>
      </Estado>
    )
  const n = numerosDoBrasil(municipios)
  const ufs = [...new Set(municipios.map((m) => UFS[m.uf] ?? m.uf))]
  const top = [...municipios].sort((a, b) => b.ha_carbono - a.ha_carbono).slice(0, 8)
  return (
    <div className="painel-conteudo">
      <h1>Onde dá para restaurar, com dono e título</h1>
      <p className="frase">{fraseDoBrasil(n, ufs, fmtInt)}</p>
      {/* urucum só no número que mais importa para a ação: a área que pode voltar a ser mata */}
      <dl className="numeros">
        <div>
          <dt>Imóveis lidos</dt>
          <dd className="num">{fmtInt(n.imoveis)}</dd>
        </div>
        <div>
          <dt>Fazendas aptas</dt>
          <dd className="num">{fmtInt(n.aptas)}</dd>
        </div>
        <div>
          <dt>Podem voltar a ser mata</dt>
          <dd className="num destaque">{fmtHa(n.ha)}</dd>
        </div>
      </dl>
      <section className="secao-painel" aria-labelledby="top-titulo">
        <h2 id="top-titulo">Municípios com mais área para restaurar</h2>
        <ol className="lista-municipios">
          {top.map((m) => (
            <li key={m.cod_ibge}>
              <a href={linkMunicipio(m.cod_ibge)}>
                <span>
                  <strong>{m.municipio}</strong>
                  <small>{comLista.has(m.cod_ibge) ? "Lista por fazenda pronta" : "Funil pronto, lista a caminho"}</small>
                </span>
                <span className="num">{fmtHa(m.ha_carbono)}</span>
              </a>
            </li>
          ))}
        </ol>
      </section>
      <p className="legenda-frase">
        No mapa, verde-claro é município já processado e cinza é município que ainda não foi lido. Os círculos verdes
        juntam as fazendas aptas, com o número dentro. Toque num município ou busque pelo nome.
      </p>
      {carregando && <span className="sr">Carregando</span>}
    </div>
  )
}
