# App de tickets para Super Match

La app analiza estadísticas y **arma** combinadas. No apuesta: vos cargás las jugadas en Super Match, ponés la plata y apretás "Apostar".

## En el celular

La app está adaptada para teléfono: las jugadas se apilan, la casilla de cuota es grande y fácil de tocar, y las pestañas se deslizan al costado. Para usarla en el celular tenés dos caminos:
- **En tu casa (gratis):** la app corre en la PC y la abrís desde el celular en el mismo Wi-Fi.
- **Desde cualquier lado:** publicándola (ver GUIA_IPHONE.md). Igual funciona en Android, no solo iPhone.

En el celular, el menú de **Opciones** (banca, fecha) se abre con el botón **»** arriba a la izquierda.

## Cómo abrirla

Doble clic en **`armar-tickets.bat`** (carpeta "1" del Escritorio). Se abre en el navegador (http://localhost:8501).
No cierres la ventana negra mientras la uses.

## Pestañas

| Pestaña | Para qué |
|---|---|
| 🎟️ Tickets | Las combinadas del día (Goles, Mixta y Seguro), de 2–3 jugadas, solo con mercados que existen en Super Match |
| 🧩 Armá tu ticket | Todas las jugadas. Escribís la cuota de Super Match en la tabla, ordenás por **valor** y marcás las que quieras |
| 📊 Partidos | Goles y corners esperados de cada partido y de dónde salen los datos |
| 📒 Mi historial | Tus apuestas anotadas: ganancia/pérdida, rendimiento y si la app acierta |
| 🧪 Prueba del modelo | Cómo le habría ido al modelo con los partidos ya jugados |
| ❓ Cómo usarla | Ayuda |

## Más casas para comparar (The Odds API) — opcional pero recomendado

Para detectar valor real en **muchas más ligas** (Champions, Europa League, Libertadores, Argentina, Brasil, Uruguay, etc.), la app puede comparar con las cuotas de **decenas de casas** usando The Odds API:

1. Sacá una API key gratis en https://the-odds-api.com (plan free: 500 consultas/mes).
2. Pegala en `.streamlit\secrets.toml`, en `ODDS_API_KEY`.

Sin esta key, la app sigue funcionando, pero el "💰 Real" solo se calcula en las ligas europeas de football-data. Con la key, se extiende a casi todas tus ligas. Las ligas y regiones se configuran en `oddsApi` dentro de `config.json`.

## Ligas sin historial (uruguaya y más)

Con The Odds API activa, la app analiza partidos **aunque no tengan estadísticas históricas** (liga uruguaya, muchas sudamericanas): compara Super Match directo contra las casas grandes. Esos partidos aparecen con "goles esperados: –" y la nota "solo con cuotas del mercado". Es la forma de buscar valor donde antes no se podía.

## Movimiento de cuotas y CLV automático

Cada vez que abrís la app, guarda cómo están las cuotas del mercado. En **📋 Pegar cuotas** → "📉 Cómo se movieron las cuotas" ves si una jugada subió o bajó (si baja, las casas le dan más probabilidad: ahí va la plata inteligente). Y tu **CLV se calcula solo**, sin que tengas que volver a pegar nada, comparando la cuota que tomaste con la del cierre del mercado.

## Aviso diario por Telegram (opcional)

Para que cada día te llegue al celular los partidos del día y cómo salieron tus apuestas, configurá Telegram (instrucciones completas en `aviso.py`):
1. Creá un bot con @BotFather en Telegram → te da un TOKEN.
2. Conseguí tu CHAT_ID (ver aviso.py).
3. Pegá ambos en `.streamlit\secrets.toml` (TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID).
4. Programá `aviso.py` para que corra cada día, o probalo con el botón de la app.

## Veredicto del día

Arriba de todo, la app te dice en una línea si hoy conviene apostar:
- **✅ Hay valor real:** aparecen jugadas donde Super Match paga más que otras casas. Jugá poco y solo esas.
- **🤚 No hay valor:** lo más rentable es no apostar.
- **📋 Pegá cuotas:** todavía no cargaste nada, así que no se puede saber.

## Gráfico de tu banca

En **📒 Mi historial**, cuando tengas 2 o más tickets resueltos, ves un gráfico de tu ganancia acumulada en el tiempo. Es la foto honesta de si el plan funciona.

## ¿Por qué? de cada jugada

Debajo de cada jugada aparece una línea con los goles y córners esperados, el 1/X/2 y si usa xG, para que entiendas de dónde sale la recomendación.

## 📋 Pegar cuotas (lo más útil)

En vez de escribir las cuotas una por una:
1. En Super Match entrá al partido, abrí la pestaña **Goles**, tocá en la página, **Ctrl+A** y **Ctrl+C**. Repetí con **Otro** y **Mas Jugado** si querés.
2. En la app, pestaña **📋 Pegar cuotas**: elegí el partido, pegá el texto (Ctrl+V) y tocá **📥 Leer cuotas**.
3. La app lee todas las cuotas, calcula el valor de cada jugada y, en **⭐ Mejores jugadas del día**, junta las que convienen de todos los partidos que pegaste. **🧩 Armar ese ticket** te arma uno con la mejor de cada partido.

La app no se conecta a Super Match: solo lee el texto que vos pegás.

### Cómo decide si una jugada conviene
La prueba con más de 18.000 casos de partidos pasados mostró que **las casas predicen mejor que el modelo**. Por eso la probabilidad que usa la app es:
1. La de las **casas grandes**, si el partido es de una liga europea (es la más precisa).
2. Si no, **80% Super Match + 20% modelo** (cuando pegaste las cuotas).
3. Si no hay cuotas, el modelo solo.

En las mejores jugadas vas a ver dos tipos de valor:
- **💰 Real**: Super Match paga más que el promedio de las casas grandes. Es el único valor que se sostiene a la larga.
- **🔮 Modelo**: solo lo dice el modelo. En la prueba con partidos pasados, este tipo de apuesta **perdió plata**.

### 📈 CLV (¿le ganás a la cuota de cierre?)
Después de apostar, **volvé a pegar las cuotas del partido un rato antes de que empiece**. La app compara la cuota que tomaste con la del cierre. En **Mi historial** ves el CLV promedio: si se mantiene positivo después de 30 o más jugadas, estás tomando mejores cuotas que el mercado final, que es la mejor señal de que la estrategia funciona.

## Mercados de Super Match que usa la app

Cada jugada aparece escrita **igual que en Super Match** ("Mercado → Opción") y con la **pestaña** donde está:

| En la app | Pestaña en Super Match |
|---|---|
| Total ( 2.5 ) → Más De 2.5 / Menos De 2.5 | Goles |
| Brujas total ( 1.5 ) → Más De 1.5 | Goles |
| 1x2 y total ( 2.5 ) → Liverpool & Más De 2.5 | Goles |
| Total y ambos equipos marcan ( 2.5 ) → Más De 2.5 Y Sí | Goles |
| Liverpool Portería a cero → No (= Brujas hace al menos un gol) | Otro |
| Qué equipo marca → Ambos Equipos | Otro |
| Rango de goles → 2-3 | Otro |
| 1x2 → Gana Liverpool | Mas Jugado |
| Total córneres ( 9.5 ) → Más De 9.5 | Goles |

- **Córners:** Super Match ofrece **una sola línea** por partido (y una por equipo). Por eso no entran en los tickets automáticos: en "Armá tu ticket" buscá la línea que coincide con la de Super Match.
- **Doble oportunidad:** Super Match no la ofrece, así que la app no la recomienda.
- **⚠️ Sospechoso:** si la cuota de Super Match da un valor de +20% o más, la app te avisa. Casi siempre significa que el modelo se equivoca, no que encontraste una ganga.

## Uso diario

1. Elegí un ticket (o armá uno propio).
2. **🚀 Cargar en Super Match**: te guía jugada por jugada (copia el equipo, abre Super Match, te dice qué tocar).
3. En cada jugada escribí la **cuota que ves en Super Match**. La app te dice ✅ Conviene / ⚠️ Justo / ❌ Cambiala y el **valor** (+/- %).
4. Apostás en Super Match con el **monto sugerido**.
5. Tocá **📒 Ya lo aposté** para anotarlo. Los resultados se buscan solos (si alguno no aparece, lo marcás a mano en Mi historial).

La cuota que escribís en un lugar se copia sola en todos los tickets que tengan esa jugada.

## Cuidar la plata

- En la barra izquierda cargá tu **banca**: la plata que destinás a apostar (no tus ahorros).
- **Monto sugerido**: sin cuotas, un % fijo de la banca (más chico si el ticket tiene 3 o más jugadas). Con las cuotas cargadas, una fracción (25%) del criterio de Kelly, con un tope del 3% de la banca. Si el ticket no tiene valor, te sugiere no jugarlo.
- **Límite semanal**: si en 7 días perdés el 10% de la banca (contando lo que está en juego), la app te avisa y deja de sugerir montos.

## De dónde salen los números

- **Partidos del día**: API-Football (plan gratis: solo ayer, hoy y mañana).
- **Historial de los equipos**: football-data.co.uk. Usa los últimos 10 partidos, con más peso a los recientes, separando local y visitante, y mezclando goles reales con **goles esperados (xG)** cuando están.
- **Comparación con el mercado**: en las ligas europeas, la app toma las cuotas promedio de otras casas para los próximos partidos y las mezcla 50/50 con el modelo (ganador, doble oportunidad y más/menos 2.5). Si el modelo y el mercado difieren mucho, la jugada aparece con ⚠️ y no entra en los tickets automáticos.
- **Historial propio**: cada vez que abrís la app guarda los resultados de ayer y hoy de todos los partidos. Así se van juntando datos de ligas que football-data no tiene (por ejemplo la **uruguaya**). Cuando un equipo junta 5 partidos guardados, entra en el análisis (solo goles). Conviene abrir la app todos los días.

## Qué dijo la prueba del modelo

Con unos 4.800 partidos ya jugados:
- Las probabilidades se cumplen bastante bien (cuando el modelo dice 70–80%, sale alrededor del 75%).
- **Apostar donde el modelo "le gana" al mercado perdió plata** (cerca de −15%). Cuando el modelo contradice al mercado, el que se equivoca suele ser el modelo. Por eso ahora la app se apoya en el mercado y te avisa con ⚠️.
- Las jugadas "seguras" quedaron casi en cero a cuotas de cierre de casas grandes. En Super Match, que paga algo menos, sería un poco peor.

## Ajustes en `config.json`

- `probMinima`: probabilidad mínima para los tickets automáticos.
- `tickets.*`: cuota objetivo y cantidad máxima de jugadas de cada ticket.
- `pesoMercado` (0.5): cuánto pesan las cuotas del mercado frente al modelo.
- `banca`: % base, fracción de Kelly, tope por ticket y límite semanal.
- `alias`: si un equipo sale "sin historial" porque tiene otro nombre en football-data: `"alias": { "Nombre en API-Football": "Nombre en football-data" }`.
- `nombresSuperMatch`: para mostrar un equipo como lo escribe Super Match: `{ "Napoli": "Nápoles" }`.
- `footballData.temporadaActual`: en agosto de 2027 cambialo a `"2728"` y `temporadaAnterior` a `"2627"`.

## Archivos

- `app.py` (pantallas), `engine.py` (análisis), `historial.py` (tus apuestas), `config.json` (ajustes).
- `data\historial.json`: tus apuestas anotadas. `data\ajustes.json`: tu banca. `data\partidos_api.json`: el historial propio de resultados.
- `bot.ps1`: la versión vieja (reporte HTML), ya no hace falta.

## Aviso

Ningún modelo garantiza ganar: las casas cobran margen en cada jugada y en las combinadas se multiplica. Apostá solo lo que estés dispuesto a perder.
