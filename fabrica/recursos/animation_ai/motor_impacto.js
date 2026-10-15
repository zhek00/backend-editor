/* animation-ai, tema impacto: as cenas animadas com foto real, letra gigante e construção progressiva.

   Vem do protótipo de 2026-10-13 (teste-estilos/prototipo), pedido do usuário depois de comparar os modelos antigos
   ("textinho todo feio") com vídeos de referência: escala (letra de 120 a 340 px), movimento o tempo todo, a cena se
   montando peça por peça, a foto da coisa no lugar do cartão de texto, luz e grão, uma cor de destaque.

   Recebe o mesmo window.AAI do motor.js ({tipo, s, dur, estilo, variante}): os campos que a IA preenche e os tempos que
   o Python resolveu (s.t, s.itens[i].t...). Fotos: s.fundo (a foto da cena) e it.foto / s.esq.foto... (as dos itens),
   caminhos dentro da pasta. Seis receitas cobrem os tipos do catálogo (QUAL, no fim); tipo sem receita cai na frase.

   Tudo vai na linha do tempo do GSAP, pausada: o HyperFrames grava quadro a quadro por ela. Nada de relógio do navegador
   nem sorteio. A faixa de baixo (abaixo de 790 px) fica livre para a legenda queimada. */
(function () {
  const A = window.AAI, s = A.s || {}, DUR = A.dur, TIPO = A.tipo;
  const tl = gsap.timeline({ paused: true });
  window.__timelines = window.__timelines || {};
  window.__timelines["main"] = tl;
  const root = document.getElementById("root");
  const palco = document.getElementById("palco");
  const SVGNS = "http://www.w3.org/2000/svg";
  // camadas que se cobrem de propósito (texto sobre foto, cartas empilhadas): a conferência do HyperFrames não reprova
  const PERMITE = "data-layout-allow-overlap data-layout-allow-occlusion";
  const T = (v, padrao) => (typeof v === "number" && isFinite(v) ? v : padrao);
  const esc = v => String(v == null ? "" : v).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const limpo = v => String(v == null ? "" : v).replace(/\*/g, "").trim();
  const fmt = (v, casas) => Number(v).toLocaleString(document.documentElement.lang || "pt-BR", { minimumFractionDigits: casas || 0, maximumFractionDigits: casas || 0 });
  const FIM = Math.max(0.6, DUR - 0.5);

  function el(html, pai) {
    const m = document.createElement("template");
    m.innerHTML = html.trim();
    const e = m.content.firstElementChild;
    (pai || palco).appendChild(e);
    return e;
  }
  // aparece só entre ini e fim
  function janela(e, ini, fim) {
    tl.set(e, { autoAlpha: 0 }, 0);
    tl.set(e, { autoAlpha: 1 }, ini);
    if (fim !== undefined && fim < DUR) tl.set(e, { autoAlpha: 0 }, fim);
  }
  // entradas: chega desacelerando, de maior, de baixo ou do lado, com desfoque de movimento
  const JEITOS = {
    sobe: { y: 70, autoAlpha: 0, filter: "blur(12px)" },
    // dentro de cartão: os 70 px do sobe passavam da borda de baixo (cenas 94 e 224 do brasil-selvagem)
    curto: { y: 26, autoAlpha: 0, filter: "blur(8px)" },
    soco: { scale: 1.3, autoAlpha: 0, filter: "blur(16px)" },
    esquerda: { x: -240, autoAlpha: 0, filter: "blur(14px)" },
    direita: { x: 240, autoAlpha: 0, filter: "blur(14px)" },
    baixo: { y: 380, autoAlpha: 0, rotation: 4 },
    carimbo: { scale: 2.0, autoAlpha: 0, rotation: -12 },
  };
  function entra(e, t, jeito, d) {
    const de = JEITOS[jeito || "sobe"];
    const para = { duration: d || 0.45, ease: jeito === "carimbo" ? "back.out(1.6)" : "power3.out", autoAlpha: 1 };
    for (const k of Object.keys(de)) if (k !== "autoAlpha") para[k] = k === "filter" ? "blur(0px)" : (k === "scale" ? 1 : 0);
    tl.fromTo(e, de, para, Math.max(0, Math.min(t, FIM)));
    return e;
  }
  function sai(e, t, para, d) {
    tl.to(e, Object.assign({ y: -140, autoAlpha: 0, filter: "blur(12px)", duration: d || 0.25, ease: "power2.in" }, para || {}), t);
  }
  // os contadores: o encaixe mede com o valor final (o número chega maior que o 0) e depois volta ao valor da hora
  const contadores = [];
  function conta(e, ate, t, d, casas) {
    const o = { v: 0 };
    const mostra = () => { e.textContent = fmt(o.v, casas); };
    contadores.push({ e, final: fmt(ate, casas), mostra });
    e.textContent = fmt(0, casas);
    tl.fromTo(o, { v: 0 }, { v: 0, duration: 0.001, ease: "none", immediateRender: false, onUpdate: mostra }, 0);
    tl.to(o, { v: ate, duration: d || 0.8, ease: "power2.out", onUpdate: mostra }, t);
  }
  function brilho(x, y, r, cor, ini) {
    const b = el(`<div class="brilho" ${PERMITE} style="left:${x - r}px;top:${y - r}px;width:${2 * r}px;height:${2 * r}px;background:${cor}"></div>`);
    // atrás de tudo, logo depois do fundo: desenhado por cima, ele embaçava os cartões (comparar, cena 220 do
    // everything-you-need-to-answer)
    const bg = palco.querySelector(".bg");
    palco.insertBefore(b, bg ? bg.nextSibling : palco.firstChild);
    janela(b, ini);
    tl.fromTo(b, { scale: 0.85 }, { scale: 1.15, duration: 1.2, ease: "sine.inOut", yoyo: true,
                                     repeat: Math.max(0, Math.ceil((DUR - ini) / 1.2) - 1) }, ini);
    return b;
  }
  function flash(t) {
    const f = el(`<div class="flash" ${PERMITE}></div>`, root);
    tl.fromTo(f, { opacity: 0 }, { opacity: 0.45, duration: 0.05, ease: "none" }, t);
    tl.to(f, { opacity: 0, duration: 0.22, ease: "power2.out" }, t + 0.05);
  }
  function linhas() {
    const v = document.createElementNS(SVGNS, "svg");
    v.setAttribute("class", "linhas");
    v.setAttribute("viewBox", "0 0 1920 1080");
    palco.appendChild(v);
    return v;
  }
  function linha(svg, d, t, dur, cor, larg) {
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("d", d);
    p.setAttribute("fill", "none");
    p.setAttribute("stroke", cor || "var(--acc, #FFD23F)");
    p.setAttribute("stroke-width", larg || 7);
    p.setAttribute("stroke-linecap", "round");
    svg.appendChild(p);
    const L = Math.ceil(p.getTotalLength()) + 2;
    p.style.strokeDasharray = L + " " + L;
    tl.fromTo(p, { strokeDashoffset: L }, { strokeDashoffset: 0, duration: dur || 0.6, ease: "power2.inOut" }, t);
  }
  // a foto atrás de tudo, andando devagar; sem foto, um fundo escuro com luz
  function fundo(src, o) {
    o = o || {};
    let b;
    if (src) {
      b = el(`<div class="bg" ${PERMITE}><img alt="" src="${esc(src)}" style="object-position:${o.pos || "50% 50%"};${o.desfoque ? `filter:blur(${o.desfoque}px);` : ""}"><i class="escuro ${o.lado ? "lado" : ""}" style="opacity:${o.escuro == null ? 1 : o.escuro}"></i>${o.forte ? '<i class="escuro forte"></i>' : ""}</div>`);
      tl.fromTo(b.querySelector("img"), { scale: o.de || 1.12, transformOrigin: o.origem || "50% 50%" },
                { scale: o.para || 1.24, duration: DUR, ease: "none" }, 0);
    } else {
      b = el(`<div class="bg vazio" ${PERMITE}></div>`);
      tl.fromTo(b, { scale: 1.0 }, { scale: 1.12, duration: DUR, ease: "none" }, 0);
    }
    palco.insertBefore(b, palco.firstChild);
    return b;
  }
  // cartão com foto (ou um painel escuro, sem foto)
  function carta(src, x, y, w, h, o) {
    o = o || {};
    const c = src
      ? el(`<div class="card" ${PERMITE} style="left:${x}px;top:${y}px;width:${w}px;height:${h}px"><img alt="" src="${esc(src)}" style="object-position:${o.pos || "50% 45%"}">${o.sombra ? '<i class="sombra"></i>' : ""}</div>`, o.pai)
      : el(`<div class="card vazio" ${PERMITE} style="left:${x}px;top:${y}px;width:${w}px;height:${h}px">${o.sombra ? '<i class="sombra"></i>' : ""}</div>`, o.pai);
    if (src && o.kb) tl.fromTo(c.querySelector("img"), { scale: 1.16 }, { scale: 1.0, duration: Math.max(0.5, DUR - o.kb), ease: "none" }, o.kb);
    return c;
  }
  // texto palavra por palavra a partir de t; *destaque* ganha a tarja colorida
  function escreve(pai, texto, t, o) {
    o = o || {};
    const passo = o.passo == null ? 0.08 : o.passo;
    let i = 0;
    String(texto || "").split(/(\*[^*]+\*)/).filter(Boolean).forEach(parte => {
      const forte = /^\*.+\*$/.test(parte);
      parte.replace(/\*/g, "").split(/\s+/).filter(Boolean).forEach(w => {
        const s_ = forte
          ? el(`<span class="p caixa ${o.cor || "escura"}" ${PERMITE}><i></i>${esc(w)}</span>`, pai)
          : el(`<span class="p" ${PERMITE}>${esc(w)}</span>`, pai);
        const tt = Math.min(t + i * passo, FIM);
        entra(s_, tt, o.jeito || "sobe", o.d);
        if (forte) tl.fromTo(s_.querySelector("i"), { scaleX: 0 }, { scaleX: 1, duration: 0.32, ease: "power3.out" }, Math.min(tt + 0.1, FIM));
        i++;
      });
    });
  }
  // o texto encolhe até caber na caixa dele (de novo quando as fontes terminam de carregar)
  const encaixes = [];
  function cabe(e, w, h, min) {
    // mede sem as entradas: no começo cada palavra está no ponto de partida (70 px abaixo, 1,3 vez maior, desfocada),
    // e isso conta na área de rolagem. Medindo assim, todo texto encolhia até o mínimo
    const pecas = [e, ...e.querySelectorAll("*")].map(x => [x, x.style.transform, x.style.filter]);
    pecas.forEach(([x]) => { x.style.transform = "none"; x.style.filter = "none"; });
    let f = parseFloat(e.dataset.f || e.style.fontSize) || parseFloat(getComputedStyle(e).fontSize);
    e.dataset.f = e.dataset.f || String(f);
    e.style.fontSize = f + "px";
    let n = 0;
    while ((e.scrollWidth > w + 1 || e.scrollHeight > h + 1) && f > min && n++ < 90) {
      f = Math.max(min, f - 4);
      e.style.fontSize = f + "px";
    }
    pecas.forEach(([x, tr, fi]) => { x.style.transform = tr; x.style.filter = fi; });
  }
  function texto(pai, classe, estilo, w, h, min) {
    const e = el(`<div class="${classe}" ${PERMITE} style="width:${w}px;${estilo || ""}"></div>`, pai);
    encaixes.push([e, w, h, min]);
    return e;
  }
  function camera() {
    tl.fromTo(palco, { scale: 1.0 }, { scale: 1.05, duration: DUR, ease: "sine.inOut" }, 0);
  }

  // ------------------------------------------------------------------------------------------- as receitas
  const R = {};

  // número herói: a foto num cartão e o número gigante contando, com o que ele mede
  R.heroi = function () {
    const t = T(s.t, 0.3);
    fundo(s.fundo, { desfoque: 16 });
    brilho(1350, 430, 340, "rgba(255,210,63,.32)", Math.max(0, t - 0.2));
    let prefixo = "", sufixo = "", numero = null, casas = 0, fixo = null;
    if (TIPO === "porcentagem") { numero = Number(s.valor); casas = T(s.casas, 0); sufixo = "%"; }
    else if (TIPO === "proporcao") { fixo = `${s.parte} em ${s.total}`; }
    else if (s.contar && typeof s.numero === "number") { numero = s.numero; casas = T(s.casas, 0); prefixo = s.prefixo || ""; sufixo = s.sufixo || ""; }
    else { fixo = limpo(s.valor); prefixo = ""; }
    const legenda = limpo(s.legenda || s.rotulo);
    const temFoto = !!s.fundo;
    const bloco = temFoto
      ? el(`<div class="bloco" ${PERMITE} style="left:1040px;top:130px"></div>`)
      : el(`<div class="bloco" ${PERMITE} style="left:160px;top:150px;text-align:center"></div>`);
    const largura = temFoto ? 790 : 1600;
    if (temFoto) {
      const c = carta(s.fundo, 100, 130, 880, 600, { sombra: true, kb: 0 });
      entra(c, Math.max(0.05, t - 0.35), "esquerda", 0.5);
    }
    const n = texto(bloco, "gigante uma-linha cor-acc sombra-txt", "font-size:" + (temFoto ? 300 : 340) + "px", largura, temFoto ? 300 : 340, 90);
    if (prefixo) el(`<span ${PERMITE}>${esc(prefixo)}</span>`, n);
    if (numero !== null) { const v = el(`<span ${PERMITE}>0</span>`, n); conta(v, numero, t + 0.05, 0.9, casas); }
    else el(`<span ${PERMITE}>${esc(fixo)}</span>`, n);
    if (sufixo) el(`<span ${PERMITE} style="font-size:.45em;letter-spacing:-0.02em">${esc(sufixo)}</span>`, n);
    entra(n, t, "soco", 0.5);
    if (legenda) {
      const l = texto(bloco, "medio sombra-txt", "font-size:84px;margin-top:22px", largura, 210, 40);
      escreve(l, legenda, T(s.t_legenda, t + 0.5));
    }
    if (s.nota) {
      const no = texto(bloco, "serif", "font-size:60px;margin-top:18px;color:#fff", largura, 140, 32);
      escreve(no, limpo(s.nota), T(s.t_nota, t + 1.0), { passo: 0.06 });
    }
  };

  // frase: a foto inteira com zoom lento e o texto grande ao lado, com a palavra-chave na tarja
  R.frase = function () {
    const t = T(s.t, 0.3);
    const temFoto = !!s.fundo;
    fundo(s.fundo, { desfoque: 0, escuro: 1, lado: true, de: 1.0, para: 1.2, origem: "30% 50%" });
    let kicker = s.kicker, principal = s.texto, sub = null, chips = null;
    if (TIPO === "palavra_chave") { principal = `*${limpo(s.termo)}*`; chips = s.itens || []; }
    else if (TIPO === "citacao") { principal = `“${limpo(s.texto)}”`; sub = s.autor; }
    else if (TIPO === "definicao") { kicker = s.termo; principal = s.definicao; }
    else if (TIPO === "manchete") { kicker = s.veiculo; principal = s.titulo; sub = s.sub; }
    else if (TIPO === "documento") { principal = s.titulo; chips = s.linhas || []; }
    else if (TIPO === "fato") { sub = s.fonte; }
    principal = principal || s.titulo || s.legenda || s.termo || "";
    const largura = temFoto ? 1040 : 1600;
    const bloco = temFoto
      ? el(`<div class="bloco" ${PERMITE} style="right:110px;top:120px;text-align:right"></div>`)
      : el(`<div class="bloco" ${PERMITE} style="left:160px;top:140px;text-align:center"></div>`);
    if (kicker) escreve(texto(bloco, "leve", "margin-bottom:18px", largura, 80, 30), limpo(kicker), T(s.t_kicker, 0.1), { passo: 0.06 });
    const grande = TIPO === "citacao"
      ? texto(bloco, "serif sombra-txt", "font-size:104px;line-height:1.08;color:#fff", largura, 470, 44)
      : texto(bloco, "gigante sombra-txt", "font-size:" + (TIPO === "palavra_chave" ? 230 : 128) + "px", largura, TIPO === "palavra_chave" ? 280 : 470, 48);
    escreve(grande, principal, t, { jeito: TIPO === "palavra_chave" ? "soco" : "sobe" });
    if (chips && chips.length) {
      const linha_ = texto(bloco, "leve", "margin-top:22px;font-size:54px", largura, 150, 28);
      chips.forEach((it, i) => {
        const c = el(`<span class="p" ${PERMITE} style="margin-right:.6em">${esc(limpo(it.texto || it))}</span>`, linha_);
        entra(c, T(it.t, t + 0.6 + i * 0.4), "sobe");
      });
    }
    if (sub) escreve(texto(bloco, "serif", "font-size:62px;margin-top:20px;color:#fff", largura, 140, 30), limpo(sub), Math.min(t + 1.1, FIM), { passo: 0.06 });
    if (temFoto) flash(Math.max(0, t - 0.05));
  };

  // baralho: uma carta com foto por item, cada uma entrando no seu segundo e empurrando as anteriores para trás
  R.baralho = function () {
    const itens = (s.itens || []).filter(it => it && (it.texto || it.titulo));
    fundo(s.fundo, { desfoque: 8, forte: true });  // com 20, o vídeo todo ficava fosco
    if (s.titulo) {
      const ti = texto(el(`<div class="bloco" ${PERMITE} style="left:0;top:34px;width:1920px;text-align:center"></div>`),
                       "leve", "margin:0 auto", 1700, 80, 30);
      escreve(ti, limpo(s.titulo), T(s.t_titulo, 0.2), { passo: 0.06 });
    }
    const numerado = ["lista", "passos", "ranking", "pilha_cartoes"].includes(TIPO);
    const marca = { errado: "✕", alerta: "!", estrela: "★", certo: "✓" }[s.marca] || (TIPO === "checklist" ? "✓" : null);
    const POS = ["50% 40%", "30% 50%", "70% 45%", "50% 70%", "20% 30%", "80% 60%"];
    const pilha = [];
    // com foto própria em algum item, o cartão sem foto fica sem: a foto da cena é a de outro item, e o nome
    // embaixo dela mentiria (o "bichos-preguiça" sobre o macaco-prego)
    const proprias = itens.some(it => it.foto);
    const topo = s.titulo ? 180 : 150;  // com título, o baralho desce para não cobrir o título
    itens.forEach((it, i) => {
      const t = T(it.t, 0.4 + i * 0.8);
      const emb = el(`<div class="embrulho" ${PERMITE} style="left:460px;top:${topo}px;width:1000px;height:560px"></div>`);
      const foto = it.foto || (proprias ? null : s.fundo) || null;
      const c = carta(foto, 0, 0, 1000, 560, { sombra: true, kb: t, pos: it.foto ? "50% 45%" : POS[i % POS.length], pai: emb });
      emb.pelicula = el(`<i class="pelicula" ${PERMITE}></i>`, c);
      // cartão de texto (sem foto): o texto no meio, grande, e não colado embaixo de um vazio escuro
      const caixa = foto
        ? el(`<div class="bloco" ${PERMITE} style="left:54px;bottom:60px"></div>`, c)
        : el(`<div class="bloco" ${PERMITE} style="left:70px;top:150px"></div>`, c);
      emb.caixa = caixa;
      const nome = texto(caixa, "gigante sombra-txt", "font-size:112px", 890, 250, 44);
      escreve(nome, it.titulo || it.texto, t + 0.08, { passo: 0.06, jeito: "curto" });
      if (it.titulo && it.texto) escreve(texto(caixa, "serif", "font-size:46px;margin-top:10px;color:#fff", 890, 120, 26), limpo(it.texto), t + 0.4, { passo: 0.05, jeito: "curto" });
      const simbolo = numerado ? String(i + 1) : marca;
      if (simbolo) {
        const selo = el(`<div class="selo" ${PERMITE} style="left:-34px;top:-34px">${esc(simbolo)}</div>`, emb);
        entra(selo, t + 0.3, "carimbo", 0.4);
      }
      if (TIPO === "ranking" && i === s.destaque) c.style.boxShadow = "0 50px 110px rgba(0,0,0,.65), 0 0 0 6px var(--acc, #FFD23F)";
      entra(emb, Math.max(0, t - 0.1), "baixo", 0.5);
      pilha.forEach((ant, j) => {
        const fundo_ = pilha.length - j;
        const leva = { scale: 1 - 0.06 * fundo_, x: -110 * fundo_, y: 14 * fundo_, rotation: -2.5 * fundo_,
                       duration: 0.45, ease: "power3.out" };
        if (fundo_ > 3) leva.autoAlpha = 0;
        tl.to(ant, leva, Math.max(0, t - 0.1));
        tl.to(ant.pelicula, { opacity: Math.min(0.7, 0.24 * fundo_), duration: 0.45, ease: "power3.out" }, Math.max(0, t - 0.1));
        // o texto do cartão de trás some: sob a película, a caixa amarela escurecia e o texto escuro dela sumia
        // (contraste 1,1:1, cena 43 do brasil-selvagem); quem fala é o cartão da frente
        if (fundo_ === 1) tl.to(ant.caixa, { autoAlpha: 0, duration: 0.3, ease: "power2.out" }, Math.max(0, t - 0.1));
      });
      pilha.push(emb);
    });
  };

  // ---- outros desenhos dos tipos de itens (lista, destaques, checklist...). Pedido do usuário em 2026-10-14: 15 dos 19
  // trechos animados do everything-you-need-to-answer saíram como o baralho, e o vídeo ficava sempre igual
  const itensDe = (max) => (s.itens || []).filter(it => it && (it.texto || it.titulo)).slice(0, max);
  const simboloDe = (i) => {
    const marca = { errado: "✕", alerta: "!", estrela: "★", certo: "✓" }[s.marca] || (TIPO === "checklist" ? "✓" : null);
    return ["lista", "passos", "ranking", "pilha_cartoes"].includes(TIPO) ? String(i + 1) : marca;
  };
  function tituloNoAlto(top) {
    if (!s.titulo) return;
    const ti = texto(el(`<div class="bloco" ${PERMITE} style="left:0;top:${top}px;width:1920px;text-align:center"></div>`),
                     "leve", "margin:0 auto", 1700, 80, 30);
    escreve(ti, limpo(s.titulo), T(s.t_titulo, 0.2), { passo: 0.06 });
  }

  // grade: os itens lado a lado, cada um com a sua foto; quem entra fica aceso e os de antes escurecem um pouco
  R.grade = function () {
    const itens = itensDe(4);
    if (itens.length < 2) { R.baralho(); return; }
    fundo(s.fundo, { desfoque: 8, forte: true });
    tituloNoAlto(40);
    const k = itens.length, gap = 40, w = Math.min(500, (1640 - (k - 1) * gap) / k), h = 540;
    const x0 = (1920 - (k * w + (k - 1) * gap)) / 2, y = 175;
    const feitos = [];
    itens.forEach((it, i) => {
      const t = T(it.t, 0.4 + i * 0.8);
      const emb = el(`<div class="embrulho" ${PERMITE} style="left:${x0 + i * (w + gap)}px;top:${y}px;width:${w}px;height:${h}px"></div>`);
      const c = carta(it.foto || null, 0, 0, w, h, { sombra: true, kb: t, pai: emb });
      emb.pelicula = el(`<i class="pelicula" ${PERMITE}></i>`, c);
      const caixa = it.foto
        ? el(`<div class="bloco" ${PERMITE} style="left:30px;bottom:36px"></div>`, c)
        : el(`<div class="bloco" ${PERMITE} style="left:34px;top:110px"></div>`, c);
      escreve(texto(caixa, "medio sombra-txt", "font-size:62px", w - 64, 230, 28), it.titulo || it.texto, t + 0.08,
              { passo: 0.05, jeito: "curto" });
      const simbolo = simboloDe(i);
      if (simbolo) entra(el(`<div class="selo" ${PERMITE} style="left:-28px;top:-28px">${esc(simbolo)}</div>`, emb), t + 0.25, "carimbo", 0.4);
      entra(emb, Math.max(0, t - 0.1), "baixo", 0.5);
      feitos.forEach(ant => tl.to(ant.pelicula, { opacity: 0.45, duration: 0.4, ease: "power2.out" }, Math.max(0, t - 0.1)));
      feitos.push(emb);
    });
    // no fim, todos acesos de novo: a lista inteira na tela
    const ultimo = T(itens[itens.length - 1].t, DUR * 0.6);
    if (ultimo + 1.2 < FIM) feitos.forEach(ant => tl.to(ant.pelicula, { opacity: 0, duration: 0.4 }, ultimo + 1.0));
  };

  // faixas: linhas largas empilhadas, como um placar; cada uma desliza do lado com miniatura, número e texto grande
  R.faixas = function () {
    const itens = itensDe(5);
    if (itens.length < 2) { R.baralho(); return; }
    fundo(s.fundo, { desfoque: 8, forte: true });
    tituloNoAlto(36);
    const n = itens.length, gap = 22, top0 = 140, alt = Math.min(150, (630 - (n - 1) * gap) / n);
    const fotoW = Math.round(alt * 1.7);
    const feitos = [];
    itens.forEach((it, i) => {
      const t = T(it.t, 0.4 + i * 0.7);
      const y = top0 + i * (alt + gap);
      const fx = el(`<div class="faixa-item" ${PERMITE} style="left:230px;top:${y}px;width:1460px;height:${alt}px"></div>`);
      if (it.foto) carta(it.foto, 0, 0, fotoW, alt, { pai: fx, kb: t });
      const inicioTexto = it.foto ? fotoW + 40 : 50;
      const simbolo = simboloDe(i);
      let x = inicioTexto;
      if (simbolo) {
        el(`<div class="faixa-num" ${PERMITE} style="left:${x}px;height:${alt}px;line-height:${alt}px">${esc(simbolo)}</div>`, fx);
        x += 110;
      }
      const bloco = el(`<div class="bloco" ${PERMITE} style="left:${x}px;top:0;height:${alt}px;display:flex;align-items:center"></div>`, fx);
      escreve(texto(bloco, "gigante sombra-txt uma-linha", `font-size:${Math.round(alt * 0.56)}px`, 1460 - x - 40, alt - 16, 30),
              it.titulo || it.texto, t + 0.1, { passo: 0.05, jeito: "curto" });
      fx.pelicula = el(`<i class="pelicula" ${PERMITE}></i>`, fx);
      entra(fx, Math.max(0, t - 0.1), "esquerda", 0.45);
      feitos.forEach(ant => tl.to(ant.pelicula, { opacity: 0.35, duration: 0.35 }, Math.max(0, t - 0.1)));
      feitos.push(fx);
    });
  };

  // tela cheia: cada item toma a tela inteira com a sua foto, em cortes no ritmo da fala; sem foto, um fundo de cor
  R.telacheia = function () {
    const itens = itensDe(5);
    if (itens.length < 2) { R.baralho(); return; }
    const ts = itens.map((it, i) => T(it.t, 0.3 + i * (DUR - 0.6) / itens.length));
    itens.forEach((it, i) => {
      const t = i ? Math.max(0, ts[i] - 0.12) : 0;
      const fim = i + 1 < itens.length ? ts[i + 1] + 0.25 : undefined;
      const camada = el(`<div class="camada" ${PERMITE}></div>`);
      if (it.foto) {
        const img = el(`<img alt="" src="${esc(it.foto)}">`, camada);
        tl.fromTo(img, { scale: 1.02 }, { scale: 1.14, duration: (fim || DUR) - t, ease: "none" }, t);
        el(`<i class="escuro lado-baixo" ${PERMITE}></i>`, camada);
      } else {
        el(`<div class="bg vazio" ${PERMITE} style="left:0;top:0;width:100%;height:100%"></div>`, camada);
      }
      const simbolo = simboloDe(i) || String(i + 1);
      el(`<div class="contador" ${PERMITE}>${esc(simbolo)}<span ${PERMITE}>/${itens.length}</span></div>`, camada);
      const bloco = el(`<div class="bloco" ${PERMITE} style="left:120px;top:430px"></div>`, camada);
      escreve(texto(bloco, "gigante sombra-txt", "font-size:170px", 1680, 330, 64), it.titulo || it.texto,
              Math.max(t + 0.1, ts[i] - 0.05), { passo: 0.07, jeito: "soco", d: 0.45 });
      if (i + 1 < itens.length) tl.to(bloco, { autoAlpha: 0, duration: 0.15, ease: "power2.in" }, Math.max(0, ts[i + 1] - 0.15));
      janela(camada, t, fim);
      tl.fromTo(camada, { clipPath: "inset(0% 0% 0% 100%)" }, { clipPath: "inset(0% 0% 0% 0%)", duration: 0.35, ease: "power3.inOut" }, t);
      if (i) flash(t + 0.05);
    });
    tituloNoAlto(40);
  };

  // versus: a tela cortada na diagonal, um lado contra o outro, com o selo VS no meio
  R.versus = function () {
    if (TIPO !== "comparar") { R.comparar(); return; }
    const lados = [s.esq || {}, s.dir || {}];
    const t0 = T(lados[0].t, 0.3), t1 = Math.max(T(lados[1].t, DUR * 0.45), t0 + 0.8);
    fundo(null);
    const CORTE = ["polygon(0 0, 57% 0, 43% 100%, 0 100%)", "polygon(57% 0, 100% 0, 100% 100%, 43% 100%)"];
    lados.forEach((lado, k) => {
      const tlado = k ? t1 : t0;
      const metade = el(`<div class="camada" ${PERMITE} style="clip-path:${CORTE[k]}"></div>`);
      const foto = lado.foto || null;
      if (foto) {
        const img = el(`<img alt="" src="${esc(foto)}" style="object-position:${k ? "70% 50%" : "30% 50%"}">`, metade);
        tl.fromTo(img, { scale: 1.15 }, { scale: 1.0, duration: Math.max(0.5, DUR - tlado), ease: "none" }, tlado);
        el(`<i class="escuro forte" ${PERMITE}></i>`, metade);
      } else {
        el(`<div class="bg vazio" ${PERMITE} style="left:0;top:0;width:100%;height:100%"></div>`, metade);
      }
      el(`<i class="tinta ${k ? "vermelha" : ""}" ${PERMITE}></i>`, metade);
      entra(metade, Math.max(0, tlado - 0.1), k ? "direita" : "esquerda", 0.5);
      const bloco = el(`<div class="bloco" ${PERMITE} style="${k ? "right:110px;top:150px;text-align:right" : "left:110px;top:430px"}"></div>`);
      escreve(texto(bloco, "gigante sombra-txt", "font-size:150px", 760, 240, 50), `*${limpo(lado.titulo || lado.texto)}*`, tlado + 0.1,
              { cor: k && !s.neutro ? "vermelha" : "escura", passo: 0.07 });
      (lado.itens || []).slice(0, 2).forEach((it, i) => escreve(texto(bloco, "leve", "font-size:46px;margin-top:12px", 760, 120, 26),
              limpo(it.texto), T(it.t, tlado + 0.5 + i * 0.4), { passo: 0.05 }));
    });
    entra(el(`<div class="selo vs" ${PERMITE}>VS</div>`), t1 + 0.05, "carimbo", 0.45);
    flash(t1);
    if (s.legenda) escreve(texto(el(`<div class="bloco" ${PERMITE} style="left:0;top:720px;width:1920px;text-align:center"></div>`),
                                  "serif", "font-size:50px;margin:0 auto;color:#fff", 1600, 64, 28), limpo(s.legenda), Math.min(t1 + 0.9, FIM), { passo: 0.05 });
  };

  // comparar: um lado grande no meio; o outro entra e a tela divide (amarelo contra vermelho)
  R.comparar = function () {
    fundo(s.fundo, { desfoque: 8, forte: true });
    const lados = TIPO === "comparar" ? [s.esq || {}, s.dir || {}] : [s.antes || {}, s.depois || {}];
    const t0 = T(lados[0].t, 0.3), t1 = Math.max(T(lados[1].t, DUR * 0.45), t0 + 0.8);
    const neutro = !!s.neutro;
    const colunas = lados.map((lado, k) => {
      const col = el(`<div class="embrulho" ${PERMITE} style="left:${k ? 1010 : 90}px;top:70px;width:820px"></div>`);
      const dentro = el(`<div ${PERMITE}></div>`, col);
      const foto = lado.foto || (lados.some(l => l.foto) ? null : s.fundo) || null;  // como no baralho
      const c = carta(foto, 0, 0, 820, 400, { sombra: true, kb: k ? t1 : t0, pos: lado.foto ? "50% 45%" : (k ? "75% 50%" : "25% 50%"), pai: dentro });
      c.style.position = "relative";
      const tlado = k ? t1 : t0;
      if (TIPO === "comparar") {
        const tit = texto(dentro, "gigante sombra-txt", "font-size:112px;margin-top:30px", 820, 210, 44);
        escreve(tit, `*${limpo(lado.titulo || lado.texto)}*`, tlado + 0.1, { cor: k && !neutro ? "vermelha" : "escura", passo: 0.07 });
        const its = (lado.itens || []).slice(0, 2);
        its.forEach((it, i) => escreve(texto(dentro, "leve", "font-size:46px;margin-top:12px", 820, 120, 26), limpo(it.texto), T(it.t, tlado + 0.5 + i * 0.4), { passo: 0.05 }));
      } else {
        escreve(texto(dentro, "leve", "margin-top:26px", 820, 80, 28), limpo(lado.rotulo), tlado, { passo: 0.06 });
        const v = texto(dentro, "gigante uma-linha sombra-txt " + (k ? "cor-acc2" : "cor-acc"), "font-size:170px;margin-top:8px", 820, 190, 60);
        const m = /^(\D*?)(\d[\d.]*(?:,\d+)?)(.*)$/.exec(limpo(lado.valor));
        if (m) {
          const num = parseFloat(m[2].replace(/\./g, "").replace(",", "."));
          const casas = (m[2].split(",")[1] || "").length;
          if (m[1]) el(`<span ${PERMITE}>${esc(m[1])}</span>`, v);
          const span = el(`<span ${PERMITE}>0</span>`, v);
          conta(span, num, tlado + 0.1, 0.8, casas);
          if (m[3]) el(`<span ${PERMITE} style="font-size:.5em">${esc(m[3])}</span>`, v);
        } else el(`<span ${PERMITE}>${esc(limpo(lado.valor))}</span>`, v);
        entra(v, tlado + 0.05, "soco");
      }
      entra(dentro, Math.max(0, tlado - 0.1), k ? "direita" : "esquerda", 0.5);
      return col;
    });
    // o primeiro lado começa sozinho, grande no meio; abre espaço quando o segundo chega
    tl.set(colunas[0], { x: 410, y: -10, scale: 1.12 }, 0);
    tl.to(colunas[0], { x: 0, y: 0, scale: 1, duration: 0.55, ease: "power3.inOut" }, Math.max(0, t1 - 0.45));
    linha(linhas(), "M 960 110 L 960 760", t1 + 0.05, 0.5, "rgba(255,255,255,.35)", 3);
    brilho(500, 420, 320, "rgba(255,210,63,.32)", t0);
    brilho(1420, 420, 320, neutro ? "rgba(255,210,63,.32)" : "rgba(255,77,61,.32)", t1);
    if (s.legenda) {
      const lg = texto(el(`<div class="bloco" ${PERMITE} style="left:0;top:722px;width:1920px;text-align:center"></div>`),
                       "serif", "font-size:52px;margin:0 auto;color:#fff", 1600, 70, 28);
      escreve(lg, limpo(s.legenda), Math.min(t1 + 0.9, FIM), { passo: 0.05 });
    }
    flash(t1);
  };

  // ligação: as coisas no alto, a consequência (o último item) nasce embaixo e todas se ligam a ela
  R.ligacao = function () {
    const itens = (s.itens || []).filter(it => it && (it.texto || it.data));
    if (itens.length < 2) { R.frase(); return; }
    fundo(s.fundo, { desfoque: 8, forte: true });
    const destino = itens[itens.length - 1], fontes = itens.slice(0, -1);
    const k = fontes.length, w = Math.min(520, (1700 - (k - 1) * 30) / k), h = 250;
    const x0 = (1920 - (k * w + (k - 1) * 30)) / 2;
    const svg = linhas();
    const tDest = Math.max(T(destino.t, DUR * 0.6), T(fontes[k - 1].t, 0) + 0.6);
    fontes.forEach((it, i) => {
      const x = x0 + i * (w + 30), t = T(it.t, 0.3 + i * 0.7);
      const c = carta(it.foto || null, x, 60, w, h, { sombra: true, kb: t, pos: it.foto ? "50% 45%" : "50% 50%" });
      const rot = texto(el(`<div class="bloco" ${PERMITE} style="left:24px;bottom:24px"></div>`, c), "medio sombra-txt", "font-size:46px", w - 48, 110, 22);
      escreve(rot, limpo(it.texto), t + 0.1, { passo: 0.05, jeito: "curto" });
      if (it.data) { const et = el(`<div class="etiqueta" ${PERMITE} style="left:18px;top:16px">${esc(it.data)}</div>`, c); entra(et, t + 0.2, "carimbo", 0.35); }
      entra(c, t, "sobe", 0.5);
      linha(svg, `M ${x + w / 2} ${60 + h} C ${x + w / 2} ${60 + h + 90}, 960 ${330}, 960 ${405}`, tDest - 0.15 + i * 0.08, 0.55);
    });
    // sem foto, o cartão do destino seria um retângulo vazio atrás da frase: fica só a frase (cenas 71 e 296)
    const fotoDest = destino.foto || (fontes.some(it => it.foto) ? null : s.fundo) || null;
    const cd = fotoDest
      ? carta(fotoDest, 410, 410, 1100, 360, { sombra: true, kb: tDest, pos: "50% 55%" })
      : el(`<div class="bloco" ${PERMITE} style="left:410px;top:410px;width:1100px;height:360px"></div>`);
    entra(cd, Math.max(0, tDest - 0.35), "baixo", 0.55);
    if (destino.data) { const et = el(`<div class="etiqueta" ${PERMITE} style="left:24px;top:20px;font-size:40px">${esc(destino.data)}</div>`, cd); entra(et, tDest + 0.2, "carimbo", 0.35); }
    const pino = el(`<div class="pino" ${PERMITE} style="left:938px;top:388px"></div>`);
    entra(pino, tDest + 0.3, "carimbo", 0.4);
    const fim = texto(el(`<div class="bloco" ${PERMITE} style="left:160px;top:575px;text-align:center"></div>`),
                      "gigante sombra-txt", "font-size:150px", 1600, 190, 50);
    escreve(fim, /\*/.test(destino.texto || "") ? destino.texto : `*${limpo(destino.texto)}*`, tDest, { passo: 0.04 });
    flash(tDest + 0.15);
  };

  // título: a palavra gigante sobre a foto, com o que vem em cima e embaixo dela
  R.titulo = function () {
    const tt = T(s.t_titulo, T(s.t, 0.3));
    fundo(s.fundo, { desfoque: 0, escuro: 1, de: 1.1, para: 1.28 });
    brilho(960, 470, 420, "rgba(77,163,255,.45)", Math.max(0, tt - 0.2));
    const bloco = el(`<div class="bloco" ${PERMITE} style="left:110px;top:150px;text-align:center"></div>`);
    if (s.kicker) escreve(texto(bloco, "leve", "margin:0 auto 22px", 1700, 80, 30), limpo(s.kicker), T(s.t_kicker, 0.1), { passo: 0.06 });
    const titulo = s.titulo || s.texto || "";
    const g = texto(bloco, "gigante sombra-txt", "font-size:260px;margin:0 auto", 1700, 400, 80);
    escreve(g, titulo, tt, { jeito: "soco", passo: 0.1, d: 0.5 });
    const sub = s.sub || s.proximo;
    if (sub) escreve(texto(bloco, "serif", "font-size:72px;margin:28px auto 0;color:#fff", 1600, 170, 32), limpo(sub), T(s.t_sub, tt + 1.0), { passo: 0.06 });
  };

  const QUAL = {
    numero: "heroi", porcentagem: "heroi", medidor: "heroi", proporcao: "heroi",
    frase: "frase", pergunta: "frase", fato: "frase", palavra_chave: "frase", citacao: "frase", definicao: "frase",
    manchete: "frase", documento: "frase",
    lista: "baralho", destaques: "baralho", checklist: "baralho", cartoes: "baralho", pilha_cartoes: "baralho",
    ranking: "baralho", passos: "baralho",
    comparar: "comparar", antes_depois: "comparar", deslizar: "comparar",
    causa_efeito: "ligacao", linha_do_tempo: "ligacao",
    abertura: "titulo", capitulo: "titulo", revelacao: "titulo", encerramento: "titulo",
  };
  camera();
  // s._layout: outro desenho do mesmo tipo (grade, faixas, telacheia; versus no comparar), escolhido pelo Python
  // para duas cenas animadas seguidas não saírem iguais
  const receita = s._layout && R[s._layout] ? s._layout : QUAL[TIPO];
  (R[receita] || R.frase)();
  // o acabamento fica por cima de tudo, de propósito: a conferência não conta como texto escondido
  el(`<div class="vinheta" ${PERMITE}></div>`, root);
  el(`<div class="faixa" ${PERMITE}></div>`, root);
  const grao = el(`<div class="grao" ${PERMITE}></div>`, root);
  tl.to(grao, { x: 180, y: 140, duration: DUR, ease: `steps(${Math.max(1, Math.round(DUR * 24))})` }, 0);

  function encaixar() {
    contadores.forEach(c => { c.e.textContent = c.final; });
    encaixes.forEach(([e, w, h, min]) => cabe(e, w, h, min));
    contadores.forEach(c => c.mostra());
  }
  encaixar();
  tl.seek(0);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { encaixar(); tl.seek(tl.time()); });
  window.quadro = t => tl.seek(t);
})();
