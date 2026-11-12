"""Rascunho do relatório de perda (Loss Event Report Template v5.0 da Verra) e KML da área afetada.

Duas línguas: `pt` para o fundador conferir e `en` para entregar à Verra (o modelo é em inglês). As seções seguem o
modelo: 1 Loss Event Details (1.1 a 1.4), 2 Data and Parameters (2.1 e 2.2), 3 Quantification of Estimated Loss
(3.1 a 3.3) e 4 Additional Information. O que a Raíz não sabe fica marcado [preencher]; nada é inventado.
O rascunho não leva nome de pessoa nem CPF/CNPJ: quem prepara e assina preenche na hora de entregar.
"""

from __future__ import annotations

import datetime as dt

import shapely

from raiz.vigilancia import kml
from raiz.vigilancia.projetos import Projeto
from raiz.vigilancia.regras import Regras

MESES_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FONTES = {
    "mapbiomas_alerta": (
        "MapBiomas Alerta (alerta validado em imagem de alta resolução)",
        "MapBiomas Alerta (alert validated on high-resolution imagery)",
    ),
    "deter": ("DETER, INPE (alerta quase diário)", "DETER, INPE (near-daily deforestation alert)"),
    "prodes": ("PRODES, INPE (mapeamento anual)", "PRODES, INPE (annual deforestation mapping)"),
    "firms": (
        "NASA FIRMS, VIIRS NOAA-20 e NOAA-21 (foco de calor, pixel de 375 m)",
        "NASA FIRMS, VIIRS NOAA-20 and NOAA-21 (active fire, 375 m pixel)",
    ),
    "ibama_embargo": ("Ibama, termo de embargo", "Ibama, embargo term"),
}
TIPOS = {
    "desmatamento": ("desmatamento", "deforestation"),
    "degradacao": ("degradação florestal", "forest degradation"),
    "fogo": ("fogo", "fire"),
    "embargo": ("embargo ambiental", "environmental embargo"),
}
P = "[preencher]"
F = "[to be completed]"
# textos longos do modelo (português, inglês)
H21 = ("Dados e parâmetros monitorados na área afetada", "Data and Parameters Monitored in Affected Area")
H22 = (
    "Impacto nas atividades e no plano de monitoramento",
    "Description of Impact on Project Activities and Monitoring Plan",
)
DESC_AREA = (
    "Área da área de carbono do projeto atingida pelo evento",
    "Area of the project carbon area affected by the loss event",
)
EQUIP = ("sensores orbitais das fontes acima", "satellite sensors of the sources above")
QAQC = (
    "cada alerta é conferido em campo, com o cliente ou com imagem nova e marcado verdadeiro ou falso",
    "each alert is checked in the field, with the client or with new imagery and marked true or false",
)
VARIACAO = (
    "Variação do estoque de carbono pelo evento (tCO2e)",
    "Carbon stock change resulting from the loss event (tCO2e)",
)
VERIFICADO = (
    "Reduções e remoções líquidas já verificadas (tCO2e)",
    "Previously verified net reductions and removals (tCO2e)",
)


def _d(d: dt.date | None, idioma: str) -> str:
    if not d:
        return P if idioma == "pt" else F
    return d.strftime("%d/%m/%Y") if idioma == "pt" else f"{d.day:02d}-{MESES_EN[d.month - 1]}-{d.year}"


def _n(x: float | None, idioma: str, casas: int = 2) -> str:
    if x is None:
        return P if idioma == "pt" else F
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") if idioma == "pt" else s


def _id_evento(projeto: Projeto, perda: dict) -> str:
    base = projeto.get("verra_id") or projeto.id
    return f"{base}_LE{perda['numero']}"


def kml_da_perda(projeto: Projeto, perda: dict) -> str:
    g = shapely.from_wkb(perda["geometria"]) if perda.get("geometria") else None
    partes = list(getattr(g, "geoms", [g])) if g is not None else []
    pms = []
    for k, parte in enumerate(partes, start=1):
        pms.append(
            {
                "nome": f"{_id_evento(projeto, perda)} area {k}",
                "geometria": parte,
                "campos": {
                    "loss_event_id": _id_evento(projeto, perda),
                    "area_ha": round(float(perda["partes"][k - 1]["ha"]), 4) if k <= len(perda["partes"]) else None,
                    "discovery_date": str(perda["descoberta_em"]),
                    "sources": ",".join(perda["fontes"]),
                },
            }
        )
    return kml.escrever(_id_evento(projeto, perda), pms)


def rascunho(projeto: Projeto, perda: dict, regras: Regras, hoje: dt.date, idioma: str = "pt") -> str:
    en = idioma == "en"
    t = lambda pt, ing: ing if en else pt  # noqa: E731
    v = regras.verra
    pr = perda["prazo"]
    mag = perda["magnitude"]
    le = _id_evento(projeto, perda)
    fontes = "; ".join(FONTES.get(f, (f, f))[1 if en else 0] for f in perda["fontes"])
    tipos = ", ".join(TIPOS.get(x, (x, x))[1 if en else 0] for x in perda["tipos"])
    mon = projeto.get("monitoramento") or {}
    linhas: list[str] = []
    add = linhas.append

    # nota da Raíz (em português sempre: é para o fundador)
    obrig = "" if pr["relatorio_obrigatorio"] else ", obrigatório se o projeto já emitiu VCU"
    add("> **Rascunho gerado pela vigilância da Raíz. Conferir antes de entregar.**")
    add(
        f"> Evento {perda['perda_id']} ({perda['estado']}), confiança {perda['confianca']:.0%}. "
        f"Descoberta em {_d(perda['descoberta_em'], 'pt')}."
    )
    add(
        f"> Avisar a Verra por e-mail ({v.get('email')}) até {_d(pr['aviso_verra_ate'], 'pt')} "
        f"({pr['aviso_verra_dias_restantes']} dias). Relatório de perda até {_d(pr['relatorio_ate'], 'pt')} "
        f"({pr['relatorio_dias_restantes']} dias){obrig}."
    )
    add(f"> Base: {v.get('documento')}; modelo {v.get('modelo_relatorio')}. Regra da Raíz: {regras.versao}.")
    if mag["falta"]:
        add("> Falta para a magnitude da perda: " + "; ".join(mag["falta"]) + " (arquivo privado dos projetos).")
    add(
        "> Entregar como PDF não editável, na fonte e no formato do modelo, com a declaração do evento de perda "
        "assinada pelo proponente e verificação por VVB."
    )
    add("")
    add(f"# Loss Event Report: {projeto.get('verra_id') or P}, {le}")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| {t('Nome do projeto', 'Project name')} | {projeto.nome} |")
    add(f"| {t('Versão', 'Version')} | {t('rascunho 0.1', 'draft 0.1')} |")
    add(f"| {t('ID do evento de perda', 'Loss event ID')} | {le} |")
    add(f"| {t('Data de conclusão do documento', 'Document completion date')} | {P if not en else F} |")
    add(f"| {t('ID do projeto (Verra)', 'Project ID')} | {projeto.get('verra_id') or (P if not en else F)} |")
    add(f"| {t('Início do monitoramento', 'Monitoring period start')} | {_d(_dd(mon.get('inicio')), idioma)} |")
    add(f"| {t('Fim do monitoramento', 'Monitoring period end')} | {_d(_dd(mon.get('fim')), idioma)} |")
    add(f"| {t('Preparado por', 'Prepared by')} | {P if not en else F} |")
    add(f"| {t('Contato', 'Contact')} | {P if not en else F} |")
    add("")
    add(f"## 1 {t('Detalhes do evento de perda', 'Loss Event Details')}")
    add("")
    add(f"### 1.1 {t('Descrição resumida', 'Summary Description of the Loss Event')}")
    add("")
    classes = ", ".join(f"{c} {_n(h, idioma)} ha" for c, h in perda["classes_ha"].items()) or "-"
    add(
        t(
            f"A vigilância diária da Raíz encontrou sinal de {tipos} dentro da área de carbono do projeto, em "
            f"{_n(perda['area_ha'], 'pt')} ha ({classes}), entre {_d(perda['data_evento_inicio'], 'pt')} e "
            f"{_d(perda['data_evento_fim'], 'pt')}. Fontes: {fontes}. "
            f"{len(perda['alertas'])} alerta(s) formam este evento; situação: {perda['estado']}. "
            "O evento é uma perda inesperada de estoque de carbono que deveria ser mantido no cenário do projeto, "
            "a confirmar em campo ou com imagem nova.",
            f"The Raíz daily monitoring detected {tipos} inside the project carbon area, over "
            f"{_n(perda['area_ha'], 'en')} ha ({classes}), between {_d(perda['data_evento_inicio'], 'en')} and "
            f"{_d(perda['data_evento_fim'], 'en')}. Sources: {fontes}. "
            f"{len(perda['alertas'])} alert(s) make up this event; status: {perda['estado']}. "
            "This is an unexpected loss of carbon stocks expected to be maintained in the project scenario, "
            "to be confirmed in the field or with new imagery.",
        )
    )
    add("")
    add(f"### 1.2 {t('Data do evento de perda', 'Date of Loss Event')}")
    add("")
    add(
        f"| {t('Data do evento', 'Date of the loss event')} | {t('Data da descoberta', 'Date of discovery')} | "
        f"{t('Tamanho (ha atingidos)', 'Size (hectares impacted)')} |"
    )
    add("|---|---|---|")
    inicio, fim = perda["data_evento_inicio"], perda["data_evento_fim"]
    datas = _d(inicio, idioma) if inicio == fim else f"{_d(inicio, idioma)} {t('a', 'to')} {_d(fim, idioma)}"
    add(f"| {datas} | {_d(perda['descoberta_em'], idioma)} | {_n(perda['area_ha'], idioma)} ha |")
    add("")
    add(
        t(
            "A data da descoberta é a mais cedo entre a publicação pela fonte e a primeira leitura pela Raíz.",
            "The discovery date is the earliest of the source publication date and the first detection by Raíz.",
        )
    )
    add("")
    add(f"### 1.3 {t('Local do evento de perda', 'Location of Loss Event')}")
    add("")
    add(f"| {t('Área', 'Area')} | ha | {t('Centro (latitude, longitude)', 'Centroid (latitude, longitude)')} |")
    add("|---|---|---|")
    for k, p in enumerate(perda["partes"], start=1):
        add(f"| {k} | {_n(p['ha'], idioma)} | {p['centro'][1]:.6f}, {p['centro'][0]:.6f} |")
    add("")
    add(
        t(
            f"Polígonos da área afetada: arquivo {le}.kml (gerado pela Raíz; conferir com os Geolocation File "
            "Requirements v5.0).",
            f"Polygons of the affected area: file {le}.kml (generated by Raíz; check against the Geolocation File "
            "Requirements v5.0).",
        )
    )
    if perda["imoveis"]:
        add("")
        add(t("Imóveis do CAR tocados pelas mesmas ocorrências:", "Rural properties (CAR) touched by the same alerts:"))
        for im in perda["imoveis"][:20]:
            add(f"- {im['cod_imovel']} ({_n(im['area_ha'], idioma)} ha)")
    add("")
    add(f"### 1.4 {t('Probabilidade de reversão', 'Likelihood of Reversal')}")
    add("")
    add(
        f"| {t('O evento deve se qualificar como reversão?', 'Is the loss event likely to qualify as a reversal?')} "
        f"| ☐ {t('Sim', 'Yes')} ☐ {t('Não', 'No')} |"
    )
    add("|---|---|")
    pista = (
        t(
            "Fogo pode ser reversão inevitável (causa natural) ou evitável (ação humana); conferir a causa.",
            "Fire may be an unavoidable (natural cause) or avoidable (human-caused) reversal; check the cause.",
        )
        if "fogo" in perda["tipos"]
        else t(
            "Derrubada costuma ser reversão evitável; conferir a causa.",
            "Clearing is usually an avoidable reversal; check the cause.",
        )
    )
    add(f"| {t('Justificativa', 'Justification')} | {pista} {P if not en else F} |")
    add("")
    add(f"## 2 {t('Dados e parâmetros', 'Data and Parameters')}")
    add("")
    add(f"### 2.1 {t(*H21)}")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| {t('Dado/Parâmetro', 'Data/Parameter')} | A_loss |")
    add(f"| {t('Unidade', 'Data unit')} | ha |")
    add(f"| {t('Descrição', 'Description')} | {t(*DESC_AREA)} |")
    add(f"| {t('Fonte do dado', 'Source of data')} | {fontes} |")
    add(
        f"| {t('Método de medição', 'Description of measurement methods and procedures to be applied')} | "
        + t(
            "Interseção dos polígonos dos alertas com os polígonos do projeto, em SIRGAS 2000 / Brazil Polyconic "
            "(EPSG:5880); foco de calor como o pixel do VIIRS (scan x track). Responsável: Raíz.",
            "Intersection of alert polygons with project polygons in SIRGAS 2000 / Brazil Polyconic (EPSG:5880); "
            "active fire as the VIIRS pixel footprint (scan x track). Responsible: Raíz.",
        )
        + " |"
    )
    add(f"| {t('Frequência', 'Frequency of monitoring/recording')} | {t('diária', 'daily')} |")
    add(f"| {t('Valor aplicado', 'Value applied')} | {_n(perda['area_ha'], idioma, 4)} |")
    add(f"| {t('Equipamento', 'Monitoring equipment')} | {t(*EQUIP)} |")
    add(f"| QA/QC | {t(*QAQC)} |")
    add(f"| {t('Finalidade', 'Purpose of data')} | {t('cálculo da perda', 'calculation of the loss')} |")
    add("")
    estoques = {c: projeto.estoque(c) for c in perda["classes_ha"]}
    if any(e is not None for e in estoques.values()):
        add("| | |")
        add("|---|---|")
        add(f"| {t('Dado/Parâmetro', 'Data/Parameter')} | C_stock |")
        add(f"| {t('Unidade', 'Data unit')} | tCO2e/ha |")
        add(
            f"| {t('Valor aplicado', 'Value applied')} | "
            + "; ".join(f"{c}: {_n(e, idioma)}" for c, e in estoques.items() if e is not None)
            + " |"
        )
        add(f"| {t('Fonte do dado', 'Source of data')} | {t('cadastro privado do projeto', 'project records')} |")
        add("")
    add(f"### 2.2 {t(*H22)}")
    add("")
    add(P if not en else F)
    add("")
    add(f"## 3 {t('Quantificação da perda estimada', 'Quantification of Estimated Loss')}")
    add("")
    add(
        f"### 3.1 {t('Estoque de carbono da linha de base depois do evento', 'Baseline Carbon Stock after Loss Event')}"
    )
    add("")
    add(
        t("[preencher conforme a metodologia aplicada]", "[to be completed in accordance with the applied methodology]")
    )
    add("")
    add(f"### 3.2 {t('Estoque de carbono do projeto depois do evento', 'Project Carbon Stock after Loss Event')}")
    add("")
    if mag["perda_tco2e"] is not None:
        add(
            t(
                f"Estimativa conservadora: todo o estoque da área afetada perdido. Perda = soma (área da classe x "
                f"estoque por hectare da classe) = {_n(mag['perda_tco2e'], 'pt')} tCO2e.",
                f"Conservative estimate: all carbon stock in the affected area is lost. Loss = sum (class area x "
                f"class carbon stock per hectare) = {_n(mag['perda_tco2e'], 'en')} tCO2e.",
            )
        )
    else:
        add(
            t(
                "[preencher conforme a metodologia, com monitoramento de toda a área afetada]",
                "[to be completed in accordance with the applied methodology, based on monitoring of the full "
                "affected area]",
            )
        )
    add("")
    add(f"### 3.3 {t('Resumo da perda estimada', 'Summary of Estimated Loss Event')}")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| {t(*VARIACAO)} | {_n(mag['perda_tco2e'], idioma)} |")
    add(f"| {t(*VERIFICADO)} | {_n(mag['verificado_tco2e'], idioma)} |")
    add(f"| {t('Magnitude da perda (%)', 'Magnitude of loss (%)')} | {_n(mag['pct'], idioma, 3)} |")
    add("")
    add(
        t(
            f"Pelo modelo v5.0, é evento de perda quando a perda passa de {mag['limiar_pct']:g}% das reduções e "
            "remoções já verificadas. Plantio, desbaste e colheita previstos no plano não contam.",
            f"Under template v5.0, a loss event is a loss greater than {mag['limiar_pct']:g}% of previously verified "
            "net reductions and removals. Planned harvesting, thinning and planned land use changes do not qualify.",
        )
    )
    add("")
    add(f"## 4 {t('Informações adicionais', 'Additional Information')}")
    add("")
    add(
        f"| {t('Alerta', 'Alert')} | {t('Fonte', 'Source')} | {t('Classe', 'Class')} | {t('Data', 'Date')} | ha | "
        f"{t('Confiança', 'Confidence')} | {t('Marcação', 'Check')} |"
    )
    add("|---|---|---|---|---|---|---|")
    for a in perda["alertas"]:
        m = a["marcacao"]
        ms = t("pendente", "pending") if m is None else t("verdadeiro", "true") if m else t("falso", "false")
        add(
            f"| {a['alerta_id']} | {a['fonte']} | {a['classe']} | {_d(a['data_evento'], idioma)} | "
            f"{_n(a.get('area_projeto_ha'), idioma, 4)} | {float(a['confianca']):.0%} | {ms} |"
        )
    add("")
    add(
        t(
            f"Gerado em {_d(hoje, 'pt')} pela regra {regras.versao}.",
            f"Generated on {_d(hoje, 'en')} by rule {regras.versao}.",
        )
    )
    return "\n".join(linhas) + "\n"


def _dd(v) -> dt.date | None:
    if not v:
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])
