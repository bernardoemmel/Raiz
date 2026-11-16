"""Simulação para testes e demonstração sem chamar a API: cliente falso da Anthropic, certidão de exemplo em PDF e a
leitura que o modelo devolveria para ela. Tudo fictício: nenhum nome ou documento real (os CPFs de exemplo são
gerados na hora e saem mascarados).
"""

from __future__ import annotations

import copy
import io
import json
from dataclasses import dataclass, field
from types import SimpleNamespace


def cpf_ficticio(base9: str = "123456789") -> str:
    """CPF com dígitos verificadores válidos, montado na hora (nunca escrito em arquivo)."""
    d = [int(x) for x in base9]
    for n in (9, 10):
        soma = sum(d[i] * (n + 1 - i) for i in range(n))
        d.append((soma * 10 % 11) % 10)
    s = "".join(map(str, d))
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


# --- cliente falso --------------------------------------------------------------------------------------------------


@dataclass
class _Fluxo:
    resposta: object

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.resposta


@dataclass
class ClienteSimulado:
    """Imita anthropic.Anthropic: messages.stream e beta.messages.stream devolvem a próxima resposta da fila."""

    simulado = True

    respostas: list = field(default_factory=list)
    modelo: str = "claude-opus-5-5"
    chamadas: list = field(default_factory=list)

    def __post_init__(self):
        self.messages = SimpleNamespace(stream=self._stream)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self.files = SimpleNamespace(upload=lambda **k: SimpleNamespace(id="file_simulado"), delete=lambda i: None)

    def _stream(self, **kw):
        self.chamadas.append(kw)
        r = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, dict) and "stop_reason" in r and "dados" in r:
            stop, dados = r["stop_reason"], r["dados"]
        else:
            stop, dados = "end_turn", r
        texto = dados if isinstance(dados, str) else json.dumps(dados, ensure_ascii=False)
        msg = SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
            usage=SimpleNamespace(
                input_tokens=12000, output_tokens=1800, cache_read_input_tokens=1500, cache_creation_input_tokens=0
            ),
            stop_reason=stop,
            stop_details=SimpleNamespace(category="cyber") if stop == "refusal" else None,
            model=self.modelo,
        )
        return _Fluxo(msg)


# --- leitura de exemplo ---------------------------------------------------------------------------------------------


def leitura_exemplo(
    cns: str = "06.842-9",
    matricula: str = "5.178",
    area_valor: float = 290.0,
    area_unidade: str = "ha",
    municipio: str = "Nova Esperança do Piriá",
    uf: str = "PA",
    com_hipoteca_ativa: bool = False,
    encerrada: bool = False,
    data_emissao: str = "2026-11-01",
    com_nomes: bool = False,
) -> dict:
    """O JSON que o modelo devolveria. com_nomes=True simula um modelo que desobedece e escreve nome e CPF inteiro,
    para testar as trancas."""
    cpf = cpf_ficticio()
    p1_doc = cpf if com_nomes else "***.456.789-**"
    atos = [
        dict(
            numero="abertura",
            tipo="abertura",
            data="1998-05-10",
            natureza="abertura",
            afeta="propriedade",
            transmitentes=[],
            adquirentes=["P1"],
            fracao_pct=None,
            cancela=[],
            area_valor=None,
            area_unidade=None,
            matricula_destino=None,
            pagina=1,
            resumo="abertura da matrícula por título do INCRA em favor de P1",
        ),
        dict(
            numero="R-1",
            tipo="registro",
            data="2004-03-02",
            natureza="compra_e_venda",
            afeta="propriedade",
            transmitentes=["P1"],
            adquirentes=["P2", "P3"],
            fracao_pct=None,
            cancela=[],
            area_valor=None,
            area_unidade=None,
            matricula_destino=None,
            pagina=1,
            resumo=(
                "Fulano de Tal vende o imóvel a Beltrana Souza" if com_nomes else "P1 vende o imóvel todo a P2 e P3"
            ),
        ),
        dict(
            numero="R-2",
            tipo="registro",
            data="2010-08-20",
            natureza="hipoteca",
            afeta="onus",
            transmitentes=["P2"],
            adquirentes=["P4"],
            fracao_pct=None,
            cancela=[],
            area_valor=None,
            area_unidade=None,
            matricula_destino=None,
            pagina=2,
            resumo="hipoteca cedular em favor do Banco da Amazônia, devedor P2",
        ),
        dict(
            numero="AV-3",
            tipo="averbacao",
            data="2015-01-12",
            natureza="georreferenciamento",
            afeta="cadastro",
            transmitentes=[],
            adquirentes=[],
            fracao_pct=None,
            cancela=[],
            area_valor=area_valor,
            area_unidade=area_unidade,
            matricula_destino=None,
            pagina=2,
            resumo="averbação do georreferenciamento certificado pelo INCRA",
        ),
    ]
    if not com_hipoteca_ativa:
        atos.append(
            dict(
                numero="AV-4",
                tipo="averbacao",
                data="2016-06-30",
                natureza="cancelamento",
                afeta="onus",
                transmitentes=[],
                adquirentes=[],
                fracao_pct=None,
                cancela=["R-2"],
                area_valor=None,
                area_unidade=None,
                matricula_destino=None,
                pagina=2,
                resumo="cancelamento da hipoteca do R-2 por quitação",
            )
        )
    if encerrada:
        atos.append(
            dict(
                numero="AV-5",
                tipo="averbacao",
                data="2020-02-03",
                natureza="encerramento_matricula",
                afeta="encerramento",
                transmitentes=[],
                adquirentes=[],
                fracao_pct=None,
                cancela=[],
                area_valor=None,
                area_unidade=None,
                matricula_destino="9.001",
                pagina=3,
                resumo="matrícula encerrada; imóvel transportado para a matrícula 9.001",
            )
        )
    return copy.deepcopy(
        dict(
            documento=dict(
                tipo_documento="certidao_inteiro_teor",
                data_emissao=data_emissao,
                legivel=True,
                paginas_ilegiveis=[],
                observacoes=[],
            ),
            cartorio=dict(nome="Cartório do Registro de Imóveis de Exemplo", cns=cns, comarca="Exemplo", uf=uf),
            matricula=dict(
                numero=matricula,
                livro="2",
                cnm=None,
                data_abertura="1998-05-10",
                origem="titulo_publico",
                origem_referencia="título INCRA 123",
                situacao_declarada="encerrada" if encerrada else "ativa",
                matricula_destino="9.001" if encerrada else None,
            ),
            imovel=dict(
                municipio=municipio,
                uf=uf,
                area_valor=area_valor,
                area_unidade=area_unidade,
                area_original_valor=area_valor,
                area_original_unidade=area_unidade,
                codigo_incra_sncr=None,
                car=None,
                cib_nirf=None,
                georreferenciado=True,
                certificacao_sigef=None,
            ),
            partes=[
                dict(
                    rotulo="P1",
                    tipo="pessoa_fisica",
                    documento=p1_doc,
                    nome_instituicao="Fulano de Tal" if com_nomes else None,
                ),
                dict(rotulo="P2", tipo="pessoa_fisica", documento="***.111.222-**", nome_instituicao=None),
                dict(rotulo="P3", tipo="pessoa_fisica", documento=None, nome_instituicao=None),
                dict(
                    rotulo="P4",
                    tipo="instituicao_financeira",
                    documento="**.902.995/****-**",
                    nome_instituicao="Banco da Amazônia",
                ),
            ],
            atos=atos,
            proprietarios_atuais=[dict(rotulo="P2", fracao_pct=50.0), dict(rotulo="P3", fracao_pct=50.0)],
            confianca="alta",
        )
    )


def pdf_exemplo(texto: str = "CERTIDÃO DE INTEIRO TEOR (EXEMPLO FICTÍCIO)", paginas: int = 2) -> bytes:
    """PDF pequeno, só para o pipeline ter um arquivo (o cliente simulado não lê o conteúdo)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i in range(paginas):
        c.drawString(72, 780, f"{texto} - página {i + 1}")
        c.drawString(72, 760, "Matrícula 5.178 - Livro 2 - Registro de Imóveis de Exemplo")
        c.showPage()
    c.save()
    return buf.getvalue()


def edital_exemplo() -> dict:
    """O JSON que o modelo devolveria para um edital fictício de restauração."""
    req = [
        (
            "R1",
            "habilitacao_juridica",
            "Ato constitutivo da empresa ou associação proponente",
            True,
            True,
            "nenhum",
            None,
            None,
            "item 6.1, p. 8",
        ),
        (
            "R2",
            "regularidade_fiscal",
            "Certidões negativas de débitos federais, estaduais e municipais",
            True,
            True,
            "nenhum",
            None,
            None,
            "item 6.2, p. 9",
        ),
        ("R3", "imovel_e_area", "Imóveis com CAR ativo", False, True, "car_ativo", None, None, "item 4.1, p. 5"),
        (
            "R4",
            "imovel_e_area",
            "Sem embargo ambiental vigente",
            False,
            True,
            "sem_embargo",
            None,
            None,
            "item 4.2, p. 5",
        ),
        (
            "R5",
            "imovel_e_area",
            "Sem desmatamento depois de 22/07/2008",
            False,
            True,
            "sem_desmatamento_apos_2008",
            None,
            None,
            "item 4.3, p. 5",
        ),
        (
            "R6",
            "imovel_e_area",
            "Área somada do projeto de pelo menos 500 ha",
            False,
            True,
            "area_minima_ha",
            500,
            None,
            "item 4.4, p. 6",
        ),
        ("R7", "imovel_e_area", "Imóveis no bioma Amazônia", False, True, "bioma", None, "Amazônia", "item 3.1, p. 4"),
        (
            "R8",
            "imovel_e_area",
            "Matrícula regular ou posse comprovada",
            True,
            True,
            "matricula_regular",
            None,
            None,
            "item 4.5, p. 6",
        ),
        (
            "R9",
            "proposta_tecnica",
            "Plano de restauração com cronograma de 5 anos",
            True,
            True,
            "nenhum",
            None,
            None,
            "anexo II, p. 21",
        ),
    ]
    return dict(
        e_edital=True,
        orgao="Órgão Ambiental de Exemplo",
        numero="Chamada Pública 01/2026",
        modalidade="Chamamento público",
        objeto="Seleção de projetos de restauração florestal em imóveis rurais.",
        uf="PA",
        municipios=["Nova Esperança do Piriá"],
        area_total_ha=None,
        data_publicacao="2026-11-01",
        prazos=[
            dict(evento="Pedido de esclarecimento", data="2026-11-20", hora=None, referencia="item 9.1"),
            dict(evento="Entrega das propostas", data="2026-12-15", hora="17:00", referencia="item 10.1"),
        ],
        garantia=None,
        valor_estimado="R$ 10 milhões",
        criterios_julgamento=["técnica"],
        requisitos=[
            dict(
                id=a,
                grupo=b,
                descricao=c,
                documento=d,
                obrigatorio=e,
                criterio=f,
                valor_num=g,
                valor_texto=h,
                referencia=i,
            )
            for a, b, c, d, e, f, g, h, i in req
        ],
        observacoes=["Exemplo fictício para teste."],
        confianca="alta",
    )
