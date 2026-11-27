"""ThumbHash: uma miniatura de ~25 bytes que vira um borrão com as cores da foto enquanto ela carrega (E9, ficha leve).

Porte para Python de rgbaToThumbHash e thumbHashToRGBA da implementação de referência (thumbhash 0.1.1, MIT,
Copyright (c) 2023 Evan Wallace; ver NOTICE.md). O arredondamento é o do JavaScript (Math.round: metade para cima),
para o hash sair igual ao do pacote npm que o front usa para desenhar o borrão.

`de_imagem(img)` reduz a imagem para caber em 100 x 100 e devolve o hash em base64 (o que vai no JSON da ficha);
`para_data_url(hash)` desenha o borrão como PNG em data URL, para a página do servidor que abre sem JavaScript.
"""

from __future__ import annotations

import base64
import io
import math


def _round(x: float) -> int:
    """Math.round do JavaScript."""
    return math.floor(x + 0.5)


def rgba_para_hash(w: int, h: int, rgba: bytes | bytearray | list[int]) -> bytes:
    if w > 100 or h > 100:
        raise ValueError(f"{w}x{h} não cabe em 100x100")
    n = w * h
    avg_r = avg_g = avg_b = avg_a = 0.0
    for i in range(n):
        j = 4 * i
        alpha = rgba[j + 3] / 255
        avg_r += alpha / 255 * rgba[j]
        avg_g += alpha / 255 * rgba[j + 1]
        avg_b += alpha / 255 * rgba[j + 2]
        avg_a += alpha
    if avg_a:
        avg_r /= avg_a
        avg_g /= avg_a
        avg_b /= avg_a

    tem_alfa = avg_a < n
    l_limite = 5 if tem_alfa else 7
    lx = max(1, _round(l_limite * w / max(w, h)))
    ly = max(1, _round(l_limite * h / max(w, h)))
    lum, p, q, a = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n
    for i in range(n):
        j = 4 * i
        alpha = rgba[j + 3] / 255
        r = avg_r * (1 - alpha) + alpha / 255 * rgba[j]
        g = avg_g * (1 - alpha) + alpha / 255 * rgba[j + 1]
        b = avg_b * (1 - alpha) + alpha / 255 * rgba[j + 2]
        lum[i] = (r + g + b) / 3
        p[i] = (r + g) / 2 - b
        q[i] = r - g
        a[i] = alpha

    def canal(c: list[float], nx: int, ny: int) -> tuple[float, list[float], float]:
        dc, ac, escala = 0.0, [], 0.0
        for cy in range(ny):
            cx = 0
            while cx * ny < nx * (ny - cy):
                fx = [math.cos(math.pi / w * cx * (x + 0.5)) for x in range(w)]
                f = 0.0
                for y in range(h):
                    fy = math.cos(math.pi / h * cy * (y + 0.5))
                    base = y * w
                    for x in range(w):
                        f += c[x + base] * fx[x] * fy
                f /= w * h
                if cx or cy:
                    ac.append(f)
                    escala = max(escala, abs(f))
                else:
                    dc = f
                cx += 1
        if escala:
            ac = [0.5 + 0.5 / escala * v for v in ac]
        return dc, ac, escala

    l_dc, l_ac, l_escala = canal(lum, max(3, lx), max(3, ly))
    p_dc, p_ac, p_escala = canal(p, 3, 3)
    q_dc, q_ac, q_escala = canal(q, 3, 3)
    a_dc, a_ac, a_escala = canal(a, 5, 5) if tem_alfa else (0.0, [], 0.0)

    paisagem = w > h
    header24 = (
        _round(63 * l_dc)
        | (_round(31.5 + 31.5 * p_dc) << 6)
        | (_round(31.5 + 31.5 * q_dc) << 12)
        | (_round(31 * l_escala) << 18)
        | (int(tem_alfa) << 23)
    )
    header16 = (ly if paisagem else lx) | (_round(63 * p_escala) << 3) | (_round(63 * q_escala) << 9)
    header16 |= int(paisagem) << 15
    out = [header24 & 255, (header24 >> 8) & 255, header24 >> 16, header16 & 255, header16 >> 8]
    inicio = 6 if tem_alfa else 5
    if tem_alfa:
        out.append(_round(15 * a_dc) | (_round(15 * a_escala) << 4))
    fatores = [v for ac in ((l_ac, p_ac, q_ac, a_ac) if tem_alfa else (l_ac, p_ac, q_ac)) for v in ac]
    out += [0] * ((len(fatores) + 1) // 2)
    for k, v in enumerate(fatores):
        out[inicio + (k >> 1)] |= _round(15 * v) << ((k & 1) << 2)
    return bytes(out)


def proporcao(hash_: bytes) -> float:
    """Largura / altura aproximada da imagem original."""
    tem_alfa = hash_[2] & 0x80
    paisagem = hash_[4] & 0x80
    lx = (5 if tem_alfa else 7) if paisagem else hash_[3] & 7
    ly = hash_[3] & 7 if paisagem else (5 if tem_alfa else 7)
    return lx / ly


def hash_para_rgba(hash_: bytes) -> tuple[int, int, bytes]:
    """O borrão (até 32 x 32) em RGBA."""
    header24 = hash_[0] | (hash_[1] << 8) | (hash_[2] << 16)
    header16 = hash_[3] | (hash_[4] << 8)
    l_dc = (header24 & 63) / 63
    p_dc = ((header24 >> 6) & 63) / 31.5 - 1
    q_dc = ((header24 >> 12) & 63) / 31.5 - 1
    l_escala = ((header24 >> 18) & 31) / 31
    tem_alfa = header24 >> 23
    p_escala = ((header16 >> 3) & 63) / 63
    q_escala = ((header16 >> 9) & 63) / 63
    paisagem = header16 >> 15
    lx = max(3, (5 if tem_alfa else 7) if paisagem else header16 & 7)
    ly = max(3, header16 & 7 if paisagem else (5 if tem_alfa else 7))
    a_dc = (hash_[5] & 15) / 15 if tem_alfa else 1
    a_escala = (hash_[5] >> 4) / 15
    inicio = 6 if tem_alfa else 5
    indice = 0

    def canal(nx: int, ny: int, escala: float) -> list[float]:
        nonlocal indice
        ac = []
        for cy in range(ny):
            cx = 0 if cy else 1
            while cx * ny < nx * (ny - cy):
                ac.append((((hash_[inicio + (indice >> 1)] >> ((indice & 1) << 2)) & 15) / 7.5 - 1) * escala)
                indice += 1
                cx += 1
        return ac

    l_ac = canal(lx, ly, l_escala)
    p_ac = canal(3, 3, p_escala * 1.25)
    q_ac = canal(3, 3, q_escala * 1.25)
    a_ac = canal(5, 5, a_escala) if tem_alfa else []

    r_ = proporcao(hash_)
    w = _round(32 if r_ > 1 else 32 * r_)
    h = _round(32 / r_ if r_ > 1 else 32)
    out = bytearray(w * h * 4)
    nfx = max(lx, 5 if tem_alfa else 3)
    nfy = max(ly, 5 if tem_alfa else 3)
    i = 0
    for y in range(h):
        fy = [math.cos(math.pi / h * (y + 0.5) * cy) for cy in range(nfy)]
        for x in range(w):
            fx = [math.cos(math.pi / w * (x + 0.5) * cx) for cx in range(nfx)]
            lum, p, q, a = l_dc, p_dc, q_dc, a_dc
            j = 0
            for cy in range(ly):
                cx = 0 if cy else 1
                fy2 = fy[cy] * 2
                while cx * ly < lx * (ly - cy):
                    lum += l_ac[j] * fx[cx] * fy2
                    cx += 1
                    j += 1
            j = 0
            for cy in range(3):
                fy2 = fy[cy] * 2
                for cx in range(0 if cy else 1, 3 - cy):
                    f = fx[cx] * fy2
                    p += p_ac[j] * f
                    q += q_ac[j] * f
                    j += 1
            if tem_alfa:
                j = 0
                for cy in range(5):
                    fy2 = fy[cy] * 2
                    for cx in range(0 if cy else 1, 5 - cy):
                        a += a_ac[j] * fx[cx] * fy2
                        j += 1
            b = lum - 2 / 3 * p
            r = (3 * lum - b + q) / 2
            g = r - q
            out[i : i + 4] = bytes(int(max(0, 255 * min(1, v))) for v in (r, g, b, a))
            i += 4
    return w, h, bytes(out)


def de_imagem(img) -> str:
    """ThumbHash em base64 de uma imagem do Pillow (reduzida para caber em 100 x 100)."""
    im = img.convert("RGBA")
    im.thumbnail((100, 100))
    return base64.b64encode(rgba_para_hash(im.width, im.height, im.tobytes())).decode("ascii")


def para_data_url(hash_b64: str) -> str:
    """O borrão como PNG em data URL (cerca de 1 KB), para usar de fundo enquanto a foto chega."""
    from PIL import Image

    w, h, rgba = hash_para_rgba(base64.b64decode(hash_b64))
    b = io.BytesIO()
    Image.frombytes("RGBA", (w, h), rgba).save(b, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode("ascii")
