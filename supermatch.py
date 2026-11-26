"""Lee el texto copiado de la página de un partido en Super Match (Ctrl+A, Ctrl+C) y saca las cuotas.

No se conecta a Super Match: solo interpreta el texto que vos pegás en la app.
Devuelve {clave_del_motor: (cuota, prob_de_la_casa)}, donde prob_de_la_casa es lo que opina Super Match
(la cuota convertida en probabilidad, sacando su margen).
"""
from __future__ import annotations

import re

from engine import name_score, name_tokens

HEADER = re.compile(
    r"\(\s*[\d.]+\s*\)\s*$|^1x2$|Porter[ií]a a cero$|^Qu[ée] equipo marca$|^Rango de goles$|marca en ambas partes$|"
    r"par/impar$|^Margen de victoria$|Goles exactos$|^1\.?º gol$|^C[óo]rner|^Expulsi[óo]n$|^Tarjeta 1x2$|^Cu[áa]ndo", re.I)
NUM = re.compile(r"^\d+(?:[.,]\d+)?$")
MITAD = re.compile(r"^\d\s*\.?\s*º\s*(mitad|Mitad)", re.I)
MASMENOS = re.compile(r"^(M[áa]s|Menos) De ([\d.]+)$", re.I)


def leer_grupos(texto: str) -> list[tuple[str, str, float]]:
    """[(mercado, opción, cuota)] tal como aparecen en la página."""
    out, grupo, label = [], None, []
    for raw in texto.splitlines():
        s = raw.strip()
        if not s or s.lower() == "dividendo":
            continue
        if NUM.match(s):
            if grupo and label:
                v = float(s.replace(",", "."))
                if v > 1:
                    out.append((grupo, " ".join(label), v))
            label = []
            continue
        if HEADER.search(s):
            grupo, label = s, []
            continue
        label = (label + [s])[-4:]
    return out


def _lado(nombre: str, HN: str, AN: str) -> str | None:
    t = name_tokens(nombre)
    a, b = name_score(t, name_tokens(HN), True), name_score(t, name_tokens(AN), True)
    if max(a, b) < 0.5 or a == b:
        return None
    return "local" if a > b else "visita"


def _l(x: str) -> str:
    return str(float(x))


def a_clave(grupo: str, op: str, HN: str, AN: str) -> str | None:
    """Traduce 'Mercado → Opción' de Super Match a la clave que usa el motor."""
    g, op = grupo.strip(), op.strip()
    if MITAD.match(g):
        return None
    mm = MASMENOS.match(op)
    lado_op = None if not mm else ("mas" if mm.group(1).lower().startswith("m") and "enos" not in mm.group(1).lower() else "menos")
    m = re.match(r"^Total\s*\(\s*([\d.]+)\s*\)$", g)
    if m and mm:
        return f"goles_{lado_op}_{_l(mm.group(2))}"
    m = re.match(r"^Total c[óo]rneres\s*\(\s*([\d.]+)\s*\)$", g, re.I)
    if m and mm:
        return f"corners_{lado_op}_{_l(mm.group(2))}"
    m = re.match(r"^Total c[óo]rneres (.+?)\s*\(\s*([\d.]+)\s*\)$", g, re.I)
    if m and mm:
        lado = _lado(m.group(1), HN, AN)
        return f"{lado}_corners_{lado_op}_{_l(mm.group(2))}" if lado else None
    m = re.match(r"^1x2 y total\s*\(\s*([\d.]+)\s*\)$", g, re.I)
    if m:
        o = re.match(r"^(.+?)\s*(?:\bY\b|&)\s*(M[áa]s|Menos) De ([\d.]+)$", op, re.I)
        if not o:
            return None
        quien = "empate" if o.group(1).lower().startswith("empate") else _lado(o.group(1), HN, AN)
        lo = "menos" if o.group(2).lower().startswith("menos") else "mas"
        return f"combo_{quien}_{lo}_{_l(o.group(3))}" if quien else None
    m = re.match(r"^Total y ambos equipos marcan\s*\(\s*([\d.]+)\s*\)$", g, re.I)
    if m:
        o = re.match(r"^(M[áa]s|Menos) De ([\d.]+) Y (S[íi]|No)$", op, re.I)
        if not o:
            return None
        lo = "menos" if o.group(1).lower().startswith("menos") else "mas"
        return f"tbtts_{lo}_{'no' if o.group(3).lower() == 'no' else 'si'}_{_l(o.group(2))}"
    m = re.match(r"^(.+?) total\s*\(\s*([\d.]+)\s*\)$", g, re.I)
    if m and mm:
        lado = _lado(m.group(1), HN, AN)
        return f"{lado}_goles_{lado_op}_{_l(mm.group(2))}" if lado else None
    m = re.match(r"^(.+?) Porter[ií]a a cero$", g, re.I)
    if m:
        lado = _lado(m.group(1), HN, AN)
        return f"{lado}_porteria_{'no' if op.lower() == 'no' else 'si'}" if lado else None
    if re.match(r"^Qu[ée] equipo marca$", g, re.I) and op.lower().startswith("ambos"):
        return "btts_si"
    if re.match(r"^Rango de goles$", g, re.I):
        return f"rango_{op}"
    if g.lower() == "1x2":
        if op.lower().startswith("empate"):
            return "empate"
        lado = _lado(re.sub(r"^Gana\s+", "", op, flags=re.I), HN, AN)
        return f"gana_{lado}" if lado else None
    return None


def leer_partido(texto: str, HN: str, AN: str) -> dict[str, tuple[float, float]]:
    """{clave: (cuota, probabilidad según Super Match)} para un partido."""
    grupos = leer_grupos(texto)
    # probabilidad de la casa: dentro de cada mercado, 1/cuota normalizado (saca el margen)
    por_grupo: dict[str, list[tuple[str, float]]] = {}
    for g, op, v in grupos:
        por_grupo.setdefault(g, [])
        if op not in [o for o, _ in por_grupo[g]]:
            por_grupo[g].append((op, v))
    out = {}
    for g, ops in por_grupo.items():
        s = sum(1 / v for _, v in ops)
        for op, v in ops:
            clave = a_clave(g, op, HN, AN)
            if clave and len(ops) >= 2:
                out[clave] = (v, (1 / v) / s)
    return out
