import io
import json
import zipfile
from xml.sax.saxutils import escape

import httpx
import pytest

from raiz.coleta import compromissos_registros as fontes

KML = b"""<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><name>NAO_PUBLICAR</name><Polygon>
<outerBoundaryIs><LinearRing><coordinates>
-60,-10 -59.9,-10 -59.9,-9.9 -60,-9.9 -60,-10
</coordinates></LinearRing></outerBoundaryIs>
<innerBoundaryIs><LinearRing><coordinates>
-59.98,-9.98 -59.92,-9.98 -59.92,-9.92 -59.98,-9.92 -59.98,-9.98
</coordinates></LinearRing></innerBoundaryIs>
</Polygon></Placemark></kml>"""


def xlsx():
    rows = [
        ["Project ID", "Project Name", "Voluntary Registry", "Voluntary Status", "Scope", "Country", "State", "Owner"],
        ["VCS665", "NAO_PUBLICAR", "VCS", "Registered", "Forestry & Land Use", "Brazil", "Mato Grosso", "NAO_PUBLICAR"],
        ["GS10", "NAO_PUBLICAR", "GOLD", "Withdrawn", "Forestry & Land Use", "Brazil", "PA", "NAO_PUBLICAR"],
        ["VCS11", "NAO_PUBLICAR", "VCS", "Registered", "Renewable Energy", "Brazil", "PA", "NAO_PUBLICAR"],
        ["VCS12", "NAO_PUBLICAR", "VCS", "Registered", "Forestry & Land Use", "Peru", "", "NAO_PUBLICAR"],
    ]
    ss = [v for row in rows for v in row]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="'
            + fontes.NS["m"]
            + '">'
            + "".join("<si><t>" + escape(s) + "</t></si>" for s in ss)
            + "</sst>",
        )
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="'
            + fontes.NS["m"]
            + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="PROJECTS" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        xml = '<worksheet xmlns="' + fontes.NS["m"] + '"><sheetData>'
        for n, row in enumerate(rows):
            xml += (
                "<row>"
                + "".join(f'<c r="{chr(65 + i)}{n + 1}" t="s"><v>{n * 8 + i}</v></c>' for i in range(len(row)))
                + "</row>"
            )
        z.writestr("xl/worksheets/sheet1.xml", xml + "</sheetData></worksheet>")
    return out.getvalue()


def test_berkeley_cabecalho_pais_status_e_privacidade():
    coleta = fontes.ler_berkeley(xlsx(), observado_em="2026-11-12")
    assert len(coleta["registros"]) == 2
    assert {r["registro"] for r in coleta["registros"]} == {"VCS", "GS"}
    assert coleta["registros"][1]["situacao"] == "retirado"
    assert all(r["geometry"] is None for r in coleta["registros"])
    assert "NAO_PUBLICAR" not in json.dumps(coleta)
    assert coleta["cobertura"]["data_referencia"] == "2026-08-31"


def test_kml_furos_e_pontos_nao_viram_limites():
    geom = fontes.ler_kml(KML)
    assert geom.area == pytest.approx(0.01 - 0.0036)
    with pytest.raises(ValueError, match="sem polígono"):
        fontes.ler_kml(b"<kml><Placemark><Point><coordinates>-60,-10</coordinates></Point></Placemark></kml>")
    with pytest.raises(ValueError, match="contrato seguro"):
        fontes.ler_kml(b"<!DOCTYPE x><kml/>")


def test_verra_apenas_rota_publica_boundary_e_br_sem_dados_pessoais():
    requisicoes = []

    def handle(req):
        requisicoes.append(req)
        assert "authorization" not in req.headers
        if "getProjectById" in req.url.path:
            return httpx.Response(
                200,
                json={
                    "id": 665,
                    "state_name": "Registered",
                    "main_contact_name": "NAO_PUBLICAR",
                    "registration_date": 1586131200000,
                    "project_start_date": "2000-01-01",
                    "mixedUnitList": [{"country_name": "Brazil", "province": "State of Mato Grosso"}],
                    "documentList": [
                        {"id": 123, "type_name": "Project Boundary (KML File)", "document_name": "secret.kml"},
                        {"id": 124, "type_name": "PDD", "document_name": "bad.kml"},
                    ],
                },
            )
        assert json.loads(req.content) == {"id": 123}
        return httpx.Response(200, content=KML)

    with httpx.Client(transport=httpx.MockTransport(handle)) as c:
        coleta = fontes.coletar_verra("VCS665", cliente=c, observado_em="2026-11-12")
    r = coleta["registros"][0]
    assert len(requisicoes) == 2
    assert r["certeza"] == "poligono_oficial"
    assert r["data_referencia"] is None  # registro/consulta não são data da geometria
    assert r["observado_em"] == "2026-11-12"
    assert r["uf"] == "MT"
    assert "NAO_PUBLICAR" not in str(r)


def test_erro_http_nao_expoe_url_assinada():
    def fail(req):
        raise httpx.ConnectError("https://site.invalid?token=SEGREDO", request=req)

    with httpx.Client(transport=httpx.MockTransport(fail)) as c, pytest.raises(ValueError) as e:
        fontes.coletar_verra("665", cliente=c)
    assert "SEGREDO" not in str(e.value)


def test_iterador_retomada_por_checkpoint_e_limite(monkeypatch):
    monkeypatch.setattr(
        fontes,
        "coletar_berkeley",
        lambda: {"registros": [{"objeto_id": f"VCS{i}", "registro": "VCS"} for i in (1, 2, 3)]},
    )
    chamadas = []

    def coleta(i):
        chamadas.append(i)
        return {"registros": [], "cobertura": {"estado": "consultado"}}

    monkeypatch.setattr(fontes, "coletar_verra", coleta)
    assert len(list(fontes.iterar_compromissos(fontes=["verra"], concluidos_verra=["VCS1"], limite_verra=1))) == 1
    assert chamadas == ["2"]
    # Outra rodada sem o checkpoint revisita os projetos, inclusive os retirados.
    list(fontes.iterar_compromissos(fontes=["verra"], limite_verra=1))
    assert chamadas[-1] == "1"
