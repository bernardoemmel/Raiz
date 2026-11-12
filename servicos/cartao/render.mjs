// Cartão, adesivo e quadros do vídeo da fazenda com o Takumi (MIT ou Apache-2.0), em JPEG, PNG ou WebP, chamado pelo
// back-end da Raíz:
//   node render.mjs <pedido.json> <saida>
// O pedido traz só o que pode ir a público: município, UF, hectares, selo e código curto (e, depois do aceite do
// dono, as imagens de satélite). Nunca nome, CPF, código do CAR ou polígono antes do aceite.
import { readFile, writeFile } from "node:fs/promises";
import { Renderer } from "@takumi-rs/core";

const SELOS = {
  bronze: { cor: "#a8672f", texto: "Selo bronze · achada no CAR" },
  prata: { cor: "#7f8b93", texto: "Selo prata · título conferido" },
  ouro: { cor: "#c9a227", texto: "Selo ouro · dono aceitou" },
};
const VERDE = "#1d5a39";
const CREME = "#f4f1ea";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function selo(p, escala = 1) {
  const s = SELOS[p.selo] ?? SELOS.bronze;
  return `<div style="display:flex;align-items:center;gap:${12 * escala}px;font-size:${30 * escala}px;color:${VERDE}">
    <div style="width:${34 * escala}px;height:${34 * escala}px;border-radius:50%;background:${s.cor};border:${4 * escala}px solid white"></div>
    <div>${esc(s.texto)}</div></div>`;
}

function cartao(p, largura, altura) {
  const retrato = altura > largura;
  const k = retrato ? 1.35 : 1;
  const fundo = p.imagem
    ? `<img src="satelite" style="position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover" />
       <div style="position:absolute;left:0;top:0;width:100%;height:100%;background:rgba(15,40,25,0.55)"></div>`
    : "";
  const cor = p.imagem ? "white" : VERDE;
  return `<div style="display:flex;position:relative;width:100%;height:100%;background:${CREME};font-family:Geist">
    ${fundo}
    <div style="display:flex;flex-direction:column;justify-content:space-between;width:100%;height:100%;padding:${64 * k}px;color:${cor}">
      <div style="display:flex;flex-direction:column;gap:${10 * k}px">
        <div style="font-size:${34 * k}px;opacity:0.85">${esc(p.municipio)} · ${esc(p.uf)}</div>
        <div style="font-size:${132 * k}px;font-weight:700;line-height:1">${esc(p.hectares)} ha</div>
        <div style="font-size:${40 * k}px">${esc(p.frase)}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:${18 * k}px">
        <div style="display:flex;background:white;border-radius:${40 * k}px;padding:${10 * k}px ${22 * k}px;align-self:flex-start">${selo(p, k)}</div>
        <div style="display:flex;justify-content:space-between;align-items:flex-end;font-size:${28 * k}px">
          <div>Código ${esc(p.codigo)}</div>
          <div style="font-weight:700;font-size:${44 * k}px">raíz</div>
        </div>
      </div>
    </div></div>`;
}

function adesivo(p, lado) {
  const s = SELOS[p.selo] ?? SELOS.bronze;
  return `<div style="display:flex;width:100%;height:100%;align-items:center;justify-content:center;font-family:Geist">
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;width:${lado - 24}px;height:${lado - 24}px;border-radius:50%;background:${CREME};border:${lado / 22}px solid ${s.cor};color:${VERDE};gap:6px">
      <div style="font-size:${lado / 16}px">${esc(p.municipio)}</div>
      <div style="font-size:${lado / 6}px;font-weight:700;line-height:1">${esc(p.hectares)} ha</div>
      <div style="font-size:${lado / 18}px">${esc(p.frase_curta)}</div>
      <div style="font-size:${lado / 20}px;margin-top:8px">${esc(p.codigo)} · raíz</div>
    </div></div>`;
}

function cenas(p) {
  const tela = (corpo) => `<div style="display:flex;flex-direction:column;justify-content:center;width:100%;height:100%;padding:8%;background:${CREME};color:${VERDE};font-family:Geist;gap:24px">${corpo}</div>`;
  const foto = (src, legenda) => `<div style="display:flex;position:relative;width:100%;height:100%;background:#000">
      <img src="${src}" style="position:absolute;left:0;top:0;width:100%;height:100%;object-fit:contain" />
      <div style="position:absolute;left:0;bottom:0;width:100%;display:flex;padding:5%;font-size:44px;color:white;background:rgba(0,0,0,0.45);font-family:Geist">${esc(legenda)}</div></div>`;
  const lista = [
    { node: tela(`<div style="font-size:52px">${esc(p.municipio)} · ${esc(p.uf)}</div><div style="font-size:140px;font-weight:700;line-height:1">${esc(p.hectares)} ha</div><div style="font-size:52px">${esc(p.frase)}</div>`), durationMs: 3000 },
  ];
  if (p.imagem_hoje) lista.push({ node: foto("hoje", "Hoje"), durationMs: 3000 });
  if (p.imagem_simulacao) lista.push({ node: foto("simulacao", "Simulação em 10 anos"), durationMs: 3500 });
  lista.push({ node: tela(`<div style="display:flex">${selo(p, 1.6)}</div><div style="font-size:56px">Código ${esc(p.codigo)}</div><div style="font-size:64px;font-weight:700">raíz</div>`), durationMs: 3000 });
  return lista;
}

async function imagens(p) {
  const out = [];
  for (const [src, chave] of [["satelite", "imagem"], ["hoje", "imagem_hoje"], ["simulacao", "imagem_simulacao"]]) {
    if (p[chave]) out.push({ src, data: await readFile(p[chave]) });
  }
  return out;
}

const [, , pedidoArq, saida] = process.argv;
const p = JSON.parse(await readFile(pedidoArq, "utf8"));
const r = new Renderer();
const images = await imagens(p);
let dado;
// formato: "jpeg" (padrão do cartão, é o que a prévia do WhatsApp lê), "png" (padrão do adesivo, transparente) ou
// "webp" (com perda no cartão, sem perda no adesivo, que guarda a transparência; é o que a ficha e o site usam)
if (p.tipo === "previa" || p.tipo === "retrato") {
  const [w, h] = p.tipo === "previa" ? [1200, 630] : [1080, 1350];
  const format = p.formato === "webp" ? "webp" : "jpeg";
  dado = await r.render(cartao(p, w, h), { width: w, height: h, format, quality: p.qualidade ?? 82, images });
} else if (p.tipo === "adesivo") {
  const lado = p.lado ?? 512;
  // adesivo é de cores chapadas: o WebP sem perda sai menor que o PNG e que o WebP com perda
  const opcoes = p.formato === "webp" ? { format: "webp", lossless: true } : { format: "png" };
  dado = await r.render(adesivo(p, lado), { width: lado, height: lado, ...opcoes, images });
} else if (p.tipo === "animacao") {
  dado = await r.renderAnimation({ scenes: cenas(p), width: p.largura, height: p.altura, fps: p.fps ?? 15, format: "apng", images });
} else {
  throw new Error(`tipo desconhecido: ${p.tipo}`);
}
await writeFile(saida, dado);
