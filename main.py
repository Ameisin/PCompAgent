import index as ind
import load as ld
import clean as cln
import chunk as ck
import embed as emb

import sys
from streamlit.web import cli as stcli

if __name__ == "__main__":

    print("Cargando documentos del corpus…")
    loaded_corpus = ld.cargar_documentos()
    print(f"Documentos cargados: {len(loaded_corpus)}")

    print("Limpiando los documentos cargados…")
    cleaned_corpus = cln.limpiar_documentos(loaded_corpus)
    print(f"Documentos tras limpieza: {len(cleaned_corpus)}")

    print("Fragmentando los documentos en chunks…")
    chunks = ck.fragmentar_documentos(cleaned_corpus)
    print(f"Chunks generados: {len(chunks)}")

    print("Cargando embeddings desde cache (si existe)…")
    embeddings = emb.cargar_embeddings_cache(chunks)
    
    if embeddings == None:
        print("Generando embeddings para los chunks…")
        textos_chunks = [chunk.page_content for chunk in chunks]
        embeddings = emb.embed_documentos(textos_chunks)

    print(f"Embeddings totales: {len(embeddings)}")

    print("Guardando chunks y embeddings en JSON…")
    emb.guardar_embeddings_json(chunks, embeddings)

    print("Ejecutando indexación…")
    print("  (si ya indexaste antes, borra la colección con --recreate-index)")
    total_index = ind.ejecutar_indexacion()
    print(f"Indexación completada. Total de documentos en la colección: {total_index}")

    # Inyecta la ruta del script actual y el comando 'run'
    sys.argv = ["streamlit", "run", "app.py"]
    sys.exit(stcli.main())


