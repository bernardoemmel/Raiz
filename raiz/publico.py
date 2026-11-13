"""Link público, cartão e vídeo da fazenda (design v1 do front, item 6), pelo código curto.

Regra de privacidade: o cartão, o vídeo e o link público mostram só município, hectares, selo e código curto. Código do
CAR, polígono exato e imagem de satélite da fazenda só depois do aceite do dono (negocio.aceite = aceito). Nada de nome
ou CPF em imagem, arquivo ou log.

- /cartao/{codigo}/previa.jpg (1200 x 630, < 250 KB), retrato.jpg (1080 x 1350), adesivo.png (transparente, < 300 KB),
  feitos com o Takumi (servicos/cartao/render.mjs, MIT ou Apache-2.0), e os mesmos em WebP (previa.webp, retrato.webp,
  adesivo.webp), mais leves, para a ficha e o site; a prévia do WhatsApp (og:image) continua em JPEG;
- /video/{codigo}.mp4 (1080 x 1920) e /video/{codigo}-720p.mp4: cenas do Takumi (renderAnimation) codificadas pelo
  FFmpeg no servidor, com a voz do Qwen3-TTS quando estiver instalado (sem ele, o vídeo sai mudo e o metadado diz);
- /p/{codigo}: ficha do produtor em HTML pronto no servidor (até 150 KB), com Open Graph para o WhatsApp;
  com Accept: text/markdown, ou em /p/{codigo}.md, os mesmos campos públicos em Markdown.
Tudo fica em cache (dados/publico/<codigo>/) e é refeito quando o selo ou o aceite mudam.
"""

from __future__ import annotations

import html
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import Engine, text

from raiz import RAIZ_REPO, publico_versoes
from raiz import markdown as markdown_mod
from raiz.config import config

SERVICO = RAIZ_REPO / "servicos" / "cartao"
# tipo -> {extensão: peso máximo em KB}; a primeira extensão é a padrão
CARTOES = {
    "previa": {"jpg": 250, "webp": 150},
    "retrato": {"jpg": 600, "webp": 350},
    "adesivo": {"png": 300, "webp": 150},
}
TIPO_IMAGEM = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
VIDEOS = {"": (1080, 1920), "-720p": (720, 1280)}


def pasta() -> Path:
    return Path(getattr(config(), "publico_dir", None) or RAIZ_REPO / "dados" / "publico")


def fmt_ha(x: float) -> str:
    return f"{round(x):,}".replace(",", ".") if x >= 10 else f"{x:.1f}".replace(".", ",")


def dados(engine: Engine, codigo: str) -> dict | None:
    """O que pode ir a público para o código curto (e, à parte, o que só vale depois do aceite)."""
    with engine.connect() as con:
        r = con.execute(
            text("""select k.codigo, v.cod_imovel, v.cod_busca, r.municipio, r.uf, r.ha, r.rodada_id,
                           r.cod_municipio_ibge,
                           a.estado as aceite, r.atributos
                    from negocio.codigo_curto k
                    join funil.vigente v on v.cod_imovel = k.cod_imovel
                    join funil.resultado_imovel r on r.rodada_id = v.rodada_id and r.cod_imovel = v.cod_imovel
                    left join negocio.aceite a on a.cod_imovel = v.cod_imovel
                    where k.codigo = :c"""),
            {"c": codigo.upper()},
        ).first()
    if r is None:
        return None
    aceito = r.aceite == "aceito"
    conferida = str((r.atributos or {}).get("matricula_conferida", "")).lower() in ("true", "1")
    selo = "ouro" if aceito else "prata" if conferida else "bronze"
    ha = publico_versoes._area(r.ha)
    municipio, uf = publico_versoes.local_basico(r.cod_municipio_ibge, r.municipio, r.uf)
    return {
        "codigo": r.codigo,
        "municipio": municipio or "Não informado",
        "uf": uf or "Não informado",
        "hectares": fmt_ha(ha) if ha is not None else "Área não informada",
        "frase": "de fazenda no Cadastro Ambiental Rural",
        "frase_curta": "no CAR",
        "selo": selo,
        "aceito": aceito,
        # só depois do aceite (nunca vão ao Takumi nem à página antes disso)
        "_cod_imovel": r.cod_imovel,
        "_cod_busca": r.cod_busca,
        "_rodada_id": r.rodada_id,
    }


def _publico(d: dict) -> dict:
    campos = ("codigo", "municipio", "uf", "hectares", "frase", "frase_curta", "selo", "aceito")
    return {k: d[k] for k in campos if k in d}


def _assinatura(d: dict) -> str:
    return json.dumps(_publico(d), sort_keys=True, ensure_ascii=False)


def _cache(d: dict, nome: str) -> tuple[Path, bool]:
    """Caminho em cache e se ele ainda vale (selo, aceite e textos iguais aos de quando foi feito)."""
    if not publico_versoes.codigo_valido(d["codigo"]) or Path(nome).name != nome or "\\" in nome:
        raise ValueError("caminho público inválido")
    p = pasta() / d["codigo"]
    p.mkdir(parents=True, exist_ok=True)
    f = p / nome
    marca = p / f"{nome}.assinatura"
    valido = f.exists() and marca.exists() and marca.read_text(encoding="utf-8") == _assinatura(d)
    return f, valido


def _marcar(d: dict, f: Path) -> None:
    (f.parent / f"{f.name}.assinatura").write_text(_assinatura(d), encoding="utf-8")


def _node(pedido: dict, saida: Path) -> None:
    if shutil.which("node") is None or not (SERVICO / "node_modules" / "@takumi-rs" / "core").exists():
        raise RuntimeError("Takumi não instalado: rode `npm ci` em servicos/cartao")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as t:
        json.dump(pedido, t, ensure_ascii=False)
    try:
        subprocess.run(["node", str(SERVICO / "render.mjs"), t.name, str(saida)], check=True, cwd=SERVICO,
                       capture_output=True, timeout=600)  # fmt: skip
    finally:
        Path(t.name).unlink(missing_ok=True)


def _imagens_do_aceite(d: dict) -> dict:
    """Imagens de satélite só depois do aceite (geradas pelo raiz.satelite, se já existirem)."""
    if not d["aceito"]:
        return {}
    from raiz import satelite

    p = satelite.pasta() / d["_cod_busca"]
    out = {}
    for chave, tipo in (
        ("imagem", "hoje-produtor"),
        ("imagem_hoje", "hoje-celular"),
        ("imagem_simulacao", "simulacao"),
    ):
        if (p / f"{tipo}.webp").exists():
            out[chave] = str(p / f"{tipo}.webp")
    return out


def cartao(d: dict, tipo: str, ext: str | None = None) -> Path:
    ext = ext or next(iter(CARTOES[tipo]))
    max_kb = CARTOES[tipo][ext]
    f, valido = _cache(d, f"{tipo}.{ext}")
    if valido:
        return f
    formato = {"jpg": "jpeg", "png": "png", "webp": "webp"}[ext]
    pedido = {**_publico(d), **_imagens_do_aceite(d), "tipo": tipo, "formato": formato}
    for q in (82, 72, 62, 50):
        pedido["qualidade"] = q
        _node(pedido, f)
        if f.stat().st_size <= max_kb * 1024:
            break
    if tipo == "adesivo" and f.stat().st_size > max_kb * 1024:
        pedido["lado"] = 400
        _node(pedido, f)
    _marcar(d, f)
    return f


def narracao(d: dict) -> str:
    return (
        f"Em {d['municipio']}, {d['hectares']} hectares desta fazenda {d['frase']}. "
        f"O código da fazenda na Raíz é {' '.join(d['codigo'])}."
    )


def _voz(texto: str, saida: Path) -> bool:
    """Qwen3-TTS (voz fixa da Raíz, E9 passo 5) quando instalado; devolve se gravou."""
    try:
        from raiz import voz
    except ImportError:
        return False
    return voz.falar(texto, saida)


def video(d: dict, sufixo: str = "") -> tuple[Path, dict]:
    w, h = VIDEOS[sufixo]
    f, valido = _cache(d, f"video{sufixo}.mp4")
    meta_f = f.with_suffix(".json")
    if valido and meta_f.exists():
        return f, json.loads(meta_f.read_text(encoding="utf-8"))
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg não instalado no servidor")
    with tempfile.TemporaryDirectory() as tmp:
        anim = Path(tmp) / "cenas.apng"
        _node({**_publico(d), **_imagens_do_aceite(d), "tipo": "animacao", "largura": w, "altura": h, "fps": 15}, anim)
        audio = Path(tmp) / "voz.wav"
        tem_voz = _voz(narracao(d), audio)
        entrada_audio = ["-i", str(audio)] if tem_voz else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"]
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(anim), *entrada_audio, "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "28",
             "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(f)],
            check=True, timeout=900,
        )  # fmt: skip
    meta = {"largura": w, "altura": h, "voz": "Qwen3-TTS" if tem_voz else None,
            "aviso": None if tem_voz else "sem voz: Qwen3-TTS não instalado no servidor"}  # fmt: skip
    meta_f.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _marcar(d, f)
    return f, meta


def _foto(d: dict, base: str) -> str:
    """Satélite com o contorno, com o borrão do ThumbHash de fundo (PNG de ~1 KB embutido) enquanto a foto chega e o
    tamanho certo para a página não pular."""
    from raiz import satelite
    from raiz.thumbhash import para_data_url

    c = satelite.capa(d["_cod_busca"]) or {}
    tam = f' width="{c["largura"]}" height="{c["altura"]}"' if c.get("largura") else ' width="720"'
    fundo = f' style="background:url({para_data_url(c["thumbhash"])}) center/cover"' if c.get("thumbhash") else ""
    legenda = f"<figcaption>{html.escape(c['credito'])}</figcaption>" if c.get("credito") else ""
    return (
        f'<figure><img src="{base}/p/{html.escape(d["codigo"])}/satelite.webp" alt="Imagem de satélite da fazenda"'
        f"{tam}{fundo}>{legenda}</figure>"
    )


def pagina(d: dict, base_url: str) -> str:
    """Ficha do produtor em HTML pronto (sem JavaScript), com Open Graph para o WhatsApp. Até 150 KB."""
    e = html.escape
    base = base_url.rstrip("/")
    selo_txt = {"bronze": "Selo bronze: achada no CAR", "prata": "Selo prata: título conferido",
                "ouro": "Selo ouro: o dono aceitou"}[d["selo"]]  # fmt: skip
    titulo = f"{d['hectares']} ha em {d['municipio']} ({d['uf']})"
    desc = f"{d['hectares']} hectares {d['frase']}. {selo_txt}. Código {d['codigo']}."
    depois = ""
    if d["aceito"]:
        depois = f'<p class="car">CAR {e(d["_cod_imovel"])}</p>'
        if _imagens_do_aceite(d).get("imagem"):
            depois += _foto(d, base)
    if d.get("_versao"):
        v = d["_versao"]
        depois += (
            f'<p><a href="{base}{e(v.caminho)}">Versão datada: '
            f"{v.data_corte.strftime('%d/%m/%Y')}, rodada {v.rodada_id}</a></p>"
        )
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} · Raíz</title>
<meta name="description" content="{e(desc)}">
<link rel="alternate" type="text/markdown" href="{base}/p/{e(d["codigo"])}.md">
<meta property="og:type" content="website"><meta property="og:site_name" content="Raíz">
<meta property="og:title" content="{e(titulo)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{base}/p/{e(d["codigo"])}">
<meta property="og:image" content="{base}/cartao/{e(d["codigo"])}/previa.jpg">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<style>body{{margin:0;font:18px/1.4 system-ui,sans-serif;background:#f4f1ea;color:#1d5a39}}
main{{max-width:720px;margin:auto;padding:24px}}.ha{{font-size:64px;font-weight:700;margin:8px 0}}
.selo{{display:inline-block;background:#fff;border-radius:20px;padding:6px 14px}}.car{{font-family:monospace}}
img{{max-width:100%;height:auto;border-radius:12px;margin-top:16px}}figure{{margin:0}}
figcaption{{font-size:14px;opacity:.8}}</style></head>
<body><main><p>{e(d["municipio"])} · {e(d["uf"])}</p><p class="ha">{e(d["hectares"])} ha</p>
<p>{e(d["frase"]).capitalize()}.</p><p class="selo">{e(selo_txt)}</p><p>Código da fazenda: <b>{e(d["codigo"])}</b></p>
{depois}<p><small>Raíz · dados do CAR (SICAR/SFB) e do MapBiomas</small></p></main></body></html>"""


def pagina_markdown(d: dict, base_url: str) -> str:
    """A mesma ficha pública do HTML: CAR e satélite só saem depois do aceite, nunca chaves internas."""
    t = markdown_mod.texto
    base = base_url.rstrip("/")
    selo = {
        "bronze": "Selo bronze: achada no CAR",
        "prata": "Selo prata: título conferido",
        "ouro": "Selo ouro: o dono aceitou",
    }[d["selo"]]
    partes = [
        f"# {t(d['hectares'])} ha em {t(d['municipio'])} ({t(d['uf'])})",
        "",
        f"{t(d['hectares'])} hectares {t(d['frase'])}.",
        "",
        selo + ".",
        "",
        f"Código da fazenda na Raíz: {t(d['codigo'])}.",
        "",
    ]
    if d["aceito"]:
        partes.extend([f"CAR: {t(d['_cod_imovel'])}.", ""])
        if _imagens_do_aceite(d).get("imagem"):
            partes.extend([f"![Imagem de satélite da fazenda]({base}/p/{d['codigo']}/satelite.webp)", ""])
    if d.get("_versao"):
        v = d["_versao"]
        partes.extend(
            [f"[Versão datada: {v.data_corte.strftime('%d/%m/%Y')}, rodada {v.rodada_id}]({base}{v.caminho}).", ""]
        )
    partes.append("Fonte: CAR (SICAR/SFB) e MapBiomas.")
    return "\n".join(partes) + "\n"


def roteador(engine_de):
    """Rotas públicas, sem token (o código curto sorteado é a chave; não dá para adivinhar)."""
    r = APIRouter()

    def achar(request, codigo: str) -> dict:
        if not publico_versoes.codigo_valido(codigo):
            raise HTTPException(404, "código não existe")
        d = dados(engine_de(request), codigo)
        if d is None:
            raise HTTPException(404, "código não existe")
        return d

    def ficha_atual(request: Request, codigo: str) -> dict:
        d = achar(request, codigo)
        if d["aceito"] and d.get("_rodada_id"):
            versao = publico_versoes.registrar(engine_de(request), codigo, d["_rodada_id"])
            if versao is None:
                # O aceite pode ter sido revogado entre a primeira consulta e a revalidação.
                # Nunca renderizar o CAR ou a imagem com o estado anterior de autorização.
                raise HTTPException(404, "ficha não disponível", headers=publico_versoes.SEM_CACHE)
            d = {**d, "_versao": versao}
        return d

    def ficha_datada(request: Request, codigo: str, versao: str, markdown: bool = False) -> Response:
        achado = publico_versoes.obter(engine_de(request), codigo, versao)
        if achado is None:
            raise HTTPException(404, "versão não disponível", headers=publico_versoes.SEM_CACHE)
        v, nova = achado
        if markdown or markdown_mod.prefere_markdown(request.headers.get("accept"), "text/html"):
            resposta = markdown_mod.resposta(publico_versoes.pagina_markdown(v, nova, str(request.base_url)))
            resposta.headers.update(publico_versoes.SEM_CACHE)
            return resposta
        return HTMLResponse(publico_versoes.pagina(v, nova, str(request.base_url)), headers=publico_versoes.SEM_CACHE)

    @r.get("/p/{codigo}/v/{versao}.md")
    def p_datada_markdown(codigo: str, versao: str, request: Request) -> Response:
        return ficha_datada(request, codigo, versao, markdown=True)

    @r.get("/p/{codigo}/v/{versao}")
    def p_datada(codigo: str, versao: str, request: Request) -> Response:
        return ficha_datada(request, codigo, versao)

    @r.get("/p/{codigo}.md")
    def p_markdown(codigo: str, request: Request) -> Response:
        resposta = markdown_mod.resposta(pagina_markdown(ficha_atual(request, codigo), str(request.base_url)))
        resposta.headers.update(publico_versoes.SEM_CACHE)
        return resposta

    @r.get("/p/{codigo}", response_class=HTMLResponse)
    def p(codigo: str, request: Request) -> Response:
        d = ficha_atual(request, codigo)
        if markdown_mod.prefere_markdown(request.headers.get("accept"), "text/html"):
            resposta = markdown_mod.resposta(pagina_markdown(d, str(request.base_url)))
            resposta.headers.update(publico_versoes.SEM_CACHE)
            return resposta
        return HTMLResponse(pagina(d, str(request.base_url)), headers=publico_versoes.SEM_CACHE)

    @r.get("/p/{codigo}/satelite.webp")
    def satelite_publico(codigo: str, request: Request) -> Response:
        d = achar(request, codigo)
        img = _imagens_do_aceite(d).get("imagem")
        if not img:  # antes do aceite não há imagem da fazenda no link público
            raise HTTPException(404, "imagem só depois do aceite do dono")
        return FileResponse(img, media_type="image/webp", headers=publico_versoes.SEM_CACHE)

    @r.get("/cartao/{codigo}/{nome}")
    def cartao_rota(codigo: str, nome: str, request: Request) -> Response:
        tipo, _, ext = nome.partition(".")
        if ext not in CARTOES.get(tipo, {}):
            raise HTTPException(404, "cartão desconhecido (previa e retrato: .jpg ou .webp; adesivo: .png ou .webp)")
        f = cartao(achar(request, codigo), tipo, ext)
        return FileResponse(f, media_type=TIPO_IMAGEM[ext], headers=publico_versoes.SEM_CACHE)

    @r.get("/video/{nome}.mp4")
    def video_rota(nome: str, request: Request) -> Response:
        codigo, sufixo = (nome[:-5], "-720p") if nome.endswith("-720p") else (nome, "")
        f, meta = video(achar(request, codigo), sufixo)
        h = dict(publico_versoes.SEM_CACHE)
        if meta.get("aviso"):
            h["X-Raiz-Aviso"] = "sem voz"
        return FileResponse(f, media_type="video/mp4", headers=h)

    return r
