"use strict";

const ATUALIZAR_S = 30;
const TSE_S = 20;
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
// Fração de seções com uma casa, sem mostrar "0,0%" quando já há votos contados.
const pcSecoes = (x) => (x > 0 && x < 0.05 ? "menos de 0,1%" : pc(x, 1));
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
const ARQUIVO = params.has("sintetico")
  ? params.get("sintetico") ? `dados/sintetico-${encodeURIComponent(params.get("sintetico"))}.json` : "dados/sintetico-metade.json"
  : "dados/projecao.json";

const estado = {
  dados: null,
  bruto: "",
  falha: null,
  proximo: 0,
  tse: null,
  tseFalha: null,
  sel: null,
  referencias: null,
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
  if (estado.dados?.tse && !tseLigado) {
    tseLigado = true;
    buscarTse();
  }
}

// Arquivo nacional do TSE no formato de um ponto da série. Antes da apuração não há votos, e então não há ponto.
function pontoTse(j, numEsq, numDir) {
  const vap = {};
  for (const a of j.carg[0].agr) for (const p of a.par) for (const c of p.cand) vap[c.n] = Number(c.vap);
  const esq = vap[numEsq], dir = vap[numDir], st = Number(j.s.st), ts = Number(j.s.ts);
  if (!(esq >= 0 && dir >= 0 && ts > 0)) throw new Error("arquivo do TSE em formato inesperado");
  if (esq + dir === 0) return null;
  const [dia, mes, ano] = j.dt.split("/");
  const hora = `${ano}-${mes}-${dia}T${j.ht}-03:00`;
  if (Number.isNaN(Date.parse(hora))) throw new Error("arquivo do TSE sem hora de totalização");
  return { hora, pct_secoes: (100 * st) / ts, apurado: (100 * esq) / (esq + dir), votos_validos: esq + dir };
}

let temporizadorTse = 0;
let tseLigado = false;

async function buscarTse() {
  clearTimeout(temporizadorTse);
  const d = estado.dados;
  try {
    // Sem `?t=`: o CDN do TSE responde 304 pelo ETag, e furar o cache dele multiplicaria a carga.
    const r = await fetch(d.tse, { cache: "no-cache", signal: AbortSignal.timeout ? AbortSignal.timeout(10000) : undefined });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const ponto = pontoTse(await r.json(), d.candidatos.esq.numero, d.candidatos.dir.numero);
    estado.tseFalha = null;
    if (JSON.stringify(ponto) !== JSON.stringify(estado.tse)) {
      estado.tse = ponto;
      desenharResposta();
    }
  } catch (e) {
    console.warn("Falha ao ler o TSE:", e);
    estado.tseFalha ??= new Date();
  }
  desenharStatus();
  temporizadorTse = setTimeout(buscarTse, TSE_S * 1000);
}

/* Situação */

// A mais adiantada entre a contagem lida do TSE pelo navegador e o último ponto da projeção: mais seções vence,
// e a hora só desempata. A hora sozinha não serve: o ponto da projeção leva a hora da última seção dos arquivos
// por UF, que pode ser posterior à do arquivo nacional mesmo vendo bem menos seções. Comparar seções também
// impede que uma cópia antiga do CDN faça a contagem recuar.
function contagem(d) {
  const u = d.fase === "aguardando" ? undefined : d.serie.at(-1);
  const t = estado.tse;
  if (!t || !u) return t ?? u;
  if (t.pct_secoes !== u.pct_secoes) return t.pct_secoes > u.pct_secoes ? t : u;
  return Date.parse(t.hora) >= Date.parse(u.hora) ? t : u;
}

function situacao(d) {
  const u = d.serie.at(-1);
  const c = contagem(d);
  if (!c) return { tipo: "aguardando" };
  if (d.fase === "encerrada") return { tipo: "encerrada", u, c };
  if (!u?.projecao) return { tipo: "sem-projecao", u, c };
  const { baixo, alto } = u.projecao;
  return { tipo: baixo <= 50 && alto >= 50 ? "cruza" : "um-lado", u, c };
}

const curto = (nome) => nome.split(" ")[0];

function nomes(d) {
  const e = d.candidatos.esq, r = d.candidatos.dir;
  return { esq: curto(e.nome), dir: curto(r.nome), inicialEsq: curto(e.nome)[0], inicialDir: curto(r.nome)[0] };
}

/* Status e tema */

function desenharStatus() {
  const d = estado.dados;
  const txt = $("status");
  let msg;
  if (estado.falha && !d) msg = `Não foi possível carregar os dados às ${hms(estado.falha)}. Nova tentativa às ${hms(estado.proximo)}.`;
  else if (estado.falha) msg = `Não foi possível atualizar às ${hms(estado.falha)}. Continuamos mostrando os dados de ${hms(d.atualizado)}. Nova tentativa às ${hms(estado.proximo)}.`;
  else if (d && estado.tse) msg = `Contagem do TSE das ${hms(estado.tse.hora)}. Projeção atualizada às ${hms(d.atualizado)} (Brasília).`;
  else if (d) msg = `Dados atualizados às ${hms(d.atualizado)} (Brasília).`;
  else msg = "Carregando os dados…";
  if (d && estado.tseFalha) msg += ` O TSE não responde desde ${hms(estado.tseFalha)}.`;
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
  const { u, c } = sit;
  switch (sit.tipo) {
    case "aguardando":
      return "A apuração ainda não começou. Esta página se atualiza sozinha quando o TSE divulgar os primeiros resultados.";
    case "sem-projecao":
      if (c.pct_secoes >= d.projecao_desde_pct) return `${pc(c.pct_secoes, 1)} das seções foram apuradas. A projeção aparece em uma das próximas atualizações.`;
      return `${c.pct_secoes > 0 && c.pct_secoes < 0.05 ? "Menos de 0,1%" : `Só ${pc(c.pct_secoes, 1)}`} das seções foram apuradas. A projeção aparece quando a contagem chegar a ${n(d.projecao_desde_pct, 0)}%. Até lá, o total parcial diz pouco sobre o resultado final.`;
    case "cruza":
    case "um-lado":
      return "";
    case "encerrada": {
      const e = c.apurado ?? u?.projecao?.centro;
      const restante = c.pct_secoes < 99.995 ? ` com ${pc(c.pct_secoes, 2)} das seções apuradas` : "";
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
  // Rótulos nas pontas da faixa (acima na trilha de cima, abaixo na de baixo), encostados na borda quando não cabem centralizados.
  const [lo, hi] = trilha.querySelectorAll(".lim");
  const rotular = (el, v, x) => {
    el.textContent = pc(v, 2);
    el.style.left = `${x}%`;
    el.style.setProperty("--tx", x < 10 ? "0" : x > 90 ? "-100%" : "-50%");
  };
  rotular(lo, baixo, a);
  rotular(hi, alto, b);
}

function desenharResposta() {
  const d = estado.dados;
  const sit = situacao(d);
  const nm = nomes(d);

  for (const e of document.querySelectorAll("[data-nome]")) e.textContent = nm[e.dataset.nome];
  // O TSE pode mostrar votos antes de a projeção sair de "aguardando".
  const fase = d.fase === "aguardando" && sit.tipo !== "aguardando" ? "apurando" : d.fase;
  $("fase").textContent = ROTULO_FASE[fase];
  $("fase").dataset.fase = fase;
  $("t-contagem").textContent = d.fase === "encerrada" ? "Contagem final" : "Apuração";

  const { u, c } = sit;
  const apurado = sit.tipo === "encerrada" ? (c.apurado ?? u?.projecao?.centro) : c?.apurado;
  const temNumeros = sit.tipo !== "aguardando" && apurado != null;
  $("cartoes").hidden = !temNumeros;
  if (temNumeros) {
    pctHtml($("pct-esq"), pc(apurado));
    pctHtml($("pct-dir"), pc(100 - apurado));
    $("barra-contagem").style.setProperty("--p", `${apurado}%`);
    const margem = Math.abs(2 * apurado - 100);
    $("vantagem").textContent = margem < 0.005 ? "Empate" : `${apurado > 50 ? nm.esq : nm.dir} +${n(margem, 2)} p.p.`;
    $("apuradas").textContent = c.pct_secoes % 1 ? pcSecoes(c.pct_secoes) : pc(c.pct_secoes, 0);
    document.querySelector(".apurado").hidden = d.fase === "encerrada";
  }

  $("frase").textContent = frase(d, sit, nm);

  const proj = sit.tipo === "cruza" || sit.tipo === "um-lado" ? u.projecao : null;
  const aguarde = $("proj-aguarde");
  $("cartao-projecao").hidden = d.fase === "encerrada";
  $("cartoes").classList.toggle("so-contagem", d.fase === "encerrada");
  aguarde.hidden = !!proj;
  aguarde.textContent = `Aparece a partir de ${n(d.projecao_desde_pct, 0)}% das seções apuradas.`;
  $("proj").hidden = !proj;
  if (proj) {
    pctHtml($("proj-pct-esq"), pc(proj.centro));
    pctHtml($("proj-pct-dir"), pc(100 - proj.centro));
    const { pos, ticks } = escalaIncerteza(proj);
    posicionarTrilha($("trilha-esq"), proj.baixo, proj.alto, proj.centro, pos);
    posicionarTrilha($("trilha-dir"), 100 - proj.alto, 100 - proj.baixo, 100 - proj.centro, pos);
    $("eixo").replaceChildren(...ticks.map((t) => el("span", { style: `--x:${pos(t.v)}%`, text: t.rot })));
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
  $("legenda").hidden = !serie.length;
  if (!serie.length) {
    host.append(el("p", { class: "leitura-vazia", text: "O gráfico aparece quando os primeiros resultados chegarem." }));
    return;
  }

  const nm = nomes(d);
  const W = Math.max(280, host.clientWidth);
  const H = Math.round(Math.min(560, Math.max(300, W * 0.45)));
  const ultimo = serie.at(-1);
  // Antes de projecao_desde_pct a contagem oscila demais: fica fora do traçado e da escala.
  const cedo = ultimo.pct_secoes < d.projecao_desde_pct;
  $("legenda-contagem").hidden = cedo;
  $("legenda-cedo").hidden = !cedo;
  $("legenda-cedo").textContent = `Contagem: aparece a partir de ${n(d.projecao_desde_pct, 0)}% das seções apuradas`;
  const agora = d.fase === "apurando" && ultimo.pct_secoes < 100 && !cedo;
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

  const passo = passoNice(hi - lo, 4);
  const ticksY = [];
  for (let k = -Math.floor(desvio / passo + 1e-9); k <= Math.floor(desvio / passo + 1e-9); k++) ticksY.push(Math.round((50 + k * passo) * 100) / 100);

  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", tabindex: "0", focusable: "true" });
  svg.setAttribute("aria-label", `Gráfico da evolução. Último ponto: ${pcSecoes(ultimo.pct_secoes)} das seções apuradas`
    + (ultimo.projecao ? `, projeção de ${nm.esq} em ${pc(ultimo.projecao.centro)} e de ${nm.dir} em ${pc(100 - ultimo.projecao.centro)}` : "")
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
  const contagem = (f) => segmentos(serie, (q) => (q.pct_secoes >= d.projecao_desde_pct ? q.apurado : null)).map((s) => "M" + s.map(([q, v]) => pto(q.pct_secoes, f(v))).join("L")).join("");
  const caminho = caminhoAteFim(ultimo);
  for (const li of $("legenda").querySelectorAll("[data-proj]")) li.hidden = !caminho.length;
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
  for (const [cls, v] of pontosDe(cedo ? null : ultimo.apurado)) {
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

  // Apuração seguida do caminho projetado até 100%, ambos navegáveis pelo mouse e pelo teclado.
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
  desenharMiraComparacao();
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
  return [
    el("strong", { text: `${pc(p.x, p.final ? 0 : 2)} das seções apuradas` }),
    el("span", { class: "dica-sub", text: p.final ? "Projeção, se o ritmo atual se mantiver" : hm(p.q.hora) }),
    tabela,
    faixa ? el("span", { class: "dica-sub", text: `${p.final ? "Faixa da contagem" : "Faixa da projeção"} (${nm.esq}): ${n(faixa.baixo)} a ${n(faixa.alto)}` }) : null,
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
  const linhas = [...d.serie].reverse().map((q) => el("tr", {},
    el("th", { scope: "row", text: hm(q.hora) }),
    el("td", { text: pc(q.pct_secoes, 2) }),
    el("td", { text: f(q.apurado) }),
    el("td", { text: f(q.projecao?.centro) }),
    el("td", { text: q.projecao ? `${n(q.projecao.baixo)} a ${n(q.projecao.alto)}` : "–" }),
  ));
  corpo.replaceChildren(el("table", {},
    el("caption", { class: "vh", text: `Evolução da contagem e da projeção, em % de ${nm.esq} nos votos válidos` }),
    el("thead", {}, el("tr", {},
      ...["Hora", "Seções apuradas", `Contagem (${nm.esq} %)`, `Projeção (${nm.esq} %)`, "Faixa da projeção"].map((t) => el("th", { scope: "col", text: t })))),
    el("tbody", {}, linhas)));
}

/* Gráfico de comparação */

const CURTO = { atual: "2026", "1t2026": "1º turno 2026", "2t2022": "2022" };
const CURTO_ESTREITO = { ...CURTO, "1t2026": "1ºT 2026" };
const sinal = (v, d = 1) => (Math.abs(v) < 0.5 * 10 ** -d ? n(0, d) : (v > 0 ? "+" : "−") + n(Math.abs(v), d));

function curvasComparacao(d) {
  const atual = d.fase === "aguardando" ? [] : d.serie.filter((q) => q.apurado != null && q.pct_secoes >= d.projecao_desde_pct).map((q) => [q.pct_secoes, 2 * q.apurado - 100]);
  const rotulo = `2º turno de 2026 (${d.fase === "encerrada" ? "final" : "agora"})`;
  return [{ id: "atual", rotulo, pontos: atual }, ...estado.referencias.curvas].filter((c) => c.pontos.length);
}

function valorEm(pontos, x) {
  if (x < pontos[0][0] || x > pontos.at(-1)[0]) return null;
  const i = pontos.findIndex((p) => p[0] >= x);
  if (i <= 0) return pontos[0][1];
  const [x0, y0] = pontos[i - 1], [x1, y1] = pontos[i];
  return x1 === x0 ? y1 : y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
}

let desenhoComparacao = null;

function desenharComparacao() {
  const d = estado.dados;
  if (!estado.referencias || !d) return;
  $("comparacao").hidden = false;
  const host = $("grafico-comparacao");
  host.replaceChildren();
  desenhoComparacao = null;

  const curvas = curvasComparacao(d);
  const semAtual = d.fase !== "aguardando" && !curvas.some((c) => c.id === "atual");
  $("legenda-comparacao").replaceChildren(
    ...curvas.map((c) => el("li", {}, el("i", { class: `sw-cmp cmp-${c.id}` }), c.rotulo)),
    ...(semAtual ? [el("li", {}, `2º turno de 2026: aparece a partir de ${n(d.projecao_desde_pct, 0)}% das seções apuradas`)] : []),
  );

  const ultimo = d.serie.at(-1);
  const agora = d.fase === "apurando" && ultimo && ultimo.pct_secoes < 100 && !semAtual;
  const W = Math.max(280, host.clientWidth);
  const H = Math.round(Math.min(480, Math.max(260, W * 0.42)));
  const estreito = W < 480;
  const M = { t: agora ? 26 : 10, r: estreito ? 88 : 122, b: 44, l: 42 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;

  let min = 0, max = 0;
  for (const c of curvas) for (const [x, v] of c.pontos) if (x >= d.projecao_desde_pct) { min = Math.min(min, v); max = Math.max(max, v); }
  const folga = Math.max(1, (max - min) * 0.1);
  const lo = min - folga, hi = max + folga;
  const X = (p) => M.l + (p / 100) * iw;
  const Y = (v) => M.t + ((hi - v) / (hi - lo)) * ih;
  const passo = passoNice(hi - lo, 5);
  const ticksY = [];
  for (let v = Math.ceil(lo / passo) * passo; v <= hi + 1e-9; v += passo) ticksY.push(Math.round(v * 100) / 100);
  const casas = passo < 1 ? 1 : 0;

  const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", tabindex: "0", focusable: "true" });
  const ref = ultimo && d.fase !== "aguardando" ? ultimo.pct_secoes : 50;
  const resumo = curvas.map((c) => { const v = valorEm(c.pontos, ref); return v == null ? null : `${c.rotulo}, ${sinal(v)} p.p.`; }).filter(Boolean);
  svg.setAttribute("aria-label", `Gráfico da diferença entre Lula e Bolsonaro, em pontos percentuais, no mesmo ponto da apuração. Positivo é Lula à frente. Com ${pc(ref, 1)} das seções apuradas: ${resumo.join("; ")}. Use as setas do teclado para percorrer o gráfico.`);
  svg.append(sv("defs", {}, sv("clipPath", { id: "recorte-cmp" }, sv("rect", { x: M.l, y: M.t, width: iw, height: ih }))));

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
    if (v !== 0) svg.append(sv("line", { class: "grade", x1: M.l, x2: M.l + iw, y1: Y(v), y2: Y(v) }));
    const t = sv("text", { x: M.l - 6, y: Y(v) + 4, "text-anchor": "end" });
    t.textContent = sinal(v, casas);
    svg.append(t);
  }
  for (const p of [0, 25, 50, 75, 100]) {
    const t = sv("text", { x: X(p), y: M.t + ih + 16, "text-anchor": p === 0 ? "start" : p === 100 ? "end" : "middle" });
    t.textContent = `${p}%`;
    svg.append(t);
  }
  const titulo = sv("text", { x: M.l + iw / 2, y: H - 6, "text-anchor": "middle" });
  titulo.textContent = "Seções apuradas";
  svg.append(
    sv("line", { class: "eixo", x1: M.l, x2: M.l + iw, y1: M.t + ih, y2: M.t + ih }),
    sv("line", { class: "ref50", x1: M.l, x2: M.l + iw, y1: Y(0), y2: Y(0) }),
    titulo,
  );

  // Referências primeiro, a de hoje por cima.
  svg.append(sv("g", { "clip-path": "url(#recorte-cmp)" },
    ...[...curvas].reverse().map((c) => sv("path", { class: `linha-cmp cmp-${c.id}`, d: c.pontos.filter(([x]) => x >= d.projecao_desde_pct).map(([x, v], k) => `${k ? "L" : "M"}${X(x).toFixed(1)},${Y(v).toFixed(1)}`).join("") }))));

  // Rótulo no fim de cada linha, afastado dos vizinhos quando se encostam.
  const fins = curvas.map((c) => {
    const [x, v] = c.pontos.at(-1);
    return { c, x: X(x) + 8, y: Math.min(M.t + ih - 2, Math.max(M.t + 8, Y(v) + 4)), v };
  }).sort((a, b) => a.y - b.y);
  fins.forEach((f, i) => {
    const antes = fins.slice(0, i).filter((o) => Math.abs(o.x - f.x) < (estreito ? 72 : 104));
    if (antes.length) f.y = Math.max(f.y, antes.at(-1).y + 13);
  });
  for (const f of fins) {
    const t = sv("text", { class: `rot-cmp cmp-${f.c.id}`, x: f.x, y: f.y });
    t.textContent = `${(estreito ? CURTO_ESTREITO : CURTO)[f.c.id]} ${sinal(f.v)}`;
    svg.append(t);
    if (f.c.id === "atual") svg.append(sv("circle", { class: "ponto-cmp cmp-atual", cx: f.x - 8, cy: Y(f.v), r: 4.5 }));
  }

  const mira = sv("g", { visibility: "hidden", "pointer-events": "none" },
    sv("line", { class: "mira", y1: M.t, y2: M.t + ih }),
    ...curvas.map((c) => sv("circle", { class: `ponto-cmp cmp-${c.id}`, r: 4 })),
  );
  const alvo = sv("rect", { x: M.l, y: M.t, width: iw, height: ih, fill: "transparent" });
  const dica = el("div", { class: "dica", hidden: true });
  svg.append(mira, alvo);
  host.append(svg, dica);
  desenhoComparacao = { X, Y, M, W, mira, dica, svg, curvas, lo, hi };

  const pos = (e) => {
    const r = svg.getBoundingClientRect();
    const p = (((e.clientX - r.left) * (W / r.width) - M.l) / iw) * 100;
    definirSel(Math.min(100, Math.max(0, Math.round(p * 2) / 2)));
  };
  alvo.addEventListener("pointerdown", pos);
  alvo.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse" || e.buttons || e.pointerType === "touch") pos(e); });
  alvo.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") definirSel(null); });
  svg.addEventListener("keydown", (e) => {
    const atual = estado.sel ?? ref;
    const passoTecla = { ArrowLeft: -0.5, ArrowRight: 0.5, PageDown: -5, PageUp: 5 }[e.key];
    if (passoTecla) definirSel(Math.min(100, Math.max(0, Math.round((atual + passoTecla) * 2) / 2)));
    else if (e.key === "Home") definirSel(0);
    else if (e.key === "End" || e.key === "Escape") definirSel(null);
    else return;
    e.preventDefault();
  });

  desenharMiraComparacao();
}

function desenharMiraComparacao() {
  const g = desenhoComparacao;
  if (!g) return;
  if (estado.sel == null) { g.mira.setAttribute("visibility", "hidden"); g.dica.hidden = true; return; }
  const x = estado.sel;
  const vals = g.curvas.map((c) => valorEm(c.pontos, x));
  const [linha, ...circulos] = g.mira.children;
  linha.setAttribute("x1", g.X(x)); linha.setAttribute("x2", g.X(x));
  vals.forEach((v, k) => {
    const ok = v != null && v >= g.lo && v <= g.hi;
    circulos[k].setAttribute("visibility", ok ? "visible" : "hidden");
    if (ok) { circulos[k].setAttribute("cx", g.X(x)); circulos[k].setAttribute("cy", g.Y(v)); }
  });
  g.mira.setAttribute("visibility", "visible");

  g.dica.replaceChildren(
    el("strong", { text: `${pc(x, x % 1 ? 1 : 0)} das seções apuradas` }),
    el("div", { class: "dica-tab" }, ...g.curvas.flatMap((c, k) => [
      el("span", { class: "dica-nome" }, el("i", { class: `sw-cmp cmp-${c.id}` }), c.rotulo),
      el("span", { text: vals[k] == null ? "–" : `${sinal(vals[k])} p.p.` }),
    ])),
  );
  g.dica.hidden = false;
  const larguraSvg = g.svg.getBoundingClientRect().width;
  const cx = g.X(x) * (larguraSvg / g.W);
  const largura = g.dica.offsetWidth;
  const direita = cx + 12 + largura <= larguraSvg;
  g.dica.style.left = `${Math.max(0, direita ? cx + 12 : cx - 12 - largura)}px`;
  g.dica.style.top = `${(g.M.t + 4) * (larguraSvg / g.W)}px`;
}

async function carregarReferencias() {
  try {
    const r = await fetch("dados/referencias.json");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const { curvas } = await r.json();
    if (!Array.isArray(curvas) || !curvas.every((c) => c.id && Array.isArray(c.pontos) && c.pontos.length)) throw new Error("referências em formato inesperado");
    estado.referencias = { curvas };
    desenharComparacao();
  } catch (e) {
    console.warn("Sem as curvas de referência:", e);
  }
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
    l(u.apurado != null ? `Apuração: ${nm.esq} ${pc(u.apurado, 1)}, ${nm.dir} ${pc(100 - u.apurado, 1)}.` : "Apuração: sem votos contados."),
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
  $("aviso-sintetico").hidden = !d.exemplo;
  desenharResposta();
  desenharGrafico();
  desenharComparacao();
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
      if (estado.dados) { desenharGrafico(); desenharComparacao(); }
    }
  }).observe($("grafico"));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && estado.proximo && Date.now() > estado.proximo - 1000) buscar();
  });
  setInterval(tique, 1000);
  carregarReferencias();
  buscar();
}

iniciar();
