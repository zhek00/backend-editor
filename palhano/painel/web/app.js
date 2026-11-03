// Painel do Robô PALHANO: uma página só, sem biblioteca.
const E = {
  eu: null, catalogo: null, tela: "produzir", canais: [], maquinas: [],
  form: null, passo: 1, relogio: null,
};
const $app = document.getElementById("app");

const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (v) => (v === null || v === undefined ? "—" : "US$ " + Number(v).toFixed(2).replace(".", ","));
const mmss = (s) => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}h${String(m).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
const data = (iso) => iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const ESTADOS = { fila: ["Na fila", "vai"], produzindo: ["Produzindo", "vai"], entregue: ["Entregue", "ok"],
  falhou: ["Falhou", "ruim"], cancelado: ["Cancelado", ""], atencao: ["Precisa de atenção", "ruim"] };

function aviso(texto, erro = false) {
  const el = document.getElementById("aviso");
  el.textContent = texto; el.className = "aviso" + (erro ? " erro" : ""); el.hidden = false;
  clearTimeout(el._t); el._t = setTimeout(() => (el.hidden = true), erro ? 7000 : 3500);
}

async function api(caminho, opcoes = {}) {
  const r = await fetch(caminho, { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...opcoes,
    body: opcoes.body ? JSON.stringify(opcoes.body) : undefined });
  let d = null;
  try { d = await r.json(); } catch { d = null; }
  if (!r.ok) {
    if (r.status === 401 && !caminho.startsWith("/api/entrar")) { E.eu = null; desenhar(); }
    throw new Error((d && d.detail) || `Erro ${r.status}`);
  }
  return d;
}
const tentar = (fn) => async (...a) => { try { await fn(...a); } catch (e) { aviso(e.message, true); } };

// ------------------------------------------------------------------ início

async function iniciar() {
  E.catalogo = await api("/api/catalogo");
  try { E.eu = await api("/api/eu"); } catch { E.eu = null; }
  const tela = location.pathname.replace(/^\//, "");
  if (tela && TELAS[tela]) E.tela = tela;
  desenhar();
}

function liberado() {
  const u = E.eu;
  return u && (u.admin || (u.aprovado && u.plano));
}

function desenhar() {
  clearInterval(E.relogio);
  if (!E.eu) return telaEntrada();
  if (!liberado()) return telaEspera();
  const itens = Object.entries(TELAS).filter(([k]) => k !== "admin" || E.eu.admin);
  const limite = E.eu.limite_dia > 0 ? `${E.eu.usadas_hoje} de ${E.eu.limite_dia} vídeos hoje` : `${E.eu.usadas_hoje} vídeos hoje`;
  $app.innerHTML = `
    <div class="casca">
      <nav class="lado">
        <div class="marca">Robô <span>PALHANO</span></div>
        ${itens.map(([k, t]) => `<button data-tela="${k}" class="${k === E.tela ? "ativo" : ""}">${t.nome}</button>`).join("")}
        <div class="rodape">${esc(E.eu.email)}<br>${esc(E.eu.plano_nome || "")} · ${limite}<br>
          <button id="sair">Sair</button></div>
      </nav>
      <main class="conteudo" id="tela"></main>
    </div>`;
  $app.querySelectorAll("[data-tela]").forEach((b) => b.onclick = () => irPara(b.dataset.tela));
  document.getElementById("sair").onclick = tentar(async () => { await api("/api/sair", { method: "POST" }); E.eu = null; desenhar(); });
  tentar(TELAS[E.tela].desenhar)(document.getElementById("tela"));
}

function irPara(tela) {
  E.tela = tela;
  history.replaceState(null, "", "/" + tela);
  desenhar();
}

function telaEntrada(modo = "entrar") {
  $app.innerHTML = `
    <div class="entrada"><div class="cartao">
      <div class="marca">Robô <span style="color:var(--laranja)">PALHANO</span></div>
      <p class="sub">Cole o roteiro, o robô entrega o vídeo pronto no seu computador.</p>
      ${modo === "cadastro" ? `<label for="nome">Seu nome</label><input id="nome" autocomplete="name">` : ""}
      <label for="email">E-mail</label><input id="email" type="email" autocomplete="email">
      <label for="senha">Senha</label><input id="senha" type="password" autocomplete="${modo === "cadastro" ? "new-password" : "current-password"}">
      ${modo === "cadastro" ? `<div class="dica">Pelo menos 8 caracteres.</div>` : ""}
      <div class="linha" style="margin-top:18px"><button class="primario" id="ir">${modo === "cadastro" ? "Criar conta" : "Entrar"}</button>
      <button id="trocar">${modo === "cadastro" ? "Já tenho conta" : "Criar conta"}</button></div>
    </div></div>`;
  document.getElementById("trocar").onclick = () => telaEntrada(modo === "cadastro" ? "entrar" : "cadastro");
  const ir = tentar(async () => {
    const corpo = { email: document.getElementById("email").value, senha: document.getElementById("senha").value };
    if (modo === "cadastro") corpo.nome = document.getElementById("nome").value;
    await api(modo === "cadastro" ? "/api/cadastro" : "/api/entrar", { method: "POST", body: corpo });
    E.eu = await api("/api/eu"); desenhar();
  });
  document.getElementById("ir").onclick = ir;
  document.getElementById("senha").onkeydown = (e) => e.key === "Enter" && ir();
}

function telaEspera() {
  const u = E.eu;
  const texto = !u.aprovado ? "Seu cadastro está em análise. Assim que a administração aprovar, o painel libera."
    : "Sua conta foi aprovada, mas ainda não tem um plano ativo. Assine um plano para começar a produzir.";
  $app.innerHTML = `<div class="entrada"><div class="cartao"><h2>Quase lá</h2><p>${texto}</p>
    <p class="dica">${esc(u.email)}</p><div class="linha"><button id="de-novo">Conferir de novo</button><button id="sair">Sair</button></div></div></div>`;
  document.getElementById("de-novo").onclick = tentar(async () => { E.eu = await api("/api/eu"); desenhar(); });
  document.getElementById("sair").onclick = tentar(async () => { await api("/api/sair", { method: "POST" }); E.eu = null; desenhar(); });
}

// ------------------------------------------------------------------ Produzir (4 passos)

function formVazio() {
  return { canal_id: "", nome: "", roteiro: "", ajustes: {} };
}

async function telaProduzir(el) {
  [E.canais, E.maquinas] = await Promise.all([api("/api/canais"), api("/api/maquinas")]);
  if (!E.form) E.form = formVazio();
  desenharProduzir(el);
}

function canalAtual() { return E.canais.find((c) => String(c.id) === String(E.form.canal_id)) || null; }

function ajustesEfetivos() {
  // a mesma ordem do servidor: padrão, canal, vídeo (o servidor confere de novo na hora de enviar)
  const final = { ...E.catalogo.padrao }, c = canalAtual();
  if (c) {
    Object.entries(c.ajustes || {}).forEach(([k, v]) => { if (v !== "" && v !== null) final[k] = v; });
    ["narrador", "voice_id", "estilo"].forEach((k) => { if (c[k]) final[k] = c[k]; });
    if (c.velocidade) final.velocidade = c.velocidade;
  }
  Object.entries(E.form.ajustes).forEach(([k, v]) => { if (v !== "" && v !== null && v !== undefined) final[k] = v; });
  return final;
}

function desenharProduzir(el) {
  const online = E.maquinas.filter((m) => m.online);
  const passos = [["Canal e roteiro", "O ponto de partida"], ["Estilo", "A cara do vídeo"], ["Ajustes", "Só se quiser mudar"], ["Revisão", "Confira e envie"]];
  el.innerHTML = `
    <h1>Produzir um vídeo</h1>
    <p class="sub">Cole o roteiro. O robô narra, busca as imagens e monta o MP4 no seu computador.</p>
    <div class="cartao linha entre">
      <div>${online.length ? `<span class="selo ok">Robô conectado</span> ${online.map((m) => esc(m.nome)).join(", ")}`
        : `<span class="selo ruim">Nenhum robô conectado</span> O vídeo espera na fila até o robô ligar.`}</div>
      ${online.length ? "" : `<button id="ir-maquinas">Conectar máquina</button>`}
    </div>
    <div class="passos">${passos.map(([t, s], i) => `<div class="passo ${E.passo === i + 1 ? "atual" : ""} ${E.passo > i + 1 ? "feito" : ""}" data-passo="${i + 1}"><b>${i + 1}. ${t}</b><small>${s}</small></div>`).join("")}</div>
    <div class="cartao" id="passo"></div>
    <div class="linha entre">
      <button id="voltar" ${E.passo === 1 ? "disabled" : ""}>Voltar</button>
      <span class="dica">Passo ${E.passo} de 4</span>
      ${E.passo < 4 ? `<button class="primario" id="seguir">Continuar</button>` : `<button class="primario" id="enviar">Enviar para o robô</button>`}
    </div>`;
  const ir = el.querySelector("#ir-maquinas"); if (ir) ir.onclick = () => irPara("maquinas");
  el.querySelectorAll("[data-passo]").forEach((p) => p.onclick = () => { const n = +p.dataset.passo; if (n < E.passo || validarPasso()) { E.passo = n; desenharProduzir(el); } });
  el.querySelector("#voltar").onclick = () => { E.passo--; desenharProduzir(el); };
  const seguir = el.querySelector("#seguir"); if (seguir) seguir.onclick = () => { if (validarPasso()) { E.passo++; desenharProduzir(el); } };
  const enviar = el.querySelector("#enviar"); if (enviar) enviar.onclick = tentar(async () => {
    enviar.disabled = true;
    try {
      const p = await api("/api/producoes", { method: "POST", body: { ...E.form, canal_id: E.form.canal_id || null } });
      aviso(`"${p.nome}" entrou na fila.`);
      E.form = formVazio(); E.passo = 1; E.eu = await api("/api/eu"); irPara("acompanhar");
    } finally { enviar.disabled = false; }
  });
  tentar([null, passo1, passo2, passo3, passo4][E.passo])(el.querySelector("#passo"), el);
}

function validarPasso() {
  if (E.passo === 1 && E.form.roteiro.trim().split(/\s+/).length < 30) { aviso("Cole o roteiro (pelo menos 30 palavras).", true); return false; }
  return true;
}

function passo1(el) {
  const f = E.form;
  const palavras = f.roteiro.trim() ? f.roteiro.trim().split(/\s+/).length : 0;
  el.innerHTML = `
    <h2>Qual história vamos contar?</h2>
    <label>Canal</label>
    <select id="canal"><option value="">Sem canal (ajustes só deste vídeo)</option>
      ${E.canais.map((c) => `<option value="${c.id}" ${String(c.id) === String(f.canal_id) ? "selected" : ""}>${esc(c.nome)}</option>`).join("")}</select>
    <div class="dica">O canal traz a voz, o estilo e as diretrizes salvas. Crie em Canais.</div>
    <label>Nome do vídeo (opcional)</label><input id="nome" value="${esc(f.nome)}" placeholder="Se ficar vazio, uso a primeira linha do roteiro">
    <label for="roteiro">Roteiro</label><textarea id="roteiro" placeholder="Cole aqui o texto que será narrado…">${esc(f.roteiro)}</textarea>
    <div class="dica" id="conta">${palavras} palavras · cerca de ${(f.roteiro.replace(/\s+/g, " ").length / 914).toFixed(1).replace(".", ",")} min de vídeo</div>
    <div class="dica">Marcações aceitas: <code>[TITULO] Nome da parte</code> mostra um cartão de capítulo.</div>
    <label>Onde salvar o vídeo</label><input id="destino" value="${esc(f.ajustes.destino || "")}" placeholder="Pasta Downloads do computador do robô">
    <div class="dica">Deixe vazio para a pasta Downloads, ou escreva o caminho de uma pasta no computador do robô.</div>`;
  el.querySelector("#canal").onchange = (e) => { f.canal_id = e.target.value; };
  el.querySelector("#nome").oninput = (e) => { f.nome = e.target.value; };
  el.querySelector("#destino").oninput = (e) => { f.ajustes.destino = e.target.value; };
  el.querySelector("#roteiro").oninput = (e) => {
    f.roteiro = e.target.value; const n = f.roteiro.trim() ? f.roteiro.trim().split(/\s+/).length : 0;
    el.querySelector("#conta").textContent = `${n} palavras · cerca de ${(f.roteiro.replace(/\s+/g, " ").length / 914).toFixed(1).replace(".", ",")} min de vídeo`;
  };
}

function passo2(el) {
  const a = ajustesEfetivos();
  el.innerHTML = `
    <h2>Estilo de edição</h2>
    <div class="grade">${Object.entries(E.catalogo.estilos).map(([k, s]) => `
      <div class="escolha ${a.estilo === k ? "marcada" : ""}" data-estilo="${k}"><b>${esc(s.nome)}</b><small>${esc(s.resumo)}</small></div>`).join("")}</div>
    <div class="dica" style="margin-top:10px">O estilo muda o tema das cenas animadas e o jeito das imagens de IA.</div>
    ${liga("trilha", "Trilha sonora", "Música composta para o vídeo, no clima de cada parte. Desligue para sair só com a voz.", a.trilha)}
    ${liga("legenda", "Legenda na tela", "A fala escrita embaixo, acompanhando cada palavra.", a.legenda)}`;
  el.querySelectorAll("[data-estilo]").forEach((d) => d.onclick = () => { E.form.ajustes.estilo = d.dataset.estilo; passo2(el); });
  ligarChaves(el);
}

function liga(campo, titulo, texto, valor) {
  return `<div class="chave-liga"><input type="checkbox" data-liga="${campo}" ${valor ? "checked" : ""} id="l-${campo}">
    <label for="l-${campo}" style="margin:0;font-weight:400"><b>${titulo}</b><span class="dica">${texto}</span></label></div>`;
}
function ligarChaves(el) {
  el.querySelectorAll("[data-liga]").forEach((c) => c.onchange = () => { E.form.ajustes[c.dataset.liga] = c.checked; });
}

function passo3(el) {
  const a = ajustesEfetivos();
  el.innerHTML = `
    <h2>Ajustes deste vídeo</h2>
    <p class="dica">O que estiver no canal já vem preenchido. Mudar aqui vale só para este vídeo.</p>
    <label>Quem narra</label>
    <select id="narrador">${Object.entries(E.catalogo.narradores).map(([k, n]) => `<option value="${k}" ${a.narrador === k ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
    <label>Código da voz (voice_id)</label><input id="voice_id" value="${esc(a.voice_id || "")}" placeholder="Vazio usa a voz do canal ou a padrão">
    <div class="dica">Obrigatório na GenAI Pro. Na Fish, vazio usa a voz padrão.</div>
    <label>Velocidade da narração: <span id="vel-t">${Number(a.velocidade).toFixed(2).replace(".", ",")}</span></label>
    <input id="velocidade" type="range" min="0.7" max="1.2" step="0.05" value="${a.velocidade}">
    ${liga("ia", "Imagens de IA", "Quando nenhum banco tem a foto certa, a cena ganha uma imagem de IA (uns US$ 0,005 cada).", a.ia)}
    ${liga("vertical", "Versão em pé também", "Além do vídeo deitado, um arquivo 9:16 para Reels e Shorts. Leva mais tempo.", a.vertical)}
    ${liga("teste", "Teste sem custo", "Voz do computador e imagens de teste. Serve para conferir se tudo está funcionando.", a.teste)}
    <p class="dica" style="margin-top:14px">As cenas têm de 3 a 5 segundos, cortadas no tempo da fala, com fotos e vídeos reais primeiro e a conferência de cada imagem.</p>`;
  el.querySelector("#narrador").onchange = (e) => { E.form.ajustes.narrador = e.target.value; };
  el.querySelector("#voice_id").oninput = (e) => { E.form.ajustes.voice_id = e.target.value.trim(); };
  el.querySelector("#velocidade").oninput = (e) => { E.form.ajustes.velocidade = +e.target.value; el.querySelector("#vel-t").textContent = (+e.target.value).toFixed(2).replace(".", ","); };
  ligarChaves(el);
}

async function passo4(el) {
  el.innerHTML = `<div class="vazio">Conferindo…</div>`;
  const r = await api("/api/producoes/previa", { method: "POST", body: { ...E.form, canal_id: E.form.canal_id || null } });
  const a = r.ajustes, c = canalAtual();
  const bloqueado = r.avisos.some((x) => x.tipo === "bloqueia");
  el.innerHTML = `
    <h2>Revisar e enviar</h2>
    ${r.avisos.map((x) => `<div class="alerta ${x.tipo}">${esc(x.texto)}</div>`).join("")}
    <dl class="resumo">
      <div><dt>Vídeo</dt><dd>${esc(E.form.nome || "(primeira linha do roteiro)")}</dd></div>
      <div><dt>Canal</dt><dd>${esc(c ? c.nome : "Sem canal")}</dd></div>
      <div><dt>Roteiro</dt><dd>${E.form.roteiro.trim().split(/\s+/).length} palavras · cerca de ${String(r.minutos_estimados).replace(".", ",")} min</dd></div>
      <div><dt>Estilo</dt><dd>${esc(E.catalogo.estilos[a.estilo].nome)}</dd></div>
      <div><dt>Narração</dt><dd>${esc(E.catalogo.narradores[a.narrador])}${a.voice_id ? " · " + esc(a.voice_id) : ""} · ${String(a.velocidade).replace(".", ",")}x</dd></div>
      <div><dt>Imagens</dt><dd>Fotos e vídeos reais${a.ia ? " + IA quando faltar" : ", sem IA"}</dd></div>
      <div><dt>Trilha e legenda</dt><dd>${a.trilha ? "Com trilha" : "Sem trilha"} · ${a.legenda ? "com legenda" : "sem legenda"}</dd></div>
      <div><dt>Formato</dt><dd>${a.vertical ? "Deitado + em pé" : "Deitado (16:9)"}${a.teste ? " · TESTE sem custo" : ""}</dd></div>
      <div><dt>Destino</dt><dd>${esc(a.destino || "Downloads")}</dd></div>
    </dl>
    <p class="dica">O gasto é nas suas contas (OpenRouter, GenAI Pro e imagens de IA). Ele aparece em Custos quando o vídeo fica pronto.</p>`;
  const b = document.getElementById("enviar"); if (b) b.disabled = bloqueado;
}

// ------------------------------------------------------------------ Acompanhar

async function telaAcompanhar(el) {
  const atualizar = async () => {
    const lista = await api("/api/producoes");
    const ativas = lista.filter((p) => p.estado === "produzindo"), fila = lista.filter((p) => p.estado === "fila");
    const atencao = lista.filter((p) => ["falhou", "atencao"].includes(p.estado)).slice(0, 5);
    el.innerHTML = `
      <h1>Acompanhar</h1><p class="sub">A fila e o que o robô está fazendo agora. Atualiza sozinho.</p>
      <div class="grade" style="margin-bottom:18px">
        <div class="cartao"><div class="dica">Produzindo</div><div class="numero">${ativas.length}</div></div>
        <div class="cartao"><div class="dica">Na fila</div><div class="numero">${fila.length}</div></div>
        <div class="cartao"><div class="dica">Precisam de atenção</div><div class="numero">${atencao.length}</div></div>
      </div>
      ${ativas.map(cartaoAtiva).join("")}
      ${fila.length ? `<div class="cartao"><h2>Na fila</h2>${fila.map((p) => `<div class="linha entre" style="padding:6px 0"><span>${esc(p.nome)} <span class="dica">${esc(p.canal_nome)}</span></span><button class="pequeno perigo" data-cancelar="${p.id}">Cancelar</button></div>`).join("")}</div>` : ""}
      ${atencao.length ? `<div class="cartao"><h2>Precisam de atenção</h2>${atencao.map((p) => `<div style="padding:6px 0"><div class="linha entre"><b>${esc(p.nome)}</b><button class="pequeno" data-retomar="${p.id}">Retomar</button></div><div class="dica">${esc(p.erro)}</div></div>`).join("")}</div>` : ""}
      ${!ativas.length && !fila.length ? `<div class="cartao vazio">Nenhum vídeo sendo produzido agora.<br><br><button class="primario" id="novo">Produzir um vídeo</button></div>` : ""}`;
    ligarAcoes(el, atualizar);
    const n = el.querySelector("#novo"); if (n) n.onclick = () => irPara("produzir");
  };
  await atualizar();
  E.relogio = setInterval(tentar(atualizar), 4000);
}

function cartaoAtiva(p) {
  return `<div class="cartao">
    <div class="linha entre"><div><b>${esc(p.nome)}</b> <span class="dica">${esc(p.canal_nome)}</span></div>
      <button class="pequeno perigo" data-cancelar="${p.id}">Cancelar</button></div>
    <div class="linha entre" style="margin-top:8px"><span>${esc(p.etapa)}</span><span class="dica">${p.progresso}% · ${mmss(p.trabalho_s)} de trabalho</span></div>
    <div class="barra"><i style="width:${p.progresso}%"></i></div>
    <div class="terminal">${esc((p.linhas || []).slice(-12).join("\n"))}</div></div>`;
}

function ligarAcoes(el, depois) {
  const acao = (sel, fn) => el.querySelectorAll(sel).forEach((b) => b.onclick = tentar(async () => { b.disabled = true; await fn(b); await depois(); }));
  acao("[data-cancelar]", (b) => confirm("Cancelar esta produção?") && api(`/api/producoes/${b.dataset.cancelar}/cancelar`, { method: "POST" }));
  acao("[data-retomar]", async (b) => { await api(`/api/producoes/${b.dataset.retomar}/retomar`, { method: "POST" }); aviso("Voltou para a fila. O robô continua de onde parou."); });
  acao("[data-assistir]", async (b) => { await api(`/api/producoes/${b.dataset.assistir}/assistir`, { method: "POST" }); aviso("Abrindo o vídeo no computador do robô."); });
  acao("[data-abrir]", async (b) => { await api(`/api/producoes/${b.dataset.abrir}/abrir`, { method: "POST" }); aviso("Abrindo a pasta no computador do robô."); });
  acao("[data-tirar]", (b) => confirm("Tirar da lista? O MP4 continua no computador.") && api(`/api/producoes/${b.dataset.tirar}`, { method: "DELETE" }));
  el.querySelectorAll("[data-ver]").forEach((b) => b.onclick = (e) => { e.preventDefault(); tentar(detalhe)(b.dataset.ver); });
}

// ------------------------------------------------------------------ Produções

async function telaProducoes(el) {
  const lista = await api("/api/producoes");
  const filtro = E.filtro || "todas", canal = E.filtroCanal || "";
  const grupos = { todas: () => true, entregue: (p) => p.estado === "entregue", andamento: (p) => ["fila", "produzindo"].includes(p.estado),
    atencao: (p) => ["falhou", "atencao"].includes(p.estado), cancelado: (p) => p.estado === "cancelado" };
  const canais = [...new Set(lista.map((p) => p.canal_nome).filter(Boolean))];
  const mostra = lista.filter(grupos[filtro]).filter((p) => !canal || p.canal_nome === canal);
  el.innerHTML = `
    <h1>Produções</h1><p class="sub">Os vídeos entregues e os que pararam no caminho.</p>
    <div class="linha" style="margin-bottom:14px">
      <select id="filtro" style="width:auto">${[["todas", "Todas"], ["entregue", "Entregues"], ["andamento", "Em andamento"], ["atencao", "Precisam de atenção"], ["cancelado", "Canceladas"]].map(([k, n]) => `<option value="${k}" ${k === filtro ? "selected" : ""}>${n}</option>`).join("")}</select>
      <select id="canal" style="width:auto"><option value="">Todos os canais</option>${canais.map((c) => `<option ${c === canal ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
    </div>
    <div class="cartao">${mostra.length ? `<table><thead><tr><th>Vídeo</th><th>Estado</th><th>Trabalho</th><th>Duração</th><th>Custo</th><th></th></tr></thead><tbody>
      ${mostra.map((p) => `<tr>
        <td><a href="#" data-ver="${p.id}">${esc(p.nome)}</a><div class="dica">${esc(p.canal_nome || "Sem canal")} · ${data(p.criada)}</div></td>
        <td><span class="selo ${ESTADOS[p.estado][1]}">${ESTADOS[p.estado][0]}</span></td>
        <td>${p.trabalho_s ? mmss(p.trabalho_s) : "—"}</td><td>${p.duracao_s ? mmss(p.duracao_s) : "—"}</td><td>${usd(p.custo_usd)}</td>
        <td><div class="linha">${p.estado === "entregue" ? `<button class="pequeno" data-assistir="${p.id}">Assistir</button><button class="pequeno" data-abrir="${p.id}">Pasta</button>` : ""}
          ${["falhou", "cancelado", "atencao"].includes(p.estado) ? `<button class="pequeno" data-retomar="${p.id}">Retomar</button>` : ""}
          ${["fila", "produzindo"].includes(p.estado) ? `<button class="pequeno perigo" data-cancelar="${p.id}">Cancelar</button>` : `<button class="pequeno" data-tirar="${p.id}">Tirar</button>`}</div></td></tr>`).join("")}
      </tbody></table>` : `<div class="vazio">Nada por aqui ainda.</div>`}</div>`;
  el.querySelector("#filtro").onchange = (e) => { E.filtro = e.target.value; telaProducoes(el); };
  el.querySelector("#canal").onchange = (e) => { E.filtroCanal = e.target.value; telaProducoes(el); };
  ligarAcoes(el, () => telaProducoes(el));
}

async function detalhe(id) {
  const p = await api(`/api/producoes/${id}`);
  const fundo = document.createElement("div");
  fundo.className = "fundo-modal";
  const cat = p.custo.por_categoria || {};
  fundo.innerHTML = `<div class="modal">
    <div class="linha entre"><h2>${esc(p.nome)}</h2><button id="fechar">Fechar</button></div>
    <p><span class="selo ${ESTADOS[p.estado][1]}">${ESTADOS[p.estado][0]}</span> ${esc(p.etapa)} · ${p.progresso}%</p>
    ${p.erro ? `<div class="alerta bloqueia">${esc(p.erro)}</div>` : ""}
    <dl class="resumo">
      <div><dt>Arquivo</dt><dd>${esc(p.arquivo || "—")}</dd></div>
      <div><dt>Duração</dt><dd>${p.duracao_s ? mmss(p.duracao_s) : "—"}</dd></div>
      <div><dt>Custo total</dt><dd>${usd(p.custo_usd)}${p.custo.por_minuto_usd ? " · " + usd(p.custo.por_minuto_usd) + " por minuto" : ""}</dd></div>
      <div><dt>Cenas</dt><dd>${p.custo.cenas || "—"}</dd></div>
    </dl>
    ${Object.keys(cat).length ? `<h3>Custo por parte</h3><table>${Object.entries(cat).map(([k, v]) => `<tr><td>${esc((p.custo.rotulos || {})[k] || k)}</td><td>${usd(v)}</td></tr>`).join("")}</table>` : ""}
    <h3 style="margin-top:16px">Últimas linhas do robô</h3><div class="terminal">${esc((p.linhas || []).join("\n"))}</div>
    <h3 style="margin-top:16px">Roteiro</h3><div class="terminal" style="background:#faf9f6;color:var(--tinta)">${esc(p.roteiro)}</div></div>`;
  document.body.appendChild(fundo);
  fundo.onclick = (e) => { if (e.target === fundo || e.target.id === "fechar") fundo.remove(); };
}

// ------------------------------------------------------------------ Máquinas

async function telaMaquinas(el) {
  const lista = await api("/api/maquinas");
  el.innerHTML = `
    <h1>Máquinas</h1><p class="sub">Os computadores onde o robô está instalado. O vídeo é feito e salvo neles.</p>
    <div class="cartao"><h2>Conectar um computador</h2>
      <ol><li>Nesse computador, instale a fábrica (com <b>uv</b> e <b>ffmpeg</b>).</li>
      <li>Dê dois cliques em <b>LIGAR-ROBO.bat</b> (na pasta palhano).</li><li>Quando ele pedir, digite o código abaixo.</li></ol>
      <div id="codigo"><button class="primario" id="gerar">Gerar código de conexão</button></div></div>
    <div class="cartao"><h2>Seus computadores</h2>
      ${lista.length ? `<table><thead><tr><th>Nome</th><th>Estado</th><th>Visto</th><th></th></tr></thead><tbody>${lista.map((m) => `<tr>
        <td><b>${esc(m.nome)}</b><div class="dica">${esc(m.sistema)} · robô ${esc(m.versao)}</div></td>
        <td>${m.online ? (m.ocupada ? `<span class="selo vai">Produzindo ${m.produzindo > 1 ? m.produzindo + " vídeos" : ""}</span>` : `<span class="selo ok">Pronto</span>`) : `<span class="selo">Desligado</span>`}</td>
        <td>${data(m.visto_em)}</td><td><button class="pequeno perigo" data-tirar="${m.id}">Desconectar</button></td></tr>`).join("")}</tbody></table>`
      : `<div class="vazio">Nenhum computador conectado ainda.</div>`}</div>`;
  el.querySelector("#gerar").onclick = tentar(async () => {
    const r = await api("/api/maquinas/codigo", { method: "POST" });
    el.querySelector("#codigo").innerHTML = `<div class="codigo">${r.codigo.slice(0, 4)}-${r.codigo.slice(4)}</div>
      <div class="dica">Vale ${r.minutos} minutos e serve uma vez só.</div>`;
  });
  el.querySelectorAll("[data-tirar]").forEach((b) => b.onclick = tentar(async () => {
    if (!confirm("Desconectar este computador? O robô dele para de receber vídeos.")) return;
    await api(`/api/maquinas/${b.dataset.tirar}`, { method: "DELETE" }); telaMaquinas(el);
  }));
}

// ------------------------------------------------------------------ Canais

async function telaCanais(el, aberto) {
  E.canais = await api("/api/canais");
  const c = aberto === "novo" ? { nome: "", ajustes: {} } : E.canais.find((x) => x.id === aberto);
  el.innerHTML = `
    <h1>Canais</h1><p class="sub">Cada canal guarda a voz, o estilo e as diretrizes. O robô usa tudo em cada vídeo do canal.</p>
    <div class="linha" style="margin-bottom:14px">${E.canais.map((x) => `<button data-canal="${x.id}" class="${c && c.id === x.id ? "primario" : ""}">${esc(x.nome)}</button>`).join("")}
      <button data-canal="novo">+ Novo canal</button></div>
    <div class="cartao" id="form-canal">${c ? "" : `<div class="vazio">Escolha um canal ou crie um novo.</div>`}</div>`;
  el.querySelectorAll("[data-canal]").forEach((b) => b.onclick = () => telaCanais(el, b.dataset.canal === "novo" ? "novo" : +b.dataset.canal));
  if (!c) return;
  const a = c.ajustes || {};
  const f = el.querySelector("#form-canal");
  f.innerHTML = `
    <label>Nome</label><input id="c-nome" value="${esc(c.nome)}">
    <label>Descrição</label><input id="c-descricao" value="${esc(c.descricao || "")}" placeholder="Do que o canal fala">
    <label>Diretrizes para as imagens</label><textarea id="c-diretrizes" style="min-height:110px" placeholder="Ex.: produtos de supermercado sempre com a embalagem real; nunca desenho">${esc(c.diretrizes || "")}</textarea>
    <div class="dica">Vão para o agente que escolhe as imagens de cada cena.</div>
    <label for="c-fixa">Texto fixo da descrição</label><textarea id="c-fixa" style="min-height:110px" maxlength="1500" placeholder="Abre a descrição de todo vídeo do canal no YouTube: links, redes, contato">${esc(c.descricao_fixa || "")}</textarea>
    <div class="dica">Entra exatamente como você escrever, no topo. Embaixo vêm o resumo e os capítulos de cada vídeo.</div>
    <div class="grade">
      <div><label>Narrador</label><select id="c-narrador"><option value="">Padrão</option>${Object.entries(E.catalogo.narradores).map(([k, n]) => `<option value="${k}" ${c.narrador === k ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
      <div><label>Código da voz (voice_id)</label><input id="c-voz" value="${esc(c.voice_id || "")}"></div>
      <div><label>Velocidade (0,7 a 1,2)</label><input id="c-vel" type="number" min="0.7" max="1.2" step="0.05" value="${c.velocidade || ""}" placeholder="1,0"></div>
      <div><label>Estilo</label><select id="c-estilo"><option value="">Padrão</option>${Object.entries(E.catalogo.estilos).map(([k, s]) => `<option value="${k}" ${c.estilo === k ? "selected" : ""}>${esc(s.nome)}</option>`).join("")}</select></div>
    </div>
    ${liga("ia", "Imagens de IA", "Quando o acervo não tem a foto certa.", a.ia ?? E.catalogo.padrao.ia)}
    ${liga("trilha", "Trilha sonora", "", a.trilha ?? E.catalogo.padrao.trilha)}
    ${liga("legenda", "Legenda na tela", "", a.legenda ?? E.catalogo.padrao.legenda)}
    ${liga("vertical", "Versão em pé também", "", a.vertical ?? E.catalogo.padrao.vertical)}
    <div class="linha entre" style="margin-top:16px">${c.id ? `<button class="perigo" id="excluir">Excluir canal</button>` : "<span></span>"}<button class="primario" id="salvar">Salvar canal</button></div>`;
  const ajustes = { ...a };
  f.querySelectorAll("[data-liga]").forEach((x) => x.onchange = () => { ajustes[x.dataset.liga] = x.checked; });
  f.querySelector("#salvar").onclick = tentar(async () => {
    const corpo = { nome: f.querySelector("#c-nome").value, descricao: f.querySelector("#c-descricao").value,
      diretrizes: f.querySelector("#c-diretrizes").value, descricao_fixa: f.querySelector("#c-fixa").value, narrador: f.querySelector("#c-narrador").value,
      voice_id: f.querySelector("#c-voz").value, velocidade: f.querySelector("#c-vel").value, estilo: f.querySelector("#c-estilo").value, ajustes };
    const salvo = await api(c.id ? `/api/canais/${c.id}` : "/api/canais", { method: c.id ? "PUT" : "POST", body: corpo });
    aviso("Canal salvo."); telaCanais(el, salvo.id);
  });
  const ex = f.querySelector("#excluir"); if (ex) ex.onclick = tentar(async () => {
    if (!confirm(`Excluir o canal ${c.nome}?`)) return;
    await api(`/api/canais/${c.id}`, { method: "DELETE" }); telaCanais(el);
  });
}

// ------------------------------------------------------------------ Integrações

async function telaIntegracoes(el) {
  const r = await api("/api/chaves");
  const prov = E.catalogo.provedores;
  const estadoSelo = { testada: ["Testada", "ok"], recusada: ["Recusada", "ruim"], sem_teste: ["Sem teste", "vai"], nao_testada: ["Sem teste", "vai"] };
  el.innerHTML = `
    <h1>Integrações</h1><p class="sub">As chaves das suas contas. Ficam cifradas no painel, nunca voltam para a tela e só vão para o seu robô.</p>
    ${r.faltando.length ? `<div class="alerta bloqueia">Faltam para produzir: ${esc(r.faltando.join(", "))}.</div>` : `<div class="alerta info">Pronto para produzir: as chaves obrigatórias estão aqui.</div>`}
    ${Object.entries(prov).map(([k, p]) => {
      const minhas = r.chaves.filter((c) => c.provedor === k);
      return `<div class="cartao">
        <div class="linha entre"><h2 style="margin:0">${esc(p.nome)} ${p.obrigatoria ? `<span class="selo vai">Obrigatória</span>` : `<span class="selo">Opcional</span>`}</h2>
          <a href="${p.link}" target="_blank" rel="noopener">Pegar a chave ↗</a></div>
        <p class="dica">${esc(p.para)}</p>
        ${minhas.map((c) => `<div class="linha entre" style="padding:6px 0;border-top:1px solid var(--linha)">
          <span>•••• ${esc(c.final)} <span class="selo ${estadoSelo[c.estado][1]}">${estadoSelo[c.estado][0]}</span> <span class="dica">${esc(c.detalhe)}</span></span>
          <span class="linha"><button class="pequeno" data-testar="${c.id}">Testar</button><button class="pequeno perigo" data-apagar="${c.id}">Remover</button></span></div>`).join("")}
        ${!minhas.length || p.pool ? `<div class="linha" style="margin-top:10px"><input type="password" autocomplete="off" placeholder="${minhas.length ? "Mais uma chave (o robô reveza)" : "Cole a chave aqui"}" data-nova="${k}" style="flex:1;min-width:220px"><button data-salvar="${k}">Salvar e testar</button></div>` : ""}
      </div>`;
    }).join("")}`;
  el.querySelectorAll("[data-salvar]").forEach((b) => b.onclick = tentar(async () => {
    const campo = el.querySelector(`[data-nova="${b.dataset.salvar}"]`);
    b.disabled = true;
    try {
      const x = await api("/api/chaves", { method: "POST", body: { provedor: b.dataset.salvar, valor: campo.value } });
      aviso(x.estado === "testada" ? "Chave salva e testada." : "Chave salva. O provedor não respondeu ao teste agora.");
      telaIntegracoes(el);
    } finally { b.disabled = false; }
  }));
  el.querySelectorAll("[data-testar]").forEach((b) => b.onclick = tentar(async () => {
    const x = await api(`/api/chaves/${b.dataset.testar}/testar`, { method: "POST" });
    aviso(x.estado === "testada" ? "Funcionando." : x.detalhe || "Sem resposta.", x.estado === "recusada"); telaIntegracoes(el);
  }));
  el.querySelectorAll("[data-apagar]").forEach((b) => b.onclick = tentar(async () => {
    if (!confirm("Remover esta chave?")) return;
    await api(`/api/chaves/${b.dataset.apagar}`, { method: "DELETE" }); telaIntegracoes(el);
  }));
}

// ------------------------------------------------------------------ Custos

async function telaCustos(el) {
  const r = await api("/api/custos");
  el.innerHTML = `
    <h1>Custos</h1><p class="sub">O que cada vídeo gastou nas suas contas, medido pelo robô. Não substitui a fatura dos provedores.</p>
    <div class="grade" style="margin-bottom:18px">
      <div class="cartao"><div class="dica">Total</div><div class="numero">${usd(r.total_usd)}</div></div>
      <div class="cartao"><div class="dica">Por minuto de vídeo</div><div class="numero">${usd(r.por_minuto_usd)}</div></div>
      <div class="cartao"><div class="dica">Vídeos entregues</div><div class="numero">${r.videos}</div><div class="dica">${String(r.minutos).replace(".", ",")} min no total</div></div>
    </div>
    ${Object.keys(r.por_categoria).length ? `<div class="cartao"><h2>Por parte</h2><table>${Object.entries(r.por_categoria).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${usd(v)}</td></tr>`).join("")}</table></div>` : ""}
    <div class="cartao"><h2>Por vídeo</h2>${r.producoes.length ? `<table><thead><tr><th>Vídeo</th><th>Duração</th><th>Custo</th><th>Por minuto</th></tr></thead><tbody>
      ${r.producoes.map((p) => `<tr><td><a href="#" data-ver="${p.id}">${esc(p.nome)}</a><div class="dica">${esc(p.canal_nome || "Sem canal")} · ${data(p.terminada)}</div></td>
        <td>${mmss(p.duracao_s)}</td><td>${usd(p.custo_usd)}</td><td>${usd(p.custo.por_minuto_usd)}</td></tr>`).join("")}</tbody></table>` : `<div class="vazio">Nenhum vídeo entregue ainda.</div>`}</div>`;
  el.querySelectorAll("[data-ver]").forEach((b) => b.onclick = (e) => { e.preventDefault(); tentar(detalhe)(b.dataset.ver); });
}

// ------------------------------------------------------------------ Administração

async function telaAdmin(el) {
  const lista = await api("/api/admin/usuarios");
  const planos = E.catalogo.planos;
  el.innerHTML = `
    <h1>Administração</h1><p class="sub">Aprove cadastros, defina o plano e o vencimento. O plano decide quantos vídeos por dia.</p>
    <div class="cartao"><table><thead><tr><th>Conta</th><th>Aprovada</th><th>Plano</th><th>Vence</th><th>Hoje</th><th></th></tr></thead><tbody>
    ${lista.map((u) => `<tr data-u="${u.id}">
      <td><b>${esc(u.nome || "—")}</b><div class="dica">${esc(u.email)}${u.admin ? " · administração" : ""}</div></td>
      <td><input type="checkbox" class="u-aprovado" ${u.aprovado ? "checked" : ""} style="width:auto"></td>
      <td><select class="u-plano"><option value="">Sem plano</option>${Object.entries(planos).map(([k, p]) => `<option value="${k}" ${u.plano === k ? "selected" : ""}>${esc(p.nome)} (${p.limite_dia || "∞"}/dia)</option>`).join("")}</select></td>
      <td><input type="date" class="u-vence" value="${esc(u.vence)}"></td>
      <td>${u.usadas_hoje}${u.limite_dia > 0 ? "/" + u.limite_dia : ""}</td>
      <td><button class="pequeno u-salvar">Salvar</button></td></tr>`).join("")}</tbody></table></div>`;
  el.querySelectorAll("[data-u]").forEach((tr) => tr.querySelector(".u-salvar").onclick = tentar(async () => {
    await api(`/api/admin/usuarios/${tr.dataset.u}`, { method: "POST", body: {
      aprovado: tr.querySelector(".u-aprovado").checked, plano: tr.querySelector(".u-plano").value, vence: tr.querySelector(".u-vence").value } });
    aviso("Conta atualizada.");
  }));
}

const TELAS = {
  produzir: { nome: "Produzir", desenhar: telaProduzir },
  acompanhar: { nome: "Acompanhar", desenhar: telaAcompanhar },
  producoes: { nome: "Produções", desenhar: telaProducoes },
  maquinas: { nome: "Máquinas", desenhar: telaMaquinas },
  canais: { nome: "Canais", desenhar: (el) => telaCanais(el) },
  integracoes: { nome: "Integrações", desenhar: telaIntegracoes },
  custos: { nome: "Custos", desenhar: telaCustos },
  admin: { nome: "Administração", desenhar: telaAdmin },
};

iniciar().catch((e) => { $app.innerHTML = `<div class="entrada"><div class="cartao">Painel fora do ar: ${esc(e.message)}</div></div>`; });
