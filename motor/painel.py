"""
Raíz: painel do motor no README da pasta motor/ (estado, municípios feitos/total, o que falta, última atualização e
versão do motor), gerado do estados.json publicado no Release `dados`.

Uso:
  python motor/painel.py                  lê o estados.json publicado e atualiza motor/README.md
  python motor/painel.py estados.json     a partir de um arquivo local
O GitHub Actions atualiza sozinho depois de cada publicação (publicar_dados.py --subir), direto no branch principal,
mexendo só no trecho entre as marcas <!-- painel:inicio --> e <!-- painel:fim -->.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raiz_situacao as S  # noqa: E402

INICIO = "<!-- painel:inicio -->"
FIM = "<!-- painel:fim -->"
README = Path(__file__).resolve().parent / "README.md"


def _n(x: int) -> str:
    return f"{x:,}".replace(",", ".")


def quando(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        t = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    try:
        from zoneinfo import ZoneInfo
        t = t.astimezone(ZoneInfo("America/Sao_Paulo"))
    except Exception:
        t = t.astimezone(dt.timezone(dt.timedelta(hours=-3)))
    return t.strftime("%d/%m/%Y %H:%M")


def faltam(e: dict, uf: str) -> tuple[dict, bool]:
    """O que falta no estado. Entrada antiga (publicada antes da automação) não diz da APP: devolve conferir=True."""
    if "faltam" in e:
        return e["faltam"], False
    t, n = e.get("tabelas", {}), e.get("municipios", 0)
    f = {}
    total = e.get("total_ibge") or S.TOTAL_IBGE[uf]
    if total > n:
        f["imoveis"] = total - n
    for k in S.OBRIGATORIAS:
        if t.get(k, 0) < n:
            f[k] = n - t.get(k, 0)
    return f, True


def linha(uf: str, e: dict | None) -> str:
    nome = f"{uf} {S.NOME_UF[uf]}"
    total = S.TOTAL_IBGE[uf]
    if not e:
        return f"| {nome} | 0/{total} | não começou | — | — |"
    f, conferir = faltam(e, uf)
    feitos = e.get("municipios", 0) + e.get("sem_imoveis", 0)
    if f:
        sit = "falta " + ", ".join(f"{S.NOME_TABELA.get(k, k)} {_n(v)}" for k, v in f.items())
    else:
        sit = "completo"
    if conferir:
        sit += " (APP a conferir na primeira rodada automática)"
    m = e.get("motor") or {}
    fatias = m.get("fatias") or {}
    rodadas = [m.get("rodada") or {}] + [f.get("rodada") or {} for f in fatias.values()]
    if any(r.get("falhou_fontes") for r in rodadas):
        if sit == "completo":
            sit = "acervo completo; última coleta incompleta"
        sit += "; falha nas fontes obrigatórias"
    erros = sum(int(f.get("erros") or 0) for f in fatias.values()) if fatias else len(e.get("erros") or [])
    if erros:
        sit += f"; {erros} erro(s) na última rodada"
    if S.n_fatias(uf) > 1:
        sit += f" ({S.n_fatias(uf)} fatias em jobs separados)"
    if m.get("commit"):
        motor = m["commit"][:7]
        url = (m.get("rodada") or {}).get("url")
        motor = f"[{motor}]({url})" if url else motor
        if m.get("legado"):
            motor += " (parte manual)"
    else:
        motor = "manual"
    return f"| {nome} | {_n(feitos)}/{_n(total)} | {sit} | {quando(e.get('atualizado_em'))} | {motor} |"


def tabela(manifesto: dict) -> str:
    est = manifesto.get("estados", {})
    feitos = sum(e.get("municipios", 0) + e.get("sem_imoveis", 0) for e in est.values())
    completos = sum(1 for uf, e in est.items() if not faltam(e, uf)[0] and "faltam" in e)
    linhas = [
        INICIO,
        f"Gerado do `estados.json` de {quando(manifesto.get('gerado_em'))} (horário de Brasília). "
        f"Brasil: {_n(feitos)} de {_n(sum(S.TOTAL_IBGE.values()))} municípios com o funil pronto; "
        f"{completos} de {len(S.TOTAL_IBGE)} estados completos.",
        "",
        "| Estado | Municípios feitos/total | Situação | Última atualização | Motor |",
        "|---|---|---|---|---|",
    ]
    linhas += [linha(uf, est.get(uf)) for uf in S.ORDEM]
    linhas.append(FIM)
    return "\n".join(linhas)


def atualizar_texto(texto: str, manifesto: dict) -> str:
    novo = tabela(manifesto)
    if INICIO in texto and FIM in texto:
        a, resto = texto.split(INICIO, 1)
        _, b = resto.split(FIM, 1)
        return a + novo + b
    return texto.rstrip() + "\n\n## Painel\n\n" + novo + "\n"


def _gh(*args, entrada: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, input=entrada)


def atualizar_no_github(manifesto: dict, caminho: str = "motor/README.md", branch: str | None = None) -> bool:
    """Regrava o painel no README do branch principal pela API (sem clonar nem dar push). Se alguém mexeu no arquivo no
    meio, a API recusa (o sha não confere) e ele lê de novo."""
    repo = S.REPO
    branch = branch or os.environ.get("RAIZ_BRANCH_PAINEL") or _gh("api", f"repos/{repo}", "--jq", ".default_branch").stdout.strip() or "main"
    for _ in range(4):
        r = _gh("api", f"repos/{repo}/contents/{caminho}?ref={branch}")
        if r.returncode:
            print(f"painel: não achei {caminho} no branch {branch}; não atualizo", flush=True)
            return False
        j = json.loads(r.stdout)
        texto = base64.b64decode(j["content"]).decode("utf-8")
        novo = atualizar_texto(texto, manifesto)
        if novo == texto:
            return True
        corpo = {"message": "Painel do motor atualizado pelo GitHub Actions",
                 "content": base64.b64encode(novo.encode("utf-8")).decode(), "sha": j["sha"], "branch": branch}
        r = _gh("api", "-X", "PUT", f"repos/{repo}/contents/{caminho}", "--input", "-", entrada=json.dumps(corpo))
        if r.returncode == 0:
            print(f"painel do motor atualizado em {branch}", flush=True)
            return True
        err = r.stderr + r.stdout
        if "409" in err or "does not match" in err:
            continue
        print(f"painel: a API recusou ({err.strip()[:200]})", flush=True)
        return False
    return False


def main() -> None:
    if len(sys.argv) > 1:
        manifesto = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        manifesto = S.ler_manifesto()
    README.write_text(atualizar_texto(README.read_text(encoding="utf-8"), manifesto), encoding="utf-8")
    print(f"painel atualizado em {README}")


if __name__ == "__main__":
    main()
