![!\[Cabecera\](./assets/cabecera_thebridge.png)](assets/cabecera_thebridge.png)

# Asistente PcComponentes

<p align="left">
<img src="https://img.shields.io/badge/STATUS-EN%20DESARROLLO-green">
</p> 

[![GitHub stars](https://img.shields.io/github/stars/Ameisin?style=for-the-badge&label=Estrellas&logo=github)](https://github.com/Ameisin/PCompAgent)


## Índice
* [Descripción del proyecto](#descripción-del-proyecto)
* [Características de la aplicación](#características-de-la-aplicación)
* [Acceso al proyecto](#acceso-al-proyecto)
* [Tecnologías utilizadas](#tecnologías-utilizadas)
* [Desarrolladores del Proyecto](#desarrolladores-del-proyecto)
* [Conclusión](#conclusión)

## Descripción del proyecto
**PCompAgent** es un asistente para elegir componentes de PC: procesador, tarjeta gráfica, placa base, memoria, almacenamiento, fuente de alimentación, caja y refrigeración. A partir del uso y el presupuesto del usuario propone una configuración con piezas **reales** del catálogo, comprueba compatibilidad (socket, tipo de memoria, formato de placa y caja) y precio, y **no da el plan por cerrado hasta que una persona lo aprueba**.

El proyecto se ha construido en dos fases:

1. **Project Break 1 - RAG**: un sistema RAG completo (Retrieval-Augmented Generation) sobre un corpus propio indexado en ChromaDB. Responde preguntas sobre componentes, compatibilidades, guías de compra y requisitos de videojuegos usando solo ese corpus, y se abstiene si no tiene la información.
2. **Project Break 2 - Agente multiagente**: un agente orquestado con **LangGraph** que usa el RAG anterior como una herramienta (*tool*), junto con una búsqueda en el catálogo, una API externa de divisas, herramientas auxiliares y una herramienta multimodal que lee imágenes. Un supervisor reparte el trabajo entre dos especialistas y el plan final pasa por una **revisión humana (HITL, human-in-the-loop)** antes de cerrarse.

```text
mensaje -> procesar_turno(estado, mensaje, thread_id)
        -> grafo multiagente (MemorySaver)
        -> tools (RAG + catálogo + API + auxiliares + multimodal)
        -> pausa antes de aplicar -> la persona aprueba o rechaza
CLI y Streamlit son clientes del mismo contrato
```

El corpus del RAG combina dos formatos:

- **CSV** con el catálogo de componentes (12 categorías) y un CSV de requisitos mínimos y recomendados de videojuegos. Cada fila se convierte en una frase en lenguaje natural con metadatos (categoría, socket, precio, etc.).
- **Markdown** con guías de compra y montaje (elección de CPU, RAM, placa base, fuente, SSD, refrigeración y una guía de montaje de PC gaming).

Este proyecto es la segunda pieza de un proyecto incremental: RAG (PB1), agente (PB2) y, como siguiente paso, empaquetado, despliegue y monitorización (MLOps).

## Características de la aplicación
### Agente multiagente (LangGraph)

```text
START -> supervisor --+-- requisitos ---+
                      +-- componentes --+--> supervisor -> ...
                      +-- sintetizar ---+
                FINISH --+-- aplicar (pausa: la persona aprueba o rechaza) -> END
                         +-- END (faltan presupuesto o uso: se pregunta al usuario)
```

- **Supervisor**: elige el siguiente paso con el LLM. Si contesta algo que no tiene sentido, decide una regla en Python. Tiene un tope de vueltas (`MAX_ITER`).
- **Especialista `requisitos`**: traduce el pedido a requisitos técnicos y a un reparto del presupuesto. Si hace falta, lee la ficha de una imagen o convierte la moneda.
- **Especialista `componentes`**: busca piezas reales del catálogo y comprueba que sean compatibles entre sí.
- **`sintetizar`**: junta las notas en un plan con viñetas. Python suma los precios y avisa si se pasa del presupuesto.
- **`aplicar` (HITL)**: solo se ejecuta tras la decisión humana. Si se aprueba, la conversación queda cerrada (`done=True`). Si se rechaza, el plan se vacía y el motivo del rechazo se tiene en cuenta en el siguiente turno.
- **Memoria por conversación**: `MemorySaver` con un `thread_id` por conversación, así que el agente recuerda el pedido, los datos que faltaban y los rechazos anteriores.
- **Límites decididos en Python**: `MAX_ITER` (vueltas del supervisor), `max_steps` (llamadas a tools por especialista) y `max_turns` (mensajes por conversación).

### Herramientas del agente
Todas están en una lista de herramientas permitidas (`src/tools/__init__.py`). El LLM propone la llamada, pero el código valida los argumentos y bloquea cualquier herramienta que no esté registrada. Cada llamada queda en la traza con su nombre, argumentos, estado (`ok`, `error` o `blocked`) y un resumen del resultado.

| Categoría | Tool | Qué hace |
|---|---|---|
| RAG completo | `RAG_consultar_catalogo` | Llama a `responder()` del RAG del PB1: respuesta basada en el corpus con sus fuentes, o abstención |
| Catálogo | `buscar_componentes` | Productos reales del CSV por categoría y rango de precio, con sus especificaciones (socket, memoria, formato...) |
| API externa | `convertir_divisa` | [Frankfurter](https://frankfurter.dev) (tipos de cambio del BCE, sin clave). Si no hay red usa `data/divisas_fallback.json` |
| Auxiliares | `calcular_total_build`, `hora_actual` | Suma de la configuración frente al presupuesto, y fecha y hora |
| Multimodal | `describir_imagen` | Gemini lee `assets/imagen_demo.jpg` (ficha técnica de prueba) u otra imagen de la carpeta `assets/` |

### RAG (Project Break 1)
- **Respuestas ancladas al corpus**: el LLM solo utiliza los fragmentos recuperados y cita la fuente de cada dato.
- **Abstención**: ante preguntas fuera de dominio (geografía, productos inexistentes, benchmarks no indexados) el asistente indica que no tiene esa información en lugar de inventar.
- **Compatibilidad entre piezas**: el corpus incluye tablas derivadas (microarquitectura -> socket, socket -> tipo de memoria, tipo de caja -> formatos de placa admitidos) que enriquecen cada fila de componente.
- **Requisitos de videojuegos**: requisitos mínimos y recomendados de más de 2.000 juegos publicados desde 2019.

### Procesamiento de datos
Un área de los datos del corpus ha sido procesada para **favorecer la eficiencia en el consumo de tokens** del modelo LLM. 

Los datos se han obtenido de la **[página web oficial de Intel](https://www.intel.la/content/www/xl/es/gaming/resources/how-to-build-a-gaming-pc.html)**. Se han descargado todas las páginas con contenido relevante para el proyecto en formato **HTML**. Después, se ha desarrollado un script, `convertir_html_a_markdown`, para **convertir todos los archivos en HTML a Markdown**. 

El modelo LLM podría leer el archivo en formato HTML, pero además de leer la información crucial, leería toda la información del estilo visual, la estructura y semántica compleja, multimedia y recursos embebidos, scripts, metadatos y comportamiento. Esa información no es útil, **podría encaminar a errores** y sobre todo, **costar más cantidad de tokens de lectura** de los necesarios. 

### Interfaz Streamlit (`streamlit run app.py`)
- Chat con historial; cada mensaje es un turno del agente.
- Barra lateral con `max_steps`, `max_turns`, el `thread_id` de la conversación y el botón **Nueva conversación** (empieza un hilo nuevo).
- **HITL**: cuando hay un plan pendiente, el chat se bloquea y aparecen los botones **Aprobar** y **Rechazar**, con un campo opcional para el motivo del rechazo.
- Panel de depuración con el log del supervisor, la traza de herramientas, la traza por turno, el historial de checkpoints y los indicadores de HITL y `done`.

### CLI del agente (`python -m src.cli`)
| Comando | Descripción |
|---|---|
| `python -m src.cli` | Demo con un pedido de ejemplo; el plan se aprueba automáticamente |
| `python -m src.cli --sin-auto-aprobar` | Demo que se queda en la pausa HITL |
| `python -m src.cli --interactivo` | Chat en la terminal; con un plan pendiente se escribe `aprobar` o `rechazar` |
| `python -m src.cli --mensaje "pedido"` | Demo con otro pedido |
| `python -m src.cli --max-steps 1 --supervisor-reglas` | Límites más bajos y supervisor sin LLM, para gastar menos cuota |
| `python -m src.verificar_grafo` | Comprobaciones del grafo, el HITL y las herramientas sin llamar a la API |

### CLI del RAG (`python main.py`)
| Comando | Descripción |
|---|---|
| `python main.py --prepare` | Carga, limpia, fragmenta y vectoriza el corpus (`output/embeddings.json`) |
| `python main.py --index [--recreate-index]` | Indexa los embeddings en ChromaDB; con `--recreate-index` regenera la colección desde cero |
| `python main.py --query "pregunta" [--top-k N]` | Solo retrieval: muestra los fragmentos recuperados y su contexto |
| `python main.py --ask "pregunta" [--top-k N]` | RAG completo: respuesta del LLM con fuentes y métricas |
| `python main.py --eval` | Barrido de varios valores de K sobre las preguntas de evaluación |

### Configuración centralizada
- **`config.py`** (RAG): rutas, categorías de CSV, filtros del corpus, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MAX_CHUNKS`, proveedor y modelo de embeddings, `TOP_K`, modelo y temperatura de generación. Algunos pueden sobrescribirse por variable de entorno (`EMBEDDING_PROVIDER`, `MAX_CHUNKS`, `MAX_FILAS_POR_CSV`, `ESTRATEGIA_CHUNKING`).
- **`src/config_grafo.py`** (agente): modelo del agente, límites (`MAX_ITER`, `MAX_STEPS_DEFAULT`, `MAX_TURNS_DEFAULT`), ritmo de llamadas a la API y rutas de las herramientas. Variables de entorno opcionales: `AGENTE_GEMINI_MODEL`, `AGENTE_RAG_MODEL`, `AGENTE_LLM_RPM`, `AGENTE_SUPERVISOR_LLM`.

> ⚠️ Si cambias el modelo de embeddings, `CHUNK_SIZE` o `MAX_CHUNKS`, regenera el índice con `python main.py --index --recreate-index`.

## Acceso al proyecto
### Requisitos

- **Python 3.10 o superior** (el proyecto se ha desarrollado con Python 3.14).
- **Git** para clonar el repositorio.
- **Clave de API de Gemini** (Google AI Studio). Es la única clave necesaria: la usan el RAG, el agente y la herramienta multimodal. Puedes obtenerla en https://aistudio.google.com/apikey.
- Conexión a internet para llamar a la API de Gemini y a la API de divisas (esta última tiene respaldo local si no hay red).
- Opcional: si prefieres embeddings locales sin API, instala `sentence-transformers` y usa `EMBEDDING_PROVIDER=huggingface` (requiere varios GB de dependencias).

### Entorno virtual

1. Clona el repositorio:

   ```bash
   git clone https://github.com/Ameisin/PCompAgent.git
   cd PCompAgent
   ```

2. Crea y activa el entorno virtual.

   Windows (PowerShell):
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

   Linux / macOS:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Instala las dependencias (incluyen LangGraph y `langchain-google-genai`):

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Configura la clave de API. Copia la plantilla y edita el fichero `.env` con tu clave:

   ```bash
   cp .env.example .env
   ```

   Contenido de `.env`:
   ```
   GEMINI_API_KEY=tu_clave_aqui
   ```

   > El fichero `.env` está en `.gitignore` y nunca debe subirse al repositorio.

5. El índice de ChromaDB ya viene en el repositorio. Si quieres regenerarlo (tarda unos minutos porque vectoriza todo el corpus):

   ```bash
   python main.py --prepare
   python main.py --index --recreate-index
   ```

6. Comprueba que todo está bien sin gastar API:

   ```bash
   python -m src.verificar_grafo
   ```

7. Abre el agente en la terminal o en la interfaz:

   ```bash
   python -m src.cli --interactivo
   streamlit run app.py
   ```

   El RAG del PB1 se puede seguir usando por separado: `python main.py --ask "¿Qué socket usa un procesador Ryzen 7 7700X?"`.

### Cómo probar el HITL y la parte multimodal

- **HITL**: en `python -m src.cli --interactivo` o en Streamlit, escribe *"Ya tengo un Ryzen con socket AM4, ¿qué placa base y RAM me recomiendas por menos de 150 USD?"*. Cuando salga el plan, recházalo con el motivo *"como mucho 120 USD"*, pide *"Ajústalo a ese límite"* y apruébalo. La conversación termina con `done=True`.
- **Multimodal**: *"Mira la ficha técnica de la imagen y dime qué placa base y RAM compatibles me recomiendas por menos de 150 USD"*. En la traza aparece `describir_imagen`.
- **Datos que faltan**: *"Quiero armar una PC, ¿qué me recomiendas?"*. El agente pide presupuesto y uso antes de proponer nada.
- **Fuera de dominio**: *"¿Cuál es la capital de Francia?"*. El agente explica para qué sirve y no inventa.

> Con la capa gratuita de Gemini un turno completo tarda 2-3 minutos, porque las llamadas se espacian para no superar el límite de peticiones por minuto.

### Estructura del proyecto

```
PCompAgent/
├── README.md
├── requirements.txt
├── .env.example                 # plantilla de variables de entorno
├── .gitignore
├── config.py                    # configuración centralizada del RAG
├── main.py                      # CLI del RAG: prepare / index / query / ask / eval
├── app.py                       # interfaz Streamlit del agente (chat + HITL + depuración)
│
├── load.py                      # carga del corpus (CSV -> frases, Markdown/PDF -> Document)
├── clean.py                     # normalización de texto
├── chunk.py                     # fragmentación (Markdown por encabezados, CSV atómico)
├── embed.py                     # embeddings Gemini / Hugging Face + caché
├── index.py                     # indexación en ChromaDB
├── retrieve.py                  # retrieval top-k
├── context.py                   # formateo del contexto recuperado
├── prompt.py                    # plantilla del prompt RAG
├── generate_rep.py              # llamada al LLM (Gemini)
├── logic.py                     # API interna del RAG: responder(pregunta) -> dict
├── eval_retrival.py             # evaluación de retrieval con varios K
├── gemini_auto.py               # carga de la API key
├── verificar.py                 # comprobaciones automáticas del RAG
├── convertir_html_a_markdown.py # utilidad para añadir guías al corpus
│
├── src/                         # agente multiagente (PB2)
│   ├── config_grafo.py          # modelo, límites y rutas del agente
│   ├── llm.py                   # cliente Gemini (LangChain) + limitador de peticiones
│   ├── state.py                 # estado que ven la CLI y Streamlit
│   ├── graph.py                 # StateGraph: supervisor, especialistas, sintetizar, aplicar (HITL)
│   ├── agent.py                 # procesar_turno / aprobar_plan / run_demo
│   ├── guardrails.py            # reglas en Python: presupuesto, datos que faltan, suma de precios
│   ├── registro_tools.py        # punto por el que el grafo obtiene las tools
│   ├── cli.py                   # CLI del agente: demo / interactivo / HITL
│   ├── verificar_grafo.py       # comprobaciones sin API
│   ├── README_GRAFO.md          # detalle técnico del grafo
│   └── tools/
│       ├── __init__.py          # allowlist + validar_args + ejecutar_tool
│       ├── rag_catalogo.py      # tool -> RAG completo del PB1
│       ├── catalogo.py          # búsqueda por categoría y precio en los CSV
│       ├── divisas.py           # API externa (Frankfurter) + fallback
│       ├── auxiliares.py        # total de la configuración y hora actual
│       └── describir_imagen.py  # multimodal (imagen -> texto)
├── tools/
│   ├── tools.py                 # funciones de catálogo y presupuesto que usan las tools del agente
│   └── agent_rag_tools.py       # prototipo inicial (no se usa en el agente final)
│
├── data/
│   ├── csv/                     # catálogo de componentes + requisitos de videojuegos
│   ├── md/                      # guías de compra y montaje en Markdown
│   └── divisas_fallback.json    # tipos de cambio de respaldo para la API de divisas
├── assets/
│   ├── cabecera_thebridge.png
│   └── imagen_demo.jpg          # ficha técnica de prueba para la tool multimodal
├── queries/
│   └── preguntas_eval.json      # set de preguntas de evaluación
├── entregables/
│   ├── generacion_reflex.md     # reflexión del PB1
│   └── informe_decisiones.md    # informe del PB2: grafo, tools, HITL, multimodal y fallos
├── output/                      # embeddings.json (se regenera con --prepare)
└── chroma/                      # índice ChromaDB persistente (se regenera con --index)
```

### Fuentes del corpus

| Fuente | Formato | Contenido | Enlace |
|---|---|---|---|
| Dataset de componentes de PC (PCPartPicker) | CSV | 12 categorías de componentes con precio y especificaciones | [PCPartPicker](https://www.kaggle.com/datasets/baraazaid/pc-video-game-requirements-v2) |
| Dataset de requisitos de videojuegos | CSV | Requisitos mínimos y recomendados por juego | [Kaggle](https://www.kaggle.com/datasets/baraazaid/pc-video-game-requirements-v2) |
| Guías de compra y montaje | Markdown | 7 guías (CPU, RAM, placa base, fuente, SSD, refrigeración, montaje) | [Intel](https://www.intel.la/content/www/xl/es/gaming/resources/how-to-build-a-gaming-pc.html) |
| Tipos de cambio | API JSON | Conversión de moneda (tipos del Banco Central Europeo) | [Frankfurter](https://frankfurter.dev) |

Todos los datos son públicos y se utilizan con fines educativos. La imagen de `assets/imagen_demo.jpg` es una ficha técnica creada para el proyecto. No hay claves en el repositorio.

### Preguntas de ejemplo

- Quiero un PC gaming para jugar a 1080p con 60 fps estables, presupuesto de 700 USD.
- Ya tengo un Ryzen con socket AM4, ¿qué placa base y RAM me recomiendas por menos de 150 USD?
- Mira la ficha técnica de la imagen y dime qué placa base y RAM compatibles me recomiendas.
- Tengo 600 euros para un PC de oficina, ¿qué me recomiendas?
- ¿Qué requisitos recomendados tiene Cyberpunk 2077?
- ¿Cuál es la capital de Francia? *(fuera de corpus: el asistente debe abstenerse)*

## Tecnologías utilizadas

| Área | Tecnología | Uso en el proyecto |
|---|---|---|
| Lenguaje | **Python 3.10+** | Todo el pipeline, el agente y la interfaz |
| Agente | **LangGraph** | Grafo multiagente, `MemorySaver` (memoria por `thread_id`) e `interrupt_before` (HITL) |
| LLM del agente | **LangChain** (`langchain-google-genai`) · modelo `gemini-3.1-flash-lite` | Supervisor, especialistas, tools con `@tool` y `bind_tools` |
| Carga de documentos | **LangChain** (`langchain-core`, `langchain-community`) | `Document`, `TextLoader`, `PyPDFLoader` |
| Chunking | **langchain-text-splitters** | `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter` |
| Datos tabulares | **pandas** | Lectura y filtrado de los CSV del catálogo |
| PDF | **pypdf** | Extracción de texto de guías en PDF |
| Embeddings | **Google GenAI SDK** (`google-genai`) · modelo `gemini-embedding-001` | Vectorización de chunks y consultas (768 dimensiones) |
| Embeddings alternativos | **sentence-transformers** (opcional) | Embeddings locales sin API |
| Base vectorial | **ChromaDB** | Índice persistente con distancia coseno y metadatos |
| Generación del RAG | **Gemini** (`gemini-3-flash-preview`) | Redacción de la respuesta anclada al contexto en `main.py --ask` |
| Multimodal | **Google GenAI SDK** | Lectura de imágenes en la tool `describir_imagen` |
| API externa | **Frankfurter** + `requests` | Conversión de moneda con respaldo local |
| Interfaz | **Streamlit** | Chat del agente, botones HITL y depuración |
| Configuración | **python-dotenv** | Carga de la API key desde `.env` |
| Utilidades | **BeautifulSoup4** | Conversión de guías HTML a Markdown para ampliar el corpus |
| Control de versiones | **Git + GitHub** | Ramas `main` / `develop` / `feature/*` / `fix/*` y pull requests |

## Desarrolladores del proyecto
 - Mario Bac Díaz (github: Ameisin)
 - Javier (github: TermiJP)
 - Jaime Pérez (github: JaimePVillanueva)

## Conclusión

PCompAgent ha pasado de ser un RAG que responde preguntas sueltas a un agente que monta configuraciones completas. El RAG del PB1 sigue siendo la base del conocimiento, pero ahora es una herramienta más dentro de un grafo multiagente: un supervisor reparte el trabajo, los especialistas consultan el catálogo, la API de divisas y las imágenes, y una persona aprueba o rechaza el plan antes de cerrarlo. La CLI y la interfaz Streamlit usan el mismo contrato (`procesar_turno` y `aprobar_plan`), sin duplicar lógica.

### Qué hemos aprendido

- **El corpus manda.** La mayor parte del esfuerzo del RAG no estuvo en el LLM sino en preparar los datos: convertir filas de CSV en frases con sentido, enriquecerlas con conocimiento derivado (socket, tipo de memoria, formatos de placa) y elegir una estrategia de chunking distinta para tablas y para guías. Un retrieval mediocre no se arregla con un prompt mejor.
- **El modelo propone, Python decide.** Los límites (`MAX_ITER`, `max_steps`, `max_turns`), la lista de herramientas permitidas, la suma del presupuesto y el cierre del plan los decide el código, no el LLM. Así el agente no se queda en bucle ni da por buena una configuración que nadie ha revisado.
- **El HITL necesita memoria.** Sin un checkpointer no hay dónde guardar la pausa; con `MemorySaver` y un `thread_id` por conversación, un rechazo con motivo sirve para que el siguiente plan sea mejor.
- **Abstenerse es una funcionalidad, no un fallo.** Un asistente que reconoce que no tiene la información, o que pregunta por el presupuesto antes de recomendar, es más útil y más fiable que uno que responde siempre.
- **Integrar pronto.** Trabajar cada bloque en su rama funciona si se acuerda antes el formato de las piezas (por ejemplo, cómo se declaran las tools) y se prueba todo junto a menudo, no solo al final.

### Limitaciones actuales

- Los precios y el catálogo son una foto fija del dataset y no reflejan el mercado actual.
- El índice vectorial incluido en el repositorio no contiene todas las categorías del catálogo. Los precios de las piezas se obtienen con `buscar_componentes` directamente de los CSV, y el índice se puede regenerar con `python main.py --prepare` y `python main.py --index --recreate-index`.
- La compatibilidad la razona el LLM con los datos del catálogo; no hay una comprobación estructurada en Python, así que el plan puede no avisar de detalles como usar un solo módulo de RAM.
- La memoria del agente vive en RAM: si se reinicia el proceso se pierden las conversaciones y los planes pendientes.
- Con la capa gratuita de Gemini la cuota es limitada y cada turno tarda unos minutos.

---