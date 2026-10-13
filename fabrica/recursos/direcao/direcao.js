/* direção (fabrica/direcao.py): o motor das cenas dirigidas, as que têm câmera, tipografia cinética, formas que se
   transformam e cartões em 3D, no lugar dos modelos prontos do motor.js.

   Regras, as mesmas do motor.js:
   1. O Python manda window.DIR = {spec, dur, formato}. Os tempos de cada elemento já vêm resolvidos pela fala
      (camada.t, camada.ts, camera[i].t...): quem acha o segundo de cada palavra é o Python.
   2. quadro(t) é função PURA do tempo. Câmera, entradas, formas, contagens e o cenário saem só de t (e da semente do
      desenho). O mesmo quadro sai igual em toda gravação. Nada de relógio do computador, animação em CSS ou sorteio
      sem semente: o sorteio é o `sorteio(semente)` abaixo, que sempre dá a mesma sequência.
   3. O mesmo desenho serve para a tela deitada (1920x1080) e em pé (1080x1920). Em pé o código NÃO corta nem estica:
      ele recompõe, com as âncoras de cada formato (ANC_H e ANC_V), outro tamanho de letra e a área segura de cima
      e de baixo, onde ficam a legenda e os botões do app. */
(function () {
  const D = window.DIR, S = D.spec, DUR = D.dur, V = D.formato === "vertical";
  const W = V ? 1080 : 1920, H = V ? 1920 : 1080;
  const root = document.getElementById("root"), palco = document.getElementById("palco");
  const passos = [], paralaxe = [];

  const lim = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, k) => a + (b - a) * k;
  const EASE = {
    linear: x => lim(x),
    suave: x => { x = lim(x); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; },
    sai: x => 1 - Math.pow(1 - lim(x), 3),
    entra: x => Math.pow(lim(x), 3),
    mola: x => { x = lim(x); const c = 1.70158; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); },
    organico: x => { x = lim(x); return x * x * (3 - 2 * x); },
  };
  const ease = (nome, x) => (EASE[nome] || EASE.suave)(x);
  const RITMO = { lento: 1.6, normal: 1, rapido: 0.7 }[S.ritmo] || 1;
  const T = (v, padrao) => (typeof v === "number" && isFinite(v) ? v : padrao);
  const esc = v => String(v == null ? "" : v).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, casas) => Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
  const css = nome => getComputedStyle(root).getPropertyValue("--" + nome).trim();

  // sorteio com semente (mulberry32): a mesma semente dá sempre a mesma sequência
  function sorteio(semente) {
    let a = (semente >>> 0) || 7;
    return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function hexa(cor, a) {
    const m = /^#?([0-9a-f]{6})$/i.exec(cor || "");
    if (!m) return cor;
    const n = parseInt(m[1], 16);
    return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }
  function cria(html, pai) {
    const m = document.createElement("template");
    m.innerHTML = html.trim();
    const e = m.content.firstElementChild;
    (pai || palco).appendChild(e);
    return e;
  }

  // ----------------------------------------------------------------------------------------------- composição por formato
  // âncoras em fração da tela. Em pé: nada de lado a lado (esq/dir viram um em cima do outro) e nada nos 14% de cima
  // nem nos 30% de baixo, onde ficam a legenda e os botões do app
  const ANC_H = { centro: [.5, .46], alto: [.5, .25], baixo: [.5, .62], esq: [.27, .46], dir: [.73, .46],
                  "alto-esq": [.27, .28], "alto-dir": [.73, .28], "baixo-esq": [.27, .64], "baixo-dir": [.73, .64] };
  const ANC_V = { centro: [.5, .42], alto: [.5, .26], baixo: [.5, .58], esq: [.5, .27], dir: [.5, .57],
                  "alto-esq": [.5, .24], "alto-dir": [.5, .33], "baixo-esq": [.5, .5], "baixo-dir": [.5, .6] };
  const TAM = V ? { xl: 132, g: 98, m: 68, p: 44 } : { xl: 170, g: 122, m: 84, p: 52 };
  function ancora(L) {
    const pos = (V && L.pos_v) || L.pos || "centro";
    if (Array.isArray(pos)) return [lim(+pos[0], .05, .95), lim(+pos[1], .08, V ? .7 : .78)];
    const a = (V ? ANC_V : ANC_H)[pos] || (V ? ANC_V : ANC_H).centro;
    return a;
  }
  function larguraMax(L) {
    const pos = (V && L.pos_v) || L.pos || "centro";
    if (!V && (pos === "esq" || pos === "dir" || /-(esq|dir)$/.test(pos))) return Math.round(W * .42);
    return Math.round(W * (V ? .86 : .8));
  }
  const tamanho = L => (TAM[L.tamanho] || TAM.g);

  // ----------------------------------------------------------------------------------------------- câmera
  const cam = (S.camera || []).map(k => ({ t: T(k.t, 0), zoom: T(k.zoom, 1), x: T(k.x, 0), y: T(k.y, 0), rot: T(k.rot, 0), ease: k.ease || "suave" }))
    .sort((a, b) => a.t - b.t);
  if (!cam.length) cam.push({ t: 0, zoom: 1, x: 0, y: 0, rot: 0, ease: "suave" });
  if (S.loop) cam.push(Object.assign({}, cam[0], { t: DUR }));   // o fim volta ao começo: o vídeo emenda
  function camera(t) {
    if (t <= cam[0].t) return cam[0];
    for (let i = 0; i < cam.length - 1; i++) {
      const a = cam[i], b = cam[i + 1];
      if (t < b.t) {
        const k = ease(b.ease, (t - a.t) / Math.max(1e-6, b.t - a.t));
        return { zoom: lerp(a.zoom, b.zoom, k), x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k), rot: lerp(a.rot, b.rot, k) };
      }
    }
    return cam[cam.length - 1];
  }

  // ----------------------------------------------------------------------------------------------- cenário (canvas 2D)
  const CW = Math.round(W * 1.3), CH = Math.round(H * 1.3);
  const cv = document.createElement("canvas");
  cv.id = "cenario"; cv.width = CW; cv.height = CH;
  palco.appendChild(cv);
  const ctx = cv.getContext("2d");
  const CEN = Object.assign({ estilo: "particulas", ciclos: 1, seed: 7, densidade: 1 }, S.cenario || {});
  const rnd = sorteio(CEN.seed);
  const base = Array.from({ length: 140 }, () => [rnd(), rnd(), rnd(), rnd()]);   // x, y, tamanho, velocidade (fixos)

  function fundo(t) {
    const f = css("fundo"), f2 = css("fundo2") || f, acc = css("acc");
    const g = ctx.createLinearGradient(0, 0, 0, CH);
    g.addColorStop(0, f); g.addColorStop(1, f2);
    ctx.globalAlpha = 1; ctx.fillStyle = g; ctx.fillRect(0, 0, CW, CH);
    // brilho que passeia em círculo (volta ao mesmo lugar no fim da cena)
    const a = 2 * Math.PI * t / DUR;
    const cx = CW * (.68 + .1 * Math.cos(a)), cy = CH * (.3 + .08 * Math.sin(a));
    const r = ctx.createRadialGradient(cx, cy, 0, cx, cy, CW * .55);
    r.addColorStop(0, hexa(acc, .16)); r.addColorStop(1, hexa(acc, 0));
    ctx.fillStyle = r; ctx.fillRect(0, 0, CW, CH);
  }
  // a vinheta escurece só o cenário (não passa por cima do texto: a conferência do HyperFrames a leria como um
  // elemento opaco cobrindo as palavras)
  function vinheta() {
    const v = ctx.createRadialGradient(CW / 2, CH * .46, Math.min(CW, CH) * .3, CW / 2, CH * .46, Math.max(CW, CH) * .72);
    v.addColorStop(0, "rgba(0,0,0,0)"); v.addColorStop(1, css("vinheta") || "rgba(0,0,0,.6)");
    ctx.fillStyle = v; ctx.fillRect(0, 0, CW, CH);
  }
  const ESTILOS = {
    nenhum() {},
    grade(t, fr) {
      const acc = css("acc"), y0 = CH * .56, vx = CW / 2 + Math.sin(2 * Math.PI * fr) * CW * .02;
      ctx.lineWidth = 2;
      for (let i = -24; i <= 24; i++) { ctx.strokeStyle = hexa(acc, .2); ctx.beginPath(); ctx.moveTo(vx, y0); ctx.lineTo(vx + i * CW * .12, CH); ctx.stroke(); }
      const N = 14;
      for (let k = 0; k < N; k++) {
        const z = ((k + fr * CEN.ciclos * N * .5) % N) / N, y = y0 + (CH - y0) * z * z;
        ctx.strokeStyle = hexa(acc, .06 + .3 * z); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(CW, y); ctx.stroke();
      }
    },
    pontos(t, fr) {
      const acc = css("acc"), passo = 56 * (CW / 1920 > .7 ? 1 : .8), ph = 2 * Math.PI * fr * CEN.ciclos;
      for (let y = passo / 2; y < CH; y += passo) for (let x = passo / 2; x < CW; x += passo) {
        const r = 2.2 * (.65 + .35 * Math.sin(x * .011 + y * .014 + ph));
        ctx.fillStyle = hexa(acc, .1 + .18 * (.5 + .5 * Math.sin(x * .004 - y * .006 + ph)));
        ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
      }
    },
    ondas(t, fr) {
      const acc = css("acc"), acc2 = css("acc2") || acc, ph = 2 * Math.PI * fr * CEN.ciclos;
      for (let i = 0; i < 5; i++) {
        ctx.beginPath(); ctx.moveTo(0, CH);
        for (let x = 0; x <= CW; x += 24) ctx.lineTo(x, CH * (.5 + i * .1) + CH * .03 * Math.sin(x / CW * 2 * Math.PI * (1 + i * .4) + ph * (i % 2 ? 1 : -1) + i));
        ctx.lineTo(CW, CH); ctx.closePath();
        ctx.fillStyle = hexa(i % 2 ? acc2 : acc, .05 + i * .016); ctx.fill();
      }
    },
    particulas(t, fr) {
      const acc = css("acc"), n = Math.round(70 * CEN.densidade);
      for (let i = 0; i < Math.min(n, base.length); i++) {
        const [bx, by, bt, bv] = base[i], ciclos = Math.max(1, Math.round(CEN.ciclos * (.5 + bv)));
        const y = (((by - fr * ciclos * (.18 + .3 * bv)) % 1) + 1) % 1, x = bx + .02 * Math.sin(2 * Math.PI * (fr * ciclos + bx));
        ctx.fillStyle = hexa(acc, .1 + .35 * bt); ctx.beginPath(); ctx.arc(x * CW, y * CH, 1.6 + 5 * bt * bt, 0, 7); ctx.fill();
      }
    },
    raios(t, fr) {
      const acc = css("acc"), n = 24, cx = CW * .5, cy = CH * .42, giro = (2 * Math.PI / n) * 2 * fr * CEN.ciclos;
      for (let i = 0; i < n; i += 2) {
        const a0 = giro + i * 2 * Math.PI / n, a1 = a0 + Math.PI / n;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, CW, a0, a1); ctx.closePath();
        ctx.fillStyle = hexa(acc, .055); ctx.fill();
      }
    },
  };
  passos.push(t => { fundo(t); (ESTILOS[CEN.estilo] || ESTILOS.particulas)(t, (t / DUR) % 1); vinheta(); });

  // ----------------------------------------------------------------------------------------------- camadas
  const FORMAS = {
    circulo: () => 1,
    quadrado: th => .82 / Math.max(Math.abs(Math.cos(th)), Math.abs(Math.sin(th))),
    losango: th => .82 / Math.max(Math.abs(Math.cos(th - Math.PI / 4)), Math.abs(Math.sin(th - Math.PI / 4))),
    triangulo: th => { const n = 3, f = ((th + Math.PI / 2) % (2 * Math.PI / n) + 2 * Math.PI / n) % (2 * Math.PI / n) - Math.PI / n; return 1.05 * Math.cos(Math.PI / n) / Math.cos(f); },
    hexagono: th => { const n = 6, f = ((th + Math.PI / 2) % (2 * Math.PI / n) + 2 * Math.PI / n) % (2 * Math.PI / n) - Math.PI / n; return Math.cos(Math.PI / n) / Math.cos(f); },
    estrela: th => .62 + .38 * Math.cos(5 * (th + Math.PI / 2)),
  };
  const PONTOS = 120;

  function embrulho(L) {
    const w = cria('<div class="camada"></div>');
    if (L.prof) paralaxe.push([w, +L.prof]);
    return w;
  }
  // a camada some no fim, sozinha: no loop, todas somem um pouco antes do corte, para o fim ser igual ao começo
  const saida = L => (typeof L.ate === "number" ? L.ate : (S.loop ? DUR - 0.45 : null));
  const opacidadeFinal = (L, t) => { const s = saida(L); return s == null ? 1 : 1 - EASE.sai((t - s) / .35); };

  function unidades(texto, modo) {
    if (modo === "linha") return String(texto).split("|").map(l => l.trim()).filter(Boolean).map(l => [{ p: l.replace(/\*/g, ""), forte: false }]);
    const palavras = [];
    String(texto).split(/(\*[^*]+\*)/).filter(Boolean).forEach(seg => {
      const forte = /^\*.+\*$/.test(seg);
      seg.replace(/\*/g, "").split(/\s+/).filter(Boolean).forEach(p => palavras.push({ p, forte }));
    });
    return palavras;
  }

  const ENTRADA = {
    sobe: (e, p, fs) => { e.style.opacity = EASE.sai(p); e.style.transform = `translateY(${((1 - EASE.sai(p)) * fs * .5).toFixed(2)}px)`; },
    zoom: (e, p) => { e.style.opacity = lim(p * 2.4); e.style.transform = `scale(${(1 + (1 - EASE.sai(p)) * .9).toFixed(4)})`; },
    desfoca: (e, p) => { const k = EASE.sai(p); e.style.opacity = k; e.style.filter = k >= 1 ? "none" : `blur(${((1 - k) * 22).toFixed(2)}px)`; e.style.transform = `scale(${(1 + (1 - k) * .08).toFixed(4)})`; },
    revela: (e, p, fs) => { const k = EASE.sai(p); e.style.opacity = p > 0 ? 1 : 0; e.style.transform = `translateY(${((1 - k) * 105).toFixed(2)}%)`; },
    giro3d: (e, p) => { const k = EASE.sai(p); e.style.opacity = lim(k * 1.6); e.style.transformOrigin = "50% 100%"; e.style.transform = `perspective(700px) rotateX(${((1 - k) * -88).toFixed(2)}deg)`; },
    digita: (e, p) => { e.style.opacity = p > 0 ? 1 : 0; },
    mola: (e, p, fs) => { const m = EASE.mola(p); e.style.opacity = lim(p * 3); e.style.transform = `translateY(${((1 - m) * fs * .7).toFixed(2)}px) scale(${(.8 + .2 * m).toFixed(4)})`; },
  };

  const CAMADAS = {
    texto(L) {
      const w = embrulho(L), [ax, ay] = ancora(L), mw = larguraMax(L), fs = tamanho(L);
      const classes = ["txt", L.estilo === "serifa" ? "serifa" : "", L.estilo === "suave" ? "suave" : ""].join(" ");
      const caixa = cria(`<div class="${classes}" style="left:${ax * W}px;top:${ay * H}px;width:${mw}px;font-size:${fs}px;color:var(--${L.cor || "txt"})"></div>`, w);
      const modo = L.modo || "palavra", entrada = ENTRADA[L.entrada] ? L.entrada : "sobe", rev = entrada === "revela";
      const palavras = unidades(L.texto, modo), unids = [];
      palavras.forEach((u, i) => {
        if (Array.isArray(u)) {   // modo linha: cada linha é uma unidade
          const linha = u[0], bloco = cria(`<span style="display:block"><span class="u${rev ? "" : ""}">${esc(linha.p)}</span></span>`, caixa);
          unids.push({ e: bloco.firstElementChild, t: T((L.ts || [])[i], T(L.t, 0.3) + i * .4 * RITMO) });
          return;
        }
        const w1 = cria(`<span class="w${rev ? " rev" : ""}"></span>`, caixa);
        const base = T((L.ts || [])[i], T(L.t, 0.3) + i * Math.min(.14, 1.2 / Math.max(1, palavras.length)) * RITMO);
        const marca = u.forte ? " f" : "";
        if (modo === "letra") {
          [...u.p].forEach((c, j) => unids.push({ e: cria(`<span class="u${marca}">${esc(c)}</span>`, w1), t: base + j * .035 * RITMO }));
        } else {
          unids.push({ e: cria(`<span class="u${marca}">${esc(u.p)}</span>`, w1), t: base });
        }
        caixa.appendChild(document.createTextNode(" "));
      });
      L._unids = unids; L._caixa = caixa; L._w = w;
      const du = (entrada === "digita" ? .001 : .55) * RITMO;
      // área segura: em cima fica o nome do canal; embaixo, a legenda queimada e (em pé) os botões do app
      // com a câmera empurrando, o texto chega mais perto das bordas: a área encolhe pelo maior zoom da cena
      const zmax = Math.max(1, ...cam.map(k => k.zoom));
      const topo = Math.max((V ? .14 : .12) * H, H / 2 - (H / 2 - .09 * H) / zmax);
      const base = Math.min((V ? .70 : .72) * H, H / 2 + (.77 * H - H / 2) / zmax);
      const maxh = Math.min(base - topo, (V ? .34 : .4) * H);
      L._encaixe = () => {   // letra comprida demais encolhe até caber na caixa, e a caixa nunca sai da área segura
        let tam = fs; caixa.style.fontSize = tam + "px";
        while ((caixa.offsetHeight > maxh || caixa.scrollWidth > mw + 2) && tam > fs * .45) { tam -= 2; caixa.style.fontSize = tam + "px"; }
        const meia = caixa.offsetHeight / 2;
        caixa.style.top = Math.max(topo + meia, Math.min(base - meia, ay * H)) + "px";
      };
      passos.push(t => {
        unids.forEach(u => ENTRADA[entrada](u.e, lim((t - u.t) / du), fs));
        w.style.opacity = opacidadeFinal(L, t);
      });
    },

    forma(L) {
      const w = embrulho(L), [ax, ay] = ancora(L), R = (L.tamanho_px ? +L.tamanho_px : (V ? 360 : 330)) * (V ? .86 : 1);
      const svg = cria(`<svg class="forma" viewBox="0 0 ${W} ${H}"><polygon></polygon></svg>`, w);
      const poli = svg.firstElementChild, t0 = T(L.t, 0.3), d = 0.9 * RITMO;
      const etapas = [{ f: L.forma || "circulo", t: t0 }].concat((L.morph || []).map(m => ({ f: m.para, t: T(m.t, t0 + 1) })));
      const cor = css(L.cor || "acc"), contorno = L.estilo === "contorno";
      const w1 = 2 * Math.PI * Math.max(1, Math.round(DUR / 5)) / DUR, w2 = 2 * Math.PI * Math.max(1, Math.round(DUR / 7)) / DUR;
      poli.setAttribute("fill", contorno ? "none" : hexa(cor, .88));
      poli.setAttribute("stroke", contorno ? cor : hexa(cor, .35));
      poli.setAttribute("stroke-width", contorno ? 8 : 3);
      poli.setAttribute("stroke-linejoin", "round");
      passos.push(t => {
        let j = 0;
        for (let i = 1; i < etapas.length; i++) if (t >= etapas[i].t) j = i;
        const k = j === 0 ? 0 : ease("organico", (t - etapas[j].t) / d);
        const fa = FORMAS[etapas[Math.max(0, j - 1)].f] || FORMAS.circulo, fb = FORMAS[etapas[j].f] || FORMAS.circulo;
        const entra = EASE.mola((t - t0) / (.8 * RITMO)), giro = (L.giro || 0) * (t / DUR) * Math.PI / 180;
        const pts = [];
        for (let i = 0; i < PONTOS; i++) {
          const th = 2 * Math.PI * i / PONTOS;
          let r = j === 0 ? fa(th) : lerp(fa(th), fb(th), k);
          r *= 1 + .028 * Math.sin(3 * th + w1 * t) + .016 * Math.sin(5 * th - w2 * t);
          const rr = R * r * (.6 + .4 * entra);
          pts.push(`${(ax * W + rr * Math.cos(th + giro)).toFixed(2)},${(ay * H + rr * Math.sin(th + giro)).toFixed(2)}`);
        }
        poli.setAttribute("points", pts.join(" "));
        svg.style.opacity = lim((t - t0) / .35) * opacidadeFinal(L, t);
      });
    },

    numero(L) {
      const w = embrulho(L), [ax, ay] = ancora(L), fs = tamanho(L) * 1.15, t0 = T(L.t, 0.3);
      const num = cria(`<div class="numero" style="left:${ax * W}px;top:${ay * H}px;font-size:${fs}px;color:var(--${L.cor || "acc"})">${esc(L.prefixo || "")}<span class="c">${esc(L.valor || "")}</span>${esc(L.sufixo || "")}</div>`, w);
      const c = num.querySelector(".c");
      const leg = L.legenda ? cria(`<div class="legenda" style="left:${ax * W}px;top:${ay * H + fs * .62}px;width:${larguraMax(L)}px;font-size:${fs * .26}px">${esc(L.legenda)}</div>`, w) : null;
      passos.push(t => {
        const p = lim((t - t0) / (.9 * RITMO)), m = EASE.mola(p);
        num.style.opacity = lim(p * 3); num.style.transform = `translate(-50%,-50%) scale(${(.72 + .28 * m).toFixed(4)})`;
        // a contagem termina antes do fim da cena, mesmo quando o número é dito tarde
        if (L.contar && typeof L.numero === "number") c.textContent = fmt(L.numero * EASE.sai((t - t0) / Math.min(1.5 * RITMO, Math.max(.5, DUR - t0 - .5))), L.casas || 0);
        if (leg) leg.style.opacity = lim((t - t0 - .45) / .4);
        w.style.opacity = opacidadeFinal(L, t);
      });
    },

    card3d(L) {
      const w = embrulho(L), [ax, ay] = ancora(L), fs = tamanho(L) * .6, t0 = T(L.t, 0.3);
      const larg = Math.round(W * (V ? .76 : .42));
      const card = cria(`<div class="card3d" style="left:${ax * W - larg / 2}px;top:${ay * H - fs * 2}px;width:${larg}px;font-size:${fs}px"><div class="t">${esc(L.titulo || "")}</div>${L.texto ? `<div class="p">${esc(L.texto)}</div>` : ""}</div>`, w);
      const rx = T(L.rot_x, -10), ry = T(L.rot_y, V ? 8 : 16), ciclos = Math.max(1, Math.round(DUR / 6));
      passos.push(t => {
        const p = lim((t - t0) / (.9 * RITMO)), k = EASE.mola(p), a = 2 * Math.PI * ciclos * t / DUR;
        card.style.opacity = lim(p * 3);
        card.style.transform = `perspective(1500px) rotateX(${(rx + (1 - k) * 28 + 2.2 * Math.sin(a)).toFixed(3)}deg) rotateY(${(ry - (1 - k) * 70 + 3 * Math.cos(a)).toFixed(3)}deg) scale(${(.86 + .14 * k).toFixed(4)})`;
        w.style.opacity = opacidadeFinal(L, t);
      });
    },

    linha(L) {
      const w = embrulho(L), de = (V && L.de_v) || L.de || [.2, .6], para = (V && L.para_v) || L.para || [.8, .6];
      const x0 = de[0] * W, y0 = de[1] * H, x1 = para[0] * W, y1 = para[1] * H, curva = T(L.curva, .12) * (V ? H : W);
      const svg = cria(`<svg class="traco" viewBox="0 0 ${W} ${H}"><path fill="none" stroke="var(--${L.cor || "acc"})" stroke-width="${V ? 8 : 6}" stroke-linecap="round" d="M${x0} ${y0} Q ${(x0 + x1) / 2} ${(y0 + y1) / 2 - curva} ${x1} ${y1}"/></svg>`, w);
      const caminho = svg.firstElementChild, tam = Math.ceil(caminho.getTotalLength()) + 2, t0 = T(L.t, 0.3);
      caminho.style.strokeDasharray = tam + " " + tam;
      passos.push(t => { caminho.style.strokeDashoffset = tam * (1 - ease("suave", (t - t0) / (.9 * RITMO))); w.style.opacity = opacidadeFinal(L, t); });
    },
  };

  (S.camadas || []).forEach(L => { if (CAMADAS[L.tipo]) CAMADAS[L.tipo](L); });
  // a faixa escura de baixo (para a legenda branca ser lida) só existe em paleta clara: as escuras já bastam
  const lum = (/^#([0-9a-f]{6})$/i.exec(css("fundo")) || [0, "000000"])[1], n0 = parseInt(lum, 16);
  if ((0.299 * (n0 >> 16) + 0.587 * ((n0 >> 8) & 255) + 0.114 * (n0 & 255)) / 255 > .55) cria('<div class="faixa-legenda"></div>', root);
  if (D.canal) cria(`<div class="canal">${esc(D.canal)}</div>`, root);

  function encaixar() { (S.camadas || []).forEach(L => { if (L._encaixe) L._encaixe(); }); }

  // ----------------------------------------------------------------------------------------------- o quadro
  const TR = S.transicao || {};
  let ultimo = 0;
  function quadro(t) {
    ultimo = t;
    const c = camera(t);
    palco.style.transform = `translate(${(c.x / 100 * W).toFixed(2)}px, ${(c.y / 100 * H).toFixed(2)}px) rotate(${c.rot.toFixed(3)}deg) scale(${c.zoom.toFixed(4)})`;
    paralaxe.forEach(([w, prof]) => { w.style.translate = `${(c.x / 100 * W * prof * .7).toFixed(2)}px ${(c.y / 100 * H * prof * .7).toFixed(2)}px`; });
    for (const f of passos) f(t);
    // transição de entrada e de saída da cena inteira
    let o = 1;
    if (TR.entrada === "fade" || S.loop) o = Math.min(o, lim(t / .3));
    if (TR.saida === "fade" || S.loop) o = Math.min(o, lim((DUR - t) / .3));
    root.style.opacity = o;
    if (TR.saida === "zoom" && t > DUR - .35) palco.style.transform += ` scale(${(1 + .12 * EASE.entra((t - (DUR - .35)) / .35)).toFixed(4)})`;
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
