"""Pacote "lote pronto" para o desenvolvedor: um ZIP por opção do lote, gerado sozinho no arquivo privado.

Conteúdo (tudo derivado da tabela da opção e do resultado da consulta; nada é recalculado):

    LEIAME.md              o que há no pacote, o que ele não é e como ler a faixa
    resumo.json            totais da opção, versões, terra em espera e situação de sobreposição
    cars.csv               lista de CARs do lote (papel titular ou reserva) e grupo de vizinhança
    reservas.csv           só as fazendas de reserva
    tabela_lote.csv        ha, crédito P10/P50/P90, custo, preço de equilíbrio, TIR, caminho da terra, método
    sobreposicao.csv       status de sobreposição de cada fazenda (não verificada, risco ou sem indício)
    mapa.svg, mapa.geojson pontos do lote (sem contorno: o contorno só vem com a fazenda liberada)
    raio-x/<CAR>.pdf       Raio-X da fazenda (mesma ficha da página front/produtor), uma por CAR
    manifesto.json         SHA-256 de cada arquivo e a marca de rastreio

Nunca entram nome, CPF, CNPJ nem contato de dono. Pequenas fazendas ficam, agrupadas pelo grupo de vizinhança.
Fora do escopo: aceite do dono, contrato e Pix. O pacote é de uso restrito e não libera venda.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from html import escape
from pathlib import Path

import pandas as pd

from raiz.prospeccao_contrato import projetar_ficha
from raiz.prospeccao_pdf import gerar_pdf
from raiz.prospeccao_protecao import MarcaExportacao

VERSAO_PACOTE = "lote-pronto-1"
OPCOES = {"barata": "mais barata", "segura": "mais segura", "compacta": "mais compacta"}
DATA_ZIP = (2026, 1, 1, 0, 0, 0)  # data fixa: o mesmo lote gera o mesmo ZIP, byte a byte
COLUNAS_TABELA = (
    "papel", "cod_imovel", "uf", "municipio", "bioma", "grupo_id", "pequena", "local_aproximado", "area_ha", "ha",
    "modo", "metodo", "regeneracao_ha", "semeadura_ha", "plantio_ha", "credito_p10", "credito_p50", "credito_p90",
    "custo_credito_usd", "preco_equilibrio_usd", "tir_p10", "tir_p50", "tir_p90", "caminho", "caminho_terra",
    "risco_terra", "nivel_interesse", "restauracao_versao", "pendencias",
    "preco_minimo_tir_12_projeto_usd_t", "preco_minimo_tir_15_projeto_usd_t",
    "preco_minimo_tir_12_alavancada_usd_t", "preco_minimo_tir_15_alavancada_usd_t",
)  # fmt: skip
ROTULO_TERRA = {
    "privada_matricula": "Matrícula a conferir",
    "posse_em_titulacao": "Posse em titulação (terra em espera)",
    "assentamento": "Assentamento (terra em espera)",
    "publica_concessao": "Concessão pública",
}


def _pdf_estavel(ficha: dict, marca: MarcaExportacao) -> bytes:
    """O mesmo lote gera o mesmo PDF: o reportlab em modo invariante não grava data nem ID aleatório."""
    from reportlab import rl_config

    antes = rl_config.invariant
    rl_config.invariant = 1
    try:
        return gerar_pdf(ficha, marca=marca)
    finally:
        rl_config.invariant = antes


def marca_do_lote(consulta_id: str, opcao: str) -> MarcaExportacao:
    """Marca de rastreio do pacote gerado no arquivo privado (sem cliente). Ao entregar a um cliente, o PDF é refeito
    com a marca dele; esta marca só identifica de qual consulta e opção a cópia saiu."""
    h = hashlib.sha256(f"{consulta_id}|{opcao}".encode()).hexdigest()[:32]
    return MarcaExportacao(codigo=f"RZP-lote-{h}", versao="lote")


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _txt(v) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s or None


def situacao_sobreposicao(linha: dict) -> str:
    """nao_verificada enquanto o catálogo não traz a camada 'já comprometida' (ausência de coluna não é terra livre)."""
    if "risco_sobreposicao" not in linha and "ja_comprometida" not in linha:
        return "nao_verificada"
    # str(): o valor pode chegar como bool, numpy.bool_, None, NaN ou pd.NA conforme quem leu o parquet
    ja, risco = str(linha.get("ja_comprometida")), str(linha.get("risco_sobreposicao"))
    if ja == "True":
        return "ja_comprometida"
    if risco == "True":
        return "risco_sobreposicao"
    # nulo = imóvel sem verificação (sem limites coletados ou sem polígono do CAR): nunca vira "sem indício"
    if ("ja_comprometida" in linha and ja != "False") or linha.get("status_sobreposicao") == "nao_verificado":
        return "nao_verificada"
    return "sem_indicio_nas_fontes_consultadas"


def _medida(valor, unidade, modelo, estimado=True) -> dict:
    return {"valor": _num(valor), "unidade": unidade, "fonte": f"previsao_raiz:{modelo}", "data_referencia": None,
            "data_corte": None, "estimado": estimado}  # fmt: skip


def ficha_da_linha(linha: dict, *, sobreposicao: str) -> dict:
    """Ficha no contrato da página do produtor (prospeccao_contrato.ESQUEMA), montada da linha do lote."""
    modelo = _txt(linha.get("restauracao_versao")) or "desconhecido"
    caminho = _txt(linha.get("caminho_terra")) or "nao_classificada"
    pend = _txt(linha.get("pendencias"))
    aviso = {
        "nao_verificada": "Sobreposição não verificada: a camada 'já comprometida' ainda não cobre esta fazenda.",
        "ja_comprometida": "Fazenda já comprometida com outro projeto ou contrato.",
        "risco_sobreposicao": "Há risco de sobreposição a conferir antes de contratar.",
    }.get(sobreposicao, "Nenhum indício nas fontes efetivamente consultadas; não é certidão de terra livre.")
    return projetar_ficha(
        {
            "versao": VERSAO_PACOTE,
            "codigo_car": _txt(linha.get("cod_imovel")),
            "municipio": _txt(linha.get("municipio")),
            "cod_ibge": _txt(linha.get("cod_ibge")),
            "uf": _txt(linha.get("uf")),
            "bioma": _txt(linha.get("bioma")),
            "area_total": _medida(linha.get("ha"), "ha", modelo, estimado=False),
            "area_restauravel": _medida(linha.get("area_ha"), "ha", modelo),
            "caminho_terra": {
                "codigo": caminho,
                "rotulo": ROTULO_TERRA.get(caminho, caminho.replace("_", " ")),
                "situacao": _txt(linha.get("risco_terra")),
                "fonte": "classificacao_da_fonte",
                "regra_versao": None,
                "origem": None,
                "data_referencia": None,
            },  # fmt: skip
            "pendencias": [{"codigo": "pendencias", "texto": pend}] if pend else [],
            "credito": {
                **{p: _medida(linha.get(f"credito_{p}"), "tCO2e", modelo) for p in ("p10", "p50", "p90")},
                "base": "previsao por fazenda do lote",
                "metodo": _txt(linha.get("modo")),
                "versao_modelo": modelo,
            },
            "tir": {
                **{p: _medida(linha.get(f"tir_{p}"), "%", modelo) for p in ("p10", "p50", "p90")},
                "tipo": "caminho central legado, não quantil dos sorteios",
            },
            "risco": {
                "nivel": _txt(linha.get("risco_terra")),
                "fonte": None,
                "data_referencia": None,
                "regra_versao": None,
                "origem": None,
            },  # fmt: skip
            "agrupamento": {
                "pequena": bool(linha.get("pequena")),
                "grupo_id": _txt(linha.get("grupo_id")),
                "imoveis": None,
                "area": None,
            },  # fmt: skip
            "terra_comprometida": {
                "versao": None,
                "situacao": sobreposicao,
                "aviso": aviso,
                "evidencias": [],
                "contexto_jurisdicional": [],
                "cobertura": [],
            },  # fmt: skip
        }
    )


def mapa_svg(t: pd.DataFrame, titulo: str, largura: int = 900, altura: int = 640) -> str:
    """Pontos do lote em projeção equiretangular corrigida pela latitude; sem mapa-base nem contorno."""
    t = t.dropna(subset=["lon", "lat"])
    if t.empty:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} 80"><text x="12" y="40" '
                f'font-family="sans-serif" font-size="14">{escape(titulo)}: sem coordenadas no lote.</text></svg>')  # fmt: skip  # noqa: E501
    m = 60
    lat0 = float(t.lat.mean())
    k = math.cos(math.radians(lat0))
    xs, ys = t.lon * k, t.lat
    x0, x1, y0, y1 = float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())
    escala = min((largura - 2 * m) / max(x1 - x0, 1e-6), (altura - 2 * m - 30) / max(y1 - y0, 1e-6))
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" role="img" '
              f'aria-label="{escape(titulo)}"><rect width="100%" height="100%" fill="#F4F1E8"/>',
              f'<text x="{m}" y="28" font-family="sans-serif" font-size="16" fill="#1c2b1f">{escape(titulo)}</text>']  # fmt: skip  # noqa: E501
    for _, r in t.iterrows():
        x = m + (r.lon * k - x0) * escala
        y = altura - m - (r.lat - y0) * escala
        raio = 2.5 + min(9.0, math.sqrt(max(_num(r.get("area_ha")) or 0.0, 0.0)) / 2)
        cor = "#2F6F3E" if r.get("papel") == "titular" else "#B8860B"
        tracejado = ' stroke-dasharray="3 2"' if bool(r.get("local_aproximado")) else ""
        partes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{raio:.1f}" fill="{cor}" fill-opacity="0.65" '
                      f'stroke="#1c2b1f" stroke-width="0.6"{tracejado}/>')  # fmt: skip
    km = 100 * (largura / 4) / (escala * 111.32)  # largura de uma barra de ~1/4 do quadro, em graus de latitude
    partes.append(f'<text x="{m}" y="{altura - 14}" font-family="sans-serif" font-size="11" fill="#555D56">'
                  f'Verde: titulares. Ocre: reservas. Traço: local aproximado. Pontos, não contornos; ~{km:.0f} km '
                  f'de largura por quarto do quadro.</text></svg>')  # fmt: skip
    return "".join(partes)


def _geojson(t: pd.DataFrame) -> dict:
    pontos = []
    for _, r in t.dropna(subset=["lon", "lat"]).iterrows():
        pontos.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(r.lon), float(r.lat)]},
                       "properties": {"cod_imovel": r.cod_imovel, "papel": r.get("papel"),
                                      "local_aproximado": bool(r.get("local_aproximado")),
                                      "area_ha": _num(r.get("area_ha")), "grupo_id": _txt(r.get("grupo_id"))}})  # fmt: skip  # noqa: E501
    return {"type": "FeatureCollection", "features": pontos}


def _csv(linhas: list[dict], colunas) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(colunas), extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for li in linhas:
        w.writerow({c: ("" if li.get(c) is None or (isinstance(li.get(c), float) and math.isnan(li[c])) else li.get(c))
                    for c in colunas})  # fmt: skip
    return buf.getvalue().encode()


def _leiame(resumo: dict, opcao: str) -> bytes:
    ops = resumo["opcao"]
    sob = resumo["sobreposicao"]
    esp = resumo.get("terra_em_espera") or {}
    texto = f"""# Lote pronto: opção {OPCOES[opcao]} ({resumo["recorte"]})

Consulta `{resumo["consulta_id"][:12]}`; modelo financeiro `{resumo["modelo"]}`; seletor `{resumo["otimizador"]}`.
Pacote {VERSAO_PACOTE}, de uso restrito. Não distribua e não monte base própria com ele.

## O que é
- {ops["fazendas"]} fazendas ({ops["pequenas"]} pequenas, agrupadas por vizinhança; nenhuma foi descartada por tamanho),
  {ops["hectares"]:.1f} ha restauráveis. Créditos líquidos P10/P50/P90 do lote: {ops["creditos"].get("p10", 0):,.0f} /
  {ops["creditos"].get("p50", 0):,.0f} / {ops["creditos"].get("p90", 0):,.0f} tCO2e (faixa de carteira; soma de quantis
  por fazenda não é quantil do lote).
- `cars.csv` e `reservas.csv`: os CARs do lote e as fazendas de reserva (entram se alguém recusar).
- `tabela_lote.csv`: ha, créditos, custo por crédito, preço de equilíbrio, TIR e caminho da terra de cada fazenda.
- `mapa.svg` e `mapa.geojson`: pontos do lote. Sem contorno: o contorno só vem com a fazenda liberada.
- `raio-x/`: um PDF por fazenda, a mesma ficha da página do produtor.

## O que não é
- Não libera venda e não é oferta: é um potencial para diligência. Sem aceite do dono, contrato nem Pix.
- TIR por fazenda é o caminho central legado, não a mediana dos sorteios; TIR do lote só existe com o fluxo agregado.
- Sobreposição: **{sob["situacao"].replace("_", " ")}**. {sob["aviso"]}
- Terra em espera (fora deste lote, sem mudar o pedido): {esp.get("fazendas") or 0} fazendas de posse em titulação ou
  assentamento, que dependem de título. Para incluí-las, o pedido precisa escolhê-las em `terra`.
- Nunca há nome, CPF, CNPJ ou contato de dono. O contato passa pela Raíz.
"""
    return texto.encode()


def montar_pacote(resultado: dict, opcao: str, saida: Path, *, com_raio_x: bool = True) -> dict:
    """Escreve o ZIP da opção e devolve {caminho, sha256, bytes, fazendas}. Lê só o que a consulta já gravou."""
    item = resultado["opcoes"][opcao]
    t = pd.read_parquet(item["tabela"]["caminho"])
    if "papel" not in t:
        t["papel"] = "titular"
    t = t.sort_values(["papel", "cod_imovel"], ascending=[False, True]).reset_index(drop=True)  # titular antes
    linhas = [{k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in r.items()}
              for r in t.to_dict("records")]  # fmt: skip
    for li in linhas:
        li["metodo"] = li.get("metodo") or li.get("modo")
        li["sobreposicao"] = situacao_sobreposicao(li)
    recorte = resultado["recorte"]
    nome_recorte = (
        recorte["ufs"][0] if len(recorte["ufs"]) == 1 and not recorte["biomas"]
        else "+".join(recorte["biomas"]) if recorte["biomas"] and not recorte["ufs"]
        else "Brasil" if recorte["brasil"] else "recorte"
    )  # fmt: skip
    resumo = {
        "pacote_versao": VERSAO_PACOTE,
        "consulta_id": resultado["id"],
        "catalogo_id": resultado["catalogo_id"],
        "modelo": resultado["modelo"],
        "otimizador": resultado["versao"],
        "recorte": nome_recorte,
        "opcao_id": opcao,
        "opcao": {
            "fazendas": item["fazendas"],
            "pequenas": item["pequenas"],
            "hectares": item["area_ha"],
            "creditos": item["creditos"],
            "fecha_meta": item.get("fecha_meta"),
        },  # fmt: skip
        "por_caminho": {
            c: {
                "fazendas": n,
                "hectares": round(float(sum(li["area_ha"] or 0 for li in linhas if li["caminho"] == c)), 3),
            }
            for c, n in pd.Series([li["caminho"] for li in linhas]).value_counts().items()
        },
        "economia": item.get("economia"),
        "terra_em_espera": resultado.get("terra_em_espera"),
        "sobreposicao": resultado.get("sobreposicao"),
        "pedido": resultado["pedido"],
    }
    arquivos: dict[str, bytes] = {
        "LEIAME.md": _leiame(resumo, opcao),
        "resumo.json": json.dumps(resumo, ensure_ascii=False, indent=2, default=str).encode(),
        "cars.csv": _csv(linhas, ("cod_imovel", "papel", "grupo_id", "uf", "municipio", "pequena")),
        "reservas.csv": _csv([li for li in linhas if li.get("papel") == "reserva"], COLUNAS_TABELA),
        "tabela_lote.csv": _csv(linhas, COLUNAS_TABELA),
        "sobreposicao.csv": _csv(linhas, ("cod_imovel", "papel", "sobreposicao")),
        "mapa.svg": mapa_svg(t, f"Lote {OPCOES[opcao]}: {nome_recorte}, {item['fazendas']} fazendas").encode(),
        "mapa.geojson": json.dumps(_geojson(t), ensure_ascii=False).encode(),
    }
    marca = marca_do_lote(resultado["id"], opcao)
    saida.parent.mkdir(parents=True, exist_ok=True)
    hashes = {n: hashlib.sha256(b).hexdigest() for n, b in arquivos.items()}
    temporario = saida.with_name(saida.name + ".tmp")
    with zipfile.ZipFile(temporario, "w", compression=zipfile.ZIP_DEFLATED) as z:

        def escrever(nome: str, dados: bytes) -> None:
            info = zipfile.ZipInfo(nome, DATA_ZIP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            z.writestr(info, dados)

        for nome, dados in arquivos.items():
            escrever(nome, dados)
        if com_raio_x:
            for li in linhas:
                pdf = _pdf_estavel(ficha_da_linha(li, sobreposicao=li["sobreposicao"]), marca)
                nome = f"raio-x/{li['cod_imovel']}.pdf"
                hashes[nome] = hashlib.sha256(pdf).hexdigest()
                escrever(nome, pdf)
        manifesto = {"pacote_versao": VERSAO_PACOTE, "marca": marca.codigo, "arquivos": hashes,
                     "fazendas": len(linhas), "raio_x": bool(com_raio_x)}  # fmt: skip
        escrever("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True).encode())
    temporario.replace(saida)
    dados = saida.read_bytes()
    return {"caminho": str(saida), "sha256": hashlib.sha256(dados).hexdigest(), "bytes": len(dados),
            "fazendas": len(linhas)}  # fmt: skip
