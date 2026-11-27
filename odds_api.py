"""The Odds API: cuotas de decenas de casas de apuestas, para muchas más ligas que football-data.

Sirve para detectar valor real (💰 Real): si Super Match paga más que el promedio de las casas grandes.
Se activa solo cuando está cargado el secreto ODDS_API_KEY. Si no está, la app funciona igual (sin esta fuente).

Plan gratis: 500 consultas por mes. Para no gastarlas, se guarda en cache y se consulta cada liga una vez por día.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

import requests

import engine
import storage

BASE = "https://api.the-odds-api.com/v4"


def _key() -> str | None:
    return storage.secreto("ODDS_API_KEY")


def disponible() -> bool:
    return bool(_key())


def _cache_path(sport: str):
    d = engine.CACHE / "oddsapi"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sport}.json"


def _fetch_sport(sport: str, cfg: dict, forzar: bool, info: dict) -> list[dict]:
    """Baja (o lee de cache) los partidos con cuotas de una liga. Cache de 6 horas."""
    f = _cache_path(sport)
    if f.exists() and not forzar and time.time() - f.stat().st_mtime < 12 * 3600:
        return json.loads(f.read_text(encoding="utf-8"))
    try:
        r = requests.get(f"{BASE}/sports/{sport}/odds", params={
            "apiKey": _key(), "regions": cfg.get("oddsApi", {}).get("regiones", "eu,uk"),
            "markets": "h2h,totals", "oddsFormat": "decimal"}, timeout=30)
        if r.status_code in (401, 403):
            info["error"] = "La ODDS_API_KEY no es válida o se quedó sin consultas."
            return []
        if r.status_code in (404, 422):   # liga no existe en The Odds API
            f.write_text("[]", encoding="utf-8")
            return []
        r.raise_for_status()
        info["restantes"] = r.headers.get("x-requests-remaining")
        data = r.json()
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data
    except requests.RequestException:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def _consenso_partido(ev: dict) -> dict:
    """Para un evento de The Odds API, devuelve {clave_motor: (prob, cuota_promedio)}."""
    home, away = ev["home_team"], ev["away_team"]
    # 1x2
    hh = ha = hd = 0.0
    nh = 0
    tot = {}  # linea -> [sum_prob_over, sum_prob_under, n]
    bsi = bno = 0.0
    nb = 0
    for bk in ev.get("bookmakers", []):
        for m in bk.get("markets", []):
            if m["key"] == "btts":
                o = {x["name"]: x["price"] for x in m["outcomes"]}
                if "Yes" in o and "No" in o:
                    iy, inn = 1 / o["Yes"], 1 / o["No"]
                    s = iy + inn
                    if s > 0:
                        bsi += iy / s
                        bno += inn / s
                        nb += 1
            elif m["key"] == "h2h":
                o = {x["name"]: x["price"] for x in m["outcomes"]}
                if home in o and away in o:
                    inv_h, inv_a = 1 / o[home], 1 / o[away]
                    inv_d = 1 / o["Draw"] if "Draw" in o else 0.0
                    s = inv_h + inv_a + inv_d
                    if s > 0:
                        hh += inv_h / s
                        ha += inv_a / s
                        hd += inv_d / s
                        nh += 1
            elif m["key"] == "totals":
                over = under = point = None
                for x in m["outcomes"]:
                    if x["name"] == "Over":
                        over, point = x["price"], x.get("point")
                    elif x["name"] == "Under":
                        under = x["price"]
                if over and under and point is not None:
                    io, iu = 1 / over, 1 / under
                    s = io + iu
                    d = tot.setdefault(point, [0.0, 0.0, 0])
                    d[0] += io / s
                    d[1] += iu / s
                    d[2] += 1
    out = {}
    if nh:
        p1, px, p2 = hh / nh, hd / nh, ha / nh
        for clave, p in (("gana_local", p1), ("empate", px), ("gana_visita", p2),
                         ("dc_1x", p1 + px), ("dc_x2", p2 + px), ("dc_12", p1 + p2)):
            out[clave] = (1 / p if p > 0 else None, p)
    for point, (so, su, n) in tot.items():
        if n and float(point) in (1.5, 2.5, 3.5):
            po, pu = so / n, su / n
            out[f"goles_mas_{float(point)}"] = (1 / po if po > 0 else None, po)
            out[f"goles_menos_{float(point)}"] = (1 / pu if pu > 0 else None, pu)
    if nb:
        psi, pno = bsi / nb, bno / nb
        out["btts_si"] = (1 / psi if psi > 0 else None, psi)
        out["btts_no"] = (1 / pno if pno > 0 else None, pno)
    return dict(home=home, away=away, probs=out, commence=ev.get("commence_time", ""))


# nombre lindo de cada liga de The Odds API (para mostrar cuando no hay API-Football)
SPORT_NOMBRES = {
    "soccer_uefa_champs_league": "Champions League", "soccer_uefa_europa_league": "Europa League",
    "soccer_uefa_europa_conference_league": "Conference League", "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "LaLiga", "soccer_italy_serie_a": "Serie A", "soccer_germany_bundesliga": "Bundesliga",
    "soccer_france_ligue_one": "Ligue 1", "soccer_conmebol_copa_libertadores": "Libertadores",
    "soccer_conmebol_copa_sudamericana": "Sudamericana", "soccer_argentina_primera_division": "Liga Argentina",
    "soccer_brazil_campeonato": "Brasileirão", "soccer_uruguay_primera_division": "Primera Uruguay",
    "soccer_colombia_primera_a": "Primera A Colombia", "soccer_chile_campeonato": "Primera Chile",
}


def partidos_del_dia(cfg: dict, fecha: str, forzar: bool = False) -> tuple[list, dict]:
    """Lista de partidos del día SACADA de The Odds API (cuando API-Football no está disponible).
    Cada partido: {id, liga, hora, dia, pais, home, away, home_id, away_id, probs}."""
    import hashlib
    info: dict = {"restantes": None, "ligas": 0}
    if not disponible():
        return [], info
    tz = __import__("zoneinfo").ZoneInfo(cfg.get("zonaHoraria", "America/Montevideo"))
    mapa = cfg.get("oddsApi", {}).get("ligas", {})
    partidos = []
    for lid, sport in mapa.items():
        data = _fetch_sport(sport, cfg, forzar, info)
        if not data:
            continue
        info["ligas"] += 1
        for ev in data:
            try:
                dt = __import__("datetime").datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(tz)
            except (ValueError, KeyError):
                continue
            if dt.date().isoformat() != fecha:
                continue
            c = _consenso_partido(ev)
            probs = {k: (cu, p) for k, (cu, p) in c["probs"].items() if cu}
            if not probs:
                continue
            mid = int(hashlib.md5(f"{c['home']}|{c['away']}|{fecha}".encode()).hexdigest()[:8], 16)
            partidos.append(dict(id=mid, liga=SPORT_NOMBRES.get(sport, sport), hora=dt.strftime("%H:%M"), dia=fecha,
                                 pais="", home=c["home"], away=c["away"], home_id=mid, away_id=mid + 1,
                                 league_id=int(lid) if str(lid).isdigit() else 0, probs=probs))
    partidos.sort(key=lambda m: m["hora"])
    return partidos, info


def consenso(cfg: dict, matches: list, forzar: bool = False) -> tuple[dict, dict]:
    """Devuelve ({match_id: {clave: (cuota_promedio, prob_consenso)}}, info)."""
    info: dict = {"restantes": None, "ligas": 0}
    if not disponible():
        return {}, info
    mapa = cfg.get("oddsApi", {}).get("ligas", {})   # id API-Football (str) -> sport key de The Odds API
    # agrupar partidos por liga
    por_liga: dict[str, list] = {}
    for m in matches:
        sport = mapa.get(str(getattr(m, "league_id", "")))
        if sport:
            por_liga.setdefault(sport, []).append(m)
    res: dict = {}
    for sport, ms in por_liga.items():
        data = _fetch_sport(sport, cfg, forzar, info)
        if not data:
            continue
        info["ligas"] += 1
        eventos = [_consenso_partido(ev) for ev in data]
        for m in ms:
            htok, atok = engine.name_tokens(m.home), engine.name_tokens(m.away)
            best, bs = None, 0.0
            for ev in eventos:
                s = (engine.name_score(htok, engine.name_tokens(ev["home"]), True)
                     + engine.name_score(atok, engine.name_tokens(ev["away"]), True)) / 2
                if s > bs:
                    bs, best = s, ev
            if best and bs >= 0.6:
                res[m.id] = {k: (c, p) for k, (c, p) in best["probs"].items() if c}
    return res, info
