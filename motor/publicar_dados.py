"""Publica as saídas do motor no Release `dados` do GitHub, de onde o front baixa sozinho. Os dados grandes nunca vão para
o git: ficam só no Release.

Para cada estado monta:
  raiz_<UF>.tar.gz      todos os CSV do estado (imoveis_, direto_, filtros_, extras_, extras_direto_, mapbiomas_,
                        certidoes_, resumo_<UF>.csv e sem_imoveis_<UF>.csv), dentro da pasta <UF>/
  raiz_geo_<UF>.tar.gz  os polígonos dos imóveis (geo_<cod>.parquet, GeoParquet), dentro da pasta <UF>/
e a entrada do estado no estados.json: municípios feitos, total do IBGE, o que falta, se está completo, tamanho, versão
dos dados (sha256 do conteúdo) e versão do motor (commit e hash do código de cada tabela, lidos do saida/<UF>/rodada.json
que o rodar_estado.py grava). Só monta de novo o pacote que mudou.

Uso:
  python motor/publicar_dados.py <saida> <entrada> [UF ...] --subir
      monta em <entrada> e sobe direto no Release com o gh (GitHub Actions, com GH_TOKEN). Os pacotes de cada estado sobem
      sem esperar ninguém; o estados.json é relido do Release, recebe só as entradas destes estados e é regravado por
      último, dentro de uma trava (tag trava-publicar-dados criada pela API), para que dois jobs que terminam juntos não
      apaguem a entrada um do outro. Depois atualiza o painel em motor/README.md.
  python motor/publicar_dados.py <saida> <entrada> [UF ...]
      só monta em <entrada> (fluxo antigo pelo git: commit de <entrada> e o workflow publicar-dados.yml sobe). Pacote
      acima de 90 MB vai em partes (.part00, .part01...), porque o git não aceita arquivo acima de 100 MB.
  python motor/publicar_dados.py --indice <entrada>
      só o índice: mescla no estados.json publicado as entradas dos estados que têm pacote em <entrada> (usado pelo
      publicar-dados.yml depois de subir os pacotes).

Antes de montar, confere que nenhum CSV tem coluna de nome, CPF, CNPJ ou contato.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import raiz_situacao as S  # noqa: E402

REPO, TAG, BASE = S.REPO, S.TAG, S.BASE
PARTE = 90 * 1024 * 1024
TOTAL_IBGE, TABELAS = S.TOTAL_IBGE, S.TABELAS  # nomes antigos, mantidos para quem importa daqui
PROIBIDAS = re.compile(r"(^|_)(cpf|cnpj|nome|proprietario|titular|email|telefone)($|_)", re.I)
TRAVA = "trava-publicar-dados"


def manifesto_publicado() -> dict:
    return S.ler_manifesto()


def empacotar(uf: str, arquivos: list[Path]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for f in sorted(arquivos):
            info = tar.gettarinfo(str(f), arcname=f"{uf}/{f.name}")
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            with open(f, "rb") as fh:
                tar.addfile(info, fh)
    return buf.getvalue()


def gravar(destino: Path, nome: str, conteudo: bytes, partes: bool = True) -> list[Path]:
    if not partes or len(conteudo) <= PARTE:
        (destino / nome).write_bytes(conteudo)
        return [destino / nome]
    out = []
    for i in range(0, len(conteudo), PARTE):
        f = destino / f"{nome}.part{i // PARTE:02d}"
        f.write_bytes(conteudo[i:i + PARTE])
        out.append(f)
    return out


def versao(arquivos: list[Path]) -> str:
    h = __import__("hashlib").sha256()
    for f in sorted(arquivos):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def conferir_privacidade(csvs: list[Path]) -> None:
    for f in csvs:
        with open(f, encoding="utf-8", errors="replace") as fh:
            cab = fh.readline().strip().split(",")
        ruins = [c for c in cab if PROIBIDAS.search(c)]
        if ruins:
            raise SystemExit(f"{f.name} tem coluna proibida {ruins}: não publico.")


def estado_info(pasta: Path, uf: str) -> dict:
    return S.situacao(pasta, uf)


def motor_info(pasta: Path, antigo: dict) -> tuple[dict, list[dict]]:
    """Versão do motor que gerou os dados. Vem do rodada.json do rodar_estado.py; sem ele (publicação feita no
    computador), vale o código desta pasta, marcado com origem 'computador' (e sujo=True se tem mudança sem commit)."""
    f = pasta / "rodada.json"
    if f.exists():
        r = json.loads(f.read_text(encoding="utf-8"))
        rodada = {k: r.get(k) for k in ("url", "inicio", "fim", "continuacao", "parou_por_tempo", "progresso")}
        return ({"commit": r.get("commit"), "versao": r.get("versao_motor"), "etapas": r.get("etapas", {}),
                 "legado": r.get("legado", []), "rodada": rodada},
                [{**e, "mensagem": S.mascarar(e.get("mensagem", ""))} for e in r.get("erros", [])[:50]])
    commit, agora = S.commit_atual(), S.agora()
    velhas = (antigo.get("motor") or {}).get("etapas") or {}
    etapas = {t: (velhas[t] if (velhas.get(t) or {}).get("versao") == v else {"versao": v, "commit": commit, "desde": agora})
              for t, v in S.versoes().items()}
    return ({"commit": commit, "versao": S.hash_codigo(S.CODIGO_MOTOR), "etapas": etapas, "legado": [],
             "origem": "computador", "sujo": S.codigo_sujo()}, [])


def montar(saida: Path, destino: Path, ufs: list[str], publicado: dict, partes: bool) -> tuple[dict, list[Path]]:
    """Monta os pacotes que mudaram. Devolve as entradas novas do estados.json e os arquivos a subir."""
    from raiz.executor.armazem import ArmazemRelease
    from raiz.executor.publicacao_aberta import entrada_publica, projetar_csvs, projetar_geo

    privado = destino / "privado"
    privado.mkdir(parents=True, exist_ok=True)
    estados = publicado.get("estados", {})
    agora = S.agora()
    novas, arquivos = {}, []
    for uf in ufs:
        pasta = saida / uf
        csvs = sorted(f for f in pasta.glob("*.csv") if f.stat().st_size > 0)
        if not csvs:
            print(f"{uf}: nenhum CSV em {pasta}, nada a publicar")
            continue
        if os.environ.get("GITHUB_ACTIONS") and not (pasta / "rodada.json").exists():
            S.acao_github("warning", f"publicar {uf}", "sem rodada.json (o motor não chegou a rodar): não publico")
            continue
        antigo = estados.get(uf, {})
        if antigo.get("controle"):  # estado do executor: o pacote dele tem as tabelas do produto e o _versoes.json
            S.acao_github("warning", f"publicar {uf}", "o estado é do executor (raiz executor): publique com "
                          "`uv run raiz executor publicar --ufs " + uf + "`; não troco o pacote dele")
            continue
        conferir_privacidade(csvs)
        info = estado_info(pasta, uf)
        completos = {f.name: f.read_bytes() for f in csvs}
        # A cópia completa fica separada, para o publicador autenticado. Nunca subir esses arquivos ao aberto.
        gravar(privado, f"raiz_{uf}.tar.gz", empacotar(uf, csvs), partes=False)
        publicos = projetar_csvs(uf, completos)
        pacote = ArmazemRelease._tar(uf, publicos)
        v = __import__("hashlib").sha256(pacote).hexdigest()[:16]
        if antigo.get("versao") != v:
            arquivos += gravar(destino, f"raiz_{uf}.tar.gz", pacote, partes)
            info.update(tamanho=len(pacote), atualizado_em=agora)
            print(f"{uf}: raiz_{uf}.tar.gz {len(pacote) / 1e6:.1f} MB ({info['municipios']}/{info['total_ibge']} municípios)")
        else:
            info.update(tamanho=antigo.get("tamanho"), atualizado_em=antigo.get("atualizado_em"))
            print(f"{uf}: CSV sem mudança")
        info.update(versao=v, url=f"{BASE}/raiz_{uf}.tar.gz")
        geos = sorted(pasta.glob("geo_*.parquet"))
        if geos:
            gravar(privado, f"raiz_geo_{uf}.tar.gz", empacotar(uf, geos), partes=False)
            pg = ArmazemRelease._tar(uf, {f.name: projetar_geo(f.read_bytes()) for f in geos})
            vg = __import__("hashlib").sha256(pg).hexdigest()[:16]
            if (antigo.get("geo") or {}).get("versao") != vg:
                arquivos += gravar(destino, f"raiz_geo_{uf}.tar.gz", pg, partes)
                info["geo"] = {"versao": vg, "tamanho": len(pg), "url": f"{BASE}/raiz_geo_{uf}.tar.gz",
                               "municipios": len(geos), "escopo": "publico_basico"}
                print(f"{uf}: raiz_geo_{uf}.tar.gz {len(pg) / 1e6:.1f} MB")
            else:
                info["geo"] = antigo["geo"]
        info["motor"], info["erros"] = motor_info(pasta, antigo)
        novas[uf] = {**entrada_publica(info), "url": info["url"], **({"geo": info["geo"]} if info.get("geo") else {})}
    return novas, arquivos


def escrever_manifesto(destino: Path, estados: dict) -> Path:
    ordem = {u: i for i, u in enumerate(S.ORDEM)}
    estados = {uf: e for uf, e in estados.items() if e.get("escopo") == "publico_basico"}
    manifesto = {"gerado_em": S.agora(), "repo": REPO, "tag": TAG, "versao_publicacao": 1, "escopo": "publico_basico",
                 "estados": dict(sorted(estados.items(), key=lambda kv: ordem.get(kv[0], 99)))}
    f = destino / "estados.json"
    f.write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
    return f


# ---------------------------------------------------------------- GitHub (gh)

def gh(*args, entrada: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=entrada)
    if check and r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])} falhou: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def garantir_release() -> None:
    if gh("release", "view", TAG, "-R", REPO, check=False).returncode == 0:
        return
    gh("release", "create", TAG, "-R", REPO, "--prerelease", "--target", "main",
       "--title", "Dados do motor (atualizado sozinho)",
       "--notes", "Saídas do motor por estado, só de fontes públicas, sem nome, CPF ou CNPJ. O front baixa sozinho com "
                  "front/scripts/baixar-dados.mjs. Não editar à mão: quem publica é o workflow processar-estados.yml.",
       check=False)


def subir(arquivo: Path, tentativas: int = 4) -> None:
    from raiz.executor.publicacao_aberta import validar_asset_publico

    validar_asset_publico(arquivo.name, arquivo.read_bytes())
    for i in range(tentativas):
        r = gh("release", "upload", TAG, str(arquivo), "--clobber", "-R", REPO, check=False)
        if r.returncode == 0:
            print(f"subiu {arquivo.name} ({arquivo.stat().st_size / 1e6:.1f} MB)", flush=True)
            return
        print(f"subir {arquivo.name}: tentativa {i + 1} falhou ({r.stderr.strip()[:200]})", flush=True)
        time.sleep(15 * 2 ** i)
    raise RuntimeError(f"não consegui subir {arquivo.name}")


@contextlib.contextmanager
def trava(velha_s: int = 600):
    """Só um job por vez relê e regrava o estados.json. A trava é a tag trava-publicar-dados: criar uma referência que já
    existe dá erro na API, então só um consegue. Quem espera mais de 10 min considera a trava abandonada (job que caiu) e
    a apaga; a regravação dura segundos."""
    sha = os.environ.get("GITHUB_SHA") or gh("api", f"repos/{REPO}/commits/HEAD", "--jq", ".sha", check=False).stdout.strip()
    t0, pegou = time.time(), False
    while sha:
        r = gh("api", "-X", "POST", f"repos/{REPO}/git/refs", "-f", f"ref=refs/tags/{TRAVA}", "-f", f"sha={sha}", check=False)
        if r.returncode == 0:
            pegou = True
            break
        err = (r.stderr + r.stdout)
        if "already exists" in err or "HTTP 422" in err:
            if time.time() - t0 > velha_s:
                print("trava abandonada há mais de 10 min: apago e pego", flush=True)
                gh("api", "-X", "DELETE", f"repos/{REPO}/git/refs/tags/{TRAVA}", check=False)
                t0 = time.time()
                continue
            time.sleep(random.uniform(5, 15))
            continue
        S.acao_github("warning", "trava do estados.json", f"não consegui criar a trava ({err.strip()[:200]}); "
                      "publico sem ela e confiro depois")
        break
    try:
        yield
    finally:
        if pegou:
            gh("api", "-X", "DELETE", f"repos/{REPO}/git/refs/tags/{TRAVA}", check=False)


def mesclar_indice(novas: dict, destino: Path) -> dict:
    """Relê o estados.json publicado, troca só as entradas destes estados, sobe e confere se ficou. Dentro da trava."""
    if not novas:
        return {}
    for tentativa in range(3):
        with trava():
            atual = S.ler_manifesto()
            estados = dict(atual.get("estados", {}))
            estados.update(novas)
            f = escrever_manifesto(destino, estados)
            subir(f)
            manifesto = json.loads(f.read_text(encoding="utf-8"))
            try:
                import painel
                painel.atualizar_no_github(manifesto)
            except Exception as ex:
                S.acao_github("warning", "painel do motor", f"não atualizei o README do motor: {ex}")
        conferido = S.ler_manifesto().get("estados", {})
        faltou = [uf for uf, e in novas.items() if (conferido.get(uf) or {}).get("versao") != e.get("versao")
                  or (conferido.get(uf) or {}).get("motor") != e.get("motor")]
        if not faltou:
            print(f"estados.json publicado ({', '.join(novas)})")
            return manifesto
        print(f"estados.json sem a entrada de {faltou} (outro job regravou junto); refaço", flush=True)
        time.sleep(random.uniform(5, 20))
    raise RuntimeError("não consegui gravar o estados.json com as entradas deste job")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if "--indice" in flags:
        raise SystemExit("Publicação isolada do índice foi desativada. Use --subir ou raiz.executor.publicar_entrada.")
    if len(args) < 2:
        raise SystemExit(__doc__)
    saida, destino = Path(args[0]), Path(args[1])
    destino.mkdir(parents=True, exist_ok=True)
    ufs = [u.upper() for u in args[2:]] or sorted(p.name for p in saida.iterdir() if p.is_dir() and p.name in S.TOTAL_IBGE)
    subir_agora = "--subir" in flags
    if subir_agora:
        from raiz.executor.publicar_entrada import publicar_pasta

        publicar_pasta(saida, ufs)
        return
    publicado = S.ler_manifesto()
    novas, arquivos = montar(saida, destino, ufs, publicado, partes=not subir_agora)
    if not novas:
        print("nada a publicar")
        return
    if subir_agora:
        for f in arquivos:  # pacotes primeiro (cada estado tem os seus nomes, sem disputa); o índice por último
            subir(f)
        mesclar_indice(novas, destino)
        return
    estados = dict(publicado.get("estados", {}))
    estados.update(novas)
    escrever_manifesto(destino, estados)
    print("estados.json pronto em", destino)


if __name__ == "__main__":
    main()
