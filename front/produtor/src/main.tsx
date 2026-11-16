import "./estilo.css"

// O formulário de entrada já é HTML funcional: nem Preact nem dados individuais são necessários para lê-lo.
// A ficha e suas dependências só chegam quando o link ou o formulário identifica um CAR.
if (new URLSearchParams(location.search).get("car")) {
  Promise.all([import("preact"), import("./Ficha")]).then(([{ render, h }, { Ficha }]) => {
    render(h(Ficha, {}), document.getElementById("raiz")!)
  }).catch(() => {
    const aviso = document.getElementById("erro-abertura")
    if (aviso) aviso.hidden = false
  })
}
