"""Punto único por el que el grafo obtiene sus tools.

El grafo no conoce las tools concretas: solo el contrato de clase
(lista TOOLS de @tool + ejecutar_tool con allowlist). Así el trabajo del grafo
(feature/grafo-hitl) es independiente del de las tools (feature/tools-rag,
feature/api-externa, feature/multimodal):

  - Si existe src/tools/ (ramas del equipo ya integradas) → se usan esas.
  - Si no                                                → tools provisionales.
"""

try:
    from src.tools import TOOLS, ejecutar_tool  # contrato de clase (src/tools/__init__.py)

    ORIGEN_TOOLS = "src.tools"
except ModuleNotFoundError as e:
    # Solo se cae a las provisionales si el paquete NO existe. Si existe pero
    # falla por dentro (bug en una tool), el error debe verse, no ocultarse.
    if e.name != "src.tools":
        raise
    from src.tools_provisionales import TOOLS, ejecutar_tool

    ORIGEN_TOOLS = "src.tools_provisionales"


def describir_tools() -> str:
    """Lista 'nombre: descripción' para los prompts de los especialistas.

    Se genera a partir de TOOLS, de modo que si el equipo añade o renombra una
    tool los prompts se actualizan solos (no hay nombres fijos en el grafo).
    """
    lineas = []
    for t in TOOLS:
        descripcion = " ".join((t.description or "").split())
        lineas.append(f"- {t.name}: {descripcion}")
    return "\n".join(lineas)


__all__ = ["TOOLS", "ejecutar_tool", "describir_tools", "ORIGEN_TOOLS"]
