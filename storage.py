"""Dónde se guardan tus datos (historial de apuestas, banca, resultados juntados).

- En tu compu: archivos JSON en la carpeta data/.
- En internet (Streamlit Cloud): una base Redis gratis de Upstash, porque el servidor borra sus archivos al reiniciarse.
  Se activa sola cuando están cargados los secretos UPSTASH_REDIS_REST_URL y UPSTASH_REDIS_REST_TOKEN.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PREFIJO = "supermatch:"


def secreto(nombre: str) -> str | None:
    """Lee una clave de las variables de entorno o de los secretos de Streamlit (.streamlit/secrets.toml)."""
    v = os.environ.get(nombre)
    if v:
        return v
    try:
        import streamlit as st
        v = st.secrets.get(nombre)
        return str(v) if v else None
    except Exception:
        return None


def _redis():
    url, token = secreto("UPSTASH_REDIS_REST_URL"), secreto("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return url.rstrip("/"), {"Authorization": f"Bearer {token}"}
    return None


def en_la_nube() -> bool:
    return _redis() is not None


def cargar(nombre: str, defecto):
    r = _redis()
    if r:
        url, h = r
        resp = requests.get(f"{url}/get/{PREFIJO}{nombre}", headers=h, timeout=20)
        resp.raise_for_status()
        val = resp.json().get("result")
        return defecto if val is None else json.loads(val)
    f = DATA / f"{nombre}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return defecto


def guardar(nombre: str, obj):
    texto = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    r = _redis()
    if r:
        url, h = r
        resp = requests.post(f"{url}/set/{PREFIJO}{nombre}", headers=h, data=texto.encode("utf-8"), timeout=20)
        resp.raise_for_status()
        return
    DATA.mkdir(exist_ok=True)
    (DATA / f"{nombre}.json").write_text(texto, encoding="utf-8")
