# ruff: noqa: E501
"""Página humana de aprovação: login por e-mail e decisão explícita após ver valor e prazos."""

import html
import secrets

from fastapi.responses import HTMLResponse


def pagina(token: str) -> HTMLResponse:
    nonce = secrets.token_urlsafe(24)
    conteudo = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Aprovar reserva — Raíz</title>
<body><main><h1>Aprovar a reserva do grupo</h1>
<p>Confira a proposta antes de aprovar. A aprovação gera o Pix; o pagamento é feito por você no seu banco.</p>
<form id="login"><label>E-mail cadastrado na empresa <input id="email" type="email" required autocomplete="email"></label>
<button>Receber link de entrada</button></form>
<p id="aviso" role="status"></p><section id="resumo" hidden><h2>Condições da reserva</h2><p id="condicoes"></p>
<button id="aprovar">Aprovar e gerar Pix</button></section>
<section id="pagamento" hidden><h2>Reserva aprovada</h2><p id="vencimento"></p><div id="qr"></div>
<label>Pix copia e cola <textarea id="pix" readonly rows="5"></textarea></label>
<p>O recibo comprova sua aprovação. A exclusividade só começa após a confirmação do pagamento.</p>
<a id="recibo" download="recibo-aprovacao.jws">Baixar recibo assinado</a></section></main>
<script nonce="NONCE">
const base='/v1/reservas/confirmar/TOKEN', aviso=document.getElementById('aviso');
let sessao=sessionStorage.getItem('raiz.aprovacao.sessao');
try { sessao ||= JSON.parse(localStorage.getItem('raiz.sessao') || 'null')?.token; } catch {}
async function pedir(url, body, autenticado=false) {
 const headers={'Content-Type':'application/json'};
 if(autenticado && sessao) headers.Authorization='Bearer '+sessao;
 const resp=await fetch(url,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});
 const data=await resp.json(); if(!resp.ok) throw Error(typeof data.detail==='string'?data.detail:(data.detail?.mensagem || 'Não foi possível concluir. Entre novamente.')); return data;
}
async function mostrar() {
 if(!sessao) return;
 try { const r=await pedir(base+'/resumo',undefined,true);
  document.getElementById('condicoes').textContent='Valor: '+new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(r.valor_brl)+
   '. Preço válido até: '+new Date(r.preco_valido_ate).toLocaleString('pt-BR')+
   '. Exclusividade: '+r.exclusividade.dias+' dias após o pagamento confirmado.';
  document.getElementById('resumo').hidden=false; document.getElementById('login').hidden=true;
 } catch(e) { aviso.textContent=e.message; }
}
document.getElementById('login').onsubmit=async e=>{e.preventDefault();
 try { await pedir(base+'/entrar',{email:document.getElementById('email').value});
 aviso.textContent='Se o e-mail corresponde à empresa, você receberá um link. Abra-o para conferir a reserva.';
 } catch(e) {aviso.textContent=e.message;}
};
document.getElementById('aprovar').onclick=async e=>{e.target.disabled=true;
 try {const r=await pedir(base,{},true);document.getElementById('pagamento').hidden=false;
  document.getElementById('resumo').hidden=true;
  document.getElementById('pix').value=r.pix?.copia_e_cola || '';
  document.getElementById('vencimento').textContent='Vencimento do Pix: '+new Date(r.pix?.expira_em).toLocaleString('pt-BR');
  // SVG produzido localmente pelo gerador QR, nunca HTML de fonte externa.
  if(r.pix?.qr_svg) document.getElementById('qr').innerHTML=r.pix.qr_svg;
  document.getElementById('recibo').href=URL.createObjectURL(new Blob([r.recibo_aprovacao],{type:'application/jose'}));
  aviso.textContent=r.modo_teste?'Modo de teste: este código não efetua pagamento.':'Pague pelo aplicativo do seu banco.';
 } catch(err) {aviso.textContent=err.message;e.target.disabled=false;}
};
(async()=>{if(location.hash.startsWith('#/entrar/')) {
 const token=location.hash.slice(9); history.replaceState(null,'',location.pathname);
 try {const r=await pedir('/entrar/confirmar',{token});sessao=r.token;sessionStorage.setItem('raiz.aprovacao.sessao',sessao);}
 catch(e){aviso.textContent=e.message;}
} await mostrar();})();
</script></body></html>""".replace("NONCE", nonce).replace("TOKEN", html.escape(token, quote=True))
    return HTMLResponse(
        conteudo,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; "
            "img-src 'self' data:; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
        },
    )
