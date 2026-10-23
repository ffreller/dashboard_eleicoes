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
  sel: null,
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
    case "cruza":
    case "um-lado":
      return "";
    case "encerrada": {
      const e = u.apurado ?? u.projecao?.centro;
      const restante = u.pct_secoes < 99.995 ? ` com ${pc(u.pct_secoes, 2)} das seções apuradas` : "";
      return `A apuração foi encerrada${restante}. Na contagem, ${nm.esq} tem ${pc(e)} dos votos válidos e ${nm.dir} tem ${pc(100 - e)}. A divulgação oficial do resultado é do TSE.`;
    }
  }
}

const ROTULO_FASE = { aguardando: "Aguardando", apurando: "Apurando", encerrada: "Encerrada" };

// Eixo simétrico em torno de 50, para que o 50 fique no meio e a faixa seja legível.
function escalaIncerteza({ baixo, alto }) {
  const meia = Math.max(0.5, 1.2 * Math.max(Math.abs(baixo - 50), Math.abs(alto - 50)));
  const passo = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10].filter((p) => p <= meia).at(-1);
  const casas = [0, 1, 2].find((c) => Math.abs(passo * 10 ** c - Math.round(passo * 10 ** c)) < 1e-9);
  return {
    pos: (v) => ((v - (50 - meia)) / (2 * meia)) * 100,
    ticks: [50 - passo, 50, 50 + passo].map((v) => ({ v, rot: pc(v, v === 50 ? 0 : casas) })),
  };
}

function posicionarTrilha(trilha, baixo, alto, centro, pos) {
  const a = Math.max(0, pos(baixo)), b = Math.min(100, pos(alto));
  trilha.style.setProperty("--a", `${a}%`);
  trilha.style.setProperty("--w", `${Math.max(0, b - a)}%`);
  trilha.style.setProperty("--c", `${pos(centro)}%`);
}

function desenharResposta() {
  const d = estado.dados;
  const sit = situacao(d);
  const nm = nomes(d);

  for (const e of document.querySelectorAll("[data-nome]")) e.textContent = nm[e.dataset.nome];
  $("fase").textContent = ROTULO_FASE[d.fase];
  $("fase").dataset.fase = d.fase;
  $("t-contagem").textContent = d.fase === "encerrada" ? "Contagem final" : "Contagem até agora";

  const u = sit.u;
  const apurado = sit.tipo === "encerrada" ? (u.apurado ?? u.projecao?.centro) : u?.apurado;
  const temNumeros = sit.tipo !== "aguardando" && apurado != null;
  $("cartoes").hidden = !temNumeros;
  if (temNumeros) {
    pctHtml($("pct-esq"), pc(apurado));
    pctHtml($("pct-dir"), pc(100 - apurado));
    $("barra-contagem").style.setProperty("--p", `${apurado}%`);
    const margem = Math.abs(2 * apurado - 100);
    $("vantagem").textContent = margem < 0.005 ? "Empate" : `${apurado > 50 ? nm.esq : nm.dir} +${n(margem, 2)} p.p.`;
    $("apuradas").textContent = pc(u.pct_secoes, u.pct_secoes % 1 ? 1 : 0);
    $("progresso").style.setProperty("--p", `${u.pct_secoes}%`);
  }

  $("frase").textContent = frase(d, sit, nm);

  const proj = sit.tipo === "cruza" || sit.tipo === "um-lado" ? u.projecao : null;
  const aguarde = $("proj-aguarde");
  $("cartao-projecao").hidden = d.fase === "encerrada";
  $("cartoes").classList.toggle("so-contagem", d.fase === "encerrada");
  aguarde.hidden = !!proj;
  aguarde.textContent = `Aparece a partir de ${n(d.projecao_desde_pct, 0)}% das seções apuradas.`;
  $("proj").hidden = !proj;
  const ch = proj && chanceDe(d, u);
  $("chance").hidden = !ch;
  if (proj) {
    pctHtml($("proj-pct-esq"), pc(proj.centro));
    pctHtml($("proj-pct-dir"), pc(100 - proj.centro));
    const { pos, ticks } = escalaIncerteza(proj);
    posicionarTrilha($("trilha-esq"), proj.baixo, proj.alto, proj.centro, pos);
    posicionarTrilha($("trilha-dir"), 100 - proj.alto, 100 - proj.baixo, 100 - proj.centro, pos);
    $("eixo").replaceChildren(...ticks.map((t) => el("span", { style: `--x:${pos(t.v)}%`, text: t.rot })));
  }
  if (ch) {
    $("chance-esq").textContent = ch.esq;
    $("chance-dir").textContent = ch.dir;
    $("chance-barra").style.setProperty("--p", `${u.projecao.chance}%`);
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

function pontosDe(v) {
  return [
    ["ponto-bruto cor-esq", v],
    ["ponto-bruto cor-dir", v == null ? null : 100 - v],
  ];
}

// Caminho da contagem do ponto atual até 100% se ela terminar na projeção (ou numa ponta da faixa).
// O voto restante entra a uma taxa constante, então a parcial acumulada é a média ponderada
// do que já foi contado com essa taxa: anda rápido logo depois do ponto atual e depois se acomoda.
function caminhoAteFim(q, passos = 32) {
  const pr = q.projecao;
  if (!pr || q.apurado == null || q.pct_secoes >= 100) return [];
  const f0 = (q.pct_aptos ?? q.pct_secoes) / 100;
  const acumulado = (fim, f) => {
    const taxa = (fim - f0 * q.apurado) / (1 - f0);
    return (f0 * q.apurado + (f - f0) * taxa) / f;
  };
  return Array.from({ length: passos + 1 }, (_, k) => {
    const t = k / passos;
    const f = f0 + t * (1 - f0);
    return {
      x: q.pct_secoes + t * (100 - q.pct_secoes),
      centro: acumulado(pr.centro, f),
      baixo: acumulado(pr.baixo, f),
      alto: acumulado(pr.alto, f),
    };
  });
}

function desenharGrafico() {
  const d = estado.dados;
  const host = $("grafico");
  const serie = d.serie;
  host.replaceChildren();
  desenhoGrafico = null;
  if (!serie.length) {
    host.append(el("p", { class: "leitura-vazia", text: "O gráfico aparece quando os primeiros resultados chegarem." }));
    return;
  }

  const nm = nomes(d);
  const W = Math.max(280, host.clientWidth);
  const H = Math.round(Math.min(560, Math.max(300, W * 0.68)));
  const ultimo = serie.at(-1);
  const agora = d.fase === "apurando" && ultimo.pct_secoes < 100;
  const M = { t: agora ? 26 : 10, r: 14, b: 44, l: 42 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;

  // Eixo simétrico em torno de 50%: as linhas dos dois candidatos são espelhos uma da outra.
  let desvio = 3;
  for (const v of [...serie.filter((q) => q.pct_secoes >= d.projecao_desde_pct).map((q) => q.apurado), ultimo.projecao?.baixo, ultimo.projecao?.alto]) {
    if (v != null) desvio = Math.max(desvio, Math.abs(v - 50));
  }
  desvio = Math.min(50, desvio * 1.16);
  const lo = 50 - desvio, hi = 50 + desvio;

  const X = (p) => M.l + (p / 100) * iw;
  const Y = (v) => M.t + ((hi - v) / (hi - lo)) * ih;

  const passo = passoNice(hi - lo, 3);
  const ticksY = [];
  for (let k = -Math.floor(desvio / passo + 1e-9); k <= Math.floor(desvio / passo + 1e-9); k++) ticksY.push(Math.round((50 + k * passo) * 100) / 100);

  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", tabindex: "0", focusable: "true" });
  svg.setAttribute("aria-label", `Gráfico da evolução. Último ponto: ${pc(ultimo.pct_secoes, 1)} das seções apuradas`
    + (ultimo.projecao ? `, projeção final de ${nm.esq} em ${pc(ultimo.projecao.centro)} e de ${nm.dir} em ${pc(100 - ultimo.projecao.centro)}` : "")
    + `. Use as setas do teclado para percorrer os pontos. Os mesmos dados estão na tabela abaixo.`);

  const recorte = sv("clipPath", { id: "recorte" }, sv("rect", { x: M.l, y: M.t, width: iw, height: ih }));
  svg.append(sv("defs", {}, recorte));

  const y50 = Y(50);

  if (agora) {
    svg.append(
      sv("rect", { class: "futuro", x: X(ultimo.pct_secoes), y: M.t, width: X(100) - X(ultimo.pct_secoes), height: ih }),
      sv("line", { class: "agora", x1: X(ultimo.pct_secoes), x2: X(ultimo.pct_secoes), y1: M.t - 4, y2: M.t + ih }),
    );
    const rotAgora = sv("text", { x: X(ultimo.pct_secoes), y: M.t - 10, "text-anchor": "middle" });
    rotAgora.textContent = "Agora";
    svg.append(rotAgora);
  }
  for (const v of ticksY) {
    if (v === 50) continue;
    svg.append(sv("line", { class: "grade", x1: M.l, x2: M.l + iw, y1: Y(v), y2: Y(v) }));
  }
  for (const p of [0, 25, 50, 75, 100]) {
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
  titulo.textContent = "Seções apuradas";
  svg.append(
    sv("line", { class: "eixo", x1: M.l, x2: M.l + iw, y1: M.t + ih, y2: M.t + ih }),
    sv("line", { class: "ref50", x1: M.l, x2: M.l + iw, y1: y50, y2: y50 }),
    titulo,
  );

  const pto = (x, y) => `${X(x).toFixed(1)},${Y(y).toFixed(1)}`;
  const espelhar = (v) => 100 - v;
  const igual = (v) => v;
  const contagem = (f) => segmentos(serie, (q) => q.apurado).map((s) => "M" + s.map(([q, v]) => pto(q.pct_secoes, f(v))).join("L")).join("");
  const caminho = caminhoAteFim(ultimo);
  const fimLinha = (f) => caminho.length ? "M" + caminho.map((c) => pto(c.x, f(c.centro))).join("L") : "";
  const fimFaixa = (f) => caminho.length
    ? `M${caminho.map((c) => pto(c.x, f(c.alto))).join("L")}L${caminho.map((c) => pto(c.x, f(c.baixo))).reverse().join("L")}Z`
    : "";
  const grupo = sv("g", { "clip-path": "url(#recorte)" },
    sv("path", { class: "faixa-area cor-esq", d: fimFaixa(igual) }),
    sv("path", { class: "faixa-area cor-dir", d: fimFaixa(espelhar) }),
    sv("path", { class: "linha-proj cor-esq", d: fimLinha(igual) }),
    sv("path", { class: "linha-proj cor-dir", d: fimLinha(espelhar) }),
    sv("path", { class: "linha-bruta cor-esq", d: contagem(igual) }),
    sv("path", { class: "linha-bruta cor-dir", d: contagem(espelhar) }),
  );
  svg.append(grupo);

  const dentro = (v) => v != null && v >= lo && v <= hi;
  if (caminho.length) {
    for (const [cls, v] of [["ponto-proj cor-esq", ultimo.projecao.centro], ["ponto-proj cor-dir", 100 - ultimo.projecao.centro]]) {
      if (dentro(v)) svg.append(sv("circle", { class: cls, cx: X(100), cy: Y(v), r: 5 }));
    }
  }
  for (const [cls, v] of pontosDe(ultimo.apurado)) {
    if (dentro(v)) svg.append(sv("circle", { class: cls, cx: X(ultimo.pct_secoes), cy: Y(v), r: 4.5 }));
  }

  const mira = sv("g", { visibility: "hidden", "pointer-events": "none" },
    sv("line", { class: "mira", y1: M.t, y2: M.t + ih }),
    ...pontosDe(null).map(([cls]) => sv("circle", { class: cls, r: 4.5 })),
  );
  svg.append(mira);

  const alvo = sv("rect", { x: M.l, y: M.t, width: iw, height: ih, fill: "transparent" });
  svg.append(alvo);
  const dica = el("div", { class: "dica", hidden: true });
  host.append(svg, dica);

  // Contagem até agora seguida do caminho projetado até 100%, ambos navegáveis pelo mouse e pelo teclado.
  const pontos = [
    ...serie.map((q) => ({ x: q.pct_secoes, v: q.apurado, q })),
    ...caminho.slice(1).map((c) => ({ x: c.x, v: c.centro, c, final: ultimo.projecao })),
  ];
  desenhoGrafico = { X, Y, M, W, mira, dica, svg, pontos, lo, hi, nm, d };
  const pctDe = (clientX) => {
    const r = svg.getBoundingClientRect();
    return ((clientX - r.left) * (W / r.width) - M.l) / iw * 100;
  };
  const pos = (e) => definirSel(pontos[indiceMaisProximo(pontos, pctDe(e.clientX))].x);
  alvo.addEventListener("pointerdown", pos);
  alvo.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse" || e.buttons || e.pointerType === "touch") pos(e); });
  alvo.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") definirSel(null); });
  svg.addEventListener("keydown", (e) => {
    const atual = indiceMaisProximo(pontos, estado.sel ?? ultimo.pct_secoes);
    const passoTecla = { ArrowLeft: -1, ArrowRight: 1, PageDown: -10, PageUp: 10 }[e.key];
    const ir = (i) => definirSel(pontos[Math.min(pontos.length - 1, Math.max(0, i))].x);
    if (passoTecla) ir(atual + passoTecla);
    else if (e.key === "Home") ir(0);
    else if (e.key === "End" || e.key === "Escape") definirSel(null);
    else return;
    e.preventDefault();
  });

  desenharMira();
}

function indiceMaisProximo(pontos, p) {
  let a = 0, b = pontos.length - 1;
  while (b - a > 1) {
    const m = (a + b) >> 1;
    if (pontos[m].x <= p) a = m; else b = m;
  }
  return Math.abs(pontos[a].x - p) <= Math.abs(pontos[b].x - p) ? a : b;
}

function definirSel(x) {
  if (x === estado.sel) return;
  estado.sel = x;
  desenharMira();
}

function conteudoDica(d, nm, p) {
  const linha = (lado, ...vals) => [
    el("span", { class: `dica-nome cor-${lado}` }, el("i", { class: "dica-cor" }), nm[lado]),
    ...vals.map((v) => el("span", { text: v })),
  ];
  const f = (v) => (v == null ? "–" : pc(v));
  const proj = p.final ?? p.q.projecao;
  const comFinal = proj != null;
  const tabela = el("div", { class: `dica-tab${comFinal ? " com-final" : ""}` },
    el("span"),
    el("span", { class: "dica-cab", text: p.final ? "Contagem estimada" : "Contagem" }),
    comFinal ? el("span", { class: "dica-cab", text: "Final projetado" }) : null,
    ...linha("esq", f(p.v), ...(comFinal ? [f(proj.centro)] : [])),
    ...linha("dir", f(p.v == null ? null : 100 - p.v), ...(comFinal ? [f(100 - proj.centro)] : [])),
  );
  const faixa = p.final ? p.c : proj;
  const chance = p.final ? null : chanceDe(d, p.q);
  return [
    el("strong", { text: `${pc(p.x, p.final ? 0 : 2)} das seções apuradas` }),
    el("span", { class: "dica-sub", text: p.final ? "Projeção, se o ritmo atual se mantiver" : hm(p.q.hora) }),
    tabela,
    faixa ? el("span", { class: "dica-sub", text: `${p.final ? "Faixa da contagem" : "Faixa da projeção"} (${nm.esq}): ${n(faixa.baixo)} a ${n(faixa.alto)}` }) : null,
    chance ? el("span", { class: "dica-sub", text: `Chance de vencer: ${nm.esq} ${chance.esq} · ${nm.dir} ${chance.dir}` }) : null,
  ];
}

function desenharMira() {
  const g = desenhoGrafico;
  if (!g) return;
  if (estado.sel == null) { g.mira.setAttribute("visibility", "hidden"); g.dica.hidden = true; return; }
  const p = g.pontos[indiceMaisProximo(g.pontos, estado.sel)];
  const [linha, ...circulos] = g.mira.children;
  linha.setAttribute("x1", g.X(p.x)); linha.setAttribute("x2", g.X(p.x));
  pontosDe(p.v).forEach(([cls, v], k) => {
    const ok = v != null && v >= g.lo && v <= g.hi;
    circulos[k].setAttribute("visibility", ok ? "visible" : "hidden");
    circulos[k].setAttribute("class", p.final ? cls.replace("ponto-bruto", "ponto-proj") : cls);
    if (ok) { circulos[k].setAttribute("cx", g.X(p.x)); circulos[k].setAttribute("cy", g.Y(v)); }
  });
  g.mira.setAttribute("visibility", "visible");

  g.dica.replaceChildren(...conteudoDica(g.d, g.nm, p).filter(Boolean));
  g.dica.hidden = false;
  const escala = g.svg.getBoundingClientRect().width / g.W;
  const cx = g.X(p.x) * escala;
  const largura = g.dica.offsetWidth;
  const direita = cx + 12 + largura <= g.svg.getBoundingClientRect().width;
  g.dica.style.left = `${Math.max(0, direita ? cx + 12 : cx - 12 - largura)}px`;
  g.dica.style.top = `${(g.M.t + 4) * escala}px`;
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

function iniciarAbas() {
  const abas = [...document.querySelectorAll('[role="tab"]')];
  const mostrar = (aba, foco) => {
    for (const a of abas) {
      const ativa = a === aba;
      a.setAttribute("aria-selected", ativa);
      a.tabIndex = ativa ? 0 : -1;
      $(a.getAttribute("aria-controls")).hidden = !ativa;
    }
    if (foco) aba.focus();
    history.replaceState(null, "", aba === abas[0] ? location.pathname + location.search : `#${aba.getAttribute("aria-controls")}`);
  };
  abas.forEach((a, i) => {
    a.addEventListener("click", () => mostrar(a));
    a.addEventListener("keydown", (e) => {
      const passo = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (passo) { e.preventDefault(); mostrar(abas[(i + passo + abas.length) % abas.length], true); }
      else if (e.key === "Home") { e.preventDefault(); mostrar(abas[0], true); }
      else if (e.key === "End") { e.preventDefault(); mostrar(abas.at(-1), true); }
    });
  });
  const inicial = abas.find((a) => a.getAttribute("aria-controls") === location.hash.slice(1));
  if (inicial) mostrar(inicial);
}

function iniciar() {
  iniciarTema();
  iniciarAbas();
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
