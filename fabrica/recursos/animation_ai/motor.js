/* animation-ai (fabrica/animation_ai.py): o motor das cenas animadas da fábrica.

   Como funciona, em três partes:
   1. montar: o Python manda window.AAI = {tipo, s, dur, canal}. Os tempos de cada elemento já vêm resolvidos pela fala
      (s.t, s.itens[i].t...): quem acha o segundo de cada palavra é o Python, que também tira os sons das mesmas entradas.
   2. quadro(t): função pura do tempo. Câmera, entradas, contagens, linhas e barras saem só de t: o mesmo quadro sai
      sempre igual, e o HyperFrames grava quadro a quadro pela linha do tempo do GSAP (um relógio de 0 a dur).
   3. encaixar: texto comprido encolhe até caber na caixa dele (data-fit="largura,altura,mínimo"), de novo quando as
      fontes terminam de carregar.
   Nada de animação em CSS, sorteio sem semente ou relógio do computador: o quadro dependeria de quando foi tirado.
   Área livre: de 150 a 1770 px na largura e de 100 a 800 px na altura; embaixo fica a legenda queimada. */
(function () {
  const A = window.AAI, s = A.s || {}, DUR = A.dur;
  const root = document.getElementById("root");
  const palco = document.getElementById("palco");
  const entradas = [], passos = [], impactos = [];

  const lim = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const sai = x => 1 - Math.pow(1 - lim(x), 3);
  const vaivem = x => { x = lim(x); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
  const mola = x => { x = lim(x); const c = 1.70158; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
  const esc = v => String(v == null ? "" : v).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // *trecho* no texto vira destaque na cor do canal
  const rico = v => esc(v).replace(/\*(.+?)\*/g, '<span class="d">$1</span>');
  const fmt = (v, casas) => Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
  const T = (v, padrao) => (typeof v === "number" && isFinite(v) ? v : padrao);

  function cria(html, pai) {
    const m = document.createElement("template");
    m.innerHTML = html.trim();
    const e = m.content.firstElementChild;
    (pai || palco).appendChild(e);
    return e;
  }
  function entra(e, t, jeito, d) {
    entradas.push({ e, t: T(t, 0.2), jeito: jeito || "sobe", d: d || (jeito === "impacto" ? 0.38 : 0.55) });
    if (jeito === "impacto") impactos.push(T(t, 0.2));
    return e;
  }
  function conta(e, valor, casas, t, d) {
    passos.push(tt => { e.textContent = fmt(valor * sai((tt - t) / (d || 1.1)), casas); });
  }
  function desenha(caminho, t, d) {
    const L = Math.ceil(caminho.getTotalLength ? caminho.getTotalLength() : 2000) + 2;
    caminho.style.strokeDasharray = L + " " + L;
    passos.push(tt => { caminho.style.strokeDashoffset = L * (1 - vaivem((tt - t) / (d || 0.7))); });
  }
  function svg(html) { return cria(`<svg class="linha-svg" viewBox="0 0 1920 1080">${html}</svg>`); }

  const ICONES = {
    certo: '<path d="M4 12.5l5 5L20 6.5" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>',
    errado: '<path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"/>',
    alerta: '<path d="M12 3.2L22 20.5H2z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M12 9.5v5.2" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="12" cy="17.6" r="1.5" fill="currentColor"/>',
    estrela: '<path d="M12 2.8l2.8 6 6.5.7-4.9 4.4 1.4 6.4L12 17l-5.8 3.3 1.4-6.4-4.9-4.4 6.5-.7z" fill="currentColor"/>',
    seta: '<path d="M3 12h16M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>',
    aspas: '<path d="M4 18v-5.5C4 8.6 6 6 9.5 5l.8 1.8C8.4 7.8 7.6 9.3 7.6 11H10v7zm9.5 0v-5.5c0-3.9 2-6.5 5.5-7.5l.8 1.8c-1.9 1-2.7 2.5-2.7 4.2h2.4v7z" fill="currentColor"/>',
    lupa: '<circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M15.5 15.5L21 21" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"/>',
    info: '<circle cx="12" cy="12" r="9.5" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M12 10.5v6.5" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="12" cy="7.2" r="1.5" fill="currentColor"/>',
    sino: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.8 2H4.2zM10 20.5a2 2 0 0 0 4 0" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linejoin="round"/>',
    pessoa: '<circle cx="12" cy="7" r="4" fill="currentColor"/><path d="M4 22c0-5 3.6-8.4 8-8.4s8 3.4 8 8.4z" fill="currentColor"/>',
  };
  const icone = (nome, px, cor) =>
    `<span class="icone" style="width:${px}px;height:${px}px;color:${cor || "var(--acc)"}"><svg viewBox="0 0 24 24">${ICONES[nome] || ICONES.info}</svg></span>`;

  function cabeca(y) {
    // kicker e título no alto da cena, quando a cena tem
    let fim = y;
    if (s.kicker) { entra(cria(`<div class="kick" style="position:absolute;left:160px;top:${y}px">${rico(s.kicker)}</div>`), T(s.t_kicker, 0.1)); fim = y + 50; }
    if (s.titulo) {
      entra(cria(`<div class="tit" data-fit="1600,104,40" style="position:absolute;left:160px;top:${fim}px;width:1600px;font-size:76px;white-space:nowrap">${rico(s.titulo)}</div>`), T(s.t_titulo, 0.2), "impacto");
      fim += 120;
    }
    return fim;
  }

  function particulas(n, semente) {
    let r = semente >>> 0 || 7;
    const sorte = () => (r = (r * 1664525 + 1013904223) >>> 0) / 4294967296;
    const caixa = cria('<div style="position:absolute;left:0;top:0;width:1920px;height:1080px"></div>');
    const ps = [];
    for (let i = 0; i < n; i++) {
      const p = cria(`<i style="position:absolute;border-radius:50%;background:var(--acc);opacity:${(.12 + sorte() * .4).toFixed(2)}"></i>`, caixa);
      const tam = 2 + sorte() * 4;
      p.style.width = p.style.height = tam + "px";
      ps.push([p, sorte() * 1920, sorte() * 1080, (sorte() - .5) * 34, (sorte() - .5) * 22]);
    }
    passos.push(t => ps.forEach(([p, x, y, vx, vy]) => { p.style.left = (x + vx * t) + "px"; p.style.top = (y + vy * t) + "px"; }));
  }

  // ------------------------------------------------------------------------------------------------- as 24 cenas
  const CENAS = {
    abertura() {
      particulas(70, 11);
      const caixa = cria('<div style="position:absolute;left:0;top:150px;width:1920px;height:600px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px"></div>');
      if (s.kicker) entra(cria(`<div class="kick">${rico(s.kicker)}</div>`, caixa), 0.1);
      const nome = cria('<div class="tit" data-fit="1600,240,60" style="font-size:150px;text-align:center;width:1600px"></div>', caixa);
      // letra a letra, com o *destaque* na cor do canal (sem isso os asteriscos apareciam na tela)
      const letras = [];
      String(s.titulo || "").split(/(\*[^*]+\*)/).filter(Boolean).forEach(parte => {
        const forte = /^\*.+\*$/.test(parte);
        [...parte.replace(/\*/g, "")].forEach(c => letras.push([c, forte]));
      });
      const passo = Math.min(0.045, 1.2 / Math.max(1, letras.length));
      letras.forEach(([c, forte], i) => entra(cria(`<span style="display:inline-block${forte ? ";color:var(--acc)" : ""}">${c === " " ? "&nbsp;" : esc(c)}</span>`, nome),
                                              T(s.t_titulo, 0.2) + i * passo, "sobe", 0.4));
      const barra = cria('<div style="height:8px;border-radius:4px;background:var(--acc);width:640px"></div>', caixa);
      barra.style.transformOrigin = "50% 50%";
      entra(barra, T(s.t_titulo, 0.2) + 0.7, "risca", 0.6);
      if (s.sub) entra(cria(`<div class="sub" data-fit="1500,110,26" style="text-align:center;width:1500px">${rico(s.sub)}</div>`, caixa), T(s.t_sub, 1.2));
    },

    capitulo() {
      const y = s.sub ? 300 : 350;
      if (s.kicker) entra(cria(`<div class="kick" style="position:absolute;left:160px;top:${y - 64}px">${rico(s.kicker)}</div>`), T(s.t_kicker, 0.1));
      entra(cria(`<div class="tit" data-fit="1560,260,56" style="position:absolute;left:160px;top:${y}px;width:1560px;font-size:118px">${rico(s.titulo)}</div>`), T(s.t_titulo, 0.3), "impacto");
      const linha = cria(`<div style="position:absolute;left:162px;top:${y + 290}px;width:420px;height:10px;border-radius:5px;background:var(--acc);transform-origin:0 50%"></div>`);
      entra(linha, T(s.t_titulo, 0.3) + 0.35, "risca", 0.6);
      if (s.sub) entra(cria(`<div class="sub" data-fit="1500,120,26" style="position:absolute;left:160px;top:${y + 330}px;width:1500px">${rico(s.sub)}</div>`), T(s.t_sub, 1.0));
    },

    pergunta() {
      // o ? de fundo é desenho (SVG), não texto: um ? de 1.100 px saía da tela e a conferência reprovava a cena
      entra(cria('<div style="position:absolute;left:1380px;top:90px;width:420px;height:700px;opacity:.08"><svg viewBox="0 0 24 40" width="420" height="700"><path d="M4 11a8 8 0 1 1 13 6.3c-2.6 2-4 3.3-4 6.7v2" fill="none" stroke="var(--acc)" stroke-width="5" stroke-linecap="round"/><circle cx="13" cy="35" r="3" fill="var(--acc)"/></svg></div>'), 0, "surge", 1.2);
      if (s.kicker) entra(cria(`<div class="kick" style="position:absolute;left:160px;top:250px">${rico(s.kicker)}</div>`), T(s.t_kicker, 0.1));
      entra(cria(`<div class="tit" data-fit="1300,470,48" style="position:absolute;left:160px;top:310px;width:1300px;font-size:100px">${rico(s.texto)}</div>`), T(s.t, 0.3), "impacto");
    },

    frase() {
      const caixa = cria('<div style="position:absolute;left:180px;top:150px;width:1560px;height:620px;display:flex;align-items:center;justify-content:center"></div>');
      const texto = cria(`<div class="tit" data-fit="1560,560,44" style="font-size:88px;text-align:center;width:1560px"></div>`, caixa);
      texto.innerHTML = esc(s.texto).replace(/\*(.+?)\*/g, '<span class="d" style="position:relative;display:inline-block">$1<i class="sublinha" style="position:absolute;left:0;right:0;bottom:-6px;height:10px;border-radius:5px;background:var(--acc2);transform-origin:0 50%"></i></span>');
      entra(texto, T(s.t, 0.25), "sobe", 0.7);
      texto.querySelectorAll(".sublinha").forEach(e => entra(e, T(s.t_destaque, T(s.t, 0.25) + 0.7), "risca", 0.5));
    },

    numero() {
      const tv = T(s.t, 0.3), y = s.legenda ? 210 : 320;
      const anel = cria('<div style="position:absolute;left:660px;top:' + (y - 90) + 'px;width:600px;height:600px;border-radius:50%;border:3px solid var(--acc);opacity:0"></div>');
      passos.push(t => { const p = lim((t - tv) / 0.9); anel.style.opacity = p > 0 && p < 1 ? (1 - p) * 0.5 : 0; anel.style.transform = `scale(${0.5 + p * 0.9})`; });
      const linha = cria(`<div class="num" data-fit="1640,300,90" style="position:absolute;left:140px;top:${y}px;width:1640px;text-align:center;font-size:260px;color:var(--acc)"></div>`);
      linha.innerHTML = `${esc(s.prefixo || "")}<span class="contagem">${esc(s.valor || "")}</span>${esc(s.sufixo || "")}`;
      entra(linha, tv, "impacto");
      if (s.contar && typeof s.numero === "number") conta(linha.querySelector(".contagem"), s.numero, s.casas || 0, tv, 1.1);
      if (s.legenda) entra(cria(`<div data-fit="1560,150,28" style="position:absolute;left:180px;top:${y + 330}px;width:1560px;text-align:center;font:700 54px var(--f-txt);line-height:1.2">${rico(s.legenda)}</div>`), T(s.t_legenda, tv + 0.5));
      if (s.nota) entra(cria(`<div class="mut" data-fit="1500,80,22" style="position:absolute;left:210px;top:${y + 490}px;width:1500px;text-align:center;font:500 32px var(--f-txt)">${rico(s.nota)}</div>`), T(s.t_nota, tv + 1.0));
    },

    lista() {
      const itens = s.itens || [], n = itens.length;
      const y0 = cabeca(140) + 20, passo = Math.min(126, (790 - y0) / Math.max(1, n));
      itens.forEach((it, i) => {
        const linha = cria(`<div style="position:absolute;left:160px;top:${y0 + i * passo}px;width:1600px;display:flex;gap:30px;align-items:center"></div>`);
        cria(`<div class="selo">${i + 1}</div>`, linha);
        cria(`<div data-fit="1480,${passo - 12},24" style="font:700 ${n > 4 ? 40 : 48}px var(--f-txt);line-height:1.2;width:1480px">${rico(it.texto)}</div>`, linha);
        entra(linha, it.t, "esquerda", 0.45);
      });
    },

    checklist() {
      const itens = s.itens || [], n = itens.length;
      const y0 = cabeca(140) + 20, passo = Math.min(120, (790 - y0) / Math.max(1, n));
      itens.forEach((it, i) => {
        const linha = cria(`<div style="position:absolute;left:160px;top:${y0 + i * passo}px;width:1600px;display:flex;gap:28px;align-items:center"></div>`);
        const caixa = cria('<div style="flex:none;width:70px;height:70px;border-radius:16px;border:4px solid var(--linha);position:relative"></div>', linha);
        const marca = cria(`<div style="position:absolute;left:-4px;top:-4px;width:70px;height:70px;border-radius:16px;background:var(--ok);display:flex;align-items:center;justify-content:center">${icone("certo", 46, "var(--tinta)")}</div>`, caixa);
        cria(`<div data-fit="1490,${passo - 12},24" style="font:700 46px var(--f-txt);line-height:1.2;width:1490px">${rico(it.texto)}</div>`, linha);
        entra(linha, it.t, "esquerda", 0.4);
        entra(marca, it.t + 0.3, "escala", 0.35);
      });
    },

    passos() {
      const itens = s.itens || [], n = Math.max(1, itens.length);
      const y0 = Math.max(cabeca(170) + 40, 360), vao = 46, w = Math.min(340, (1620 - (n - 1) * vao) / n);
      const x0 = (1920 - (n * w + (n - 1) * vao)) / 2;
      itens.forEach((it, i) => {
        const x = x0 + i * (w + vao), forte = i === s.destaque;
        const card = cria(`<div class="card" style="left:${x}px;top:${y0}px;width:${w}px;height:320px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:26px;text-align:center;border:3px solid ${forte ? "var(--acc)" : "var(--linha)"}"></div>`);
        cria(`<div class="num" style="font-size:84px;color:var(--acc)">${i + 1}</div>`, card);
        cria(`<div data-fit="${w - 52},170,22" style="font:700 32px var(--f-txt);line-height:1.22;width:${w - 52}px">${rico(it.texto)}</div>`, card);
        entra(card, it.t, "escala", 0.5);
        if (i < n - 1) entra(cria(`<div style="position:absolute;left:${x + w + 4}px;top:${y0 + 140}px;width:38px;height:38px">${icone("seta", 38, "var(--mut)")}</div>`), it.t + 0.25, "surge", 0.3);
      });
    },

    comparar() {
      const lados = [[s.esq || {}, s.neutro ? "var(--acc2)" : "var(--verm)", s.neutro ? "seta" : "errado", 140, "esquerda"],
                     [s.dir || {}, s.neutro ? "var(--acc)" : "var(--ok)", s.neutro ? "seta" : "certo", 990, "direita"]];
      lados.forEach(([c, cor, ic, x, jeito]) => {
        const card = cria(`<div class="card" style="left:${x}px;top:150px;width:790px;min-height:380px;max-height:640px;padding:50px 54px 56px;border-top:10px solid ${cor}"></div>`);
        cria(`<div class="tit" data-fit="680,100,30" style="font-size:72px;color:${cor};width:680px;white-space:nowrap">${rico(c.titulo)}</div>`, card);
        entra(card, c.t, jeito, 0.5);
        (c.itens || []).forEach((it, i) => {
          const linha = cria(`<div style="margin-top:${i ? 28 : 44}px;display:flex;gap:20px;align-items:flex-start"></div>`, card);
          cria(icone(ic, 48, cor), linha);
          cria(`<div data-fit="610,120,24" style="font:600 44px var(--f-txt);line-height:1.25;width:610px">${rico(it.texto)}</div>`, linha);
          entra(linha, it.t, "esquerda", 0.4);
        });
      });
    },

    barras() {
      const itens = s.itens || [], n = Math.max(1, itens.length);
      const maior = Math.max(1e-9, ...itens.map(x => Math.abs(+x.valor || 0)));
      const y0 = cabeca(140) + 50, passo = Math.min(130, (740 - y0) / n);
      itens.forEach((it, i) => {
        const y = y0 + i * passo, largura = 900 * Math.abs(+it.valor || 0) / maior;
        entra(cria(`<div data-fit="480,${passo - 16},20" style="position:absolute;left:160px;top:${y}px;width:480px;font:700 36px var(--f-txt);line-height:1.15">${rico(it.rotulo)}</div>`), it.t, "esquerda", 0.4);
        const barra = cria(`<div style="position:absolute;left:680px;top:${y - 4}px;height:60px;border-radius:30px;background:${i === s.destaque || (s.destaque == null && i === 0) ? "var(--acc)" : "var(--acc2)"};width:0"></div>`);
        const valor = cria(`<div class="num" style="position:absolute;top:${y + 2}px;font-size:40px">${esc(it.texto || fmt(+it.valor || 0, 0))}</div>`);
        passos.push(t => { const p = sai((t - it.t) / 0.9); barra.style.width = (largura * p) + "px"; valor.style.left = (700 + largura * p) + "px"; valor.style.opacity = lim((t - it.t - 0.4) / 0.3); });
      });
      if (s.fonte) entra(cria(`<div class="fonte" style="position:absolute;left:160px;top:770px">Fonte: ${rico(s.fonte)}</div>`), T(s.t_fonte, DUR * 0.6), "surge");
    },

    linha_do_tempo() {
      const itens = s.itens || [], n = Math.max(1, itens.length);
      const x0 = 230, x1 = 1690, y = (s.titulo || s.kicker) ? 520 : 470;
      cabeca(140);
      cria(`<div class="trilho" style="left:${x0}px;top:${y}px;width:${x1 - x0}px"></div>`);
      const cheio = cria(`<div class="cheio" style="left:${x0}px;top:${y}px;width:0"></div>`);
      const px = i => n === 1 ? (x0 + x1) / 2 : x0 + (x1 - x0) * i / (n - 1);
      const larg = Math.min(380, (x1 - x0) / n + 60);
      passos.push(t => {
        let w = 0;
        itens.forEach((it, i) => { if (t >= it.t) w = px(i) - x0; else if (i > 0 && t > itens[i - 1].t) w = Math.max(w, px(i - 1) - x0 + (px(i) - px(i - 1)) * sai((t - itens[i - 1].t) / Math.max(0.3, it.t - itens[i - 1].t))); });
        cheio.style.width = w + "px";
      });
      itens.forEach((it, i) => {
        const x = px(i), cima = i % 2 === 0;
        entra(cria(`<div style="position:absolute;left:${x - 24}px;top:${y - 20}px;width:48px;height:48px;border-radius:50%;background:var(--fundo);border:7px solid var(--acc)"></div>`), it.t, "escala", 0.35);
        const rot = cria(`<div style="position:absolute;left:${x - larg / 2}px;top:${cima ? y - 250 : y + 66}px;width:${larg}px;text-align:center"></div>`);
        cria(`<div class="num" data-fit="${larg},76,30" style="font-size:62px;color:var(--acc);width:${larg}px">${esc(it.data)}</div>`, rot);
        cria(`<div data-fit="${larg},120,20" style="font:600 30px var(--f-txt);line-height:1.25;margin-top:10px;width:${larg}px">${rico(it.texto)}</div>`, rot);
        entra(rot, it.t + 0.1, cima ? "desce" : "sobe", 0.45);
      });
    },

    citacao() {
      entra(cria(`<div style="position:absolute;left:150px;top:120px;width:150px;height:150px">${icone("aspas", 150, "var(--acc)")}</div>`), 0.1, "escala", 0.5);
      entra(cria(`<div data-fit="1440,430,40" style="position:absolute;left:300px;top:200px;width:1440px;font-family:var(--f-d);font-style:italic;font-weight:600;font-size:76px;line-height:1.22">${rico(s.texto)}</div>`), T(s.t, 0.3), "sobe", 0.7);
      if (s.autor) {
        const a = cria(`<div style="position:absolute;left:300px;top:680px;display:flex;gap:20px;align-items:center;font:700 36px var(--f-txt);color:var(--txt2)"><i style="width:60px;height:5px;border-radius:3px;background:var(--acc);display:inline-block"></i><span data-fit="1300,60,22" style="width:1300px">${rico(s.autor)}</span></div>`);
        entra(a, T(s.t_autor, T(s.t, 0.3) + 1.0), "esquerda");
      }
    },

    definicao() {
      const cor = s.alerta ? "var(--verm)" : "var(--acc)";
      const card = cria(`<div class="card" style="left:200px;top:120px;width:1520px;height:660px;padding:56px 70px;border-left:14px solid ${cor}"></div>`);
      const topo = cria(`<div style="display:flex;gap:20px;align-items:center"></div>`, card);
      cria(icone(s.alerta ? "alerta" : "info", 54, cor), topo);
      cria(`<div class="kick" style="color:${cor}">${esc(s.rotulo || (s.alerta ? "Atenção" : "Definição"))}</div>`, topo);
      cria(`<div class="tit" data-fit="1380,130,40" style="margin-top:26px;font-size:96px;width:1380px">${rico(s.termo)}</div>`, card);
      const def = cria(`<div class="sub" data-fit="1380,${(s.pontos || []).length ? 130 : 250},24" style="margin-top:18px;font-size:42px;width:1380px">${rico(s.definicao)}</div>`, card);
      entra(card, T(s.t, 0.2), "escala", 0.55);
      entra(def, T(s.t_definicao, T(s.t, 0.2) + 0.6), "sobe");
      (s.pontos || []).forEach((p, i) => {
        const l = cria(`<div style="margin-top:${i ? 14 : 30}px;display:flex;gap:18px;align-items:center;font:600 36px var(--f-txt)"><i style="flex:none;width:14px;height:14px;border-radius:50%;background:${cor};display:inline-block"></i><span data-fit="1340,56,20" style="width:1340px">${rico(p.texto)}</span></div>`, card);
        entra(l, p.t, "esquerda", 0.4);
      });
    },

    cartoes() {
      const itens = s.itens || [], n = Math.max(1, itens.length);
      const y0 = Math.max(cabeca(130) + 30, 300), vao = 50, w = (1620 - (n - 1) * vao) / n, x0 = 150;
      const altura = Math.min(780 - y0, 420);
      itens.forEach((it, i) => {
        const card = cria(`<div class="card" style="left:${x0 + i * (w + vao)}px;top:${y0}px;width:${w}px;height:${altura}px;padding:44px 40px;border-top:10px solid ${i % 2 ? "var(--acc2)" : "var(--acc)"}"></div>`);
        cria(`<div class="tit" data-fit="${w - 80},${Math.round(altura * 0.38)},30" style="font-size:66px;color:${i % 2 ? "var(--acc2)" : "var(--acc)"};width:${w - 80}px">${rico(it.titulo)}</div>`, card);
        cria(`<div data-fit="${w - 80},${Math.round(altura * 0.5)},22" style="margin-top:20px;font:600 42px var(--f-txt);line-height:1.3;color:var(--txt2);width:${w - 80}px">${rico(it.texto)}</div>`, card);
        entra(card, it.t, "escala", 0.5);
      });
    },

    destaques() {
      const itens = s.itens || [], n = Math.max(1, itens.length);
      const marca = s.marca || "errado", cor = marca === "estrela" ? "var(--acc)" : marca === "certo" ? "var(--ok)" : "var(--verm)";
      const y0 = cabeca(140) + 30, passo = Math.min(150, (790 - y0) / n);
      itens.forEach((it, i) => {
        const linha = cria(`<div class="card" style="left:160px;top:${y0 + i * passo}px;width:1600px;height:${passo - 22}px;display:flex;gap:30px;align-items:center;padding:0 40px"></div>`);
        cria(icone(marca, Math.min(64, passo - 50), cor), linha);
        cria(`<div data-fit="1440,${passo - 34},22" style="font:700 44px var(--f-txt);line-height:1.2;width:1440px">${rico(it.texto)}</div>`, linha);
        entra(linha, it.t, i === 0 ? "impacto" : "escala", i === 0 ? 0.38 : 0.45);
      });
    },

    fato() {
      const card = cria('<div class="card" style="left:190px;top:150px;width:1540px;height:600px;display:flex;gap:60px;align-items:center;padding:60px 70px"></div>');
      const ic = cria(`<div style="flex:none;width:250px;height:250px;border-radius:50%;background:var(--painel2);display:flex;align-items:center;justify-content:center">${icone(s.icone === "alerta" ? "alerta" : "lupa", 140, "var(--acc)")}</div>`, card);
      const col = cria('<div style="display:flex;flex-direction:column;gap:22px"></div>', card);
      if (s.kicker) cria(`<div class="kick">${rico(s.kicker)}</div>`, col);
      cria(`<div data-fit="1100,${s.fonte ? 330 : 400},30" style="font:700 54px var(--f-txt);line-height:1.25;width:1100px">${rico(s.texto)}</div>`, col);
      if (s.fonte) cria(`<div class="fonte">Fonte: ${rico(s.fonte)}</div>`, col);
      entra(card, T(s.t, 0.25), "escala", 0.55);
      entra(ic, T(s.t, 0.25) + 0.25, "impacto");
    },

    porcentagem() {
      const tv = T(s.t, 0.3), valor = lim(+s.valor || 0, 0, 100), R = 230, L = 2 * Math.PI * R;
      const g = svg(`<circle cx="620" cy="450" r="${R}" fill="none" stroke="var(--linha)" stroke-width="44"/>
        <circle class="arco" cx="620" cy="450" r="${R}" fill="none" stroke="var(--acc)" stroke-width="44" stroke-linecap="round" transform="rotate(-90 620 450)" stroke-dasharray="${L} ${L}" stroke-dashoffset="${L}"/>`);
      const arco = g.querySelector(".arco");
      const centro = cria(`<div class="num" style="position:absolute;left:390px;top:385px;width:460px;text-align:center;font-size:128px"><span class="contagem">0</span>%</div>`);
      passos.push(t => { const p = sai((t - tv) / 1.3); arco.style.strokeDashoffset = L * (1 - p * valor / 100); centro.querySelector(".contagem").textContent = fmt(valor * p, s.casas || 0); });
      entra(centro, tv, "escala", 0.45);
      entra(cria(`<div data-fit="780,420,30" style="position:absolute;left:960px;top:260px;width:780px;font:700 58px var(--f-txt);line-height:1.22">${rico(s.legenda)}</div>`), T(s.t_legenda, tv + 0.5), "direita");
    },

    antes_depois() {
      const a = s.antes || {}, d = s.depois || {};
      const bloco = (lado, x, cor) => {
        const b = cria(`<div class="card" style="left:${x}px;top:200px;width:640px;height:440px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;padding:30px;text-align:center"></div>`);
        cria(`<div class="kick" style="color:var(--mut)">${rico(lado.rotulo)}</div>`, b);
        cria(`<div class="num" data-fit="580,190,60" style="font-size:150px;color:${cor};width:580px">${esc(lado.valor)}</div>`, b);
        return b;
      };
      entra(bloco(a, 150, "var(--txt2)"), T(a.t, 0.25), "esquerda");
      const seta = svg('<path d="M820 420 C 900 360, 1020 360, 1100 420" fill="none" stroke="var(--acc)" stroke-width="10" stroke-linecap="round"/><path d="M1078 392 L1104 424 L1066 438" fill="none" stroke="var(--acc)" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>');
      seta.querySelectorAll("path").forEach(p => desenha(p, T(d.t, 1.2) - 0.45, 0.45));
      entra(bloco(d, 1130, "var(--acc)"), T(d.t, 1.2), "impacto");
      if (s.legenda) entra(cria(`<div data-fit="1560,110,24" style="position:absolute;left:180px;top:680px;width:1560px;text-align:center;font:700 44px var(--f-txt)">${rico(s.legenda)}</div>`), T(s.t_legenda, T(d.t, 1.2) + 0.5));
    },

    ranking() {
      const itens = s.itens || [], n = Math.max(1, itens.length);
      const y0 = cabeca(130) + 20, passo = Math.min(122, (790 - y0) / n);
      itens.forEach((it, i) => {
        const forte = i === s.destaque;
        const linha = cria(`<div style="position:absolute;left:160px;top:${y0 + i * passo}px;width:1600px;height:${passo - 18}px;border-radius:20px;display:flex;gap:34px;align-items:center;padding:0 34px;background:${forte ? "var(--acc)" : "var(--painel)"};color:${forte ? "var(--tinta)" : "var(--txt)"};border:1px solid var(--linha)"></div>`);
        cria(`<div class="num" style="flex:none;width:110px;font-size:${Math.min(64, passo - 40)}px">${i + 1}º</div>`, linha);
        cria(`<div data-fit="1380,${passo - 30},22" style="font:700 44px var(--f-txt);line-height:1.15;width:1380px">${rico(it.texto)}</div>`, linha);
        entra(linha, it.t, forte ? "impacto" : "direita", forte ? 0.38 : 0.45);
      });
    },

    causa_efeito() {
      const itens = s.itens || [], n = Math.max(1, itens.length);
      const w = 560, h = 132, dx = n > 1 ? Math.min(360, (1620 - w) / (n - 1)) : 0, dy = n > 1 ? Math.min(165, (650 - h) / (n - 1)) : 0;
      const x0 = (1920 - (w + dx * (n - 1))) / 2, y0 = 130;
      itens.forEach((it, i) => {
        const x = x0 + i * dx, y = y0 + i * dy;
        const card = cria(`<div class="card" style="left:${x}px;top:${y}px;width:${w}px;height:${h}px;display:flex;align-items:center;gap:22px;padding:0 30px;border-left:10px solid ${i === n - 1 ? "var(--acc2)" : "var(--acc)"}"></div>`);
        cria(`<div data-fit="${w - 70},${h - 24},20" style="font:700 36px var(--f-txt);line-height:1.2;width:${w - 70}px">${rico(it.texto)}</div>`, card);
        entra(card, it.t, "escala", 0.45);
        if (i < n - 1) {
          const g = svg(`<path d="M${x + 120} ${y + h + 6} C ${x + 120} ${y + h + dy * 0.55}, ${x + dx * 0.5} ${y + dy + h * 0.5}, ${x + dx - 8} ${y + dy + h * 0.5}" fill="none" stroke="var(--mut)" stroke-width="5" stroke-linecap="round" stroke-dasharray="2 12"/>`);
          desenha(g.querySelector("path"), Math.max(it.t + 0.2, (itens[i + 1].t || it.t + 1) - 0.5), 0.5);
        }
      });
    },

    proporcao() {
      const total = Math.max(2, Math.min(100, Math.round(+s.total || 10))), parte = Math.max(0, Math.min(total, Math.round(+s.parte || 1)));
      const tv = T(s.t, 0.3), colunas = total <= 10 ? total : total <= 20 ? 10 : 10, linhas = Math.ceil(total / colunas);
      const tam = total <= 10 ? 110 : total <= 20 ? 84 : 52, vao = total <= 20 ? 26 : 14;
      const largura = colunas * tam + (colunas - 1) * vao, embaixo = total <= 20;
      const x0 = embaixo ? (1920 - largura) / 2 : 160, y0 = embaixo ? 150 : 400 - (linhas * (tam + vao)) / 2;
      for (let k = 0; k < total; k++) {
        const x = x0 + (k % colunas) * (tam + vao), y = y0 + Math.floor(k / colunas) * (tam + vao);
        const forma = total <= 20 ? icone("pessoa", tam, k < parte ? "var(--acc)" : "var(--linha)")
                                  : `<span style="display:block;width:${tam}px;height:${tam}px;border-radius:50%;background:${k < parte ? "var(--acc)" : "var(--linha)"}"></span>`;
        entra(cria(`<div style="position:absolute;left:${x}px;top:${y}px">${forma}</div>`), tv + Math.min(1.2, 1.2 * k / total), k < parte ? "escala" : "surge", 0.3);
      }
      const fimGrade = y0 + linhas * (tam + vao);
      const xl = embaixo ? 160 : x0 + largura + 80, wl = embaixo ? 1600 : 1770 - xl;
      const alinha = embaixo ? "text-align:center;" : "";
      entra(cria(`<div class="num" data-fit="${wl},170,60" style="position:absolute;left:${xl}px;top:${embaixo ? fimGrade + 30 : 220}px;width:${wl}px;${alinha}font-size:${embaixo ? 130 : 150}px;color:var(--acc)">${esc(s.rotulo || (parte + " em " + total))}</div>`), tv + 1.3, "impacto");
      if (s.legenda) entra(cria(`<div data-fit="${wl},${embaixo ? 150 : 300},24" style="position:absolute;left:${xl}px;top:${embaixo ? fimGrade + 190 : 420}px;width:${wl}px;${alinha}font:700 46px var(--f-txt);line-height:1.22">${rico(s.legenda)}</div>`), T(s.t_legenda, tv + 1.7));
    },

    documento() {
      const casca = cria('<div style="position:absolute;left:400px;top:100px;width:1120px;height:700px"></div>');
      const folha = cria('<div class="papel" style="position:absolute;left:0;top:0;width:1120px;height:700px;transform:rotate(-1.6deg);border-radius:6px;box-shadow:0 30px 70px var(--sombra);padding:70px 90px"></div>', casca);
      cria(`<div data-fit="940,110,30" style="font:800 56px var(--f-d);width:940px;line-height:1.1">${rico(s.titulo)}</div>`, folha);
      cria('<div style="height:4px;background:#1E1B16;margin:24px 0 30px;opacity:.75"></div>', folha);
      entra(casca, T(s.t, 0.2), "escala", 0.55);
      (s.linhas || []).forEach((l, i) => {
        const e = cria(`<div data-fit="940,58,20" style="font:500 38px var(--f-txt);line-height:1.45;width:940px;white-space:nowrap">${rico(l.texto)}</div>`, folha);
        const t0 = l.t, d = Math.max(0.5, Math.min(1.4, String(l.texto).length * 0.035));
        passos.push(t => { const p = lim((t - t0) / d); e.style.clipPath = `inset(0 ${100 - p * 100}% 0 0)`; e.style.opacity = p > 0 ? 1 : 0; });
      });
      if (s.carimbo) {
        const c = cria(`<div style="position:absolute;right:60px;bottom:70px;transform:rotate(-9deg)"><div class="carimbo">${esc(s.carimbo)}</div></div>`, folha);
        entra(c.firstElementChild, T(s.t_carimbo, DUR - 1.2), "impacto");
      }
    },

    manchete() {
      const casca = cria('<div style="position:absolute;left:260px;top:110px;width:1400px;height:680px"></div>');
      const folha = cria('<div class="papel" style="position:absolute;left:0;top:0;width:1400px;height:680px;transform:rotate(1.2deg);box-shadow:0 30px 70px var(--sombra);padding:46px 80px"></div>', casca);
      cria(`<div style="display:flex;justify-content:space-between;align-items:flex-end;font:900 64px var(--f-d);letter-spacing:2px"><span>${esc(s.veiculo || "")}</span><span style="font:600 26px var(--f-txt)">${esc(s.data || "")}</span></div>`, folha);
      cria('<div style="height:3px;background:#1E1B16;margin:18px 0 6px"></div><div style="height:1px;background:#1E1B16;margin-bottom:34px"></div>', folha);
      const tit = cria(`<div data-fit="1240,330,40" style="font:800 92px var(--f-d);line-height:1.06;width:1240px">${rico(s.titulo)}</div>`, folha);
      tit.querySelectorAll(".d").forEach(e => { e.style.color = "var(--verm)"; e.style.fontStyle = "normal"; });
      if (s.sub) cria(`<div data-fit="1240,100,22" style="margin-top:26px;font:500 36px var(--f-txt);line-height:1.3;color:#3B3630;width:1240px">${rico(s.sub)}</div>`, folha);
      entra(casca, T(s.t, 0.25), "impacto");
    },

    encerramento() {
      particulas(50, 23);
      const caixa = cria('<div style="position:absolute;left:0;top:140px;width:1920px;height:640px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:40px"></div>');
      entra(cria(`<div class="tit" data-fit="1500,250,44" style="font-size:96px;text-align:center;width:1500px">${rico(s.texto)}</div>`, caixa), T(s.t, 0.2), "sobe");
      const linha = cria('<div style="display:flex;gap:30px;align-items:center"></div>', caixa);
      const botao = cria(`<div style="background:var(--verm);color:#fff;font:800 46px var(--f-txt);letter-spacing:2px;padding:24px 56px;border-radius:16px">${esc(s.botao || "INSCREVER-SE")}</div>`, linha);
      const sino = cria(`<div style="width:100px;height:100px;border-radius:50%;background:var(--painel);border:1px solid var(--linha);display:flex;align-items:center;justify-content:center">${icone("sino", 56, "var(--acc)")}</div>`, linha);
      entra(linha, T(s.t_botao, T(s.t, 0.2) + 0.6), "escala", 0.5);
      const clique = T(s.t_botao, T(s.t, 0.2) + 0.6) + 0.9;
      passos.push(t => { const k = t - clique; botao.style.transform = k > 0 && k < 0.3 ? `scale(${1 - 0.08 * Math.sin(k / 0.3 * Math.PI)})` : ""; if (k > 0) botao.style.background = "var(--mut)"; sino.style.transform = k > 0.2 && k < 1.0 ? `rotate(${Math.sin((k - 0.2) * 22) * 16 * (1 - (k - 0.2) / 0.8)}deg)` : ""; });
      if (s.proximo) entra(cria(`<div class="card" style="position:relative;padding:22px 40px;display:flex;gap:20px;align-items:center"><span class="kick" style="color:var(--mut)">Próximo vídeo</span><span data-fit="900,60,22" style="font:700 40px var(--f-txt);width:900px">${rico(s.proximo)}</span></div>`, caixa), T(s.t_proximo, DUR * 0.6), "sobe");
    },
  };

  // ------------------------------------------------------------------------------------------------- montar e mover
  cria('<div class="fundo"></div>');
  cria('<div class="pontos"></div>');
  if (A.canal) root.appendChild(Object.assign(document.createElement("div"), { className: "canal", innerHTML: `<i></i>${esc(A.canal)}` }));
  (CENAS[A.tipo] || CENAS.frase)();
  root.appendChild(Object.assign(document.createElement("div"), { className: "vinheta" }));
  root.appendChild(Object.assign(document.createElement("div"), { className: "faixa-legenda" }));

  function encaixar() {
    document.querySelectorAll("[data-fit]").forEach(e => {
      const [w, h, minimo] = e.dataset.fit.split(",").map(Number);
      if (!e.dataset.fs0) e.dataset.fs0 = parseFloat(getComputedStyle(e).fontSize);
      let fs = +e.dataset.fs0;
      e.style.fontSize = fs + "px";
      while ((e.scrollHeight > h + 2 || e.scrollWidth > w + 2) && fs > minimo) { fs -= 2; e.style.fontSize = fs + "px"; }
    });
  }

  let ultimo = 0;
  function quadro(t) {
    ultimo = t;
    // câmera: chega assentando nos primeiros 0,5 s e aproxima devagar até o fim; treme curto em cada impacto
    const z = 1 + 0.03 * (t / DUR) + 0.035 * (1 - sai(t / 0.5));
    let dx = 0, dy = 0;
    for (const ti of impactos) { const k = t - ti; if (k > 0 && k < 0.28) { const a = 7 * (1 - k / 0.28); dx += Math.sin(k * 95) * a; dy += Math.cos(k * 71) * a * 0.6; } }
    palco.style.transform = `translate(${dx.toFixed(2)}px,${dy.toFixed(2)}px) scale(${z.toFixed(4)})`;
    for (const x of entradas) {
      const p = lim((t - x.t) / x.d);
      let o = p, tr = "";
      if (x.jeito === "sobe") { o = sai(p); tr = `translateY(${((1 - sai(p)) * 38).toFixed(2)}px)`; }
      else if (x.jeito === "desce") { o = sai(p); tr = `translateY(${((1 - sai(p)) * -38).toFixed(2)}px)`; }
      else if (x.jeito === "esquerda") { o = sai(p); tr = `translateX(${((1 - sai(p)) * -70).toFixed(2)}px)`; }
      else if (x.jeito === "direita") { o = sai(p); tr = `translateX(${((1 - sai(p)) * 70).toFixed(2)}px)`; }
      else if (x.jeito === "escala") { o = lim(p * 2.2); tr = `scale(${(0.82 + 0.18 * mola(p)).toFixed(4)})`; }
      else if (x.jeito === "impacto") { const k = lim((t - x.t) / 0.38); o = lim((t - x.t) / 0.08); tr = `scale(${(k < 1 ? 1 + 0.36 * Math.pow(1 - k, 3) : 1).toFixed(4)})`; }
      else if (x.jeito === "risca") { o = t >= x.t ? 1 : 0; tr = `scaleX(${sai(p).toFixed(4)})`; }
      x.e.style.opacity = o;
      x.e.style.transform = tr;
    }
    for (const f of passos) f(t);
  }

  encaixar();
  quadro(0);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { encaixar(); quadro(ultimo); });

  const relogio = { t: 0 };
  const tl = gsap.timeline({ paused: true });
  tl.to(relogio, { t: DUR, duration: DUR, ease: "none", onUpdate: () => quadro(relogio.t) }, 0);
  window.__timelines = window.__timelines || {};
  window.__timelines["main"] = tl;
  window.quadro = quadro;
})();
