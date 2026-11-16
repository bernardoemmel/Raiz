# ruff: noqa: E501
"""Página humana que reutiliza a conta, contrato e cobranças existentes."""

import html
import secrets

from fastapi.responses import HTMLResponse


def pagina(premissas: dict) -> HTMLResponse:
    nonce = secrets.token_urlsafe(24)
    sinal = float(premissas["liberacao"]["sinal_rs"])
    minimo = float(premissas["recarga"]["minimo_rs"])
    conteudo = r"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Conta da empresa — Raíz</title>
<body><main><h1>Conta da empresa</h1>
<p>Uma pessoa da empresa confere e autoriza cada ação. O pagamento é feito no aplicativo do seu banco.</p>
<form id="login"><label>E-mail cadastrado <input id="email" type="email" required autocomplete="email"></label>
<button>Receber link de entrada</button></form><p id="aviso" role="status"></p>
<section id="conta" hidden><h2>Saldo e liberação</h2><p id="saldo"></p><p id="liberacao"></p>
<p>Saldo e sinal são separados. O detalhe exige sinal confirmado e contrato aceito.</p>
<section id="contrato"><h3>Contrato de não contornar</h3>
<p>Ao aceitar, a empresa se compromete a conduzir o contato e a negociação das fazendas apresentadas pela Raíz
pela própria Raíz, conforme os <a href="/v1/termos" target="_blank" rel="noopener">termos de uso</a>.</p>
<label><input id="aceito" type="checkbox"> Li e aceito o contrato em nome da empresa.</label>
<button id="aceitar" disabled>Aceitar contrato</button></section>
<p><button id="sinal">Gerar Pix do sinal: R$ SINAL</button></p>
<form id="recarga"><label>Recarga em reais <input id="valor" type="number" min="MINIMO" max="999999999999" step="0.01" value="MINIMO" required></label>
<button>Gerar Pix da recarga</button></form><button id="atualizar">Conferir pagamento e saldo</button></section>
<p><a id="pix" hidden>Ver Pix para pagar no meu banco</a></p></main>
<script nonce="NONCE">
const aviso=document.getElementById('aviso'); let sessao=sessionStorage.getItem('raiz.aprovacao.sessao');
try { sessao ||= JSON.parse(localStorage.getItem('raiz.sessao') || 'null')?.token; } catch {}
async function pedir(url, body, autenticado=false) {
 const headers={'Content-Type':'application/json'}; if(autenticado && sessao) headers.Authorization='Bearer '+sessao;
 const r=await fetch(url,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});
 const d=await r.json(); if(!r.ok) throw Error(typeof d.detail==='string'?d.detail:'Não foi possível concluir. Entre novamente.'); return d;
}
async function mostrar() {
 if(!sessao) return;
 const c=await pedir('/v1/conta',undefined,true);
 document.getElementById('saldo').textContent='Saldo: '+new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(c.saldo_rs)+'. Testes restantes: '+c.testes_restantes+'.';
 document.getElementById('liberacao').textContent=c.liberada?'Conta liberada.':'Liberação pendente: sinal pago e contrato aceito.';
 document.getElementById('contrato').hidden=!!c.contrato_aceito_em;
 document.getElementById('sinal').hidden=!!c.sinal_pago_em;
 document.getElementById('conta').hidden=false; document.getElementById('login').hidden=true;
}
async function acao(botao, trabalho) {
 botao.disabled=true; aviso.textContent='';
 try {await trabalho();} catch(e) {aviso.textContent=e.message;} finally {botao.disabled=false;}
}
async function cobrar(url) {
 const c=await pedir(url,{},true), link=new URL(c.link_para_uma_pessoa,location.origin);
 if(link.origin!==location.origin || !/^\/v1\/cobrancas\/[A-Za-z0-9_-]{24,128}$/.test(link.pathname) || link.search || link.hash) throw Error('Link de pagamento inválido.');
 const a=document.getElementById('pix'); a.href=link.href; a.hidden=false;
 aviso.textContent='Pix preparado. Abra o link e confira o valor antes de pagar. Gerar o Pix não confirma pagamento.';
}
document.getElementById('login').onsubmit=e=>{e.preventDefault();acao(e.submitter,async()=>{
 await pedir('/v1/conta/gerenciar/entrar',{email:document.getElementById('email').value});
 aviso.textContent='Se o e-mail está cadastrado, você receberá um link de entrada.';
});};
document.getElementById('aceito').onchange=e=>{document.getElementById('aceitar').disabled=!e.target.checked;};
document.getElementById('aceitar').onclick=e=>{if(document.getElementById('aceito').checked) acao(e.target,async()=>{await pedir('/v1/conta/contrato',{},true);await mostrar();});};
document.getElementById('sinal').onclick=e=>acao(e.target,()=>cobrar('/v1/conta/sinal'));
document.getElementById('recarga').onsubmit=e=>{e.preventDefault();acao(e.submitter,()=>cobrar('/v1/conta/recarga?valor_rs='+encodeURIComponent(document.getElementById('valor').value)));};
document.getElementById('atualizar').onclick=e=>acao(e.target,mostrar);
(async()=>{try {
 if(location.hash.startsWith('#/entrar/')) {const token=location.hash.slice(9);history.replaceState(null,'',location.pathname);
 const r=await pedir('/entrar/confirmar',{token});sessao=r.token;sessionStorage.setItem('raiz.aprovacao.sessao',sessao);}
 await mostrar();
} catch(e) {aviso.textContent=e.message;}})();
</script></body></html>"""
    conteudo = (
        conteudo.replace("NONCE", nonce)
        .replace("SINAL", html.escape(f"{sinal:.2f}"))
        .replace("MINIMO", f"{minimo:.2f}")
    )
    return HTMLResponse(
        conteudo,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        },
    )
