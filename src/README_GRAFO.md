# Grafo multiagente, HITL y persistencia (`src/`)

Parte del Project Break 2 desarrollada en la rama `feature/grafo-hitl`: orquestación con **LangGraph** (supervisor + especialistas + sintetizar + aplicar), **human-in-the-loop** antes de cerrar el plan y **persistencia** por `thread_id` con `MemorySaver`.

El RAG del PB1 (`logic.responder`) no se modifica: el agente lo **invoca como tool**.

```text
mensaje → procesar_turno(estado, mensaje, thread_id)        ← src/agent.py
       → grafo multiagente (MemorySaver)                     ← src/graph.py
       → tools (allowlist)                                   ← src/registro_tools.py
       → interrupt_before[aplicar] → humano aprueba / rechaza
CLI (src/cli.py) / Streamlit = clientes (mismo thread_id)
```

---

## El grafo

```text
START → supervisor ──┬── requisitos ───┐
                     ├── componentes ──┼──► supervisor → …
                     └── sintetizar ───┘
                               │
                FINISH ──┬── aplicar (interrupt_before → decisión humana) → END
                         └── END  (faltan datos: se pregunta al usuario, sin HITL)
```

| Nodo | Oficio | Escribe | Tools |
|------|--------|---------|-------|
| `supervisor` | Elige el siguiente rol (LLM, temperatura 0). Si la respuesta no vale, decide Python (`_fallback_siguiente` + `_eleccion_valida`). Tope `MAX_ITER`. | `siguiente`, `iteracion`, `log` | — |
| `requisitos` | Python extrae presupuesto/uso. Si faltan datos, deja una pregunta y el turno acaba. Si no, traduce el pedido a requisitos técnicos y a un reparto del presupuesto. | `preferencias`, `faltan_datos`, `notas_requisitos` | Sí (mini-bucle, `max_steps`) |
| `componentes` | Elige piezas concretas del catálogo, una consulta por categoría, y comprueba la compatibilidad (socket, DDR, formato, fuente). | `notas_componentes` | Sí (mini-bucle, `max_steps`) |
| `sintetizar` | Une las notas en `respuesta` + `plan` (viñetas). Python suma los precios y avisa si se pasa del presupuesto. | `respuesta`, `plan`, `resumen_presupuesto` | — |
| `aplicar` | Solo tras la decisión humana. Si se aprueba, `done=True`. Si se rechaza, resetea el plan y guarda el motivo en el historial del hilo. | `done`, `respuesta`, `historial` | — |

**Por qué estos especialistas.** Separan los dos oficios que el PB1 no sabía hacer a la vez:

1. Entender *qué necesita* el usuario (rendimiento, requisitos de juegos, reparto del presupuesto).
2. Encontrar *qué piezas reales* del catálogo lo cumplen y si son compatibles.

Cada uno tiene su propio prompt y usa el RAG para cosas distintas.

**Por qué el HITL va antes de `aplicar`.** El plan es una recomendación de compra con precios. Ninguna configuración se da por cerrada (`done`) sin que una persona la apruebe, y la aprueba viendo la suma real de precios calculada por Python.

---

## Ficheros

| Fichero | Responsabilidad |
|---------|-----------------|
| `config_grafo.py` | Modelo, límites (`MAX_ITER`, `MAX_STEPS_DEFAULT`, `MAX_TURNS_DEFAULT`), ritmo de llamadas, demo |
| `llm.py` | Factory `ChatGoogleGenerativeAI` + limitador de peticiones por minuto |
| `state.py` | Estado de producto (lo que ven la CLI y Streamlit) |
| `graph.py` | `EstadoGrafo`, nodos, router, `build_graph` (`MemorySaver` + `interrupt_before`) |
| `agent.py` | `procesar_turno`, `aprobar_plan`, `nuevo_thread_id`, `historial_checkpoints`, `run_demo` |
| `guardrails.py` | Reglas deterministas: preferencias, datos que faltan, suma del presupuesto |
| `registro_tools.py` | Punto único de tools: `src/tools/` del equipo o, si no existe, las provisionales |
| `tools_provisionales.py` | `RAG_consultar_catalogo` (envuelve `logic.responder`) + `hora_actual` |
| `cli.py` | Cliente CLI: demo / interactivo / HITL |
| `verificar_grafo.py` | 12 comprobaciones sin API (LLM simulado) |
| `requirements_grafo.txt` | Dependencias adicionales (LangGraph, langchain-google-genai) |
| `JUSTIFICACION_CODIGO_PROPIO.md` | Qué código no viene de los apuntes y por qué |

---

## Instalación

Desde la raíz del proyecto, con el índice del RAG ya construido (`python main.py --prepare` y `python main.py --index`):

```bash
python -m pip install -r requirements.txt -r src/requirements_grafo.txt
```

La clave `GEMINI_API_KEY` se lee del mismo `.env` que usa el RAG.

## Ejecución (siempre desde la raíz)

```bash
python -m src.verificar_grafo
```

Son 12 comprobaciones sin llamar a la API. Ejecútalas antes que nada.

```bash
python -m src.cli
```

Demo: pedido de `config_grafo.DEMO_MENSAJES` con el HITL auto-aprobado.

```bash
python -m src.cli --sin-auto-aprobar
```

La demo se queda en la pausa HITL (`pendiente_hitl=True`, `done=False`).

```bash
python -m src.cli --interactivo
```

Chat. Con un plan pendiente, escribe `aprobar` o `rechazar`; al rechazar se pide un motivo opcional.

```bash
python -m src.cli --mensaje "PC para oficina, presupuesto de 400 USD"
```

Demo con otro pedido.

```bash
python -m src.cli --max-steps 1 --supervisor-reglas
```

Límites más bajos y supervisor sin LLM, para ahorrar cuota.

### Variables de entorno (opcionales)

| Variable | Por defecto | Efecto |
|----------|-------------|--------|
| `AGENTE_GEMINI_MODEL` | `gemini-3.1-flash-lite` | Modelo de los nodos del agente |
| `AGENTE_RAG_MODEL` | el del agente | Modelo con el que genera la tool RAG (`responder(..., modelo=...)`). El del PB1 (`gemini-3-flash-preview`) solo admite 20 peticiones/día en la capa gratuita |
| `AGENTE_LLM_RPM` | `10` | Peticiones/min máximas del modelo del agente (las comparte la tool RAG si usa el mismo modelo) |
| `AGENTE_RAG_RPM` | `4` | Peticiones/min de la tool RAG cuando usa **otro** modelo (`gemini-3-flash`: 5/min; se deja margen) |
| `AGENTE_SUPERVISOR_LLM` | `1` | `0` = supervisor solo con reglas Python |

---

## Contrato para los clientes (Streamlit)

La UI **no** contiene lógica del grafo: solo llama a estas funciones y pinta el estado.

```python
from src.agent import aprobar_plan, historial_checkpoints, nuevo_thread_id, procesar_turno
from src.state import crear_estado

# Al iniciar / «Nueva conversación»
st.session_state.agent_state = crear_estado("")
st.session_state.thread_id = nuevo_thread_id()        # nuevo hilo en el MemorySaver

# Mensaje del chat
estado = procesar_turno(st.session_state.agent_state, prompt,
                        st.session_state.thread_id, max_steps=..., max_turns=...)

# Botones de la sidebar (solo si estado["pendiente_hitl"])
estado = aprobar_plan(st.session_state.thread_id, True, estado)
estado = aprobar_plan(st.session_state.thread_id, False, estado, comentario="motivo opcional")
```

Campos del estado de producto que usa la UI:

| Campo | Uso |
|-------|-----|
| `respuesta` | Texto del asistente (plan, pregunta aclaratoria, cierre o error amigable) |
| `plan` | Viñetas del plan (para mostrar en la sidebar HITL) |
| `resumen_presupuesto` | `total`, `presupuesto`, `dentro` (True/False/None) |
| `pendiente_hitl` | True → bloquear el chat y mostrar **Aprobar** / **Rechazar** |
| `done` | True → conversación cerrada (plan aprobado) |
| `error` | Mensaje técnico; la UI muestra `respuesta` y no se cae |
| `log`, `traza` | Expander de debug: log del supervisor; por turno, `log` y `tools` (`tool`, `args`, `status`, `preview`) |
| `thread_id` | Mostrar en la sidebar |

`historial_checkpoints(thread_id)` devuelve las fotos del hilo para el debug, sin llamar al modelo. `procesar_turno` ya rechaza mensajes nuevos con un plan pendiente o con la conversación cerrada, así que la UI no tiene que replicar esas reglas.

## Contrato para las tools (`src/tools/`)

Cuando el equipo integre su paquete, el grafo lo detecta solo (`registro_tools.py`). Requisitos, iguales que en clase:

```python
# src/tools/__init__.py
TOOLS = [rag_..., api_..., hora_actual, describir_imagen]   # objetos @tool de LangChain
def ejecutar_tool(nombre: str, args: dict | None = None) -> str:
    ...  # allowlist: "Error: tool '<nombre>' no está permitida." si no está registrada
```

- Los prompts de los especialistas listan las tools a partir de `TOOLS` (nombre + docstring). Un buen docstring es lo que hace que el modelo elija bien la tool.
- La traza clasifica el `status` por el texto devuelto: `blocked` si contiene «no está permitida», `error` si empieza por «Error» y `ok` en el resto de casos. Mantened esos mensajes.
- Cuando exista `src/tools/`, se pueden borrar `tools_provisionales.py` y la rama `except` de `registro_tools.py`.

---

## Límites (decididos en Python)

| Límite | Dónde | Qué corta |
|--------|-------|-----------|
| `MAX_ITER` (8) | `nodo_supervisor` | Vueltas supervisor ↔ especialistas por turno |
| `max_steps` (3) | `_ejecutar_con_tools` | Vueltas modelo ↔ tools dentro de un especialista |
| `max_turns` (6) | `procesar_turno` + CLI | Mensajes de usuario por conversación |
| Allowlist | `ejecutar_tool` | Tools no registradas → `blocked` |
| `done` | `nodo_aplicar` | Solo tras aprobación humana |
| `faltan_datos` | `guardrails` + supervisor | Sin presupuesto/uso no se recomienda un equipo |

## Persistencia

- `MemorySaver` en RAM, dentro del grafo compilado una sola vez por proceso (`get_app`). Si se reinicia el proceso, se pierden los hilos (limitación conocida: el siguiente paso sería `SqliteSaver`).
- Mismo `thread_id` → mismo hilo. El campo `historial` acumula los mensajes y las decisiones HITL, así que un rechazo con motivo o un dato que faltaba mejora el siguiente turno.
- Otro `thread_id` → conversación vacía (lo comprueba `verificar_grafo`).

## Pruebas realizadas

| Prueba | Resultado |
|--------|-----------|
| `python -m src.verificar_grafo` (LLM simulado) | 13/13 `[OK]` |
| Tool RAG aislada, in-corpus («placa base AM4 por menos de 100 USD») | 4 placas reales con precio y fuente (`motherboard.csv`) |
| Tool RAG aislada, fuera de corpus («¿capital de Francia?») | Se abstiene: «El contexto proporcionado no contiene información…» |
| Demo CLI con HITL auto-aprobado | `supervisor → requisitos → componentes → sintetizar → FINISH → aplicar`, `done=True` |
| Pedido → **rechazo** con motivo («como mucho 550 USD») → nuevo turno → **aprobación** | El segundo plan respeta el límite del motivo; `done=True`; el historial de checkpoints muestra la pausa ante `aplicar` |
| CLI `--interactivo`: pedido ambiguo → datos → rechazar con motivo → ajustar → aprobar | Pregunta aclaratoria sin plan ni HITL (1 llamada al LLM); el segundo plan usa el presupuesto del motivo; `done=True` |
| Demo «placa base y RAM para un Ryzen AM4 por menos de 150 USD» | ASRock B550M-HDV (89,99) + T-Force Vulcan Z DDR4 (38,99): compatibles; Python suma 128,98 ≤ 150; el supervisor quiso repetir `sintetizar` y Python lo cerró con `FINISH` |

**Cuota diaria.** En la capa gratuita, `gemini-3-flash` (el modelo del PB1) solo admite **20 peticiones al día**. Las pruebas la agotaron, y por eso la tool RAG genera ahora, por defecto, con el modelo del agente (`AGENTE_RAG_MODEL`). Ante un límite diario no se reintenta: la tool devuelve el error y la traza lo muestra como `error`.

**Hallazgo para el equipo del RAG.** El índice de Chroma actual (3.902 chunks) solo contiene `cpu`, `placa_base`, `ram`, `caja` y `videojuego`. No contiene gráficas, fuentes, almacenamiento ni refrigeración, y tampoco las guías Markdown, aunque `config.CATEGORIAS_CSV` sí las incluye. Por eso el agente las marca como «pendiente (sin dato en el catálogo)»: se abstiene en vez de inventar, que es el comportamiento correcto. Para planes completos hay que regenerar el índice (`python main.py --prepare` y `python main.py --index --recreate-index`).

## Limitaciones conocidas

- **Cuota gratuita.** Un turno completo hace unas 10-20 peticiones y tarda de 2 a 4 minutos, porque el limitador las espacia para no recibir un 429. Con `--supervisor-reglas` se ahorran unas 4 por turno.
- **Compatibilidad en un solo paso.** El modelo lite suele pedir todas las consultas del catálogo en la misma respuesta, sin encadenar socket → placa → RAM. En una prueba propuso RAM DDR5 para una placa AM4. `sintetizar` lo detectó y lo dijo en el plan, pero no hay una comprobación estructurada en Python. Es candidato a especialista o tool de compatibilidad en la siguiente iteración.
- **Plan sin datos.** Si todas las consultas al RAG fallan (cuota agotada), el plan sale con todas las piezas «pendiente» y aun así llega al HITL. La persona ve el problema y puede rechazar.
- **Calidad del plan.** Depende del RAG: si la búsqueda de una categoría no devuelve productos, el plan la marca como «sin dato en el catálogo» en lugar de inventarla.
- **Preferencias por palabras clave.** Un pedido redactado de forma muy distinta puede pasar desapercibido; en ese caso el agente pregunta, no inventa.
