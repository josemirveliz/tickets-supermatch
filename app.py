"""App de tickets para Super Match. Arma jugadas; la apuesta la hacés vos en Super Match."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import aviso
import engine
import historial as H
import storage
import supermatch as SMP

SUPERMATCH_URL = "https://www.supermatch.com.uy/"
COLORES = {"Goles": "#2563eb", "Corners": "#b45309", "Resultado": "#7c3aed", "Tarjetas": "#dc2626", "Hándicap": "#0891b2"}
def pista(l: dict) -> str:
    """Dónde está la jugada dentro del partido en Super Match."""
    grupo, _, opcion = l["mercado"].partition(" → ")
    txt = f"En el partido abrí la pestaña **{l.get('pestana', 'Goles')}**, buscá **{grupo}** y tocá **{opcion or grupo}**."
    if l.get("linea_unica"):
        txt += (" Super Match suele ofrecer **una sola línea** de este mercado por partido: si la que ves no es esta, "
                "salteala y buscá en la app la jugada con la línea que sí aparece.")
    return txt

st.set_page_config(page_title="Tickets Super Match", page_icon="⚽", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:1.6rem;max-width:1200px}
.tag{display:inline-block;font-size:.72rem;font-weight:700;padding:1px 8px;border-radius:99px;border:1px solid currentColor;margin-right:6px}
.meta{font-size:.8rem;color:#6b7280}
.warn{font-size:.8rem;color:#b45309}
.leg-h{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;font-weight:600}
.ok{color:#15803d;font-weight:700}.mid{color:#b45309;font-weight:700}.bad{color:#b91c1c;font-weight:700}.na{color:#9ca3af}
hr.sep{margin:.4rem 0;border:0;border-top:1px solid #e5e7eb}
@media (max-width: 640px){
  .block-container{padding:.8rem .7rem 3rem}
  h1{font-size:1.4rem !important;line-height:1.2}
  h2{font-size:1.2rem !important}
  h3{font-size:1.1rem !important}
  /* título del ticket + cuota/prob: compactos */
  .stSubheader, [data-testid="stSubheader"]{font-size:1.1rem !important}
  /* métricas de a dos por fila en el celular */
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){flex-wrap:wrap !important;gap:.4rem .8rem}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]{min-width:calc(50% - .8rem) !important;flex:1 1 calc(50% - .8rem) !important}
  [data-testid="stMetricValue"]{font-size:1.3rem}
  [data-testid="stMetricLabel"]{font-size:.75rem}
  /* pestañas más compactas para que entren más en pantalla */
  [data-baseweb="tab"]{padding-left:.4rem !important;padding-right:.4rem !important}
  [data-baseweb="tab"] p{font-size:.85rem !important}
  /* tablas: fuente más chica y scroll horizontal suave */
  [data-testid="stDataFrame"], [data-testid="stDataEditor"]{font-size:.8rem}
  [data-testid="stDataFrame"] *, [data-testid="stDataEditor"] *{-webkit-overflow-scrolling:touch}
  /* botones y campos a lo ancho, bien tocables */
  .stButton>button, .stDownloadButton>button{min-height:2.6rem}
  textarea{font-size:.85rem !important}
  /* el campo de cuota más grande para el dedo */
  [data-testid="stNumberInput"] input{font-size:1.05rem;min-height:2.6rem}
}
</style>""", unsafe_allow_html=True)

cfg = engine.load_config()

# ----------------------------------------------------------------------------- contraseña (si está configurada)
_clave = storage.secreto("APP_PASSWORD")
if _clave and not st.session_state.get("autorizado"):
    st.title("⚽ Tickets para Super Match")
    with st.form("login"):
        pw = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if hmac.compare_digest(pw.encode(), _clave.encode()):
                st.session_state.autorizado = True
                st.rerun()
            st.error("Contraseña incorrecta")
    st.stop()

ajustes = H.cargar_ajustes()
margen = 1 + float(cfg["margenSeguridad"])


def guardar_ajuste(k: str, wkey: str):
    ajustes[k] = st.session_state[wkey]
    H.guardar_ajustes(ajustes)


# ----------------------------------------------------------------------------- barra lateral
with st.sidebar:
    st.header("⚙️ Opciones")
    dia = st.radio("Partidos de", ["Hoy", "Mañana", "Ayer"], horizontal=True,
                   help="El plan gratis de API-Football solo deja ver ayer, hoy y mañana.")
    fecha = (engine.hoy(cfg) + {"Hoy": timedelta(0), "Mañana": timedelta(1), "Ayer": timedelta(-1)}[dia]).isoformat()
    demo = st.toggle("Modo demo (datos ficticios)", value=False)
    prob_min = st.slider("Probabilidad mínima por jugada", 0.60, 0.85, float(cfg["probMinima"]), 0.01,
                         format="%.2f", help="Para los tickets automáticos. Más alto = más seguros pero con cuota más baja.")
    forzar = st.button("🔄 Actualizar datos", width="stretch",
                       help="Vuelve a bajar los partidos y el historial.")
    st.divider()
    st.subheader("💰 Mi banca")
    banca = st.number_input("Plata total que destinás a apostar ($)", min_value=0.0, step=500.0,
                            value=float(ajustes.get("banca", 0.0)), key="w_banca", on_change=guardar_ajuste, args=("banca", "w_banca"),
                            help="Solo la plata para apuestas, no tus ahorros. Se usa para sugerirte cuánto apostar.")
    st.slider("Apuesta base por ticket (% de la banca)", 0.5, 5.0, float(ajustes.get("pct", cfg["banca"]["porcentajePorTicket"])), 0.5,
              key="w_pct", on_change=guardar_ajuste, args=("pct", "w_pct"))
    st.caption(f"Límite de pérdida semanal: {cfg['banca']['limiteSemanalPorcentaje']:.0f}% de la banca "
               f"(${banca * float(cfg['banca']['limiteSemanalPorcentaje']) / 100:,.0f}).")
    st.divider()
    if aviso.configurado():
        if st.button("📲 Enviar aviso de prueba a Telegram", width="stretch"):
            st.toast("Aviso enviado ✅" if aviso.enviar(aviso.armar_texto(cfg)) else "No se pudo enviar (revisá el token)")
    else:
        st.caption("📲 Aviso diario por Telegram: opcional. Configuralo en secrets.toml (ver aviso.py).")
    st.divider()
    st.caption(("☁️ Tus datos se guardan en la nube." if storage.en_la_nube() else "💾 Tus datos se guardan en esta compu.")
               + " La app arma las jugadas. Cargarlas, poner la plata y apostar lo hacés vos en Super Match.")


@st.cache_data(ttl=1800, show_spinner=False)
def analizar(fecha: str, demo: bool, prob_min: float, nonce: int, forzar: bool):
    return engine.correr(fecha, demo=demo, cfg=dict(cfg, probMinima=prob_min), forzar=forzar)


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def prueba(prob_min: float):
    return engine.prueba_modelo(dict(cfg, probMinima=prob_min))


if "nonce" not in st.session_state:
    st.session_state.nonce = 0
if forzar:
    st.session_state.nonce += 1

try:
    with st.spinner("Analizando partidos y estadísticas..."):
        res = analizar(fecha, demo, prob_min, st.session_state.nonce, forzar)
except engine.BotError as e:
    st.error(str(e))
    st.stop()
except Exception as e:  # red caída, etc.
    st.error(f"No se pudieron cargar los datos: {e}")
    st.stop()

if "resultados_buscados" not in st.session_state and not demo:
    try:
        st.session_state.resultados_buscados = H.buscar_resultados(cfg)
    except Exception:
        st.session_state.resultados_buscados = 0

if "aviso_toast" in st.session_state:
    st.toast(st.session_state.pop("aviso_toast"))

hist = H.cargar()
stats = H.estadisticas(hist)
limite = banca * float(cfg["banca"]["limiteSemanalPorcentaje"]) / 100
limite_alcanzado = banca > 0 and stats["perdida_semana"] >= limite

# ----------------------------------------------------------------------------- cuotas cargadas (compartidas)
if "odds" not in st.session_state:
    st.session_state.odds = {}
if "casa" not in st.session_state:
    st.session_state.casa = {}      # sel_id -> probabilidad según Super Match (de las cuotas pegadas)
if "leidos" not in st.session_state:
    st.session_state.leidos = {}    # match_id -> info de la última lectura
PESO_CASA = float(cfg.get("pesoCasa", 0.5))


def prob_final(l: dict) -> float:
    """Probabilidad que usa la app. La prueba con 14.000 partidos mostró que las casas predicen mejor que el modelo, así que:
    1) si hay cuotas de las casas grandes (ligas europeas), se usa esa probabilidad (la más precisa);
    2) si no, y pegaste las cuotas de Super Match, se mezcla 80% Super Match + 20% modelo;
    3) si no hay nada, queda el modelo solo."""
    if l.get("cuota_mercado") and l.get("prob_mercado") is not None:
        return l["prob_mercado"]
    pc = st.session_state.casa.get(l["sel_id"])
    return l["prob"] if pc is None else (1 - PESO_CASA) * l["prob"] + PESO_CASA * pc


def tipo_valor(l: dict) -> str:
    """'real' si el valor viene de que Super Match paga más que las casas grandes; 'modelo' si solo lo dice el modelo."""
    return "real" if l.get("cuota_mercado") and l.get("prob_mercado") is not None else "modelo"


# info de cada partido (goles/corners esperados) para explicar el "por qué" de las jugadas
INFO_PARTIDO = {r["match"].id: r for r in res.resumen if r["ok"]}


def por_que(l: dict) -> str:
    r = INFO_PARTIDO.get(l["match_id"])
    if not r:
        return ""
    partes = []
    if r.get("lh") is not None:
        partes.append(f"goles esperados {r['lh']:.1f}–{r['la']:.1f}")
    if r.get("xc"):
        partes.append(f"córners esperados {r['xc']:.1f}")
    if r.get("p1") or r.get("p2"):
        partes.append(f"1/X/2: {r['p1']*100:.0f}/{r['px']*100:.0f}/{r['p2']*100:.0f}%")
    if "con xG" in (r.get("nota") or ""):
        partes.append("usa goles esperados (xG)")
    if l.get("prob_mercado") is not None:
        partes.append(f"las casas grandes le dan {l['prob_mercado']*100:.0f}%")
    return " · ".join(partes)


def justa(l: dict) -> float:
    return 1 / prob_final(l)


def vs_mercado(l: dict, v: float) -> str:
    """Compara la cuota de Super Match con el promedio de las otras casas (solo ligas europeas)."""
    cm = l.get("cuota_mercado")
    if not v or not cm:
        return ""
    d = v / cm - 1
    if d >= 0.02:
        return f"<br><span class='ok'>💰 Super Match paga {d * 100:.0f}% más que el promedio de las casas ({cm:.2f})</span>"
    if d <= -0.02:
        return f"<br><span class='meta'>Super Match paga {abs(d) * 100:.0f}% menos que el promedio de las casas ({cm:.2f})</span>"
    return f"<br><span class='meta'>Igual que el promedio de las casas ({cm:.2f})</span>"


def odd_input(sel_id: str, wkey: str):
    """Casilla de cuota. La misma jugada comparte la cuota en todos los tickets y en la guía de carga."""
    odds = st.session_state.odds
    cur = odds.get(sel_id, 0.0)
    last_key = "_last_" + wkey
    if wkey not in st.session_state or st.session_state.get(last_key) != cur:
        st.session_state[wkey] = cur
    v = st.number_input("Cuota en Super Match", min_value=0.0, max_value=100.0, step=0.05, format="%.2f",
                        key=wkey, label_visibility="collapsed")
    if v != cur:
        odds[sel_id] = v
    st.session_state[last_key] = odds.get(sel_id, 0.0)
    return v


def estado(v: float, justa: float) -> str:
    if not v:
        return "<span class='na'>cargá la cuota</span>"
    ev = v / justa - 1
    if ev >= 0.20:
        return (f"<span class='mid'>⚠️ Sospechoso</span> <span class='meta'>valor {ev * 100:+.0f}%: Super Match opina muy distinto, "
                f"probablemente el modelo se equivoca. Mejor no jugarla.</span>")
    if v >= justa * margen:
        return f"<span class='ok'>✅ Conviene</span> <span class='meta'>valor {ev * 100:+.0f}%</span>"
    if v >= justa:
        return f"<span class='mid'>⚠️ Justo</span> <span class='meta'>valor {ev * 100:+.0f}%</span>"
    return f"<span class='bad'>❌ Cambiala</span> <span class='meta'>valor {ev * 100:+.0f}%</span>"


def tag(cat: str) -> str:
    return f"<span class='tag' style='color:{COLORES.get(cat, '#444')}'>{cat}</span>"


def info_mercado(l: dict) -> str:
    donde = f"<br><span class='meta'>📍 Super Match → pestaña <b>{l.get('pestana', 'Goles')}</b></span>"
    if l.get("linea_unica"):
        donde += "<span class='meta'> · solo si Super Match ofrece esta línea</span>"
    return donde + _info_mercado(l)


def _info_mercado(l: dict) -> str:
    txt = ""
    if l.get("aviso"):
        txt += f"<br><span class='warn'>⚠️ {l['aviso']}</span>"
    elif l.get("prob_mercado") is not None and l.get("prob_modelo") is not None:
        txt += f"<br><span class='meta'>modelo {l['prob_modelo'] * 100:.0f}% · otras casas {l['prob_mercado'] * 100:.0f}%</span>"
    elif l.get("prob_mercado") is not None:
        txt += f"<br><span class='meta'>según {l['prob_mercado'] * 100:.0f}% de las casas grandes (sin historial propio)</span>"
    pc = st.session_state.casa.get(l["sel_id"])
    if pc is not None:
        txt += f"<br><span class='meta'>la app {l['prob'] * 100:.0f}% · Super Match {pc * 100:.0f}% → <b>{prob_final(l) * 100:.0f}%</b></span>"
    return txt


def sugerido(legs) -> tuple[float, str]:
    if limite_alcanzado:
        return 0.0, "Llegaste a tu límite de pérdida semanal: esta semana no conviene apostar más."
    return H.monto_sugerido([dict(l, prob=prob_final(l)) for l in legs], st.session_state.odds, banca, cfg, ajustes)


def copy_button(text: str, label: str, abrir: bool):
    """Botón que copia el nombre del equipo (y opcionalmente abre Super Match en otra pestaña)."""
    abrir_js = f"window.open({json.dumps(SUPERMATCH_URL)}, 'supermatch');" if abrir else ""
    components.html(f"""
<div style="font-family:system-ui,Segoe UI,sans-serif">
<button id="b" style="background:#d7263d;color:#fff;border:0;border-radius:8px;padding:10px 16px;font-size:15px;font-weight:600;cursor:pointer">{label}</button>
<div id="m" style="margin-top:6px;font-size:14px;color:#15803d"></div></div>
<script>
const t = {json.dumps(text)};
document.getElementById('b').onclick = async () => {{
  let ok = false;
  try {{ await navigator.clipboard.writeText(t); ok = true; }} catch (e) {{
    const a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select();
    try {{ ok = document.execCommand('copy'); }} catch (e2) {{}}
    a.remove();
  }}
  {abrir_js}
  const m = document.getElementById('m');
  m.textContent = ok ? '✓ Copiado. Pegalo en Super Match con Ctrl+V' : 'No se pudo copiar: copialo de abajo';
  m.style.color = ok ? '#15803d' : '#b91c1c';
}};
</script>""", height=82)


def guardar_en_historial(nombre: str, legs: list[dict], key: str, default: float):
    """Formulario chico para anotar un ticket que ya apostaste."""
    m = st.number_input("¿Cuánto apostaste? ($)", min_value=0.0, step=50.0, value=float(default or 100.0), key=f"monto_{key}")
    faltan = sum(1 for l in legs if not st.session_state.odds.get(l["sel_id"]))
    if faltan:
        st.caption(f"Faltan {faltan} cuota(s) de Super Match: cargalas para que el historial calcule bien lo que cobrás.")
    if st.button("📒 Guardar en mi historial", key=f"save_{key}", type="primary", disabled=m <= 0):
        H.agregar_ticket(nombre, legs, st.session_state.odds, m)
        st.session_state.aviso_toast = f"Ticket guardado en tu historial (${m:,.0f}) ✅"
        st.session_state.pop("carga", None)
        st.rerun()
    return False


def ir_a(paso: int):
    st.session_state.carga["i"] = paso


@st.dialog("🚀 Cargar ticket en Super Match", width="large")
def dialogo_carga():
    c = st.session_state.carga
    legs, i, n = c["legs"], c["i"], len(c["legs"])
    if i < n:
        l = legs[i]
        st.progress(i / n, text=f"Jugada {i + 1} de {n} · {c['nombre']}")
        st.markdown(f"### {l['partido']}")
        st.caption(f"{l['liga']} · {l['hora']} hs")
        st.markdown(f"**Jugada a tocar:** {tag(l['categoria'])}**{l['mercado']}**", unsafe_allow_html=True)
        st.markdown(pista(l))
        st.markdown("**1.** Copiá el nombre y pegalo en el buscador de Super Match:")
        if i == 0:
            copy_button(l["buscar"], f"📋 Copiar «{l['buscar']}» y abrir Super Match", abrir=True)
        else:
            copy_button(l["buscar"], f"📋 Copiar «{l['buscar']}»", abrir=False)
            st.caption(f"Volvé a la pestaña de Super Match que ya tenés abierta. Si la cerraste: [abrir Super Match]({SUPERMATCH_URL})")
        st.code(l["buscar"], language=None)
        st.markdown(f"**2.** Entrá al partido, tocá la jugada y fijate la cuota. Tiene que pagar **≥ {justa(l) * margen:.2f}**.")
        c1, c2 = st.columns([1, 2], vertical_alignment="center")
        with c1:
            v = odd_input(l["sel_id"], f"dlg_{l['sel_id']}")
        c2.markdown(estado(v, justa(l)) + vs_mercado(l, v) + ("<br><span class='meta'>Si no conviene, salteala con Siguiente y no la agregues.</span>"
                                                            if v and v < justa(l) else ""), unsafe_allow_html=True)
        st.divider()
        b1, b2 = st.columns(2)
        b1.button("⬅ Anterior", on_click=ir_a, args=(i - 1,), disabled=i == 0, width="stretch")
        b2.button("Siguiente ➡" if i < n - 1 else "Terminar ✅", on_click=ir_a, args=(i + 1,), type="primary", width="stretch")
    else:
        st.success(f"¡Listo! Recorriste las {n} jugadas de {c['nombre']}.")
        vals = [st.session_state.odds.get(l["sel_id"], 0.0) for l in legs]
        for l, v in zip(legs, vals):
            st.markdown(f"- **{l['partido']}**: {l['mercado']} → " + (f"cuota {v:.2f} " + estado(v, justa(l)) if v else "<span class='na'>sin cuota</span>"),
                        unsafe_allow_html=True)
        sug, motivo = sugerido(legs)
        if all(vals):
            total = math.prod(vals)
            st.metric("Cuota total en Super Match", f"{total:.2f}", help="Tiene que coincidir con la que te muestra el cupón de Super Match.")
        if sug:
            st.caption(f"Monto sugerido: **${sug:,.0f}** · {motivo}")
        else:
            st.warning(motivo)
        st.info("**Último paso (lo hacés vos):** en el cupón de Super Match revisá que estén todas las jugadas, poné el monto y apretá **Apostar**.")
        st.markdown("**¿Ya lo apostaste?** Anotalo para llevar la cuenta de cuánto ganás o perdés:")
        guardar_en_historial(c["nombre"], legs, "dlg", sug)
        b1, b2 = st.columns(2)
        b1.button("⬅ Volver a la última", on_click=ir_a, args=(n - 1,), width="stretch")
        if b2.button("Cerrar sin guardar", width="stretch"):
            del st.session_state["carga"]
            st.rerun()


def checklist_texto(nombre: str, legs: list[dict]) -> str:
    """El ticket entero como lista de pasos, para copiar y tener a mano mientras lo cargás en Super Match."""
    lineas = [f"TICKET: {nombre}", ""]
    for i, l in enumerate(legs, 1):
        grupo, _, opcion = l["mercado"].partition(" → ")
        lineas.append(f"{i}) {l['partido']}  ({l['hora']} hs)")
        lineas.append(f"    Buscá en Super Match: {l['buscar']}")
        lineas.append(f"    Pestaña {l.get('pestana', 'Goles')} → {grupo}" + (f" → {opcion}" if opcion else ""))
        lineas.append("")
    lineas.append("Cargá las jugadas, poné el monto y tocá Apostar. (Apostar lo hacés vos.)")
    return "\n".join(lineas)


def botones_ticket(nombre: str, legs: list[dict], key: str):
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("🚀 Cargar paso a paso", key=f"cargar_{key}", type="primary", width="stretch"):
            st.session_state.carga = {"nombre": nombre, "legs": legs, "i": 0}
            dialogo_carga()
    with c2:
        with st.popover("📒 Ya lo aposté: anotarlo", width="stretch"):
            guardar_en_historial(nombre, legs, key, sugerido(legs)[0])
    with st.expander("🔴 Abrir Super Match con el ticket copiado"):
        st.caption("Tocá el botón: se abre Super Match y se copia el ticket entero como lista. Pegalo donde quieras "
                   "(o tenelo a la vista) y cargá cada jugada. La app no puede tocar Super Match, así que cargar y apostar lo hacés vos.")
        copy_button(checklist_texto(nombre, legs), "🔴 Abrir Super Match y copiar el ticket", abrir=True)
        st.code(checklist_texto(nombre, legs), language=None)


def resumen_ticket(legs):
    vals = [st.session_state.odds.get(l["sel_id"], 0.0) for l in legs]
    prob = math.prod(prob_final(l) for l in legs)
    sug, motivo = sugerido(legs)
    if all(vals):
        total = math.prod(vals)
        ev = prob * total - 1
        malas = sum(1 for v, l in zip(vals, legs) if v < justa(l))
        c1, c2, c3 = st.columns(3)
        c1.metric("Cuota total en Super Match", f"{total:.2f}")
        c2.metric("Monto sugerido", f"${sug:,.0f}", help=motivo)
        c3.metric("Valor según el modelo", f"{ev * 100:+.0f}%",
                  help="Ganancia o pérdida promedio esperada por cada $100, si las probabilidades del modelo son correctas.")
        if sug:
            st.caption(f"Si sale, con ${sug:,.0f} cobrás ${sug * total:,.0f}.")
        if malas:
            st.warning(f"{malas} jugada(s) pagan menos que la cuota justa. Conviene cambiarlas o sacarlas.")
        elif ev > 0:
            st.success("Todas las jugadas pagan igual o más que la cuota justa.")
        if not sug:
            st.caption(motivo)
    else:
        st.caption(f"Cargá la cuota de Super Match en las {len(legs)} jugadas para ver el total y si conviene. "
                   + (f"Monto sugerido por ahora: ${sug:,.0f} ({motivo})." if sug else motivo))


def fila_jugadas(legs: list[dict], prefix: str):
    """Una jugada por fila: info a la izquierda, cuota y estado a la derecha (en el celular quedan uno abajo del otro)."""
    for li, l in enumerate(legs):
        if li:
            st.markdown("<hr class='sep'>", unsafe_allow_html=True)
        izq, der = st.columns([3, 1.3], vertical_alignment="center")
        izq.markdown(
            f"**{l['partido']}**<br><span class='meta'>{l['liga']} · {l['hora']} hs</span><br>"
            f"{tag(l['categoria'])}{l['mercado']}{info_mercado(l)}<br>"
            f"<span class='meta'>Prob. <b>{prob_final(l) * 100:.0f}%</b> · Jugala si paga <b>≥ {justa(l) * margen:.2f}</b></span>",
            unsafe_allow_html=True)
        with der:
            st.markdown("<div class='leg-h'>Cuota en Super Match</div>", unsafe_allow_html=True)
            v = odd_input(l["sel_id"], f"w_{prefix}_{li}_{l['sel_id']}")
            st.markdown(estado(v, justa(l)) + vs_mercado(l, v), unsafe_allow_html=True)
        pq = por_que(l)
        if pq:
            izq.caption("¿Por qué? " + pq)


# ----------------------------------------------------------------------------- encabezado
h1, h2 = st.columns([3, 1])
with h1:
    st.title("⚽ Tickets para Super Match")
    st.caption(f"Partidos del {fecha}" + (" · **MODO DEMO, datos ficticios**" if demo else ""))
with h2:
    st.write("")
    st.link_button("Abrir Super Match ↗", SUPERMATCH_URL, width="stretch", type="primary")

if limite_alcanzado:
    st.error(f"🛑 Esta semana ya perdiste ${stats['perdida_semana']:,.0f}, que es tu límite (${limite:,.0f}). "
             "Te recomiendo frenar hasta la semana que viene: perseguir pérdidas es la forma más rápida de perder más.")
for a in res.avisos:
    st.warning(a)

ok = [r for r in res.resumen if r["ok"]]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Partidos de tus ligas", len(res.resumen))
m2.metric("Con estadísticas", len(ok))
m3.metric("Tickets armados", len(res.tickets))
m4.metric("Tu resultado acumulado", f"${stats['ganancia']:+,.0f}" if stats["cerrados"] else "—",
          help="Ganancia o pérdida de los tickets anotados en el historial que ya se resolvieron.")

# ----------------------------------------------------------------------------- veredicto del día
def veredicto():
    con_odds = [c for c in res.candidatos if st.session_state.odds.get(c["sel_id"])]
    reales = [c for c in con_odds if tipo_valor(c) == "real"
              and (st.session_state.odds[c["sel_id"]] >= justa(c) * margen)
              and (st.session_state.odds[c["sel_id"]] / justa(c) - 1) < 0.20]
    if not con_odds:
        st.info("📋 **Veredicto del día:** todavía no pegaste cuotas. Andá a **📋 Pegar cuotas**, cargá uno o más partidos "
                "y la app te dice si hoy hay algo que valga la pena.")
    elif reales:
        st.success(f"✅ **Veredicto del día:** hay **{len(reales)} jugada(s) con valor real** (Super Match paga más que otras casas). "
                   "Están en 📋 Pegar cuotas → ⭐ Mejores jugadas. Jugá poco y solo esas.")
    else:
        st.warning("🤚 **Veredicto del día:** con las cuotas que pegaste, **no hay valor real hoy**. "
                   "Lo más rentable es no apostar. Mañana será otro día.")


veredicto()
if res.odds_api.get("error"):
    st.caption("⚠️ The Odds API: " + res.odds_api["error"])
elif res.odds_api.get("ligas"):
    rem = res.odds_api.get("restantes")
    st.caption(f"💰 Comparando con muchas casas vía The Odds API ({res.odds_api['ligas']} ligas"
               + (f", quedan {rem} consultas este mes" if rem else "") + ").")

tabs = st.tabs(["🎟️ Tickets", "📋 Pegar cuotas", "🧩 Armá tu ticket", "📊 Partidos", "📒 Mi historial", "🧪 Prueba del modelo",
                "❓ Cómo usarla"])
T_TICKETS, T_PEGAR, T_ARMA, T_PARTIDOS, T_HIST, T_PRUEBA, T_AYUDA = tabs

# ----------------------------------------------------------------------------- tickets
with T_TICKETS:
    if not res.tickets:
        st.info("Hoy no hay jugadas que pasen los filtros. Mejor no apostar, o bajá la probabilidad mínima en la barra de la izquierda.")
    for ti, t in enumerate(res.tickets):
        with st.container(border=True):
            a, b, c = st.columns([3, 1, 1])
            a.subheader(t["nombre"])
            a.caption(t["desc"])
            b.metric("Cuota justa", f"{t['cuota']:.2f}")
            c.metric("Probabilidad", f"{t['prob'] * 100:.0f}%")
            fila_jugadas(t["legs"], f"t{ti}")
            resumen_ticket(t["legs"])
            botones_ticket(t["nombre"], t["legs"], f"t{ti}")

# ----------------------------------------------------------------------------- pegar cuotas de Super Match
with T_PEGAR:
    st.markdown("**Leé todas las cuotas de un partido de una vez.** En Super Match entrá al partido, abrí la pestaña **Goles**, "
                "tocá en la página, **Ctrl+A** (seleccionar todo) y **Ctrl+C** (copiar). Pegalo acá abajo. "
                "Podés repetir con las pestañas **Otro** y **Mas Jugado** y pegar todo junto.")
    st.caption("En el celular: mantené apretado el texto de la página → Seleccionar todo → Copiar.")
    partidos_ok = [r["match"] for r in res.resumen if r["ok"]]
    if not partidos_ok:
        st.info("No hay partidos con estadísticas en esta fecha.")
    else:
        def _nombre(m):
            hecho = " ✓" if m.id in st.session_state.leidos else ""
            return f"{m.hora} · {engine.sm_name(m.home)} vs {engine.sm_name(m.away)}{hecho}"

        idx = st.selectbox("Partido", range(len(partidos_ok)), format_func=lambda i: _nombre(partidos_ok[i]))
        mp = partidos_ok[idx]
        HNp, ANp = engine.sm_name(mp.home), engine.sm_name(mp.away)
        txt = st.text_area("Texto copiado de Super Match", height=180, key=f"txt_{mp.id}",
                           placeholder="Pegá acá (Ctrl+V) el texto de la página del partido...")
        if st.button("📥 Leer cuotas", type="primary", disabled=not txt.strip()):
            leidas = SMP.leer_partido(txt, HNp, ANp)
            cands_m = {c["clave"]: c for c in res.candidatos if c["match_id"] == mp.id}
            nuevas = {}
            for clave, (cuota, pc) in leidas.items():
                c = cands_m.get(clave)
                if c:
                    st.session_state.odds[c["sel_id"]] = cuota
                    st.session_state.casa[c["sel_id"]] = pc
                    nuevas[c["sel_id"]] = cuota
            st.session_state.leidos[mp.id] = dict(n=len(nuevas), total=len(leidas), hora=engine.ahora(cfg).strftime("%H:%M"))
            n_cierre = H.actualizar_cierre(nuevas) if not demo else 0
            if not leidas:
                st.session_state.aviso_toast = "No encontré cuotas en ese texto. ¿Copiaste la página del partido?"
            else:
                st.session_state.aviso_toast = (f"Leí {len(nuevas)} cuotas de {HNp} vs {ANp}"
                                                + (f" · actualicé {n_cierre} cuota(s) de cierre en tu historial" if n_cierre else ""))
            st.rerun()
        info = st.session_state.leidos.get(mp.id)
        if info:
            st.caption(f"Última lectura: {info['hora']} hs · {info['n']} jugadas reconocidas de {info['total']} cuotas leídas.")
        # movimiento de las cuotas del mercado (The Odds API) para este partido
        snaps = engine.movimiento(mp.id)
        if len(snaps) >= 2:
            def serie(clave):
                return [s["cuotas"].get(clave) for s in snaps if clave in s.get("cuotas", {})]
            filas_mov = []
            for clave, nombre in (("gana_local", f"Gana {HNp}"), ("gana_visita", f"Gana {ANp}"),
                                  ("goles_mas_2.5", "Más de 2.5"), ("goles_menos_2.5", "Menos de 2.5")):
                s = serie(clave)
                if len(s) >= 2 and s[0] and s[-1]:
                    flecha = "↑ sube" if s[-1] > s[0] else "↓ baja" if s[-1] < s[0] else "="
                    filas_mov.append({"Jugada": nombre, "Antes": s[0], "Ahora": s[-1], "Movimiento": flecha})
            if filas_mov:
                with st.expander("📉 Cómo se movieron las cuotas del mercado"):
                    st.dataframe(pd.DataFrame(filas_mov), hide_index=True, width="stretch",
                                 column_config={"Antes": st.column_config.NumberColumn(format="%.2f"),
                                                "Ahora": st.column_config.NumberColumn(format="%.2f")})
                    st.caption("Si una cuota baja, es que las casas le dan más probabilidad (ahí va 'la plata inteligente'). "
                               "Tomar una jugada antes de que su cuota baje es señal de que elegiste bien.")

        # tabla del partido elegido
        filas_p = []
        for c in res.candidatos:
            v = st.session_state.odds.get(c["sel_id"])
            if c["match_id"] != mp.id or not v:
                continue
            pf, pc = prob_final(c), st.session_state.casa.get(c["sel_id"])
            ev = v * pf - 1
            est = ("⚠️ Sospechoso" if v / justa(c) - 1 >= 0.20 else "✅ Conviene" if v >= justa(c) * margen
                   else "≈ Justo" if v >= justa(c) else "❌ No")
            cm = c.get("cuota_mercado")
            filas_p.append({"Jugada": c["mercado"], "Cuota SM": v, "La app": round(c["prob"] * 100),
                            "Super Match": None if pc is None else round(pc * 100), "Final": round(pf * 100),
                            "Valor": round(ev * 100), "¿Conviene?": est,
                            "Vs. otras casas": "" if not cm else f"{(v / cm - 1) * 100:+.0f}% ({cm:.2f})"})
        if filas_p:
            filas_p.sort(key=lambda x: -x["Valor"])
            st.dataframe(pd.DataFrame(filas_p), hide_index=True, width="stretch",
                         column_config={"Cuota SM": st.column_config.NumberColumn(format="%.2f"),
                                        "La app": st.column_config.NumberColumn(format="%d%%"),
                                        "Super Match": st.column_config.NumberColumn(format="%d%%"),
                                        "Final": st.column_config.NumberColumn(format="%d%%", help="Mezcla de la app y Super Match"),
                                        "Valor": st.column_config.NumberColumn(format="%+d%%")})
            st.caption("**La app** = lo que calcula el modelo. **Super Match** = lo que opina la casa (su cuota sin el margen). "
                       f"**Final** = {PESO_CASA * 100:.0f}% Super Match + {(1 - PESO_CASA) * 100:.0f}% modelo, o la opinión de las casas "
                       "grandes cuando la hay (es la más precisa). El valor se calcula con la final. **Vs. otras casas**: si Super Match paga "
                       "más que el promedio de las casas grandes, esa diferencia es valor real (solo ligas europeas, ganador y más/menos 2.5).")

    # las mejores del día, entre todos los partidos con cuotas leídas
    st.divider()
    st.subheader("⭐ Mejores jugadas del día")
    mejores = []
    for c in res.candidatos:
        v = st.session_state.odds.get(c["sel_id"])
        if not v or c["sel_id"] not in st.session_state.casa:
            continue
        r_ = v / justa(c) - 1
        if v >= justa(c) * margen and r_ < 0.20:
            mejores.append((v * prob_final(c) - 1, v, c))
    if not mejores:
        st.caption("Pegá las cuotas de uno o más partidos y acá aparecen las jugadas que convienen, ordenadas por valor.")
    else:
        mejores.sort(key=lambda x: (tipo_valor(x[2]) != "real", -x[0]))
        st.dataframe(pd.DataFrame([{"Tipo de valor": "💰 Real" if tipo_valor(c) == "real" else "🔮 Modelo",
                                    "Hora": c["hora"], "Partido": c["partido"], "Jugada": c["mercado"], "Cuota SM": v,
                                    "Prob.": round(prob_final(c) * 100), "Valor": round(ev * 100)} for ev, v, c in mejores]),
                     hide_index=True, width="stretch",
                     column_config={"Cuota SM": st.column_config.NumberColumn(format="%.2f"),
                                    "Prob.": st.column_config.NumberColumn(format="%d%%"),
                                    "Valor": st.column_config.NumberColumn(format="%+d%%")})
        st.caption("**💰 Real**: Super Match paga más que el promedio de las casas grandes. Es el único valor que se sostiene a la larga. "
                   "**🔮 Modelo**: solo lo dice el modelo. En la prueba con partidos pasados, este tipo de apuesta **perdió plata**: "
                   "jugalo poco o nada.")
        # mejor jugada de cada partido, hasta 3, para armar un ticket corto
        top, vistos = [], set()
        for ev, v, c in mejores:
            if c["match_id"] not in vistos:
                top.append(c)
                vistos.add(c["match_id"])
            if len(top) == 3:
                break
        if len(top) >= 2:
            cuota_top = math.prod(st.session_state.odds[c["sel_id"]] for c in top)
            prob_top = math.prod(prob_final(c) for c in top)
            st.caption(f"Ticket con la mejor de cada partido ({len(top)} jugadas): cuota **{cuota_top:.2f}**, "
                       f"probabilidad **{prob_top * 100:.0f}%**.")
            if st.button("🧩 Armar ese ticket", type="primary"):
                st.session_state.elegidas = {c["sel_id"] for c in top}
                st.session_state.aviso_toast = "Ticket armado: lo tenés en la pestaña 🧩 Armá tu ticket."
                st.rerun()

# ----------------------------------------------------------------------------- armá tu ticket
with T_ARMA:
    st.caption("Todas las jugadas analizadas. Escribí la cuota de Super Match en la tabla y ordená por **valor** "
               "para encontrar las que pagan más de lo que valen. Marcá las que quieras y se arma tu ticket abajo.")
    f1, f2, f3 = st.columns([2, 1.2, 1.2])
    _tipos = ["Goles", "Corners", "Resultado", "Tarjetas", "Hándicap"]
    cats = f1.multiselect("Tipo", _tipos, default=_tipos)
    pmin2 = f2.slider("Prob. mínima", 0.40, 0.90, 0.55, 0.05, format="%.2f", key="pmin_libre")
    orden = f3.selectbox("Ordenar por", ["Partido", "Más probables", "Más valor (con cuota cargada)"])
    cand = [c for c in res.candidatos if prob_final(c) >= pmin2 and c["categoria"] in cats]
    odds = st.session_state.odds
    if "elegidas" not in st.session_state:
        st.session_state.elegidas = set()

    def valor(c):
        v = odds.get(c["sel_id"]) or 0
        return v * prob_final(c) - 1 if v else None

    if orden == "Más probables":
        cand.sort(key=lambda c: -prob_final(c))
    elif orden.startswith("Más valor"):
        cand.sort(key=lambda c: (valor(c) is None, -(valor(c) or 0)))
    else:
        cand.sort(key=lambda c: (c["hora"], c["partido"], -c["prob"]))
    if not cand:
        st.info("No hay jugadas con esos filtros.")
    else:
        df = pd.DataFrame([{
            "Elegir": c["sel_id"] in st.session_state.elegidas, "Hora": c["hora"], "Partido": c["partido"], "Tipo": c["categoria"],
            "Jugada": c["mercado"] + (" ⚠️" if c["aviso"] else ""), "Prob.": round(prob_final(c) * 100),
            "Jugala si paga ≥": round(justa(c) * margen, 2), "Cuota Super Match": float(odds.get(c["sel_id"]) or "nan"),
            "Valor": float("nan") if valor(c) is None else float(round(valor(c) * 100)), "id": c["sel_id"]} for c in cand])
        firma = hashlib.md5(json.dumps([df["id"].tolist(), df["Elegir"].tolist(), df["Cuota Super Match"].tolist()],
                                       default=str).encode()).hexdigest()[:10]
        ed = st.data_editor(
            df, hide_index=True, width="stretch", key=f"ed_{firma}",
            column_order=["Elegir", "Hora", "Partido", "Jugada", "Prob.", "Jugala si paga ≥", "Cuota Super Match", "Valor", "Tipo"],
            disabled=["Hora", "Partido", "Tipo", "Jugada", "Prob.", "Jugala si paga ≥", "Valor"],
            column_config={"id": None, "Prob.": st.column_config.NumberColumn(format="%d%%"),
                           "Jugala si paga ≥": st.column_config.NumberColumn(format="%.2f"),
                           "Cuota Super Match": st.column_config.NumberColumn(format="%.2f", min_value=1.0, max_value=100.0,
                                                                              help="Escribí la cuota que ves en Super Match"),
                           "Valor": st.column_config.NumberColumn(format="%+d%%", help="Ganancia esperada por cada $100 según el modelo")})
        cambio = False
        for _, r in ed.iterrows():
            v = r["Cuota Super Match"]
            v = 0.0 if pd.isna(v) else float(v)
            if v != (odds.get(r["id"]) or 0.0):
                odds[r["id"]] = v
                cambio = True
        nuevas = set(ed.loc[ed["Elegir"], "id"].tolist()) | (st.session_state.elegidas - set(df["id"]))
        if nuevas != st.session_state.elegidas:
            st.session_state.elegidas = nuevas
            cambio = True
        if cambio:
            st.rerun()
        legs = [c for c in res.candidatos if c["sel_id"] in st.session_state.elegidas]
        if legs:
            partidos = [l["match_id"] for l in legs]
            if len(set(partidos)) < len(partidos):
                st.warning("Elegiste dos jugadas del mismo partido. Super Match puede no dejarte combinarlas, y además dependen entre sí.")
            if len(legs) > 3:
                st.warning("Más de 3 jugadas: cada una suma el margen de la casa. A la larga las combinadas cortas rinden mejor.")
            with st.container(border=True):
                hh1, hh2 = st.columns([4, 1])
                hh1.subheader("Mi ticket")
                if hh2.button("Vaciar", width="stretch"):
                    st.session_state.elegidas = set()
                    st.rerun()
                fila_jugadas(legs, "mi")
                st.caption(f"Cuota justa del ticket: {math.prod(justa(l) for l in legs):.2f} · "
                           f"probabilidad {math.prod(prob_final(l) for l in legs) * 100:.0f}%")
                resumen_ticket(legs)
                botones_ticket("Mi ticket", legs, "mi")

# ----------------------------------------------------------------------------- partidos
with T_PARTIDOS:
    filas = []
    for r in res.resumen:
        m = r["match"]
        if r["ok"]:
            filas.append({"Hora": m.hora, "Partido": f"{engine.sm_name(m.home)} vs {engine.sm_name(m.away)}", "Liga": m.liga,
                          "Goles esperados": "–" if r.get("lh") is None else f"{r['lh']:.2f} - {r['la']:.2f}",
                          "1 / X / 2": f"{r['p1']*100:.0f}% / {r['px']*100:.0f}% / {r['p2']*100:.0f}%",
                          "Corners esperados": "–" if r.get("xc") is None else f"{r['xc']:.1f}",
                          "Datos de": "mercado" if r.get("fuente") == "mercado" else f"{m.home_fd or 'propio'} / {m.away_fd or 'propio'}",
                          "Nota": r["nota"]})
        else:
            filas.append({"Hora": m.hora, "Partido": f"{m.home} vs {m.away}", "Liga": m.liga, "Goles esperados": "–",
                          "1 / X / 2": "–", "Corners esperados": "–", "Datos de": "–", "Nota": r["nota"]})
    if filas:
        st.dataframe(filas, hide_index=True, width="stretch")
    else:
        st.info("No hay partidos de tus ligas en esta fecha.")
    if res.sin_datos:
        st.caption("Sin historial todavía: " + ", ".join(res.sin_datos) + ". La app va guardando los resultados de todos los partidos "
                   "cada día que la abrís; cuando un equipo junte 5 partidos (por ejemplo los de la liga uruguaya), ya entra en el análisis.")
    n_store = len(engine.load_store())
    st.caption(f"Historial propio: {n_store} partidos guardados.")

# ----------------------------------------------------------------------------- historial
with T_HIST:
    c1, c2 = st.columns([3, 1])
    c1.caption("Los tickets que anotaste con **📒 Ya lo aposté**. Los resultados se buscan solos; si alguno no aparece "
               "(por ejemplo corners de ligas sin datos), lo marcás a mano.")
    if c2.button("🔄 Buscar resultados", width="stretch"):
        n = H.buscar_resultados(cfg)
        st.toast(f"{n} jugada(s) resueltas")
        st.rerun()
    if st.session_state.get("resultados_buscados"):
        st.caption(f"Al abrir la app se resolvieron {st.session_state.resultados_buscados} jugada(s).")
    if not hist:
        st.info("Todavía no anotaste ningún ticket. Cuando apuestes uno, tocá **📒 Ya lo aposté: anotarlo** en ese ticket.")
    else:
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Apostado (cerrados)", f"${stats['apostado']:,.0f}")
        k2.metric("Cobrado", f"${stats['cobrado']:,.0f}")
        k3.metric("Ganancia / pérdida", f"${stats['ganancia']:+,.0f}")
        k4.metric("Rendimiento", f"{stats['roi'] * 100:+.1f}%", help="Ganancia dividida lo apostado.")
        k5.metric("Tickets ganados", f"{stats['ganados']} de {stats['cerrados']}", help=f"{stats['pendientes']} pendientes")
        # gráfico de la banca en el tiempo
        cerrados = sorted([t for t in hist if H.estado(t) != "pendiente"], key=lambda t: t["creado"])
        if len(cerrados) >= 2:
            acum, serie = 0.0, []
            for t in cerrados:
                acum += (H.cobro(t) or 0) - t["monto"]
                serie.append({"Fecha": t["creado"][:10], "Ganancia acumulada": round(acum)})
            st.markdown("**📈 Tu banca en el tiempo**")
            st.line_chart(pd.DataFrame(serie).set_index("Fecha"), height=200)
            st.caption("Ganancia acumulada de tus tickets ya resueltos. Si la línea baja con el tiempo, el plan no funciona: pará y revisá.")
        with st.container(border=True):
            st.markdown("**📈 ¿Le ganás a la cuota de cierre? (CLV)**")
            if stats["clv"] is None:
                st.caption("Todavía no hay datos. Cómo se mide: después de apostar, **volvé a pegar las cuotas del partido un rato antes "
                           "de que empiece** (pestaña 📋 Pegar cuotas). La app compara la cuota que tomaste con la del cierre.")
            else:
                q1, q2 = st.columns(2)
                q1.metric("CLV promedio", f"{stats['clv'] * 100:+.1f}%",
                          help="Cuánto mejor fue tu cuota que la del cierre, en promedio. Positivo = tomaste mejores cuotas que el mercado final.")
                q2.metric("Jugadas con mejor cuota que el cierre", f"{stats['clv_pos']} de {stats['clv_n']}")
                st.caption("Si el CLV se mantiene **positivo** después de 30 o más jugadas, la estrategia está funcionando aunque haya rachas "
                           "de pérdidas. Si es **negativo**, Super Match te está ganando aunque por ahora vengas ganando.")
        if banca:
            st.progress(min(1.0, stats["perdida_semana"] / limite) if limite else 0.0,
                        text=f"Pérdida de los últimos 7 días: ${stats['perdida_semana']:,.0f} de tu límite de ${limite:,.0f}")
        if stats["por_tipo"]:
            st.markdown("**Por tipo de ticket**")
            st.dataframe([{"Ticket": k, "Jugados": v["tickets"], "Ganados": v["ganados"], "Apostado": f"${v['apostado']:,.0f}",
                           "Resultado": f"${v['cobrado'] - v['apostado']:+,.0f}",
                           "Rendimiento": f"{(v['cobrado'] - v['apostado']) / v['apostado'] * 100:+.0f}%" if v["apostado"] else "–"}
                          for k, v in stats["por_tipo"].items()], hide_index=True, width="stretch")
        if stats["tramos"]:
            st.markdown("**¿Acierta la app con las probabilidades?** (tus jugadas ya resueltas)")
            st.dataframe([{"La app decía": x["tramo"], "Jugadas": x["jugadas"], "Prob. promedio": f"{x['prob_media'] * 100:.0f}%",
                           "Salieron": f"{x['salieron'] * 100:.0f}%"} for x in stats["tramos"]], hide_index=True, width="stretch")
            st.caption("Si 'Salieron' queda bastante por debajo de 'Prob. promedio', la app es demasiado optimista: subí la probabilidad mínima. "
                       "Con pocas jugadas (menos de 30 por fila) todavía es suerte.")
        st.markdown("**Tickets**")
        iconos = {"ganado": "✅", "perdido": "❌", "pendiente": "⏳"}
        for t in hist:
            e = H.estado(t)
            ct = H.cuota_total(t)
            cob = H.cobro(t)
            titulo = (f"{iconos[e]} {t['creado'][:10]} · {t['nombre']} · ${t['monto']:,.0f}"
                      + (f" a {ct:.2f}" if ct else "") + (f" → cobrado ${cob:,.0f}" if e == "ganado" and cob else ""))
            with st.expander(titulo):
                for l in t["legs"]:
                    a, b, c = st.columns([4, 1.4, 1.4], vertical_alignment="center")
                    a.markdown(f"**{l['partido']}** · {l['dia']} {l['hora']}<br>{tag(l['categoria'])}{l['mercado']}"
                               f"<br><span class='meta'>prob. {l['prob'] * 100:.0f}% · cuota {l['cuota'] or '–'}"
                               f"{' · cierre ' + format(l['cuota_cierre'], '.2f') if l.get('cuota_cierre') else ''}"
                               f"{' · ' + l['marcador'] if l.get('marcador') else ''}</span>", unsafe_allow_html=True)
                    b.markdown({"ganada": "<span class='ok'>✅ Salió</span>", "perdida": "<span class='bad'>❌ No salió</span>",
                                "anulada": "<span class='na'>Anulada</span>", "pendiente": "<span class='na'>⏳ Pendiente</span>"}[l["resultado"]],
                               unsafe_allow_html=True)
                    nuevo = c.selectbox("Marcar", H.ESTADOS, index=H.ESTADOS.index(l["resultado"]), key=f"mk_{t['id']}_{l['sel_id']}",
                                        label_visibility="collapsed")
                    if nuevo != l["resultado"]:
                        H.marcar(t["id"], l["sel_id"], nuevo)
                        st.rerun()
                if st.button("🗑️ Borrar este ticket", key=f"del_{t['id']}"):
                    H.borrar(t["id"])
                    st.rerun()

# ----------------------------------------------------------------------------- prueba del modelo
with T_PRUEBA:
    st.markdown("Simula cómo le habría ido al modelo con los partidos ya jugados (las ligas de football-data): "
                "para cada partido calcula las probabilidades **solo con los partidos anteriores** y las compara con lo que pasó "
                "y con las **cuotas de cierre** del mercado (promedio de las casas grandes).")
    if st.button("▶️ Correr la prueba", type="primary"):
        st.session_state.correr_prueba = True
    if st.session_state.get("correr_prueba"):
        with st.spinner("Recorriendo miles de partidos..."):
            bt = prueba(prob_min)
        st.caption(f"{bt['partidos']} partidos desde el {bt['desde']}.")
        a, b = st.columns(2)
        with a.container(border=True):
            v = bt["valor"]
            st.markdown("**Estrategia 1: apostar donde el modelo ve valor contra el mercado**")
            st.caption(f"Apuestas simples (ganador o más/menos 2.5) cuando el modelo da {bt['borde'] * 100:.0f}% o más de valor.")
            x1, x2, x3 = st.columns(3)
            x1.metric("Apuestas", v["n"])
            x2.metric("Acertadas", f"{v['aciertos'] * 100:.0f}%")
            x3.metric("Rendimiento", f"{v['roi'] * 100:+.1f}%")
        with b.container(border=True):
            v = bt["altas"]
            st.markdown("**Estrategia 2: jugadas seguras como las de la app**")
            st.caption(f"Ganador o más/menos 2.5 con probabilidad ≥ {prob_min * 100:.0f}%, a la cuota de cierre.")
            x1, x2, x3 = st.columns(3)
            x1.metric("Apuestas", v["n"])
            x2.metric("Acertadas", f"{v['aciertos'] * 100:.0f}%")
            x3.metric("Rendimiento", f"{v['roi'] * 100:+.1f}%")
        if bt["valor"]["roi"] < 0:
            st.warning("**Qué significa:** cuando el modelo contradice al mercado, casi siempre el que se equivoca es el modelo. "
                       "Por eso la app mezcla su cálculo con las cuotas del mercado cuando las tiene, y te avisa (⚠️) si hay mucha diferencia. "
                       "No apuestes a una jugada solo porque la app la ve 'con valor' si el mercado opina muy distinto.")
        if bt.get("pesos"):
            st.markdown("**¿A quién creerle: al modelo o a la casa?**")
            st.dataframe([{"Peso de la casa": f"{x['peso_casa'] * 100:.0f}%", "Error de predicción": f"{x['error']:.4f}",
                           "Apuestas 'con valor'": x["apuestas"],
                           "Rendimiento": "–" if x["roi"] is None else f"{x['roi'] * 100:+.1f}%"} for x in bt["pesos"]],
                         hide_index=True, width="stretch")
            st.caption(f"{bt['n_obs']} casos. Menor error = mejor predicción. Si el error baja a medida que sube el peso de la casa, "
                       "la casa predice mejor que el modelo; por eso la app usa 80% Super Match cuando pegás sus cuotas, "
                       "y las cuotas de las casas grandes cuando las tiene.")
        st.markdown("**¿Las probabilidades del modelo se cumplen?** (goles, ambos anotan, doble oportunidad, corners)")
        st.dataframe([{"El modelo decía": x["tramo"], "Jugadas": x["n"], "Prob. promedio": f"{x['prob_media'] * 100:.1f}%",
                       "Salieron": f"{x['salio'] * 100:.1f}%"} for x in bt["tramos"]], hide_index=True, width="stretch")
        st.caption("Si 'Salieron' está cerca de 'Prob. promedio', el modelo está bien calibrado.")
        with st.expander("Detalle por jugada y por liga"):
            st.dataframe([{"Jugada": x["clave"], "Casos": x["n"], "Prob. promedio": f"{x['prob_media'] * 100:.1f}%",
                           "Salió": f"{x['salio'] * 100:.1f}%", "Error (Brier)": f"{x['brier']:.3f}"} for x in bt["calibracion"]],
                         hide_index=True, width="stretch")
            st.dataframe([{"Liga": k, "Apuestas con valor": v["n"], "Acertadas": f"{v['aciertos'] * 100:.0f}%",
                           "Rendimiento": f"{v['roi'] * 100:+.1f}%"} for k, v in bt["por_liga"].items()], hide_index=True, width="stretch")
        st.caption("Ojo: las cuotas de cierre de las casas grandes suelen ser mejores que las de Super Match, "
                   "así que en Super Match el resultado sería algo peor.")

# ----------------------------------------------------------------------------- ayuda
with T_AYUDA:
    st.markdown(f"""
**La forma más rápida (recomendada)**
1. En **📋 Pegar cuotas** elegí un partido, copiá la página de Super Match (pestañas Goles y Otro) y pegala. La app lee todas las cuotas sola.
2. Repetí con los partidos que te interesen. En **⭐ Mejores jugadas del día** te quedan las que convienen, ordenadas por valor.
3. Tocá **🧩 Armar ese ticket** y después **🚀 Cargar en Super Match**.
4. Un rato antes de que empiecen los partidos, volvé a pegar las cuotas: así la app mide tu **CLV** (si le ganás a la cuota de cierre).

**Uso diario**
1. Mirá los tickets en **Tickets**, o armá uno propio en **Armá tu ticket** (ahí podés escribir cuotas en la tabla y ordenar por valor).
2. Tocá **🚀 Cargar en Super Match** y seguí la guía jugada por jugada.
3. En cada jugada escribí la **cuota que te muestra Super Match**:
   - ✅ **Conviene**: paga más que la cuota justa + {cfg['margenSeguridad']*100:.0f}% de margen.
   - ⚠️ **Justo**: paga apenas lo que vale.
   - ❌ **Cambiala**: paga menos de lo que vale. Sacala o elegí otra.
4. En Super Match ponés el monto (la app te sugiere uno) y apretás **Apostar**. Eso lo hacés vos.
5. Tocá **📒 Ya lo aposté** para anotarlo. Los resultados se buscan solos y en **Mi historial** ves cuánto vas ganando o perdiendo.

**Cuidar la plata**
- Cargá tu **banca** (la plata que destinás a apostar) en la barra izquierda. El monto sugerido sale de ahí: un % fijo, o con las cuotas cargadas,
  una fracción del criterio de Kelly (más chico cuanto menos valor tenga el ticket).
- Si en 7 días perdés el {cfg['banca']['limiteSemanalPorcentaje']:.0f}% de la banca, la app te avisa y deja de sugerir montos.
- Combinadas cortas (2–3 jugadas): cada jugada extra suma el margen de la casa.

**De dónde salen los números**
- Partidos del día: API-Football. Historial: football-data.co.uk (últimos {cfg['partidosHistorial']} partidos, con más peso a los recientes,
  separando local y visitante, y con goles esperados xG cuando están).
- Si el partido es de una liga europea, se compara con las cuotas del mercado y se mezcla ({cfg['pesoMercado'] * 100:.0f}% mercado).
- Ligas sin datos (como la uruguaya): la app guarda cada día los resultados de todos los partidos; cuando un equipo junta 5, entra en el análisis (solo goles).

**Importante:** ningún modelo garantiza ganar. Las casas cobran margen en cada jugada. Apostá solo lo que estés dispuesto a perder.
""")
