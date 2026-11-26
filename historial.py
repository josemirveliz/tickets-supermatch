"""Historial de apuestas: guarda los tickets que jugaste, busca los resultados y calcula cómo te va."""
from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime, timedelta

import engine
import storage

ESTADOS = ["pendiente", "ganada", "perdida", "anulada"]


# ------------------------------------------------------------------ guardado (archivo local o nube)
def cargar() -> list[dict]:
    return storage.cargar("historial", [])


def guardar(tickets: list[dict]):
    storage.guardar("historial", tickets)


def cargar_ajustes() -> dict:
    return storage.cargar("ajustes", {})


def guardar_ajustes(a: dict):
    storage.guardar("ajustes", a)


def agregar_ticket(nombre: str, legs: list[dict], cuotas: dict, monto: float) -> dict:
    t = dict(
        id=uuid.uuid4().hex[:10], creado=engine.ahora().isoformat(timespec="minutes"), nombre=nombre, monto=float(monto),
        legs=[dict(sel_id=l["sel_id"], match_id=l["match_id"], clave=l["clave"], dia=l["dia"], hora=l["hora"],
                   partido=l["partido"], mercado=l["mercado"], categoria=l["categoria"], prob=l["prob"],
                   cuota_justa=l["cuota"], cuota=float(cuotas.get(l["sel_id"]) or 0) or None, cuota_cierre=None,
                   home_fd=l.get("home_fd"), away_fd=l.get("away_fd"), resultado="pendiente", manual=False)
              for l in legs],
    )
    hist = cargar()
    hist.insert(0, t)
    guardar(hist)
    return t


# ------------------------------------------------------------------ cálculo del ticket
def cuota_total(t: dict) -> float | None:
    cs = []
    for l in t["legs"]:
        if l["resultado"] == "anulada":
            continue
        if not l["cuota"]:
            return None
        cs.append(l["cuota"])
    return math.prod(cs) if cs else 1.0


def estado(t: dict) -> str:
    rs = [l["resultado"] for l in t["legs"]]
    if "perdida" in rs:
        return "perdido"
    if "pendiente" in rs:
        return "pendiente"
    return "ganado"


def cobro(t: dict) -> float | None:
    e = estado(t)
    if e == "perdido":
        return 0.0
    if e == "ganado":
        c = cuota_total(t)
        return None if c is None else t["monto"] * c
    return None


# ------------------------------------------------------------------ buscar resultados
def buscar_resultados(cfg: dict) -> int:
    """Completa las jugadas pendientes con los resultados del historial propio (API) y de football-data."""
    hist = cargar()
    pend = [l for t in hist for l in t["legs"] if l["resultado"] == "pendiente" and not l.get("manual")]
    if not pend:
        return 0
    store = engine.load_store()
    fd = engine.load_football_data(cfg)
    por_equipos = {}
    for m in fd.partidos:
        por_equipos.setdefault((m["home"], m["away"]), []).append(m)
    n = 0
    for l in pend:
        hg = ag = hc = ac = None
        api = store.get(str(l["match_id"]))
        if api:
            hg, ag = api["hg"], api["ag"]
        if l.get("home_fd") and l.get("away_fd"):
            d = datetime.fromisoformat(l["dia"])
            for m in por_equipos.get((l["home_fd"], l["away_fd"]), []):
                if abs((m["date"] - d).days) <= 1:
                    if hg is None:
                        hg, ag = m["hg"], m["ag"]
                    hc, ac = m["hc"], m["ac"]
        if hg is None:
            continue
        r = engine.evaluar(l["clave"], hg, ag, hc, ac)
        if r is None:
            continue
        l["resultado"] = "ganada" if r else "perdida"
        l["marcador"] = f"{hg}-{ag}" + (f" · corners {hc}-{ac}" if hc is not None else "")
        n += 1
    if n:
        guardar(hist)
    return n


def actualizar_cierre(cuotas: dict[str, float]) -> int:
    """Guarda la última cuota vista ANTES de que empiece el partido ('cuota de cierre') en las jugadas que apostaste.
    Se llama cada vez que pegás cuotas de Super Match en la app."""
    hist = cargar()
    ahora = engine.ahora()
    n = 0
    for t in hist:
        for l in t["legs"]:
            v = cuotas.get(l["sel_id"])
            if not v:
                continue
            try:
                inicio = datetime.fromisoformat(f"{l['dia']}T{l['hora']}")
            except ValueError:
                continue
            if ahora < inicio:
                l["cuota_cierre"] = float(v)
                n += 1
    if n:
        guardar(hist)
    return n


def clv_automatico() -> int:
    """Rellena la cuota de cierre de cada jugada con la última cuota del mercado antes del partido (The Odds API).
    Así el CLV se calcula solo, sin que tengas que volver a pegar cuotas."""
    hist = cargar()
    n = 0
    for t in hist:
        for l in t["legs"]:
            if l.get("cuota_cierre") or not l.get("cuota"):
                continue
            snaps = engine.movimiento(l["match_id"])
            if not snaps:
                continue
            try:
                inicio = datetime.fromisoformat(f"{l['dia']}T{l['hora']}")
            except ValueError:
                continue
            previos = [s for s in snaps if s["t"] <= inicio.isoformat() and l["clave"] in s.get("cuotas", {})]
            if previos:
                l["cuota_cierre"] = previos[-1]["cuotas"][l["clave"]]
                n += 1
    if n:
        guardar(hist)
    clv_automatico()
    return n


def marcar(ticket_id: str, sel_id: str, resultado: str):
    hist = cargar()
    for t in hist:
        if t["id"] == ticket_id:
            for l in t["legs"]:
                if l["sel_id"] == sel_id:
                    l["resultado"] = resultado
                    l["manual"] = resultado != "pendiente"
    guardar(hist)


def borrar(ticket_id: str):
    guardar([t for t in cargar() if t["id"] != ticket_id])


# ------------------------------------------------------------------ estadísticas
def estadisticas(hist: list[dict]) -> dict:
    cerrados = [t for t in hist if estado(t) != "pendiente"]
    apostado = sum(t["monto"] for t in cerrados)
    cobrado = sum(cobro(t) or 0 for t in cerrados)
    hace7 = engine.ahora() - timedelta(days=7)
    semana = [t for t in cerrados if datetime.fromisoformat(t["creado"]) >= hace7]
    pend_semana = [t for t in hist if estado(t) == "pendiente" and datetime.fromisoformat(t["creado"]) >= hace7]
    perdida_semana = sum(t["monto"] for t in semana) - sum(cobro(t) or 0 for t in semana) + sum(t["monto"] for t in pend_semana)
    por_tipo = {}
    for t in cerrados:
        d = por_tipo.setdefault(t["nombre"], dict(tickets=0, ganados=0, apostado=0.0, cobrado=0.0))
        d["tickets"] += 1
        d["ganados"] += estado(t) == "ganado"
        d["apostado"] += t["monto"]
        d["cobrado"] += cobro(t) or 0
    legs = [l for t in hist for l in t["legs"] if l["resultado"] in ("ganada", "perdida")]
    tramos = []
    for lo, hi in ((0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        xs = [l for l in legs if lo <= l["prob"] < hi]
        if xs:
            tramos.append(dict(tramo=f"{lo * 100:.0f}–{min(hi, 1) * 100:.0f}%", jugadas=len(xs),
                               prob_media=sum(l["prob"] for l in xs) / len(xs),
                               salieron=sum(l["resultado"] == "ganada" for l in xs) / len(xs)))
    por_cat = {}
    for l in legs:
        d = por_cat.setdefault(l["categoria"], [0, 0])
        d[0] += 1
        d[1] += l["resultado"] == "ganada"
    # CLV: cuánto mejor (o peor) fue tu cuota que la del cierre. Positivo sostenido = le estás ganando a Super Match.
    clv = [l["cuota"] / l["cuota_cierre"] - 1 for t in hist for l in t["legs"] if l.get("cuota") and l.get("cuota_cierre")]
    return dict(tickets=len(hist), cerrados=len(cerrados), ganados=sum(estado(t) == "ganado" for t in cerrados),
                pendientes=len(hist) - len(cerrados), apostado=apostado, cobrado=cobrado, ganancia=cobrado - apostado,
                roi=(cobrado - apostado) / apostado if apostado else 0.0, perdida_semana=max(0.0, perdida_semana),
                por_tipo=por_tipo, tramos=tramos, por_cat=por_cat,
                clv=sum(clv) / len(clv) if clv else None, clv_n=len(clv), clv_pos=sum(1 for x in clv if x > 0))


# ------------------------------------------------------------------ cuánto apostar
def monto_sugerido(legs: list[dict], cuotas: dict, banca: float, cfg: dict, ajustes: dict) -> tuple[float, str]:
    b = cfg["banca"]
    pct = float(ajustes.get("pct", b["porcentajePorTicket"])) / 100
    maxpct = float(b["porcentajeMaximo"]) / 100
    if banca <= 0:
        return 0.0, "Cargá tu banca en Opciones (en el celular, el botón » de arriba a la izquierda) para ver cuánto apostar."
    vals = [cuotas.get(l["sel_id"]) or 0 for l in legs]
    if all(vals):
        o = math.prod(vals)
        p = math.prod(l["prob"] for l in legs)
        if p * o - 1 <= 0:
            return 0.0, "Con estas cuotas el ticket no tiene valor según el modelo: mejor no jugarlo."
        kelly = (p * o - 1) / (o - 1)
        f = min(maxpct, float(b["fraccionKelly"]) * kelly)
        return round(banca * f / 10) * 10 or 10.0, f"Kelly al {float(b['fraccionKelly']) * 100:.0f}% (máx. {maxpct * 100:.1f}% de la banca)"
    factor = {1: 1.0, 2: 1.0, 3: 0.75}.get(len(legs), 0.5)
    return round(banca * pct * factor / 10) * 10 or 10.0, f"{pct * factor * 100:.1f}% de la banca (cargá las cuotas para afinarlo)"
