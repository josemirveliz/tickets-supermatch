"""Motor de análisis: partidos del día (API-Football), historial (football-data.co.uk + historial propio),
modelo de probabilidades, comparación con el mercado y armado de tickets. No apuesta: solo arma jugadas."""
from __future__ import annotations

import bisect
import csv
import io
import json
import math
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import storage

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
FD_DIR = CACHE / "fd"
DATA = ROOT / "data"
API_BASE = "https://v3.football.api-sports.io"
FINAL = {"FT", "AET", "PEN"}


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def ahora(cfg: dict | None = None) -> datetime:
    """Hora de Uruguay (o la de config.json), aunque la app corra en un servidor de otro país."""
    tz = ZoneInfo((cfg or load_config()).get("zonaHoraria", "America/Montevideo"))
    return datetime.now(tz).replace(tzinfo=None)


def hoy(cfg: dict | None = None) -> date:
    return ahora(cfg).date()


class BotError(Exception):
    pass


# =========================================================================== nombres como en Super Match
SM_NOMBRES = {
    "Bayern München": "Bayern Múnich", "Bayern Munich": "Bayern Múnich", "Paris Saint Germain": "Paris Saint-germain",
    "Sporting CP": "Sporting Portugal", "Club Brugge KV": "Brujas", "AC Milan": "Ac Milán", "Olympiakos Piraeus": "Olympiacos Pireo",
    "Atletico Madrid": "Atlético Madrid", "AS Roma": "As Roma", "Celta Vigo": "Celta De Vigo", "Bournemouth": "Afc Bournemouth",
    "Estudiantes L.P.": "Estudiantes De La Plata",
}
try:
    SM_NOMBRES.update(load_config().get("nombresSuperMatch") or {})
except (OSError, ValueError):
    pass


def sm_name(name: str) -> str:
    return SM_NOMBRES.get(name, name)


# =========================================================================== API-Football
@dataclass
class ApiInfo:
    consultas: int = 0
    restantes: int | None = None


def api_get(cfg: dict, path: str, params: dict, info: ApiInfo) -> dict:
    key = storage.secreto("API_FOOTBALL_KEY") or cfg.get("apiKey", "")
    if not key or key.startswith("PEGA_"):
        raise BotError("Falta la API key de API-Football (secreto API_FOOTBALL_KEY) o usá el modo demo.")
    r = requests.get(f"{API_BASE}/{path}", params=params, headers={"x-apisports-key": key}, timeout=40)
    info.consultas += 1
    rem = r.headers.get("x-ratelimit-requests-remaining")
    if rem and rem.isdigit():
        info.restantes = int(rem)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise BotError(f"La API respondió con error: {json.dumps(j['errors'], ensure_ascii=False)}")
    return j


def fixtures_del_dia(cfg: dict, fecha: str, info: ApiInfo, forzar: bool = False) -> list[dict]:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"dia_{fecha}.json"
    ttl = 3 * 3600 if fecha >= hoy(cfg).isoformat() else 30 * 3600
    if f.exists() and not forzar and time.time() - f.stat().st_mtime < ttl:
        j = json.loads(f.read_text(encoding="utf-8"))
    else:
        j = api_get(cfg, "fixtures", {"date": fecha, "timezone": cfg["zonaHoraria"]}, info)
        f.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    return j.get("response", [])


# ---------------------------------------------------------------- historial propio (resultados que vamos juntando)
DIAS_STORE = 240


def load_store() -> dict:
    return storage.cargar("partidos_api", {})


def save_store(store: dict):
    # se guardan solo los últimos ~8 meses para que no crezca sin límite
    corte = (date.today() - timedelta(days=DIAS_STORE)).isoformat()
    storage.guardar("partidos_api", {k: v for k, v in store.items() if v["date"] >= corte})


# --------------------------------------------------------- movimiento de cuotas del mercado (para CLV automático)
def guardar_snapshot(consenso: dict, cfg: dict):
    """Guarda cómo están las cuotas del mercado ahora, para ver su movimiento y calcular el CLV sin pegar nada."""
    if not consenso:
        return
    mov = storage.cargar("cuotas_mov", {})
    ahora_iso = ahora(cfg).isoformat(timespec="minutes")
    for mid, claves in consenso.items():
        hist = mov.get(str(mid), [])
        snap = {"t": ahora_iso, "cuotas": {k: round(c, 2) for k, (c, p) in claves.items() if c}}
        if not hist or hist[-1]["t"][:13] != ahora_iso[:13]:   # máximo una por hora
            hist.append(snap)
        else:
            hist[-1] = snap
        mov[str(mid)] = hist[-8:]
    # limpiar partidos viejos (más de 3 días sin tocar)
    corte = (ahora(cfg) - timedelta(days=3)).isoformat()
    mov = {k: v for k, v in mov.items() if v and v[-1]["t"] >= corte}
    storage.guardar("cuotas_mov", mov)


def movimiento(match_id) -> list[dict]:
    return storage.cargar("cuotas_mov", {}).get(str(match_id), [])


def guardar_terminados(store: dict, fixtures: list[dict], ligas: set[int] | None = None) -> int:
    n = 0
    for f in fixtures:
        if f["fixture"]["status"]["short"] not in FINAL:
            continue
        if ligas is not None and int(f["league"]["id"]) not in ligas:
            continue
        ft = (f.get("score") or {}).get("fulltime") or {}
        hg, ag = ft.get("home"), ft.get("away")
        if hg is None:
            hg, ag = f["goals"]["home"], f["goals"]["away"]
        if hg is None:
            continue
        fid = str(f["fixture"]["id"])
        if fid not in store:
            n += 1
        store[fid] = dict(date=f["fixture"]["date"][:10], league_id=f["league"]["id"], league=f["league"]["name"],
                          country=f["league"]["country"], home=f["teams"]["home"]["name"], away=f["teams"]["away"]["name"],
                          home_id=f["teams"]["home"]["id"], away_id=f["teams"]["away"]["id"], hg=int(hg), ag=int(ag))
    return n


def store_rows(store: dict, team_id: int) -> list[dict]:
    rows = []
    for m in store.values():
        if m["home_id"] == team_id:
            rows.append(dict(date=datetime.fromisoformat(m["date"]), home=True, gf=m["hg"], ga=m["ag"], xgf=None, xga=None, cf=None, ca=None, kf=None, ka=None))
        elif m["away_id"] == team_id:
            rows.append(dict(date=datetime.fromisoformat(m["date"]), home=False, gf=m["ag"], ga=m["hg"], xgf=None, xga=None, cf=None, ca=None, kf=None, ka=None))
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


# =========================================================================== football-data.co.uk
def fd_file(rel: str, ttl_h: float, forzar: bool) -> Path | None:
    FD_DIR.mkdir(parents=True, exist_ok=True)
    f = FD_DIR / rel.replace("/", "_")
    miss = f.with_name(f.name + ".noexiste")
    if miss.exists():
        return None
    if f.exists() and (ttl_h < 0 or (not forzar and time.time() - f.stat().st_mtime < ttl_h * 3600)):
        return f
    try:
        r = requests.get(f"https://www.football-data.co.uk/{rel}", timeout=60)
        if r.status_code == 404:
            if ttl_h < 0:
                miss.write_text("")
            return f if f.exists() else None
        r.raise_for_status()
        f.write_bytes(r.content)
        return f
    except requests.RequestException:
        return f if f.exists() else None


def _num(c, i):
    if i < 0 or i >= len(c) or c[i].strip() == "":
        return None
    try:
        return float(c[i])
    except ValueError:
        return None


def read_fd_csv(path: Path, cut: datetime, con_resultado: bool = True):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return
    ix = {}
    for i, h in enumerate(rows[0]):
        h = h.strip().lstrip("﻿")
        if h and h not in ix:
            ix[h] = i

    def col(*names):
        for n in names:
            if n in ix:
                return ix[n]
        return -1

    iD, iDiv, iH, iA = col("Date"), col("Div", "League"), col("HomeTeam", "Home"), col("AwayTeam", "Away")
    iHG, iAG, iHC, iAC, iHX, iAX = col("FTHG", "HG"), col("FTAG", "AG"), col("HC"), col("AC"), col("HxG"), col("AxG")
    iHY, iAY, iHR, iAR = col("HY"), col("AY"), col("HR"), col("AR")   # tarjetas amarillas y rojas
    odds_cols = {"H": ("AvgCH", "AvgH"), "D": ("AvgCD", "AvgD"), "A": ("AvgCA", "AvgA"),
                 "O25": ("AvgC>2.5", "Avg>2.5"), "U25": ("AvgC<2.5", "Avg<2.5")}
    odds_ix = {k: [col(n) for n in v] for k, v in odds_cols.items()}
    for c in rows[1:]:
        try:
            if len(c) <= max(iA, iH, iD) or not c[iD]:
                continue
            ds = c[iD].strip()
            dt = datetime.strptime(ds, "%d/%m/%Y" if len(ds) > 8 else "%d/%m/%y")
            if dt < cut:
                continue
            hg, ag = _num(c, iHG), _num(c, iAG)
            if con_resultado and hg is None:
                continue
            odds = {}
            for k, ids in odds_ix.items():
                for i in ids:
                    v = _num(c, i)
                    if v and v > 1:
                        odds[k] = v
                        break
            hc, ac = _num(c, iHC), _num(c, iAC)
            hy, ay = _num(c, iHY), _num(c, iAY)
            hk = None if hy is None or ay is None else int(hy) + int(_num(c, iHR) or 0)   # tarjetas del local (amarillas+rojas)
            ak = None if hy is None or ay is None else int(ay) + int(_num(c, iAR) or 0)   # tarjetas del visitante
            yield dict(date=dt, div=c[iDiv].strip() if iDiv >= 0 else "", home=c[iH].strip(), away=c[iA].strip(),
                       hg=None if hg is None else int(hg), ag=None if ag is None else int(ag),
                       hc=None if hc is None or ac is None else int(hc), ac=None if hc is None or ac is None else int(ac),
                       hk=hk, ak=ak, hxg=_num(c, iHX), axg=_num(c, iAX), odds=odds)
        except (ValueError, IndexError):
            continue


@dataclass
class FootballData:
    rows: dict[str, list[dict]]          # equipo -> partidos (más nuevo primero), desde su punto de vista
    pais: dict[str, str]
    tokens: dict[str, list[str]]
    paises: set[str]
    partidos: list[dict]                 # todos los partidos (para la prueba del modelo y resultados de corners)
    proximos: list[dict]                 # próximos partidos con cuotas del mercado (fixtures.csv)


def team_row(m: dict, home: bool) -> dict:
    if home:
        return dict(date=m["date"], home=True, gf=m["hg"], ga=m["ag"], xgf=m["hxg"], xga=m["axg"], cf=m["hc"], ca=m["ac"],
                    kf=m.get("hk"), ka=m.get("ak"))
    return dict(date=m["date"], home=False, gf=m["ag"], ga=m["hg"], xgf=m["axg"], xga=m["hxg"], cf=m["ac"], ca=m["hc"],
                kf=m.get("ak"), ka=m.get("hk"))


_FD_MEMO: dict = {}


def load_football_data(cfg: dict, forzar: bool = False) -> FootballData:
    """Lee los CSV (con memoria de 1 hora para que la app responda rápido)."""
    memo = _FD_MEMO.get("fd")
    if memo and not forzar and time.time() - memo[0] < 3600:
        return memo[1]
    fd = _load_football_data(cfg, forzar)
    _FD_MEMO["fd"] = (time.time(), fd)
    return fd


def _load_football_data(cfg: dict, forzar: bool) -> FootballData:
    fcfg = cfg["footballData"]
    cut = datetime.now() - timedelta(days=int(fcfg["diasHistorial"]))
    files = []
    for l in fcfg["europa"]:
        files.append((f"mmz4281/{fcfg['temporadaActual']}/{l['codigo']}.csv", l["pais"], 12))
        files.append((f"mmz4281/{fcfg['temporadaAnterior']}/{l['codigo']}.csv", l["pais"], -1))
    for l in fcfg["extra"]:
        files.append((f"new/{l['codigo']}.csv", l["pais"], 12))
    rows: dict[str, list[dict]] = {}
    pais: dict[str, str] = {}
    partidos = []
    for rel, p, ttl in files:
        path = fd_file(rel, ttl, forzar)
        if not path:
            continue
        liga = rel.split("/")[-1].replace(".csv", "")
        for m in read_fd_csv(path, cut):
            m["pais"], m["liga"] = p, liga
            partidos.append(m)
            for t in (m["home"], m["away"]):
                if t not in rows:
                    rows[t] = []
                    pais[t] = p
            rows[m["home"]].append(team_row(m, True))
            rows[m["away"]].append(team_row(m, False))
    for t in rows:
        rows[t].sort(key=lambda r: r["date"], reverse=True)
    partidos.sort(key=lambda m: m["date"])
    proximos = []
    path = fd_file("fixtures.csv", 6, forzar)
    if path:
        proximos = list(read_fd_csv(path, datetime.now() - timedelta(days=2), con_resultado=False))
    return FootballData(rows, pais, {t: name_tokens(t) for t in rows}, set(pais.values()), partidos, proximos)


# =========================================================================== emparejar nombres
STOP = set("fc cf afc sc ac as ss ssc us cd ud sd rc rcd club de del la el le les the y do da vfb vfl tsg sv fsv bv osc ogc "
           "losc ca cs sk fk kv krc kaa stade olympique real calcio ec se cr".split())
ALIAS = {
    "Manchester United": "Man United", "Manchester City": "Man City", "Nottingham Forest": "Nott'm Forest",
    "Wolverhampton Wanderers": "Wolves", "Sheffield Wednesday": "Sheffield Weds", "Atletico Madrid": "Ath Madrid",
    "Athletic Club": "Ath Bilbao", "Athletic Bilbao": "Ath Bilbao", "Espanyol": "Espanol", "Bayern Munchen": "Bayern Munich",
    "Bayern Munich": "Bayern Munich", "Borussia Monchengladbach": "M'gladbach", "Paris Saint Germain": "Paris SG",
    "Stade Rennais": "Rennes", "Stade Brestois 29": "Brest", "Olympique Lyonnais": "Lyon", "Sporting CP": "Sp Lisbon",
    "SC Braga": "Sp Braga", "Olympiakos Piraeus": "Olympiakos", "Inter": "Inter",
}


def name_tokens(s: str) -> list[str]:
    s = s.replace("ß", "ss").replace("ø", "o").replace("æ", "ae")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return ["st" if t == "saint" else t for t in s.split() if t not in STOP and not t.isdigit()]


def name_score(a: list[str], b: list[str], contain: bool) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    used, m = set(), 0
    for x in a:
        for j, y in enumerate(b):
            if j in used:
                continue
            if x == y or (len(x) >= 3 and y.startswith(x)) or (len(y) >= 3 and x.startswith(y)):
                used.add(j)
                m += 1
                break
    score = 2.0 * m / (len(a) + len(b))
    if contain and m == min(len(a), len(b)):
        score = max(score, 0.85)
    return score


def find_fd_team(api_name: str, pais: str, fd: FootballData, cfg: dict) -> str | None:
    tok = name_tokens(api_name)
    aliases = {" ".join(name_tokens(k)): v for k, v in ALIAS.items()}
    for k, v in (cfg.get("alias") or {}).items():
        aliases[" ".join(name_tokens(k))] = v
    key = " ".join(tok)
    if key in aliases and aliases[key] in fd.rows:
        return aliases[key]
    local = pais in fd.paises
    pool = [t for t in fd.rows if fd.pais[t] == pais] if local else list(fd.rows)
    minimo = 0.6 if local else 0.8
    best, bs, second = None, 0.0, 0.0
    for t in pool:
        s = name_score(tok, fd.tokens[t], local)
        if s > bs:
            best, bs, second = t, s, bs
        elif s > second:
            second = s
    if bs < minimo or (bs < 1.0 and second >= bs):
        return None
    return best


# =========================================================================== matemática
def pois(l: float, n: int) -> list[float]:
    p = [math.exp(-l)]
    for k in range(1, n + 1):
        p.append(p[-1] * l / k)
    return p


def negbin(mu: float, disp: float, n: int) -> list[float]:
    r = mu / (disp - 1)
    q = mu / (r + mu)
    p = [(r / (r + mu)) ** r]
    for k in range(n):
        p.append(p[-1] * (k + r) / (k + 1) * q)
    return p


def p_over(dist: list[float], line: float) -> float:
    return max(0.0, 1 - sum(dist[: int(math.floor(line)) + 1]))


def rate(values: list[float], line: float, over: bool) -> float | None:
    if not values:
        return None
    return sum(1 for v in values if (v > line if over else v < line)) / len(values)


def avg(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


# =========================================================================== modelo
@dataclass
class Fuerza:
    n: int
    ataque: float
    defensa: float
    nc: int
    c_favor: float
    c_contra: float
    usa_xg: bool
    nt: int = 0           # cuántos partidos con dato de tarjetas
    t_self: float = 2.0   # tarjetas que suele recibir el equipo
    t_opp: float = 2.0    # tarjetas que suele recibir el rival


def _wavg(rows: list[dict], fn, decay: float):
    num = den = 0.0
    n = 0
    for i, r in enumerate(rows):
        v = fn(r)
        if v is None:
            continue
        w = decay ** i
        num += w * v
        den += w
        n += 1
    return (num / den if den else None), n


def _goles_ataque(r):  # mezcla goles reales y goles esperados (xG) si están
    return r["gf"] if r["xgf"] is None else 0.5 * r["gf"] + 0.5 * r["xgf"]


def _goles_defensa(r):
    return r["ga"] if r["xga"] is None else 0.5 * r["ga"] + 0.5 * r["xga"]


def fuerza(rows: list[dict], de_local: bool, cfg: dict) -> Fuerza:
    """Ataque/defensa con más peso a lo reciente y teniendo en cuenta si juega de local o visitante."""
    decay = float(cfg.get("decaimiento", 0.85))

    def stat(fn, prior):
        tot, n = _wavg(rows, fn, decay)
        if tot is None:
            return prior, 0
        sede = [r for r in rows if r["home"] == de_local]
        sv, ns = _wavg(sede, fn, decay)
        if sv is not None and ns >= 3:
            tot = 0.6 * tot + 0.4 * sv
        return (tot * n + prior * 3) / (n + 3), n

    at, n = stat(_goles_ataque, 1.35)
    de, _ = stat(_goles_defensa, 1.35)
    cf, nc = stat(lambda r: r["cf"], 5.0)
    ca, _ = stat(lambda r: r["ca"], 5.0)
    ts, nt = stat(lambda r: r.get("kf"), 2.0)
    to, _ = stat(lambda r: r.get("ka"), 2.0)
    return Fuerza(n, at, de, nc, cf, ca, any(r["xgf"] is not None for r in rows), nt, ts, to)


# Mercados y líneas que ofrece Super Match (revisado en su página, nov-2026)
GOLES_MAS = (1.5, 2.5, 3.5, 4.5)
GOLES_MENOS = (2.5, 3.5, 4.5, 5.5)
GOLES_EQUIPO = (1.5, 2.5)
COMBO_LINEAS = (2.5, 3.5, 4.5)
# Córners: Super Match ofrece UNA sola línea por partido (y una por equipo); calculamos varias
# y la app te muestra la que coincide con la de Super Match.
CORNERS_LINEAS = (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)
CORNERS_EQUIPO = (2.5, 3.5, 4.5, 5.5, 6.5)
# Tarjetas (amarillas + rojas) de todo el partido; Super Match ofrece una sola línea por partido
TARJETAS_LINEAS = (2.5, 3.5, 4.5, 5.5)


def modelo(h_rows: list[dict], a_rows: list[dict], cfg: dict, con_corners: bool = True) -> dict:
    """Devuelve {'probs': {clave: prob}, 'lh', 'la', 'xc', 'p1', 'px', 'p2', 'xg'}. Las claves se evalúan con evaluar()."""
    h, a = fuerza(h_rows, True, cfg), fuerza(a_rows, False, cfg)
    w = float(cfg["pesoModelo"])

    def mix(model, emp):
        return model if emp is None else w * model + (1 - w) * emp

    lh = (h.ataque + a.defensa) / 2 * 1.04
    la = (a.ataque + h.defensa) / 2 * 0.96
    ph, pa = pois(lh, 10), pois(la, 10)
    tot = [0.0] * 21
    p1 = px = p2 = pbtts = 0.0
    for i in range(11):
        for j in range(11):
            pr = ph[i] * pa[j]
            tot[i + j] += pr
            if i > j:
                p1 += pr
            elif i == j:
                px += pr
            else:
                p2 += pr
            if i and j:
                pbtts += pr
    emp_g = [r["gf"] + r["ga"] for r in h_rows + a_rows]
    emp_b = [int(r["gf"] > 0 and r["ga"] > 0) for r in h_rows + a_rows]
    eb = avg(emp_b) if emp_b else None
    P = {}
    for l in GOLES_MAS:
        P[f"goles_mas_{l}"] = mix(p_over(tot, l), rate(emp_g, l, True))
    for l in GOLES_MENOS:
        P[f"goles_menos_{l}"] = mix(1 - p_over(tot, l), rate(emp_g, l, False))
    P["btts_si"] = mix(pbtts, eb)
    P["btts_no"] = 1 - P["btts_si"]
    # "Portería a cero": local_porteria_no = el local recibe gol (= el visitante marca)
    P["local_porteria_si"], P["local_porteria_no"] = pa[0], 1 - pa[0]
    P["visita_porteria_si"], P["visita_porteria_no"] = ph[0], 1 - ph[0]
    for l in GOLES_EQUIPO:
        P[f"local_goles_mas_{l}"], P[f"local_goles_menos_{l}"] = p_over(ph, l), 1 - p_over(ph, l)
        P[f"visita_goles_mas_{l}"], P[f"visita_goles_menos_{l}"] = p_over(pa, l), 1 - p_over(pa, l)
    P["dc_1x"], P["dc_x2"], P["dc_12"] = p1 + px, p2 + px, p1 + p2   # solo para la prueba del modelo
    P["gana_local"], P["gana_visita"], P["empate"] = p1, p2, px
    # combinados de Super Match: "1x2 y total", "Total y ambos equipos marcan", "Rango de goles"
    M = [[ph[i] * pa[j] for j in range(11)] for i in range(11)]

    def S(cond):
        return sum(M[i][j] for i in range(11) for j in range(11) if cond(i, j))

    res_fn = {"local": lambda i, j: i > j, "empate": lambda i, j: i == j, "visita": lambda i, j: i < j}
    for l in COMBO_LINEAS:
        for res, f in res_fn.items():
            P[f"combo_{res}_mas_{l}"] = S(lambda i, j, f=f, l=l: f(i, j) and i + j > l)
            P[f"combo_{res}_menos_{l}"] = S(lambda i, j, f=f, l=l: f(i, j) and i + j < l)
    for lado in ("mas", "menos"):
        for b in ("si", "no"):
            P[f"tbtts_{lado}_{b}_2.5"] = S(lambda i, j, lado=lado, b=b: ((i + j > 2.5) == (lado == "mas"))
                                            and ((i > 0 and j > 0) == (b == "si")))
    P["rango_0-1"], P["rango_2-3"] = sum(tot[0:2]), sum(tot[2:4])
    P["rango_4-5"], P["rango_6+"] = sum(tot[4:6]), sum(tot[6:])
    xc = None
    min_n = int(cfg["minPartidosConDatos"])
    if con_corners and h.nc >= min_n and a.nc >= min_n:
        ch = (h.c_favor + a.c_contra) / 2 * 1.03
        ca = (a.c_favor + h.c_contra) / 2 * 0.97
        xc = ch + ca
        dt, dh, da = negbin(xc, 1.3, 40), negbin(ch, 1.3, 30), negbin(ca, 1.3, 30)
        emp_c = [r["cf"] + r["ca"] for r in h_rows + a_rows if r["cf"] is not None and r["ca"] is not None]
        for l in CORNERS_LINEAS:
            P[f"corners_mas_{l}"] = mix(p_over(dt, l), rate(emp_c, l, True))
            P[f"corners_menos_{l}"] = mix(1 - p_over(dt, l), rate(emp_c, l, False))
        for l in CORNERS_EQUIPO:
            P[f"local_corners_mas_{l}"], P[f"local_corners_menos_{l}"] = p_over(dh, l), 1 - p_over(dh, l)
            P[f"visita_corners_mas_{l}"], P[f"visita_corners_menos_{l}"] = p_over(da, l), 1 - p_over(da, l)
    # Tarjetas de todo el partido (muy ligadas al árbitro y al estilo del cruce)
    xt = None
    if con_corners and h.nt >= min_n and a.nt >= min_n:
        xt = (h.t_self + a.t_opp) / 2 + (a.t_self + h.t_opp) / 2
        dtk = negbin(xt, 1.25, 25)
        emp_t = [r["kf"] + r["ka"] for r in h_rows + a_rows if r.get("kf") is not None and r.get("ka") is not None]
        for l in TARJETAS_LINEAS:
            P[f"tarjetas_mas_{l}"] = mix(p_over(dtk, l), rate(emp_t, l, True))
            P[f"tarjetas_menos_{l}"] = mix(1 - p_over(dtk, l), rate(emp_t, l, False))
    # Goles del primer tiempo (~45% del juego): Más/Menos de 0.5 y 1.5
    ph1, pa1 = pois(lh * 0.45, 8), pois(la * 0.45, 8)
    tot1 = [0.0] * 17
    for i in range(9):
        for j in range(9):
            tot1[i + j] += ph1[i] * pa1[j]
    for l in (0.5, 1.5):
        P[f"pt_mas_{l}"] = p_over(tot1, l)
    for l in (1.5, 2.5):
        P[f"pt_menos_{l}"] = 1 - p_over(tot1, l)
    # Hándicap (margen de goles) a partir de la matriz del marcador
    P["hcap_loc_g2"] = S(lambda i, j: i - j >= 2)
    P["hcap_loc_g3"] = S(lambda i, j: i - j >= 3)
    P["hcap_loc_m1"] = S(lambda i, j: i - j >= -1)
    P["hcap_vis_g2"] = S(lambda i, j: j - i >= 2)
    P["hcap_vis_g3"] = S(lambda i, j: j - i >= 3)
    P["hcap_vis_m1"] = S(lambda i, j: j - i >= -1)
    return dict(probs=P, lh=lh, la=la, xc=xc, xt=xt, p1=p1, px=px, p2=p2, xg=h.usa_xg or a.usa_xg, n=(h.n, a.n))


def evaluar(clave: str, hg, ag, hc=None, ac=None):
    """True/False si la jugada salió o no; None si falta el dato (por ejemplo corners)."""
    m = re.match(r"(goles|corners|local_goles|visita_goles|local_corners|visita_corners)_(mas|menos)_([\d.]+)$", clave)
    if m:
        que, lado, l = m.group(1), m.group(2), float(m.group(3))
        if "corners" in que and (hc is None or ac is None):
            return None
        base = {"goles": hg + ag, "local_goles": hg, "visita_goles": ag,
                "corners": (hc or 0) + (ac or 0), "local_corners": hc, "visita_corners": ac}[que]
        return base > l if lado == "mas" else base < l
    m = re.match(r"combo_(local|empate|visita)_(mas|menos)_([\d.]+)$", clave)
    if m:
        res = {"local": hg > ag, "empate": hg == ag, "visita": hg < ag}[m.group(1)]
        l = float(m.group(3))
        return res and ((hg + ag > l) if m.group(2) == "mas" else (hg + ag < l))
    m = re.match(r"tbtts_(mas|menos)_(si|no)_([\d.]+)$", clave)
    if m:
        l = float(m.group(3))
        return ((hg + ag > l) == (m.group(1) == "mas")) and ((hg > 0 and ag > 0) == (m.group(2) == "si"))
    t = hg + ag
    return {"btts_si": hg > 0 and ag > 0, "btts_no": not (hg > 0 and ag > 0), "dc_1x": hg >= ag, "dc_x2": ag >= hg,
            "dc_12": hg != ag, "gana_local": hg > ag, "gana_visita": ag > hg, "empate": hg == ag,
            "local_porteria_si": ag == 0, "local_porteria_no": ag > 0, "visita_porteria_si": hg == 0, "visita_porteria_no": hg > 0,
            "hcap_loc_g2": hg - ag >= 2, "hcap_loc_g3": hg - ag >= 3, "hcap_loc_m1": hg - ag >= -1,
            "hcap_vis_g2": ag - hg >= 2, "hcap_vis_g3": ag - hg >= 3, "hcap_vis_m1": ag - hg >= -1,
            "rango_0-1": t <= 1, "rango_2-3": 2 <= t <= 3, "rango_4-5": 4 <= t <= 5, "rango_6+": t >= 6}.get(clave)


# Claves que NO se ofrecen como jugada (Super Match no tiene ese mercado o ya está con otro nombre)
NO_OFRECIDAS = {"dc_1x", "dc_x2", "dc_12", "empate"}


def etiqueta(clave: str, HN: str, AN: str) -> tuple[str, str, str]:
    """(categoría, jugada tal como figura en Super Match 'Mercado → Opción', pestaña de Super Match)"""
    def num(l):
        return l.rstrip("0").rstrip(".") if "." in l and l.endswith("0") else l

    m = re.match(r"(goles|corners|local_goles|visita_goles|local_corners|visita_corners)_(mas|menos)_([\d.]+)$", clave)
    if m:
        que, lado, l = m.group(1), m.group(2), num(m.group(3))
        op = f"{'Más' if lado == 'mas' else 'Menos'} De {l}"
        eq = HN if que.startswith("local") else AN if que.startswith("visita") else None
        if "corners" in que:
            grupo = f"Total córneres {eq} ( {l} )" if eq else f"Total córneres ( {l} )"
            return "Corners", f"{grupo} → {op}", "Goles"
        if eq and l == "0.5":   # tickets viejos
            return "Goles", f"{eq} anota al menos 1 gol", "Goles"
        grupo = f"{eq} total ( {l} )" if eq else f"Total ( {l} )"
        return "Goles", f"{grupo} → {op}", "Goles"
    m = re.match(r"combo_(local|empate|visita)_(mas|menos)_([\d.]+)$", clave)
    if m:
        res, lado, l = m.group(1), m.group(2), num(m.group(3))
        op = f"{'Más' if lado == 'mas' else 'Menos'} De {l}"
        quien = {"local": f"{HN} Y", "empate": "Empate Y", "visita": f"{AN} &"}[res]
        return "Resultado", f"1x2 y total ( {l} ) → {quien} {op}", "Goles"
    m = re.match(r"tbtts_(mas|menos)_(si|no)_([\d.]+)$", clave)
    if m:
        l = num(m.group(3))
        op = f"{'Más' if m.group(1) == 'mas' else 'Menos'} De {l} Y {'Sí' if m.group(2) == 'si' else 'No'}"
        return "Goles", f"Total y ambos equipos marcan ( {l} ) → {op}", "Goles"
    m = re.match(r"tarjetas_(mas|menos)_([\d.]+)$", clave)
    if m:
        l = num(m.group(2))
        op = f"{'Más' if m.group(1) == 'mas' else 'Menos'} De {l}"
        return "Tarjetas", f"Total tarjetas ( {l} ) → {op}", "Tarjetas/Corners"
    m = re.match(r"pt_(mas|menos)_([\d.]+)$", clave)
    if m:
        l = num(m.group(2))
        op = f"{'Más' if m.group(1) == 'mas' else 'Menos'} De {l}"
        return "Goles", f"1º Mitad - total ( {l} ) → {op}", "1ª mitad/ 2ª mitad"
    if clave.startswith("rango_"):
        return "Goles", f"Rango de goles → {clave[6:]}", "Otro"
    return {
        "btts_si": ("Goles", "Ambos equipos marcan → Sí", "Otro"),
        "btts_no": ("Goles", "Ambos equipos marcan → No", "Otro"),
        "hcap_loc_g2": ("Hándicap", f"Hándicap ( 0:1 ) → {HN}", "Hándicap"),
        "hcap_loc_g3": ("Hándicap", f"Hándicap ( 0:2 ) → {HN}", "Hándicap"),
        "hcap_loc_m1": ("Hándicap", f"Hándicap ( 2:0 ) → {HN}", "Hándicap"),
        "hcap_vis_g2": ("Hándicap", f"Hándicap ( 1:0 ) → {AN}", "Hándicap"),
        "hcap_vis_g3": ("Hándicap", f"Hándicap ( 2:0 ) → {AN}", "Hándicap"),
        "hcap_vis_m1": ("Hándicap", f"Hándicap ( 0:2 ) → {AN}", "Hándicap"),
        "local_porteria_si": ("Goles", f"{HN} Portería a cero → Sí", "Otro"),
        "local_porteria_no": ("Goles", f"{HN} Portería a cero → No", "Otro"),
        "visita_porteria_si": ("Goles", f"{AN} Portería a cero → Sí", "Otro"),
        "visita_porteria_no": ("Goles", f"{AN} Portería a cero → No", "Otro"),
        "gana_local": ("Resultado", f"1x2 → Gana {HN}", "Mas Jugado"),
        "gana_visita": ("Resultado", f"1x2 → Gana {AN}", "Mas Jugado"),
        "empate": ("Resultado", "1x2 → Empate", "Mas Jugado"),
        "dc_1x": ("Resultado", f"Doble oportunidad: {HN} o empate", "Mas Jugado"),
        "dc_x2": ("Resultado", f"Doble oportunidad: {AN} o empate", "Mas Jugado"),
        "dc_12": ("Resultado", "Doble oportunidad: no hay empate", "Mas Jugado"),
    }[clave]


# =========================================================================== cuotas del mercado (otras casas)
def probs_mercado(odds: dict) -> dict:
    """Pasa cuotas promedio del mercado a probabilidades (sacando el margen de la casa)."""
    out = {}
    if all(k in odds for k in ("H", "D", "A")):
        inv = [1 / odds["H"], 1 / odds["D"], 1 / odds["A"]]
        s = sum(inv)
        p1, px, p2 = (x / s for x in inv)
        out.update(gana_local=p1, empate=px, gana_visita=p2, dc_1x=p1 + px, dc_x2=p2 + px, dc_12=p1 + p2)
    if "O25" in odds and "U25" in odds:
        o, u = 1 / odds["O25"], 1 / odds["U25"]
        out["goles_mas_2.5"], out["goles_menos_2.5"] = o / (o + u), u / (o + u)
    return out


# clave del motor -> cuota promedio del mercado (fixtures.csv de football-data)
CLAVE_MERCADO = {"gana_local": "H", "gana_visita": "A", "empate": "D", "goles_mas_2.5": "O25", "goles_menos_2.5": "U25"}


def buscar_mercado(fd: FootballData, home_fd: str | None, away_fd: str | None, dia: str) -> dict:
    """Mercado de football-data (ligas europeas) como {clave: {'prob':.., 'cuota':..}}."""
    if not home_fd or not away_fd:
        return {}
    d = datetime.fromisoformat(dia)
    for m in fd.proximos:
        if m["home"] == home_fd and m["away"] == away_fd and abs((m["date"] - d).days) <= 1:
            probs, odds = probs_mercado(m["odds"]), m["odds"]
            out = {}
            for clave, p in probs.items():
                out[clave] = {"prob": p, "cuota": odds.get(CLAVE_MERCADO.get(clave, ""))}
            return out
    return {}


def unir_mercados(*fuentes: dict) -> dict:
    """Combina mercados {clave:{prob,cuota}}. La primera fuente que tenga una clave manda (va primero la que más casas tiene)."""
    out: dict = {}
    for f in fuentes:
        for clave, d in (f or {}).items():
            if clave not in out and d.get("prob") is not None:
                out[clave] = d
    return out


# =========================================================================== análisis del día
@dataclass
class Match:
    id: int
    liga: str
    hora: str
    dia: str
    pais: str
    home: str
    away: str
    home_id: int
    away_id: int
    league_id: int = 0
    home_fd: str | None = None
    away_fd: str | None = None


@dataclass
class Resultado:
    fecha: str
    demo: bool
    resumen: list[dict] = field(default_factory=list)
    candidatos: list[dict] = field(default_factory=list)
    tickets: list[dict] = field(default_factory=list)
    sin_datos: list[str] = field(default_factory=list)
    api: ApiInfo = field(default_factory=ApiInfo)
    total_dia: int = 0
    nuevos_guardados: int = 0
    avisos: list[str] = field(default_factory=list)
    odds_api: dict = field(default_factory=dict)


def _candidato(res, m, clave, prob, p_mod, p_mer, cuota_mer):
    HN, AN = sm_name(m.home), sm_name(m.away)
    if prob <= 0.01 or clave in NO_OFRECIDAS:
        return
    cat, txt, pestana = etiqueta(clave, HN, AN)
    aviso = None
    if p_mod is not None and p_mer is not None and abs(p_mod - p_mer) >= 0.10:
        aviso = f"El modelo dice {p_mod * 100:.0f}% y el mercado {p_mer * 100:.0f}%: tomalo con cuidado"
    res.candidatos.append(dict(
        sel_id=f"{m.id}|{clave}", match_id=m.id, clave=clave, dia=m.dia, partido=f"{HN} vs {AN}", buscar=HN,
        liga=m.liga, hora=m.hora, categoria=cat, mercado=txt, pestana=pestana, linea_unica=cat in ("Corners", "Tarjetas", "Hándicap"),
        prob=prob, prob_modelo=p_mod, prob_mercado=p_mer, cuota_mercado=cuota_mer,
        cuota=1 / prob, aviso=aviso, home_fd=m.home_fd, away_fd=m.away_fd, home_id=m.home_id, away_id=m.away_id))


def analizar_partido(m: Match, h_rows, a_rows, fuente: str, mercado: dict, cfg: dict, res: Resultado):
    min_n = int(cfg["minPartidosConDatos"])
    base = dict(match=m, fuente=fuente)
    sin_stats = h_rows is None or a_rows is None or len(h_rows) < min_n or len(a_rows) < min_n
    if sin_stats:
        # Sin historial, pero con cuotas de muchas casas: igual se puede buscar valor comparando con Super Match.
        if mercado:
            for clave, d in mercado.items():
                if d.get("prob"):
                    _candidato(res, m, clave, d["prob"], None, d["prob"], d.get("cuota"))
            p1 = (mercado.get("gana_local") or {}).get("prob", 0.0)
            px = (mercado.get("empate") or {}).get("prob", 0.0)
            p2 = (mercado.get("gana_visita") or {}).get("prob", 0.0)
            res.resumen.append(dict(base, ok=True, fuente="mercado", lh=None, la=None, xc=None, p1=p1, px=px, p2=p2,
                                    n=(0, 0), nota="solo con cuotas del mercado (sin historial)"))
        elif h_rows is None or a_rows is None:
            falta = [n for n, r in ((m.home, h_rows), (m.away, a_rows)) if r is None]
            res.resumen.append(dict(base, ok=False, nota="Sin historial de: " + ", ".join(falta)))
        else:
            res.resumen.append(dict(base, ok=False, nota="Pocos partidos recientes con datos"))
        return
    mo = modelo(h_rows, a_rows, cfg)
    wm = float(cfg.get("pesoMercado", 0.5))
    for clave, p_mod in mo["probs"].items():
        d_mer = mercado.get(clave) or {}
        p_mer = d_mer.get("prob")
        prob = p_mod if p_mer is None else (1 - wm) * p_mod + wm * p_mer
        _candidato(res, m, clave, prob, p_mod, p_mer, d_mer.get("cuota"))
    nota = []
    if fuente == "propio":
        nota.append("historial propio (solo goles)")
    elif mo["xc"] is None:
        nota.append("sin datos de corners (solo goles)")
    if mo["xg"]:
        nota.append("con xG")
    if mercado:
        nota.append("comparado con el mercado")
    res.resumen.append(dict(base, ok=True, lh=mo["lh"], la=mo["la"], xc=mo["xc"], p1=mo["p1"], px=mo["px"], p2=mo["p2"],
                            n=mo["n"], nota=" · ".join(nota)))


def pool(res: Resultado, cats: set[str], cfg: dict) -> list[dict]:
    # los córners no entran en tickets automáticos: Super Match ofrece una sola línea y casi nunca coincide
    ok = [c for c in res.candidatos if c["categoria"] in cats and c["prob"] >= float(cfg["probMinima"])
          and c["cuota"] >= float(cfg["cuotaMinimaPorSeleccion"]) and not c["aviso"] and not c.get("linea_unica")]
    best: dict[int, dict] = {}
    for c in ok:
        if c["match_id"] not in best or c["prob"] > best[c["match_id"]]["prob"]:
            best[c["match_id"]] = c
    return sorted(best.values(), key=lambda c: c["prob"], reverse=True)


def armar_ticket(nombre: str, desc: str, cands: list[dict], tcfg: dict) -> dict | None:
    legs, odd = [], 1.0
    for c in cands:
        legs.append(c)
        odd *= c["cuota"]
        if odd >= float(tcfg["cuotaObjetivo"]) or len(legs) >= int(tcfg["maxSelecciones"]):
            break
    if len(legs) < 2:
        return None
    return dict(nombre=nombre, desc=desc, legs=legs, cuota=odd, prob=math.prod(l["prob"] for l in legs))


def demo_data(cfg):
    rnd = random.Random(7)

    def samp(l):
        L, k, p = math.exp(-l), 0, 1.0
        while True:
            k += 1
            p *= rnd.random()
            if p <= L:
                return k - 1

    names = ["Atlético Norte", "Deportivo Sur", "Unión Rivera", "Racing del Valle", "Sportivo Lagos", "Club Puerto Viejo",
             "Estrella Roja FC", "Juventud Alta", "Real Colinas", "Ciudad Nueva", "Defensores Bahía", "Olimpo Central",
             "Talleres del Este", "San Lorenzo Chico", "Huracán del Oeste", "Independiente Lomas"]
    hoy = ahora(cfg)
    rows = {}
    for i, _ in enumerate(names):
        att, de = 0.8 + rnd.random() * 1.2, 0.7 + rnd.random() * 1.1
        catt, cdef = 3.5 + rnd.random() * 3.5, 3.5 + rnd.random() * 3
        rows[i + 1] = [dict(date=hoy - timedelta(days=7 * k), home=k % 2 == 0, gf=samp(att), ga=samp(de), xgf=None, xga=None,
                            cf=samp(catt), ca=samp(cdef), kf=samp(2.0), ka=samp(2.1)) for k in range(10)]
    dia = hoy.date().isoformat()
    matches = [Match(1000 + i, "Liga Demo (ficticia)", f"{14 + i:02d}:00", dia, "Demo", names[2 * i], names[2 * i + 1], 2 * i + 1, 2 * i + 2)
               for i in range(8)]
    return matches, rows


def correr(fecha: str, demo: bool = False, cfg: dict | None = None, forzar: bool = False) -> Resultado:
    cfg = cfg or load_config()
    res = Resultado(fecha=fecha, demo=demo)
    n_hist = int(cfg["partidosHistorial"])
    if demo:
        matches, demo_rows = demo_data(cfg)
        for m in matches:
            analizar_partido(m, demo_rows[m.home_id], demo_rows[m.away_id], "demo", {}, cfg, res)
    else:
        liga_ids = [int(l["id"]) for l in cfg["ligas"]]
        orden = {lid: i for i, lid in enumerate(liga_ids)}
        fd = load_football_data(cfg, forzar)
        import odds_api
        consenso: dict = {}
        matches = []
        store = load_store()
        try:
            dia = fixtures_del_dia(cfg, fecha, res.api, forzar)
            res.total_dia = len(dia)
            # juntar resultados de ayer y hoy en el historial propio (liga uruguaya e historial de apuestas)
            ligas = set(orden)
            res.nuevos_guardados += guardar_terminados(store, dia, ligas)
            h0 = hoy(cfg)
            for d in ((h0 - timedelta(days=1)).isoformat(), h0.isoformat()):
                if d != fecha:
                    try:
                        res.nuevos_guardados += guardar_terminados(store, fixtures_del_dia(cfg, d, res.api), ligas)
                    except (BotError, requests.RequestException):
                        pass
            save_store(store)
            fx = [f for f in dia if int(f["league"]["id"]) in orden and f["fixture"]["status"]["short"] == "NS"]
            fx.sort(key=lambda f: (orden[int(f["league"]["id"])], f["fixture"]["date"]))
            fx = fx[: int(cfg["maxPartidos"])]
            for f in fx:
                dt = datetime.fromisoformat(f["fixture"]["date"])
                matches.append(Match(int(f["fixture"]["id"]), f"{f['league']['name']} ({f['league']['country']})", dt.strftime("%H:%M"),
                          dt.date().isoformat(), f["league"]["country"], f["teams"]["home"]["name"], f["teams"]["away"]["name"],
                          int(f["teams"]["home"]["id"]), int(f["teams"]["away"]["id"]), league_id=int(f["league"]["id"])))
            try:
                consenso, res.odds_api = odds_api.consenso(cfg, matches, forzar)
            except Exception as e:
                res.avisos.append(f"The Odds API no disponible: {e}")
        except (BotError, requests.RequestException) as e:
            # API-Football caído o suspendido: tomo los partidos de The Odds API (no depende de API-Football)
            res.avisos.append("API-Football no está disponible, así que tomo los partidos de The Odds API.")
            partidos, res.odds_api = odds_api.partidos_del_dia(cfg, fecha, forzar)
            res.total_dia = len(partidos)
            for p in partidos[: int(cfg["maxPartidos"])]:
                matches.append(Match(p["id"], p["liga"], p["hora"], p["dia"], p["pais"], p["home"], p["away"],
                                     p["home_id"], p["away_id"], league_id=p.get("league_id", 0)))
                consenso[p["id"]] = p["probs"]
        if consenso:
            guardar_snapshot(consenso, cfg)
        cache_rows: dict[int, tuple] = {}
        for m in matches:
            fuentes = []
            sides = []
            for tid, tname in ((m.home_id, m.home), (m.away_id, m.away)):
                if tid not in cache_rows:
                    name = find_fd_team(tname, m.pais, fd, cfg)
                    if name:
                        cache_rows[tid] = (fd.rows[name][:n_hist], "football-data", name)
                    else:
                        propio = store_rows(store, tid)[:n_hist]
                        if len(propio) >= int(cfg["minPartidosConDatos"]):
                            cache_rows[tid] = (propio, "propio", None)
                        else:
                            cache_rows[tid] = (None, None, None)
                            res.sin_datos.append(tname)
                rows, fuente, name = cache_rows[tid]
                sides.append(rows)
                fuentes.append(fuente)
                if tid == m.home_id:
                    m.home_fd = name
                else:
                    m.away_fd = name
            fuente = "propio" if "propio" in fuentes else "football-data"
            # The Odds API (muchas casas, muchas ligas) tiene prioridad; football-data completa lo que falte
            oc = {k: {"prob": p, "cuota": c} for k, (c, p) in consenso.get(m.id, {}).items()}
            mercado = unir_mercados(oc, buscar_mercado(fd, m.home_fd, m.away_fd, m.dia))
            analizar_partido(m, sides[0], sides[1], fuente, mercado, cfg, res)

    T = cfg["tickets"]
    todas = {"Goles", "Corners", "Resultado"}
    for t in (
        armar_ticket("Combinada de Goles", "Total de goles, goles de un equipo, portería a cero, qué equipo marca",
                     pool(res, {"Goles"}, cfg), T["goles"]),
        armar_ticket("Super Combinada Mixta", "La mejor jugada de cada partido (goles o resultado)", pool(res, todas, cfg), T["mixto"]),
        armar_ticket("Ticket Seguro", "Las 2 jugadas más probables del día", pool(res, todas, cfg), T["seguro"]),
    ):
        if t:
            res.tickets.append(t)
    return res


# =========================================================================== prueba del modelo con partidos pasados
def prueba_modelo(cfg: dict, borde: float = 0.05) -> dict:
    """Recorre los partidos ya jugados: para cada uno calcula el modelo SOLO con partidos anteriores
    y lo compara con lo que pasó y con las cuotas de cierre del mercado."""
    fd = load_football_data(cfg)
    n_hist, min_n = int(cfg["partidosHistorial"]), int(cfg["minPartidosConDatos"])
    hist: dict[str, list[dict]] = {}
    fechas: dict[str, list] = {}
    cal = {}            # clave de jugada -> lista de (prob, salió)
    valor = []          # apuestas simples con valor contra cuotas de cierre
    altas = []          # jugadas "seguras" estilo app (prob >= probMinima) con cuota de cierre
    obs = []            # (prob modelo, prob casa, salió, cuota) para medir cuánto creerle a cada uno
    claves_cal = ["goles_mas_1.5", "goles_mas_2.5", "goles_menos_2.5", "goles_menos_3.5", "btts_si", "btts_no",
                  "dc_1x", "dc_x2", "corners_mas_8.5", "corners_menos_11.5"]
    for m in fd.partidos:
        h, a = m["home"], m["away"]
        hr, ar = hist.get(h, []), hist.get(a, [])
        if len(hr) >= min_n and len(ar) >= min_n and m["hg"] is not None:
            mo = modelo(hr[:n_hist], ar[:n_hist], cfg)
            P = mo["probs"]
            for k in claves_cal:
                if k in P:
                    r = evaluar(k, m["hg"], m["ag"], m["hc"], m["ac"])
                    if r is not None:
                        cal.setdefault(k, []).append((P[k], r))
            odds_map = {"gana_local": "H", "empate": "D", "gana_visita": "A", "goles_mas_2.5": "O25", "goles_menos_2.5": "U25"}
            pmer = probs_mercado(m["odds"])
            for k, ok in odds_map.items():
                o = m["odds"].get(ok)
                if not o or k not in P:
                    continue
                gano = evaluar(k, m["hg"], m["ag"])
                if k in pmer:
                    obs.append((P[k], pmer[k], int(gano), o))
                if P[k] * o - 1 >= borde:
                    valor.append(dict(liga=m["liga"], clave=k, prob=P[k], cuota=o, gano=gano))
                if P[k] >= float(cfg["probMinima"]):
                    altas.append(dict(liga=m["liga"], clave=k, prob=P[k], cuota=o, gano=gano))
        hist.setdefault(h, []).insert(0, team_row(m, True))
        hist.setdefault(a, []).insert(0, team_row(m, False))

    def resumen(apuestas):
        n = len(apuestas)
        if not n:
            return dict(n=0, aciertos=0, roi=0.0, ganancia=0.0)
        g = sum((x["cuota"] - 1) if x["gano"] else -1 for x in apuestas)
        return dict(n=n, aciertos=sum(x["gano"] for x in apuestas) / n, roi=g / n, ganancia=g)

    por_liga = {}
    for x in valor:
        por_liga.setdefault(x["liga"], []).append(x)
    calib = []
    for k, xs in cal.items():
        calib.append(dict(clave=k, n=len(xs), prob_media=avg(p for p, _ in xs), salio=avg(int(r) for _, r in xs),
                          brier=avg((p - r) ** 2 for p, r in xs)))
    tramos = []
    todas = [x for xs in cal.values() for x in xs]
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        xs = [(p, r) for p, r in todas if lo <= p < hi]
        if xs:
            tramos.append(dict(tramo=f"{lo * 100:.0f}–{min(hi, 1) * 100:.0f}%", n=len(xs), prob_media=avg(p for p, _ in xs),
                               salio=avg(int(r) for _, r in xs)))
    pesos = []
    for w in (0.0, 0.25, 0.5, 0.75, 0.9, 1.0):   # w = cuánto se le cree a la casa
        if not obs:
            break
        brier = sum(((1 - w) * pm + w * pc - y) ** 2 for pm, pc, y, o in obs) / len(obs)
        ap = [(y, o) for pm, pc, y, o in obs if ((1 - w) * pm + w * pc) * o - 1 >= borde]
        pesos.append(dict(peso_casa=w, error=brier, apuestas=len(ap),
                          roi=sum((o - 1) if y else -1 for y, o in ap) / len(ap) if ap else None))
    desde = fd.partidos[0]["date"].date().isoformat() if fd.partidos else "-"
    return dict(partidos=len(fd.partidos), desde=desde, valor=resumen(valor), altas=resumen(altas),
                por_liga={k: resumen(v) for k, v in sorted(por_liga.items())}, calibracion=calib, tramos=tramos, borde=borde,
                pesos=pesos, n_obs=len(obs))
