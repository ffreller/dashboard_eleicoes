"use strict";

const ATUALIZAR_S = 30;
const REPETIR_S = 15;
const PARADO_MIN = 5;
const FUSO = "America/Sao_Paulo";

// Quadrados (coluna, linha) em posição geográfica aproximada. Índices a partir de 0.
const GRADE = {
  RR: [1, 0], AP: [2, 0],
  AM: [1, 1], PA: [2, 1], MA: [3, 1], PI: [4, 1], CE: [5, 1], RN: [6, 1],
  AC: [0, 2], RO: [1, 2], MT: [2, 2], TO: [3, 2], BA: [4, 2], PE: [5, 2], PB: [6, 2],
  MS: [2, 3], GO: [3, 3], DF: [4, 3], SE: [5, 3], AL: [6, 3],
  MG: [3, 4], ES: [4, 4],
  PR: [2, 5], SP: [3, 5], RJ: [4, 5],
  SC: [2, 6], RS: [2, 7], ZZ: [6, 7],
};

// Faixas de vantagem do líder no estado: distância de 50 abaixo da qual a faixa vale, e o rótulo da legenda.
const ESCALA = [
  { ate: 3, rot: "47–53" },
  { ate: 8, rot: "53–58" },
  { ate: 15, rot: "58–65" },
  { ate: Infinity, rot: "65+" },
];

const FMT = [0, 1, 2].map((d) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
const n = (x, d = 1) => FMT[d].format(x);
const pc = (x, d = 2) => n(x, d) + "%";
const dataHora = (opts) => new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, ...opts });
const FMT_HM = dataHora({ hour: "2-digit", minute: "2-digit" });
const FMT_HMS = dataHora({ hour: "2-digit", minute: "2-digit", second: "2-digit" });
const hm = (iso) => FMT_HM.format(new Date(iso));
const hms = (t) => FMT_HMS.format(t instanceof Date ? t : new Date(t));

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";

function el(tag, props, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  e.append(...filhos.flat().filter((f) => f != null));
  return e;
}

function sv(tag, attrs, ...filhos) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  e.append(...filhos);
  return e;
}

const params = new URLSearchParams(location.search);
const ARQUIVO = params.has("exemplo")
  ? params.get("exemplo") ? `dados/exemplo-${encodeURIComponent(params.get("exemplo"))}.json` : "dados/exemplo-metade.json"
  : "dados/projecao.json";

const estado = {
  dados: null,
  bruto: "",
  falha: null,
  proximo: 0,
  idx: null,
  uf: null,
  ord: { chave: "nome", dir: 1 },
};

/* Dados */

function validar(d) {
  const ok = d && typeof d === "object" && Array.isArray(d.serie) && Array.isArray(d.ufs)
    && d.candidatos?.esq?.nome && d.candidatos?.dir?.nome && ["aguardando", "apurando", "encerrada"].includes(d.fase);
  if (!ok) throw new Error("arquivo de dados em formato inesperado");
  return d;
}

let temporizador = 0;

async function buscar() {
  clearTimeout(temporizador);
  let segundos = ATUALIZAR_S;
  try {
    const r = await fetch(`${ARQUIVO}?t=${Date.now()}`, {
      cache: "no-store",
      signal: AbortSignal.timeout ? AbortSignal.timeout(10000) : undefined,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const texto = await r.text();
    if (texto !== estado.bruto) {
      estado.dados = validar(JSON.parse(texto));
      estado.bruto = texto;
      desenhar();
    }
    estado.falha = null;
  } catch (e) {
    console.warn("Falha ao atualizar:", e);
    estado.falha = new Date();
    segundos = REPETIR_S;
  }
  estado.proximo = Date.now() + segundos * 1000;
  desenharStatus();
  temporizador = setTimeout(buscar, segundos * 1000);
}

/* Situação */

function situacao(d) {
  const u = d.serie.at(-1);
  if (d.fase === "aguardando" || !u) return { tipo: "aguardando" };
  if (d.fase === "encerrada") return { tipo: "encerrada", u };
  if (!u.projecao) return { tipo: "sem-projecao", u };
  const { baixo, alto } = u.projecao;
  return { tipo: baixo <= 50 && alto >= 50 ? "cruza" : "um-lado", u };
}

const curto = (nome) => nome.split(" ")[0];

function nomes(d) {
  const e = d.candidatos.esq, r = d.candidatos.dir;
  return { esq: curto(e.nome), dir: curto(r.nome), inicialEsq: curto(e.nome)[0], inicialDir: curto(r.nome)[0] };
}

// Nunca mostra 100% nem 0%: com 200 cenários, o extremo só diz que nenhum virou.
function rotulosChance(chance) {
  const e = Math.round(chance);
  const lado = (v, arred) => (v > 99 ? "mais de 99%" : v < 1 ? "menos de 1%" : `${arred}%`);
  return { esq: lado(chance, e), dir: lado(100 - chance, 100 - e) };
}

const chanceDe = (d, q) => (d.fase === "apurando" && q.projecao?.chance != null ? rotulosChance(q.projecao.chance) : null);

/* Status e tema */

function desenharStatus() {
  const d = estado.dados;
  const txt = $("status");
  let msg;
  if (estado.falha && !d) msg = `Não foi possível carregar os dados às ${hms(estado.falha)}. Nova tentativa às ${hms(estado.proximo)}.`;
  else if (estado.falha) msg = `Não foi possível atualizar às ${hms(estado.falha)}. Continuamos mostrando os dados de ${hms(d.atualizado)}. Nova tentativa às ${hms(estado.proximo)}.`;
  else if (d) msg = `Dados atualizados às ${hms(d.atualizado)} (Brasília).`;
  else msg = "Carregando os dados…";
  if (txt.textContent !== msg) txt.textContent = msg;
  txt.classList.toggle("falha", !!estado.falha);

  const alerta = $("alerta");
  const parado = d && d.fase === "apurando" && !d.exemplo && !estado.falha && Date.now() - Date.parse(d.atualizado) > PARADO_MIN * 60000;
  alerta.hidden = !(estado.falha || parado);
  alerta.classList.toggle("erro", !!estado.falha);
  if (estado.falha) alerta.textContent = d ? "A conexão falhou. Os números abaixo podem estar desatualizados." : "A conexão falhou e ainda não há dados para mostrar.";
  else if (parado) alerta.textContent = `Os dados não mudam desde ${hms(d.atualizado)}. A atualização pode estar parada.`;
  tique();
}

function tique() {
  const s = Math.max(0, Math.ceil((estado.proximo - Date.now()) / 1000));
  $("proxima").textContent = estado.proximo ? `Próxima atualização em ${s} s` : "";
}

function iniciarTema() {
  const botao = $("tema");
  const escuro = matchMedia("(prefers-color-scheme: dark)");
  const efetivo = () => document.documentElement.dataset.theme || (escuro.matches ? "dark" : "light");
  const pintar = () => {
    const e = efetivo();
    $("icone-lua").style.display = e === "dark" ? "none" : "";
    $("icone-sol").style.display = e === "dark" ? "" : "none";
    botao.setAttribute("aria-label", e === "dark" ? "Mudar para o tema claro" : "Mudar para o tema escuro");
  };
  botao.addEventListener("click", () => {
    const novo = efetivo() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = novo;
    try { localStorage.setItem("tema", novo); } catch (e) { /* armazenamento bloqueado */ }
    pintar();
  });
  escuro.addEventListener("change", pintar);
  pintar();
}

/* Resposta */

function setBarra(barra, centro, banda) {
  barra.querySelector(".seg-esq").style.setProperty("flex-basis", `${centro}%`);
  const b = barra.querySelector(".banda");
  if (!b) return;
  b.hidden = !banda;
  if (banda) {
    b.style.setProperty("--lo", `${banda.baixo}%`);
    b.style.setProperty("--hi", `${banda.alto}%`);
  }
}

function pctHtml(alvo, txt) {
  alvo.replaceChildren(txt === "–" ? "–" : txt.slice(0, -1), ...(txt === "–" ? [] : [el("small", { text: "%" })]));
}

function frase(d, sit, nm) {
  const { u } = sit;
  switch (sit.tipo) {
    case "aguardando":
      return "A apuração ainda não começou. Esta página se atualiza sozinha quando o TSE divulgar os primeiros resultados.";
    case "sem-projecao":
      return `Só ${pc(u.pct_secoes, 1)} das seções foram apuradas. A projeção aparece quando a contagem chegar a ${n(d.projecao_desde_pct, 0)}%. Até lá, o total parcial diz pouco sobre o resultado final.`;
    case "cruza": {
      const dif = Math.abs(2 * u.projecao.centro - 100);
      const lider = u.projecao.centro >= 50 ? nm.esq : nm.dir;
      const pontos = n(dif, 1) === "1,0" ? "ponto percentual" : "pontos percentuais";
      const centro = dif < 0.05
        ? "No centro da estimativa, os dois estão praticamente empatados."
        : `No centro da estimativa, ${lider} aparece à frente por ${n(dif, 1)} ${pontos}.`;
      return `A faixa da projeção ainda cruza os 50%, então o resultado final segue em aberto. ${centro}`;
    }
    case "um-lado": {
      const lider = u.projecao.centro >= 50 ? nm.esq : nm.dir;
      return `A projeção aponta ${lider} à frente, e a faixa inteira fica do mesmo lado dos 50%. Continua sendo uma estimativa e ela se mexe conforme a contagem avança.`;
    }
    case "encerrada": {
      const e = u.apurado ?? u.projecao?.centro;
      const restante = u.pct_secoes < 99.995 ? ` com ${pc(u.pct_secoes, 2)} das seções apuradas` : "";
      return `A apuração foi encerrada${restante}. Na contagem, ${nm.esq} tem ${pc(e)} dos votos válidos e ${nm.dir} tem ${pc(100 - e)}. A divulgação oficial do resultado é do TSE.`;
    }
  }
}

const ROTULO_FASE = { aguardando: "Aguardando", apurando: "Apurando", encerrada: "Encerrada" };

function desenharResposta() {
  const d = estado.dados;
  const sit = situacao(d);
  const nm = nomes(d);

  for (const e of document.querySelectorAll("[data-nome]")) e.textContent = nm[e.dataset.nome];
  for (const e of document.querySelectorAll("[data-num]")) {
    const c = d.candidatos[e.dataset.num];
    e.textContent = `${c.numero} · ${c.partido}`;
  }
  $("legenda-banda").hidden = !(sit.tipo === "cruza" || sit.tipo === "um-lado");
  $("legenda-banda-txt").textContent = `Faixa de incerteza da projeção (${n(d.nivel_faixa, 0)}%)`;
  $("fase").textContent = ROTULO_FASE[d.fase];
  $("fase").dataset.fase = d.fase;
  $("t-resposta").textContent = d.fase === "encerrada" ? "Contagem final" : "Projeção do resultado final";

  const temNumeros = sit.tipo !== "aguardando";
  $("hero-corpo").hidden = !temNumeros;
  if (temNumeros) {
    const proj = sit.tipo === "cruza" || sit.tipo === "um-lado" ? sit.u.projecao : null;
    const centro = sit.tipo === "encerrada" ? (sit.u.apurado ?? sit.u.projecao?.centro) : proj?.centro;
    const barra = $("barra-proj");
    barra.hidden = centro == null;
    if (centro != null) {
      pctHtml($("pct-esq"), pc(centro));
      pctHtml($("pct-dir"), pc(100 - centro));
      setBarra(barra, centro, proj);
      const nivel = n(d.nivel_faixa, 0);
      barra.setAttribute("aria-label", proj
        ? `Projeção: ${nm.esq} ${pc(centro)}, ${nm.dir} ${pc(100 - centro)}. Faixa de ${nivel}% para ${nm.esq}: de ${pc(proj.baixo)} a ${pc(proj.alto)}.`
        : `Contagem final: ${nm.esq} ${pc(centro)}, ${nm.dir} ${pc(100 - centro)}.`);
    } else {
      pctHtml($("pct-esq"), "–");
      pctHtml($("pct-dir"), "–");
    }
    $("faixa-esq").textContent = proj ? `faixa: ${n(proj.baixo)} a ${n(proj.alto)}` : centro == null ? `a partir de ${n(d.projecao_desde_pct, 0)}% das seções` : "";
    $("faixa-dir").textContent = proj ? `faixa: ${n(100 - proj.alto)} a ${n(100 - proj.baixo)}` : "";
  }

  const ch = sit.u ? chanceDe(d, sit.u) : null;
  $("chance").hidden = !ch;
  if (ch) {
    $("chance-esq").textContent = ch.esq;
    $("chance-dir").textContent = ch.dir;
    // Limita a barra a 1%–99% para nenhum lado sumir.
    setBarra($("barra-chance"), Math.min(99, Math.max(1, sit.u.projecao.chance)), null);
    $("barra-chance").setAttribute("aria-label", `Chance de vencer: ${nm.esq} ${ch.esq}, ${nm.dir} ${ch.dir}.`);
  }

  $("frase").textContent = frase(d, sit, nm);

  const u = sit.u;
  const mostrarBruto = (sit.tipo === "sem-projecao" || sit.tipo === "cruza" || sit.tipo === "um-lado") && u.apurado != null;
  $("bruto").hidden = !mostrarBruto;
  if (mostrarBruto) {
    $("apuradas").textContent = `${pc(u.pct_secoes, 2)} das seções apuradas`;
    $("progresso").style.setProperty("--p", `${u.pct_secoes}%`);
    setBarra($("barra-bruta"), u.apurado, null);
    $("barra-bruta").setAttribute("aria-label", `Contagem até agora: ${nm.esq} ${pc(u.apurado)}, ${nm.dir} ${pc(100 - u.apurado)}.`);
    $("bruto-nums").replaceChildren(`${nm.esq} ${pc(u.apurado)}`, el("span", { class: "sep", "aria-hidden": "true" }, "·"), `${nm.dir} ${pc(100 - u.apurado)}`);
  }
}

/* Gráfico de evolução */

function passoNice(span, alvo) {
  const bruto = span / alvo;
  const base = 10 ** Math.floor(Math.log10(bruto));
  return [1, 2, 5, 10].map((m) => m * base).find((s) => s >= bruto);
}

function segmentos(serie, pega) {
  const segs = [];
  let atual = null;
  for (const q of serie) {
    const v = pega(q);
    if (v == null) { atual = null; continue; }
    if (!atual) segs.push((atual = []));
    atual.push([q, v]);
  }
  return segs;
}

let desenhoGrafico = null;

function pontosDe(q) {
  const espelho = (v) => (v == null ? null : 100 - v);
  return [
    ["ponto-bruto cor-esq", q.apurado, 4.5],
    ["ponto-bruto cor-dir", espelho(q.apurado), 4.5],
    ["ponto-proj cor-esq", q.projecao?.centro, 5],
    ["ponto-proj cor-dir", espelho(q.projecao?.centro), 5],
  ];
}

function desenharGrafico() {
  const d = estado.dados;
  const host = $("grafico");
  const serie = d.serie;
  host.replaceChildren();
  desenhoGrafico = null;
  if (!serie.length) {
    host.append(el("p", { class: "leitura-vazia", text: "O gráfico aparece quando os primeiros resultados chegarem." }));
    desenharLeitura();
    return;
  }

  const nm = nomes(d);
  const W = Math.max(280, host.clientWidth);
  const H = Math.round(Math.min(360, Math.max(260, W * 0.7)));
  const M = { t: 10, r: 14, b: 44, l: 42 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;

  // Eixo simétrico em torno de 50%: as linhas dos dois candidatos são espelhos uma da outra.
  let desvio = 3;
  for (const q of serie) {
    if (q.pct_secoes < d.projecao_desde_pct) continue;
    for (const v of [q.apurado, q.projecao?.baixo, q.projecao?.alto]) {
      if (v != null) desvio = Math.max(desvio, Math.abs(v - 50));
    }
  }
  desvio = Math.min(50, desvio * 1.16);
  const lo = 50 - desvio, hi = 50 + desvio;

  const X = (p) => M.l + (p / 100) * iw;
  const Y = (v) => M.t + ((hi - v) / (hi - lo)) * ih;

  const passo = passoNice(hi - lo, 5);
  const ticksY = [];
  for (let k = -Math.floor(desvio / passo + 1e-9); k <= Math.floor(desvio / passo + 1e-9); k++) ticksY.push(Math.round((50 + k * passo) * 100) / 100);

  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", tabindex: "0", focusable: "true" });
  const ultimo = serie.at(-1);
  svg.setAttribute("aria-label", `Gráfico da evolução. Último ponto: ${pc(ultimo.pct_secoes, 1)} das seções apuradas`
    + (ultimo.projecao ? `, projeção de ${nm.esq} em ${pc(ultimo.projecao.centro)} e de ${nm.dir} em ${pc(100 - ultimo.projecao.centro)}` : "")
    + `. Use as setas do teclado para percorrer os pontos. Os mesmos dados estão na tabela abaixo.`);

  const recorte = sv("clipPath", { id: "recorte" }, sv("rect", { x: M.l, y: M.t, width: iw, height: ih }));
  svg.append(sv("defs", {}, recorte));

  const y50 = Y(50);

  for (const v of ticksY) {
    if (v === 50) continue;
    svg.append(sv("line", { class: "grade", x1: M.l, x2: M.l + iw, y1: Y(v), y2: Y(v) }));
  }
  for (const p of [0, 25, 50, 75, 100]) {
    svg.append(sv("line", { class: "grade", x1: X(p), x2: X(p), y1: M.t, y2: M.t + ih }));
    const t = sv("text", { x: X(p), y: M.t + ih + 16, "text-anchor": p === 0 ? "start" : p === 100 ? "end" : "middle" });
    t.textContent = `${p}%`;
    svg.append(t);
  }
  for (const v of ticksY) {
    const t = sv("text", { x: M.l - 6, y: Y(v) + 4, "text-anchor": "end" });
    t.textContent = `${n(v, passo < 1 ? 1 : 0)}%`;
    svg.append(t);
  }
  const titulo = sv("text", { x: M.l + iw / 2, y: H - 6, "text-anchor": "middle" });
  titulo.textContent = "% das seções apuradas";
  const zonaRot = (cls, y, seta, nome) => {
    const t = sv("text", { class: "zona-rot", x: M.l + iw - 6, y, "text-anchor": "end" });
    t.append(sv("tspan", { class: cls }, seta), ` ${nome} à frente`);
    return t;
  };
  const rotEsq = zonaRot("cor-esq", M.t + 14, "▲", nm.esq);
  const rotDir = zonaRot("cor-dir", M.t + ih - 8, "▼", nm.dir);
  svg.append(
    sv("line", { class: "eixo", x1: M.l, x2: M.l + iw, y1: M.t + ih, y2: M.t + ih }),
    sv("line", { class: "ref50", x1: M.l, x2: M.l + iw, y1: y50, y2: y50 }),
    titulo, rotEsq, rotDir,
  );

  const pto = (q, y) => `${X(q.pct_secoes).toFixed(1)},${Y(y).toFixed(1)}`;
  const area = (f) => segmentos(serie, (q) => q.projecao).map((seg) =>
    `M${seg.map(([q, pr]) => pto(q, f(pr).alto)).join("L")}L${seg.map(([q, pr]) => pto(q, f(pr).baixo)).reverse().join("L")}Z`).join("");
  const linha = (pega, f) => segmentos(serie, pega).map((s) => "M" + s.map(([q, v]) => pto(q, f(v))).join("L")).join("");
  const igual = (pr) => pr;
  const espelho = (pr) => ({ baixo: 100 - pr.alto, alto: 100 - pr.baixo });
  const espelhar = (v) => 100 - v;
  const grupo = sv("g", { "clip-path": "url(#recorte)" },
    sv("path", { class: "faixa-area cor-esq", d: area(igual) }),
    sv("path", { class: "faixa-area cor-dir", d: area(espelho) }),
    sv("path", { class: "linha-bruta cor-esq", d: linha((q) => q.apurado, igual) }),
    sv("path", { class: "linha-bruta cor-dir", d: linha((q) => q.apurado, espelhar) }),
    sv("path", { class: "linha-proj cor-esq", d: linha((q) => q.projecao?.centro, igual) }),
    sv("path", { class: "linha-proj cor-dir", d: linha((q) => q.projecao?.centro, espelhar) }),
  );
  svg.append(grupo);

  const dentro = (v) => v != null && v >= lo && v <= hi;
  for (const [cls, v, r] of pontosDe(ultimo)) {
    if (dentro(v)) svg.append(sv("circle", { class: cls, cx: X(ultimo.pct_secoes), cy: Y(v), r }));
  }

  const mira = sv("g", { visibility: "hidden", "pointer-events": "none" },
    sv("line", { class: "mira", y1: M.t, y2: M.t + ih }),
    ...pontosDe({}).map(([cls, , r]) => sv("circle", { class: cls, r })),
  );
  svg.append(mira);

  const alvo = sv("rect", { x: M.l, y: M.t, width: iw, height: ih, fill: "transparent" });
  svg.append(alvo);
  host.append(svg);

  const maisProximo = (clientX) => {
    const r = svg.getBoundingClientRect();
    const p = ((clientX - r.left) * (W / r.width) - M.l) / iw * 100;
    let a = 0, b = serie.length - 1;
    while (b - a > 1) {
      const m = (a + b) >> 1;
      if (serie[m].pct_secoes <= p) a = m; else b = m;
    }
    return Math.abs(serie[a].pct_secoes - p) <= Math.abs(serie[b].pct_secoes - p) ? a : b;
  };
  desenhoGrafico = { X, Y, mira, serie, lo, hi };
  const pos = (e) => definirIdx(maisProximo(e.clientX));
  alvo.addEventListener("pointerdown", pos);
  alvo.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse" || e.buttons || e.pointerType === "touch") pos(e); });
  alvo.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") definirIdx(null); });
  svg.addEventListener("keydown", (e) => {
    const atual = estado.idx ?? serie.length - 1;
    const passoTecla = { ArrowLeft: -1, ArrowRight: 1, PageDown: -10, PageUp: 10 }[e.key];
    if (passoTecla) definirIdx(Math.min(serie.length - 1, Math.max(0, atual + passoTecla)));
    else if (e.key === "Home") definirIdx(0);
    else if (e.key === "End" || e.key === "Escape") definirIdx(null);
    else return;
    e.preventDefault();
  });

  desenharMira();
  desenharLeitura();
}

function definirIdx(i) {
  if (i === estado.idx) return;
  estado.idx = i;
  desenharMira();
  desenharLeitura();
}

function desenharMira() {
  const g = desenhoGrafico;
  if (!g) return;
  const i = estado.idx;
  if (i == null || i >= g.serie.length) { g.mira.setAttribute("visibility", "hidden"); return; }
  const q = g.serie[i];
  const [linha, ...circulos] = g.mira.children;
  linha.setAttribute("x1", g.X(q.pct_secoes)); linha.setAttribute("x2", g.X(q.pct_secoes));
  pontosDe(q).forEach(([, v], k) => {
    const ok = v != null && v >= g.lo && v <= g.hi;
    circulos[k].setAttribute("visibility", ok ? "visible" : "hidden");
    if (ok) { circulos[k].setAttribute("cx", g.X(q.pct_secoes)); circulos[k].setAttribute("cy", g.Y(v)); }
  });
  g.mira.setAttribute("visibility", "visible");
}

function desenharLeitura() {
  const d = estado.dados;
  const host = $("leitura");
  host.hidden = !d.serie.length;
  if (!d.serie.length) return;
  const nm = nomes(d);
  const i = estado.idx != null && estado.idx < d.serie.length ? estado.idx : null;
  const q = d.serie[i ?? d.serie.length - 1];
  const topo = el("div", { class: "leitura-topo", text: `${i == null ? "Último ponto" : "Ponto escolhido"}: ${hm(q.hora)}, com ${pc(q.pct_secoes, 2)} das seções apuradas` });
  const par = (tipo, esq, dir) => [
    el("span", { class: "item" }, el("span", { class: `chave ${tipo} cor-esq`, "aria-hidden": "true" }), `${nm.esq} ${esq}`),
    el("span", { class: "item" }, el("span", { class: `chave ${tipo} cor-dir`, "aria-hidden": "true" }), `${nm.dir} ${dir}`),
  ];
  const linha = (titulo, ...itens) => el("div", { class: "leitura-linha" }, el("b", { text: titulo }), el("div", { class: "valores" }, itens.flat()));
  const p = q.projecao;
  const ch = chanceDe(d, q);
  host.replaceChildren(...[
    topo,
    p
      ? linha("Projeção", par("chave-proj", pc(p.centro), pc(100 - p.centro)),
        p.alto - p.baixo > 0.005 ? el("span", { class: "item", text: `faixa de ${nm.esq}: ${n(p.baixo)} a ${n(p.alto)}` }) : null)
      : linha("Projeção", el("span", { class: "item", text: `ainda não disponível (aparece a partir de ${n(d.projecao_desde_pct, 0)}% das seções)` })),
    q.apurado != null
      ? linha("Contagem", par("chave-bruta", pc(q.apurado), pc(100 - q.apurado)))
      : linha("Contagem", el("span", { class: "item", text: "sem votos contados" })),
    ch ? linha("Chance de vencer",
      el("span", { class: "item" }, el("i", { class: "ponto ponto-esq", "aria-hidden": "true" }), `${nm.esq} ${ch.esq}`),
      el("span", { class: "item" }, el("i", { class: "ponto ponto-dir", "aria-hidden": "true" }), `${nm.dir} ${ch.dir}`)) : null,
  ].filter(Boolean));
}

function desenharTabelaSerie() {
  const d = estado.dados;
  const corpo = $("serie-tabela-corpo");
  if (!$("serie-tabela").open) return;
  const nm = nomes(d);
  const f = (v) => (v == null ? "–" : n(v));
  const comChance = d.fase === "apurando";
  const chance = (q) => { const c = chanceDe(d, q); return c ? `${c.esq} / ${c.dir}` : "–"; };
  const linhas = [...d.serie].reverse().map((q) => el("tr", {},
    el("th", { scope: "row", text: hm(q.hora) }),
    el("td", { text: pc(q.pct_secoes, 2) }),
    el("td", { text: f(q.apurado) }),
    el("td", { text: f(q.projecao?.centro) }),
    el("td", { text: q.projecao ? `${n(q.projecao.baixo)} a ${n(q.projecao.alto)}` : "–" }),
    comChance ? el("td", { text: chance(q) }) : null,
  ));
  corpo.replaceChildren(el("table", {},
    el("caption", { class: "vh", text: `Evolução da contagem e da projeção, em % de ${nm.esq} nos votos válidos` }),
    el("thead", {}, el("tr", {},
      ...["Hora", "Seções apuradas", `Contagem (${nm.esq} %)`, `Projeção (${nm.esq} %)`, "Faixa da projeção", ...(comChance ? [`Chance de vencer (${nm.esq} / ${nm.dir})`] : [])].map((t) => el("th", { scope: "col", text: t })))),
    el("tbody", {}, linhas)));
}

/* Estados */

function binDe(pctLider, deEsq) {
  const dist = Math.abs(pctLider - 50);
  const k = ESCALA.findIndex((e) => dist < e.ate);
  return k === 0 ? "n" : (deEsq ? "l" : "b") + k;
}

function resumoUf(u, nm) {
  const c = u.projecao?.centro;
  if (c == null) return null;
  const esq = c >= 50;
  const pctLider = esq ? c : 100 - c;
  return { esq, pctLider, nome: esq ? nm.esq : nm.dir, letra: esq ? nm.inicialEsq : nm.inicialDir, bin: binDe(pctLider, esq) };
}

function desenharMapa() {
  const d = estado.dados;
  const nm = nomes(d);
  const mapa = $("mapa");
  if (!d.ufs.length) {
    mapa.replaceChildren();
    mapa.style.display = "none";
    $("mapa-legenda").replaceChildren();
    $("mapa-detalhe").textContent = "Os estados aparecem quando a apuração começar.";
    return;
  }
  mapa.style.display = "";
  const tiles = d.ufs.filter((u) => GRADE[u.uf]).map((u) => {
    const r = resumoUf(u, nm);
    const [col, lin] = GRADE[u.uf];
    const rotulo = r ? `${r.letra} ${Math.round(r.pctLider)}` : "–";
    const aria = `${u.nome}: ${pc(u.pct_secoes, 0)} das seções apuradas. `
      + (r ? `Projeção: ${r.nome} à frente com ${pc(r.pctLider, 1)}.` : "Projeção ainda não disponível.");
    return el("button", {
      type: "button", class: "tile", "data-bin": r?.bin ?? "sem", "data-uf": u.uf,
      "aria-pressed": String(estado.uf === u.uf), "aria-label": aria,
      style: `grid-column:${col + 1};grid-row:${lin + 1};--ap:${Math.min(100, u.pct_secoes)}%`,
      onclick: () => { estado.uf = estado.uf === u.uf ? null : u.uf; desenharMapa(); },
    }, el("b", { text: u.uf === "ZZ" ? "EXT" : u.uf }), el("span", { text: rotulo }), el("i", { "aria-hidden": "true" }));
  });
  mapa.replaceChildren(...tiles);

  const sel = d.ufs.find((u) => u.uf === estado.uf);
  $("mapa-detalhe").replaceChildren(...(sel ? detalheUf(sel, nm) : ["Toque ou clique em um estado para ver os números dele."]));

  const ordem = ["l3", "l2", "l1", "n", "b1", "b2", "b3"];
  const lados = ESCALA.map((e) => e.rot);
  const rots = [lados[3], lados[2], lados[1], lados[0], lados[1], lados[2], lados[3]];
  $("mapa-legenda").replaceChildren(
    el("p", { text: "Escala: % do candidato que lidera a projeção no estado. A letra no quadrado é a inicial dele." }),
    el("div", { class: "escala", "aria-hidden": "true" },
      ordem.map((b) => el("i", { style: `background:var(--t-${b})` }))),
    el("div", { class: "escala-rot", "aria-hidden": "true" }, rots.map((r) => el("span", { text: r }))),
    el("div", { class: "escala-lados", "aria-hidden": "true" },
      el("span", { text: `← ${nm.esq} (${nm.inicialEsq}) à frente` }), el("span", { text: `${nm.dir} (${nm.inicialDir}) à frente →` })),
  );
}

function detalheUf(u, nm) {
  const l = (t) => el("span", { style: "display:block", text: t });
  const p = u.projecao;
  const sub = [
    l(`${pc(u.pct_secoes, 1)} das seções apuradas.`),
    p
      ? l(`Projeção: ${nm.esq} ${pc(p.centro, 1)} (faixa de ${n(p.baixo)} a ${n(p.alto)}), ${nm.dir} ${pc(100 - p.centro, 1)}.`)
      : l("Projeção: ainda não disponível."),
    l(u.apurado != null ? `Contagem até agora: ${nm.esq} ${pc(u.apurado, 1)}, ${nm.dir} ${pc(100 - u.apurado, 1)}.` : "Contagem até agora: sem votos contados."),
    l(`Para comparar, ${nm.esq} teve ${pc(u.primeiro_turno, 1)} no 1º turno de 2026 (só entre os dois) e ${pc(u.segundo_turno_anterior, 1)} no 2º turno de 2022.`),
  ];
  return [el("strong", { text: u.nome }), ...sub];
}

const COLUNAS = [
  { chave: "nome", rot: () => "Estado", valor: (u) => u.nome },
  { chave: "pct_secoes", rot: () => "Seções apuradas", valor: (u) => u.pct_secoes },
  { chave: "apurado", rot: (nm) => `Contagem (${nm.esq} %)`, valor: (u) => u.apurado },
  { chave: "projecao", rot: (nm) => `Projeção (${nm.esq} %)`, valor: (u) => u.projecao?.centro },
  { chave: "faixa", rot: () => "Faixa da projeção", valor: (u) => u.projecao?.baixo },
  { chave: "primeiro_turno", rot: () => "1º turno 2026", valor: (u) => u.primeiro_turno },
  { chave: "segundo_turno_anterior", rot: () => "2º turno 2022", valor: (u) => u.segundo_turno_anterior },
];

function desenharTabelaUfs() {
  const d = estado.dados;
  const nm = nomes(d);
  const host = $("tabela-estados");
  $("tabela-nota").textContent = `Os números são o percentual de ${nm.esq} nos votos válidos. O de ${nm.dir} é 100 menos esse valor. Clique no título de uma coluna para ordenar.`;
  if (!d.ufs.length) {
    host.replaceChildren();
    host.hidden = true;
    $("tabela-nota").textContent = "A tabela aparece quando a apuração começar.";
    return;
  }
  host.hidden = false;
  const col = COLUNAS.find((c) => c.chave === estado.ord.chave);
  const dir = estado.ord.dir;
  const linhas = [...d.ufs].sort((a, b) => {
    const x = col.valor(a), y = col.valor(b);
    if (x == null || y == null) return (x == null) - (y == null);
    return (typeof x === "string" ? x.localeCompare(y, "pt-BR") : x - y) * dir;
  });
  const cab = COLUNAS.map((c) => {
    const ativo = c.chave === estado.ord.chave;
    return el("th", { scope: "col", "aria-sort": ativo ? (dir === 1 ? "ascending" : "descending") : "none" },
      el("button", {
        type: "button", class: "ord",
        onclick: () => {
          estado.ord = { chave: c.chave, dir: ativo ? -dir : c.chave === "nome" ? 1 : -1 };
          desenharTabelaUfs();
          host.querySelector(`th:nth-child(${COLUNAS.indexOf(c) + 1}) button`).focus();
        },
      }, c.rot(nm), el("span", { class: "seta", "aria-hidden": "true", text: ativo ? (dir === 1 ? "▲" : "▼") : "↕" })));
  });
  const f = (v) => (v == null ? "–" : pc(v, 1));
  const corpo = linhas.map((u) => {
    const r = resumoUf(u, nm);
    const p = u.projecao;
    return el("tr", {},
      el("th", { scope: "row", text: u.nome }),
      el("td", { text: pc(u.pct_secoes, 1) }),
      el("td", { text: f(u.apurado) }),
      el("td", {},
        r ? el("span", { class: `lider ${r.esq ? "lider-esq" : "lider-dir"}` }) : null,
        r ? el("span", { class: "vh", text: `${r.nome} à frente. ` }) : null,
        f(p?.centro)),
      el("td", { text: p && p.alto - p.baixo > 0.005 ? `${n(p.baixo)} a ${n(p.alto)}` : "–" }),
      el("td", { text: f(u.primeiro_turno) }),
      el("td", { text: f(u.segundo_turno_anterior) }),
    );
  });
  host.replaceChildren(el("table", {},
    el("caption", { class: "vh", text: "Estados: seções apuradas, contagem, projeção e resultados anteriores" }),
    el("thead", {}, el("tr", {}, cab)),
    el("tbody", {}, corpo)));
}

/* Como funciona */

function desenharValidacao() {
  const v = textoValidacao(estado.dados);
  $("validacao").hidden = !v;
  if (v) $("validacao-texto").textContent = v;
}

function textoValidacao(d) {
  const ensaios = d.validacao && d.validacao.ensaios;
  if (!ensaios || !ensaios.length) return null;
  const nomes = ensaios.map((e) => `o ${e.eleicao}`).join(" e ");
  const partes = [`Rodamos o mesmo método sobre ${nomes}, recebendo as seções na ordem real em que chegaram e comparando cada projeção com o resultado final.`];
  for (const e of ensaios) {
    partes.push(`No ${e.eleicao}, a partir de ${n(e.desde_pct, 0)}% das seções apuradas, a projeção errou em média ${n(e.erro_medio_pp, 2)} ponto (no máximo ${n(e.erro_max_pp, 2)}), enquanto a contagem bruta estava em média ${n(e.erro_medio_apurado_pp, 1)} pontos longe do final. A faixa de ${n(d.nivel_faixa, 0)}% continha o resultado final em ${n(e.cobertura_faixa * 100, 0)}% dos momentos testados.`);
  }
  return partes.join(" ");
}

/* Orquestração */

function desenhar() {
  const d = estado.dados;
  $("aviso-exemplo").hidden = !d.exemplo;
  desenharResposta();
  desenharGrafico();
  desenharTabelaSerie();
  desenharMapa();
  desenharTabelaUfs();
  desenharValidacao();
}

function iniciar() {
  iniciarTema();
  $("serie-tabela").addEventListener("toggle", desenharTabelaSerie);
  let larguraAnterior = 0;
  new ResizeObserver(([e]) => {
    const w = Math.round(e.contentRect.width);
    if (w && w !== larguraAnterior) {
      larguraAnterior = w;
      if (estado.dados) desenharGrafico();
    }
  }).observe($("grafico"));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && estado.proximo && Date.now() > estado.proximo - 1000) buscar();
  });
  setInterval(tique, 1000);
  buscar();
}

iniciar();
