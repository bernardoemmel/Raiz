"""Preserva e restaura bytes do executor no arquivo privado, sem validar produtos ou retratos.

O manifesto identifica apenas caminhos técnicos permitidos. Retratos são opacos:
um checkpoint íntegro não afirma que o conteúdo científico esteja válido.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from raiz import RAIZ_REPO
from raiz.executor import transferencia_privada as T

FORMATO = 1
LOTE_BYTES = 256 * 1024 * 1024
_SHA = re.compile(r"[a-f0-9]{64}")
_UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
_CSV = set(
    "imoveis filtros direto mapbiomas extras extras_direto flag terra titulo regularizacao "
    "achados ficha rebanho desenvolvedor certidoes jurisdicional".split()
)


class CheckpointInvalido(RuntimeError):
    """Erro técnico sem conteúdo, identificadores pessoais ou URLs remotas."""


def _exigir(condicao, codigo="checkpoint_invalido"):
    if not condicao:
        raise CheckpointInvalido(codigo)


def _hash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as entrada:
        for bloco in iter(lambda: entrada.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _ler_json(p: Path):
    def unico(pares):
        d = {}
        for k, v in pares:
            _exigir(k not in d)
            d[k] = v
        return d

    return json.loads(p.read_bytes(), object_pairs_hook=unico)


def _unidade(unidade: str) -> tuple[str, str]:
    _exigir(
        isinstance(unidade, str) and re.fullmatch(r"[A-Z]{2}(?:-[1-9][0-9]{0,3})?", unidade),
        "checkpoint_unidade_invalida",
    )
    uf = unidade.split("-")[0]
    _exigir(uf in _UFS, "checkpoint_unidade_invalida")
    return unidade, uf


def _raizes(raizes):
    if raizes is None:
        from raiz.executor.armazem import do_config
        from raiz.funil.rodar import dir_trabalho

        configurado = do_config()
        local = getattr(configurado, "local", configurado)
        raizes = {
            "espelho": local.raiz,
            "motor": dir_trabalho(),
            # Mesma regra de pasta_padrao(), sem importar retratos ou sua validação.
            "retratos": Path(os.environ.get("RAIZ_HISTORICO_DIR", RAIZ_REPO / "dados/historico_aprendizado")),
        }
    _exigir(set(raizes) == {"espelho", "motor", "retratos"}, "checkpoint_raizes_invalidas")
    return {k: Path(v).absolute() for k, v in raizes.items()}


def _permitido(raiz: str, relativo: str, uf: str, unidade: str) -> bool:
    p = PurePosixPath(relativo)
    if p.is_absolute() or p.as_posix() != relativo or ".." in p.parts or "\\" in relativo:
        return False
    if raiz in {"motor", "espelho"} and relativo.endswith(".meta.json"):
        if relativo.removesuffix(".meta.json").endswith(".meta.json"):
            return False
        return _permitido(raiz, relativo.removesuffix(".meta.json"), uf, unidade)
    if raiz in {"motor", "espelho"} and len(p.parts) == 3 and p.parts[:2] == ("saida", uf):
        nome = p.name
        if nome in {f"resumo_{uf}.csv", f"sem_imoveis_{uf}.csv", "rodada.json", "_versoes.json"}:
            return True
        if m := re.fullmatch(r"([a-z_]+)_([0-9]{7})\.(csv|parquet|pmtiles)", nome):
            return (m[1] in _CSV and m[3] == "csv") or (m[1] in {"geo", "camadas"} and m[3] in {"parquet", "pmtiles"})
    if raiz == "espelho":
        return bool(re.fullmatch(rf"marcas/{uf}/[0-9]{{7}}\.json", relativo) or relativo == f"estado/{uf}.json")
    if raiz == "retratos":
        return bool(re.fullmatch(rf"{uf}/[0-9]{{7}}/[a-f0-9]{{64}}\.json\.gz", relativo))
    if raiz == "motor":
        padrao = rf"\.executor/processamento/{uf}/{re.escape(unidade)}/[A-Za-z0-9_-]{{1,100}}/[0-9]{{7}}\.json"
        return bool(re.fullmatch(padrao, relativo))
    return False


def _caminho(raiz: Path, relativo: str) -> Path:
    _exigir(not any(p.is_symlink() for p in (raiz, *raiz.parents)), "checkpoint_link_recusado")
    p = raiz
    for parte in PurePosixPath(relativo).parts:
        p /= parte
        _exigir(not p.is_symlink(), "checkpoint_link_recusado")
    _exigir(p.resolve().is_relative_to(raiz.resolve()), "checkpoint_caminho_invalido")
    return p


def _fontes(raizes, uf, unidade):
    bases = {
        "espelho": (f"saida/{uf}", f"marcas/{uf}", f"estado/{uf}.json"),
        "motor": (f"saida/{uf}", f".executor/processamento/{uf}/{unidade}"),
        "retratos": (uf,),
    }
    for nome, raiz in sorted(raizes.items()):
        vistos = set()
        for base in bases[nome]:
            p = _caminho(raiz, base)
            candidatos = p.rglob("*") if p.is_dir() else (p,)
            for f in sorted(candidatos):
                rel = f.relative_to(raiz).as_posix()
                if rel in vistos or rel.endswith(".meta.json") or not _permitido(nome, rel, uf, unidade):
                    continue
                vistos.add(rel)
                f = _caminho(raiz, rel)
                if not f.exists():
                    continue
                _exigir(f.is_file(), "checkpoint_arquivo_especial")
                yield nome, rel, f


def _capturar(fonte: Path, destino: Path):
    """Copie uma versão estável do arquivo e do sidecar original, sem reinterpretá-los."""
    meta = fonte.with_name(fonte.name + ".meta.json")
    for _ in range(3):
        _exigir(not fonte.is_symlink() and not meta.is_symlink(), "checkpoint_link_recusado")
        antes = fonte.stat()
        bruto_meta = meta.read_bytes() if meta.exists() else None
        with fonte.open("rb") as entrada, destino.open("wb") as saida:
            shutil.copyfileobj(entrada, saida, 1024 * 1024)
        depois = fonte.stat()
        nova_meta = meta.read_bytes() if meta.exists() else None
        if (antes.st_ino, antes.st_size, antes.st_mtime_ns, antes.st_ctime_ns) != (
            depois.st_ino,
            depois.st_size,
            depois.st_mtime_ns,
            depois.st_ctime_ns,
        ) or bruto_meta != nova_meta:
            continue
        digest = _hash(destino)
        if bruto_meta is not None:
            m = json.loads(bruto_meta)
            _exigir(isinstance(m, dict), "checkpoint_meta_invalida")
            if m.get("sha256") is not None and m["sha256"] != digest:
                continue
        return digest, bruto_meta
    raise CheckpointInvalido("checkpoint_fonte_instavel_ou_meta_divergente")


def _enviar_verificado(nome, caminho, arm, trabalho, *, imutavel=True):
    T.enviar_arquivo(nome, caminho, imutavel=imutavel, arm=arm)
    volta = trabalho / "conferencia"
    T.baixar_arquivo(nome, volta, arm=arm)
    _exigir(
        volta.stat().st_size == caminho.stat().st_size and _hash(volta) == _hash(caminho),
        "checkpoint_remoto_divergente",
    )
    volta.unlink()


def _salvar(unidade, arm, raizes):
    unidade, uf = _unidade(unidade)
    arm = arm or T.arquivo_privado()
    _exigir(getattr(arm, "privado", False), "checkpoint_destino_nao_privado")
    arm._exigir_privado()
    raizes = _raizes(raizes)
    _exigir(LOTE_BYTES >= 20480, "checkpoint_limite_invalido")
    run, tentativa = os.environ.get("GITHUB_RUN_ID", "local"), os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    _exigir(re.fullmatch(r"local|[0-9]{1,20}", run) and re.fullmatch(r"[0-9]{1,6}", tentativa))
    with tempfile.TemporaryDirectory(prefix="raiz-checkpoint-") as td:
        trabalho = Path(td)
        arquivos, pacotes, pendentes, tamanho_lote, gasto_lote = [], [], [], 0, 0

        def fechar_lote():
            nonlocal tamanho_lote, gasto_lote
            if not pendentes:
                return
            pacote = trabalho / "lote.tar.gz"
            with pacote.open("wb") as arq, gzip.GzipFile(fileobj=arq, mode="wb", mtime=0, filename="") as gz:
                with tarfile.open(fileobj=gz, mode="w") as tar:
                    for parte, caminho in pendentes:
                        info = tarfile.TarInfo(parte["membro"])
                        info.size, info.mode = parte["bytes"], 0o600
                        with caminho.open("rb") as entrada:
                            tar.addfile(info, entrada)
            digest = _hash(pacote)
            nome = f"checkpoint-objeto-{digest}.tar.gz"
            _enviar_verificado(nome, pacote, arm, trabalho)
            pacotes.append({"nome": nome, "sha256": digest, "bytes": pacote.stat().st_size, "brutos": tamanho_lote})
            for parte, caminho in pendentes:
                parte["pacote"] = nome
                caminho.unlink()
            pendentes.clear()
            tamanho_lote = 0
            gasto_lote = 0

        def adicionar(nome, relativo, caminho, digest):
            nonlocal tamanho_lote, gasto_lote
            item = {"raiz": nome, "caminho": relativo, "sha256": digest, "bytes": caminho.stat().st_size, "partes": []}
            indice = len(arquivos)
            with caminho.open("rb") as entrada:
                restante = item["bytes"]
                while restante or not item["partes"]:
                    disponivel = ((LOTE_BYTES - 10240 - gasto_lote - 512) // 512) * 512
                    if disponivel <= 0:
                        fechar_lote()
                        disponivel = ((LOTE_BYTES - 10240 - 512) // 512) * 512
                    quantidade = min(restante, disponivel)
                    membro = f"blocos/{indice:08d}-{len(item['partes']):08d}"
                    bloco = trabalho / membro.replace("/", "-")
                    with bloco.open("wb") as saida:
                        falta = quantidade
                        while falta:
                            b = entrada.read(min(falta, 1024 * 1024))
                            _exigir(bool(b), "checkpoint_captura_truncada")
                            saida.write(b)
                            falta -= len(b)
                    parte = {"membro": membro, "bytes": quantidade, "sha256": _hash(bloco)}
                    item["partes"].append(parte)
                    pendentes.append((parte, bloco))
                    tamanho_lote += quantidade
                    gasto_lote += 512 + ((quantidade + 511) // 512) * 512
                    restante -= quantidade
            arquivos.append(item)

        for nome, relativo, fonte in _fontes(raizes, uf, unidade):
            copia = trabalho / "captura"
            digest, meta = _capturar(fonte, copia)
            adicionar(nome, relativo, copia, digest)
            if meta is not None:
                _exigir(_permitido(nome, relativo + ".meta.json", uf, unidade))
                copia.write_bytes(meta)
                adicionar(nome, relativo + ".meta.json", copia, hashlib.sha256(meta).hexdigest())
            copia.unlink()
        fechar_lote()
        if not arquivos:
            return {"situacao": "sem_arquivos", "unidade": unidade, "arquivos": 0, "pacotes": 0}
        manifesto = {
            "formato": FORMATO,
            "unidade": unidade,
            "uf": uf,
            "run": run,
            "attempt": tentativa,
            "criado_em": dt.datetime.now(dt.UTC).isoformat(),
            "retratos": "opacos_sem_validacao",
            "arquivos": arquivos,
            "pacotes": pacotes,
        }
        m = trabalho / "manifesto.json"
        m.write_bytes(_json(manifesto))
        sha = _hash(m)
        nome = f"checkpoint-{unidade}-{run}-{tentativa}-{sha}.json"
        _enviar_verificado(nome, m, arm, trabalho)
        ponteiro = {
            "formato": FORMATO,
            "unidade": unidade,
            "uf": uf,
            "run": run,
            "attempt": tentativa,
            "manifesto": nome,
            "sha256": sha,
        }
        latest = f"checkpoint-{unidade}-latest.json"
        with arm._trava(f"trava-checkpoint-{unidade}", 1800):
            anterior = trabalho / "anterior.json"
            if T.baixar_arquivo(latest, anterior, opcional=True, arm=arm):
                a = _ler_json(anterior)
                if (
                    str(a.get("run", "")).isdigit()
                    and run.isdigit()
                    and (int(a["run"]), int(a["attempt"])) > (int(run), int(tentativa))
                ):
                    return {
                        "situacao": "preservado_sem_mudar_latest",
                        "unidade": unidade,
                        "arquivos": len(arquivos),
                        "pacotes": len(pacotes),
                        "manifesto_sha256": sha,
                    }
            p = trabalho / "latest.json"
            p.write_bytes(_json(ponteiro))
            _enviar_verificado(latest, p, arm, trabalho, imutavel=False)
        return {
            "situacao": "preservado",
            "unidade": unidade,
            "arquivos": len(arquivos),
            "pacotes": len(pacotes),
            "manifesto_sha256": sha,
        }


def _restaurar(unidade, arm, raizes):
    unidade, uf = _unidade(unidade)
    arm = arm or T.arquivo_privado()
    _exigir(getattr(arm, "privado", False), "checkpoint_destino_nao_privado")
    arm._exigir_privado()
    raizes = _raizes(raizes)
    with tempfile.TemporaryDirectory(prefix="raiz-retomar-") as td:
        trabalho = Path(td)
        p = trabalho / "latest.json"
        if not T.baixar_arquivo(f"checkpoint-{unidade}-latest.json", p, opcional=True, arm=arm):
            return {"situacao": "ausente", "unidade": unidade, "arquivos": 0}
        ponteiro = _ler_json(p)
        _exigir(ponteiro["formato"] == FORMATO and ponteiro["unidade"] == unidade and ponteiro["uf"] == uf)
        sha = ponteiro["sha256"]
        _exigir(isinstance(sha, str) and _SHA.fullmatch(sha))
        _exigir(ponteiro["manifesto"] == f"checkpoint-{unidade}-{ponteiro['run']}-{ponteiro['attempt']}-{sha}.json")
        m = trabalho / "manifesto.json"
        T.baixar_arquivo(ponteiro["manifesto"], m, arm=arm)
        _exigir(_hash(m) == sha, "checkpoint_manifesto_corrompido")
        manifesto = _ler_json(m)
        _exigir(all(manifesto[k] == ponteiro[k] for k in ("formato", "unidade", "uf", "run", "attempt")))
        _exigir(manifesto["retratos"] == "opacos_sem_validacao")
        arquivos, pacotes = manifesto["arquivos"], manifesto["pacotes"]
        _exigir(isinstance(arquivos, list) and arquivos and isinstance(pacotes, list) and pacotes)
        destinos, membros = set(), {}
        for item in arquivos:
            nome, rel = item["raiz"], item["caminho"]
            _exigir(nome in raizes and _permitido(nome, rel, uf, unidade), "checkpoint_caminho_recusado")
            _caminho(raizes[nome], rel)
            _exigir((nome, rel) not in destinos, "checkpoint_destino_duplicado")
            destinos.add((nome, rel))
            _exigir(type(item["bytes"]) is int and item["bytes"] >= 0 and _SHA.fullmatch(item["sha256"]))
            _exigir(isinstance(item["partes"], list) and item["partes"])
            for parte in item["partes"]:
                chave = (parte["pacote"], parte["membro"])
                _exigir(chave not in membros and re.fullmatch(r"blocos/[0-9]{8}-[0-9]{8}", parte["membro"]))
                _exigir(
                    type(parte["bytes"]) is int
                    and 0 <= parte["bytes"] <= LOTE_BYTES
                    and _SHA.fullmatch(parte["sha256"])
                )
                membros[chave] = parte
            _exigir(sum(x["bytes"] for x in item["partes"]) == item["bytes"])
        vistos, nomes_pacotes = set(), set()
        blocos = trabalho / "partes"
        for numero, pacote in enumerate(pacotes):
            nome = pacote["nome"]
            _exigir(_SHA.fullmatch(pacote["sha256"]) and nome == f"checkpoint-objeto-{pacote['sha256']}.tar.gz")
            _exigir(nome not in nomes_pacotes and 0 <= pacote["brutos"] <= LOTE_BYTES)
            nomes_pacotes.add(nome)
            arq = trabalho / "pacote.tar.gz"
            T.baixar_arquivo(nome, arq, arm=arm)
            _exigir(
                arq.stat().st_size == pacote["bytes"] <= T.MAX_ASSET_BYTES and _hash(arq) == pacote["sha256"],
                "checkpoint_pacote_corrompido",
            )
            with tarfile.open(arq, "r:gz") as tar:
                brutos = 0
                for membro in tar:
                    chave = (nome, membro.name)
                    _exigir(membro.isfile() and chave in membros and chave not in vistos, "checkpoint_membro_recusado")
                    parte = membros[chave]
                    _exigir(membro.size == parte["bytes"])
                    vistos.add(chave)
                    brutos += membro.size
                _exigir(brutos == pacote["brutos"])
            destino = blocos / str(numero)
            T.extrair(arq, destino)
            for chave, parte in membros.items():
                if chave[0] == nome:
                    fonte = destino / parte["membro"]
                    _exigir(_hash(fonte) == parte["sha256"], "checkpoint_parte_corrompida")
                    parte["local"] = fonte
        _exigir(vistos == set(membros), "checkpoint_parte_ausente")
        prontos = []
        for numero, item in enumerate(arquivos):
            copia = trabalho / f"arquivo-{numero}"
            with copia.open("wb") as saida:
                for parte in item["partes"]:
                    with parte["local"].open("rb") as entrada:
                        shutil.copyfileobj(entrada, saida, 1024 * 1024)
            _exigir(_hash(copia) == item["sha256"], "checkpoint_arquivo_corrompido")
            destino = _caminho(raizes[item["raiz"]], item["caminho"])
            if destino.exists():
                _exigir(destino.is_file() and _hash(destino) == item["sha256"], "checkpoint_conflito_local")
            else:
                prontos.append((copia, destino, item))
        # Todos os pacotes, destinos e conflitos foram verificados antes da primeira escrita.
        for copia, destino, item in prontos:
            _caminho(raizes[item["raiz"]], item["caminho"])
            destino.parent.mkdir(parents=True, exist_ok=True)
            # Link exclusivo impede sobrescrever uma chegada concorrente; o staging fica no mesmo volume.
            with tempfile.NamedTemporaryFile(dir=destino.parent, prefix=".checkpoint-", delete=False) as tmp:
                temporario = Path(tmp.name)
                with copia.open("rb") as entrada:
                    shutil.copyfileobj(entrada, tmp, 1024 * 1024)
            try:
                os.link(temporario, destino)
            finally:
                temporario.unlink()
        return {
            "situacao": "restaurado",
            "unidade": unidade,
            "arquivos": len(arquivos),
            "gravados": len(prontos),
            "manifesto_sha256": sha,
        }


def salvar(unidade: str, *, arm=None, raizes=None) -> dict:
    """Preserva bytes e metadados originais; somente o transporte privado é necessário."""
    try:
        return _salvar(unidade, arm, raizes)
    except CheckpointInvalido:
        raise
    except Exception:
        raise CheckpointInvalido("checkpoint_preservacao_falhou") from None


def restaurar(unidade: str, *, arm=None, raizes=None) -> dict:
    """Ausência é normal; corrupção, destino público e conflito local falham sem sobrescrever."""
    try:
        return _restaurar(unidade, arm, raizes)
    except CheckpointInvalido:
        raise
    except Exception:
        raise CheckpointInvalido("checkpoint_restauracao_falhou") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acao", choices=("salvar", "restaurar"))
    parser.add_argument("--unidade", required=True)
    parser.add_argument(
        "--repositorio", type=Path, help="Checkout original quando o preservador roda em outro checkout"
    )
    for nome in ("espelho", "motor", "retratos"):
        parser.add_argument("--" + nome, type=Path, help="Raiz local explícita para " + nome)
    args = parser.parse_args()
    try:
        roots = None
        if args.repositorio is not None or any(getattr(args, n) is not None for n in ("espelho", "motor", "retratos")):
            from raiz.config import config

            repo = (args.repositorio or RAIZ_REPO).absolute()
            cfg = config()
            espelho = Path(cfg.armazem_espelho_dir) if cfg.armazem_espelho_dir else repo / "dados/armazem_local"
            roots = {
                "espelho": args.espelho or espelho.with_name(espelho.name + "_privado"),
                "motor": args.motor or Path(cfg.motor_dir_trabalho or repo / "motor"),
                "retratos": args.retratos
                or Path(os.environ.get("RAIZ_HISTORICO_DIR", repo / "dados/historico_aprendizado")),
            }
            roots = {n: p if p.is_absolute() else repo / p for n, p in roots.items()}
        resultado = (salvar if args.acao == "salvar" else restaurar)(args.unidade, raizes=roots)
    except CheckpointInvalido as erro:
        print(json.dumps({"situacao": "erro", "codigo": str(erro)}))
        raise SystemExit(1) from None
    print(json.dumps(resultado, sort_keys=True))


if __name__ == "__main__":
    main()
