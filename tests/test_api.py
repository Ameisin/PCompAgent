import io
import logging
import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from unittest.mock import patch

from fastapi.testclient import TestClient

import api
from schemas import ApproveIn, AskIn
from src import graph
from src.agent import nuevo_thread_id
from src.config_grafo import MAX_TURNS_DEFAULT
from src.state import crear_estado
from src.verificar_grafo import _LLMFalso


class ApiTests(unittest.TestCase):
    def setUp(self):
        api._estados_por_thread.clear()
        api._locks_por_thread.clear()

    def test_swagger_includes_message_schema(self):
        with TestClient(api.app) as client:
            response = client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("MessageOut", response.json()["components"]["schemas"])

    def test_invalid_text_is_rejected(self):
        with patch.dict(os.environ, {"API_KEY": "test-key"}):
            with TestClient(api.app) as client:
                for body in (
                    {"pregunta": "   "},
                    {"pregunta": "consulta", "thread_id": " "},
                    {"pregunta": "consulta", "thread_id": "x" * 129},
                ):
                    response = client.post("/ask", params={"api_key": "test-key"}, json=body)
                    self.assertEqual(response.status_code, 422)
                response = client.post(
                    "/approve", params={"api_key": "test-key"},
                    json={"thread_id": " ", "aprobado": True},
                )
                self.assertEqual(response.status_code, 422)

    def test_decisions_require_boolean_values(self):
        with patch.dict(os.environ, {"API_KEY": "test-key"}):
            with patch.object(api, "procesar_turno", return_value=crear_estado()):
                with TestClient(api.app) as client:
                    for value in ("true", "false", 1, 0):
                        with self.subTest(value=value):
                            response = client.post(
                                "/ask", params={"api_key": "test-key"},
                                json={"pregunta": "consulta", "auto_aprobar": value},
                            )
                            self.assertEqual(response.status_code, 422)
                            response = client.post(
                                "/approve", params={"api_key": "test-key"},
                                json={"thread_id": "hilo", "aprobado": value},
                            )
                            self.assertEqual(response.status_code, 422)

    def test_api_key_is_required_and_must_be_configured(self):
        with TestClient(api.app) as client:
            with patch.dict(os.environ, {"API_KEY": ""}):
                response = client.post("/ask", json={"pregunta": "consulta"})
                self.assertEqual(response.status_code, 503)
            with patch.dict(os.environ, {"API_KEY": "test-key"}):
                for params in ({}, {"api_key": "incorrecta"}):
                    response = client.post("/ask", params=params, json={"pregunta": "consulta"})
                    self.assertEqual(response.status_code, 401)

    def test_unknown_approval_does_not_create_state_or_keep_lock(self):
        response = api.approve(ApproveIn(thread_id="desconocido", aprobado=True))
        self.assertIn("No hay un plan pendiente", response.respuesta)
        self.assertNotIn("desconocido", api._estados_por_thread)
        self.assertNotIn("desconocido", api._locks_por_thread)

    def test_lock_is_released_after_exception(self):
        with patch.object(api, "procesar_turno", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                api.ask(AskIn(pregunta="consulta", thread_id="hilo"))
        self.assertNotIn("hilo", api._locks_por_thread)

    def test_generated_id_uses_full_uuid(self):
        self.assertRegex(nuevo_thread_id(), r"^pc-[0-9a-f]{32}$")

    def test_access_log_omits_query(self):
        logger = logging.getLogger("uvicorn.access")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        old_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            logger.info(
                '%s - "%s %s HTTP/%s" %d',
                "127.0.0.1",
                "POST",
                "/ask?api_key=secreto&other=valor",
                "1.1",
                200,
            )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
        self.assertIn("/ask HTTP/1.1", stream.getvalue())
        self.assertNotIn("secreto", stream.getvalue())
        self.assertNotIn("other", stream.getvalue())

    def test_ask_applies_turn_limit_and_auto_approves(self):
        estado = crear_estado("consulta")
        estado.update(respuesta="Plan", pendiente_hitl=True)
        aprobado = dict(estado, respuesta="Aprobado", pendiente_hitl=False, done=True)
        with patch.object(api, "procesar_turno", return_value=estado) as procesar:
            with patch.object(api, "aprobar_plan", return_value=aprobado) as aprobar:
                with patch.dict(os.environ, {"API_KEY": "test-key"}):
                    with TestClient(api.app) as client:
                        response = client.post(
                            "/ask",
                            params={"api_key": "test-key"},
                            json={"pregunta": "consulta", "thread_id": "hilo"},
                        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["done"])
        self.assertEqual(procesar.call_args.kwargs["max_turns"], MAX_TURNS_DEFAULT)
        aprobar.assert_called_once_with("hilo", True, estado)

    def test_limit_rejects_next_turn_without_invoking_graph(self):
        estado = crear_estado("consulta")
        estado["traza"] = [{"mensaje": "consulta"} for _ in range(MAX_TURNS_DEFAULT)]
        api._estados_por_thread["hilo"] = estado
        with patch("src.agent.hay_interrupt") as hay_interrupt:
            response = api.ask(AskIn(pregunta="otra consulta", thread_id="hilo"))
        self.assertIn("max_turns", response.respuesta)
        hay_interrupt.assert_not_called()

    def test_turn_limit_counts_user_messages_starting_with_hitl(self):
        estado = crear_estado("consulta")
        estado["traza"] = [
            {"mensaje": "HITL:rechazar", "status": "ok"}
            for _ in range(MAX_TURNS_DEFAULT - 1)
        ]
        estado["traza"].append({"mensaje": "HITL:rechazar", "comentario": ""})
        api._estados_por_thread["hilo"] = estado
        with patch("src.agent.hay_interrupt", return_value=True) as hay_interrupt:
            response = api.ask(AskIn(pregunta="consulta", thread_id="hilo"))
        self.assertIn("pendiente", response.respuesta)
        hay_interrupt.assert_called_once()

        estado["traza"].append({"mensaje": "HITL:aprobar", "status": "ok"})
        with patch("src.agent.hay_interrupt") as hay_interrupt:
            response = api.ask(AskIn(pregunta="otra consulta", thread_id="hilo"))
        self.assertIn("max_turns", response.respuesta)
        hay_interrupt.assert_not_called()

    def test_approve_waits_for_ask_on_same_thread(self):
        ask_started = threading.Event()
        release_ask = threading.Event()
        approve_started = threading.Event()

        def procesar(estado, mensaje, thread_id, max_turns):
            ask_started.set()
            if not release_ask.wait(5):
                raise TimeoutError("El test no liberó el turno")
            return dict(estado, respuesta="Plan", pendiente_hitl=True)

        def aprobar(thread_id, aprobado, estado):
            return dict(estado, respuesta="Aprobado", pendiente_hitl=False, done=aprobado)

        def solicitar_aprobacion():
            approve_started.set()
            return api.approve(ApproveIn(thread_id="hilo", aprobado=True))

        with patch.object(api, "procesar_turno", side_effect=procesar):
            with patch.object(api, "aprobar_plan", side_effect=aprobar) as mock_approve:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    turno = executor.submit(
                        api.ask, AskIn(pregunta="consulta", thread_id="hilo", auto_aprobar=False)
                    )
                    try:
                        self.assertTrue(ask_started.wait(5))
                        decision = executor.submit(solicitar_aprobacion)
                        self.assertTrue(approve_started.wait(5))
                        with self.assertRaises(FutureTimeoutError):
                            decision.result(timeout=0.2)
                    finally:
                        release_ask.set()
                    self.assertTrue(turno.result(timeout=5).pendiente_hitl)
                    self.assertTrue(decision.result(timeout=5).done)
                    mock_approve.assert_called_once()
                    self.assertNotIn("hilo", api._locks_por_thread)

    def test_different_threads_can_run_concurrently(self):
        first_started = threading.Event()
        release_first = threading.Event()

        def procesar(estado, mensaje, thread_id, max_turns):
            if thread_id == "primero":
                first_started.set()
                if not release_first.wait(5):
                    raise TimeoutError("El test no liberó el turno")
            return dict(estado, respuesta=thread_id)

        with patch.object(api, "procesar_turno", side_effect=procesar):
            with ThreadPoolExecutor(max_workers=2) as executor:
                primero = executor.submit(api.ask, AskIn(pregunta="uno", thread_id="primero"))
                try:
                    self.assertTrue(first_started.wait(5))
                    segundo = executor.submit(api.ask, AskIn(pregunta="dos", thread_id="segundo"))
                    self.assertEqual(segundo.result(timeout=2).respuesta, "segundo")
                finally:
                    release_first.set()
                self.assertEqual(primero.result(timeout=5).respuesta, "primero")

    def test_graph_is_built_once_for_simultaneous_threads(self):
        barrier = threading.Barrier(2)
        built = object()

        def build():
            time.sleep(0.1)
            return built

        def get_app():
            barrier.wait(timeout=5)
            return graph.get_app()

        with patch.object(graph, "_APP", None), patch.object(graph, "build_graph", side_effect=build) as builder:
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(get_app)
                second = executor.submit(get_app)
                self.assertIs(first.result(timeout=5), built)
                self.assertIs(second.result(timeout=5), built)
            builder.assert_called_once_with()

    def test_http_hitl_with_real_graph_and_simulated_llm(self):
        with patch.dict(os.environ, {"API_KEY": "test-key"}):
            with patch.object(graph, "_APP", None):
                with patch.object(graph, "get_llm", return_value=_LLMFalso()):
                    with patch.object(api.config_grafo, "SUPERVISOR_USA_LLM", True):
                        with TestClient(api.app) as client:
                            for approved in (False, True):
                                response = client.post(
                                    "/ask", params={"api_key": "test-key"},
                                    json={
                                        "pregunta": "PC gaming para 1080p con presupuesto de $700",
                                        "auto_aprobar": False,
                                    },
                                )
                                self.assertEqual(response.status_code, 200)
                                result = response.json()
                                self.assertIsNone(result["error"])
                                self.assertTrue(result["pendiente_hitl"])
                                decision = client.post(
                                    "/approve", params={"api_key": "test-key"},
                                    json={"thread_id": result["thread_id"], "aprobado": approved},
                                )
                                self.assertEqual(decision.status_code, 200)
                                self.assertFalse(decision.json()["pendiente_hitl"])
                                self.assertEqual(decision.json()["done"], approved)
                                self.assertIsNone(decision.json()["error"])


if __name__ == "__main__":
    unittest.main()
