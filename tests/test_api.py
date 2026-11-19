import io
import logging
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from unittest.mock import patch

from fastapi.testclient import TestClient

import api
from schemas import ApproveIn, AskIn
from src.config_grafo import MAX_TURNS_DEFAULT
from src.state import crear_estado


class ApiTests(unittest.TestCase):
    def setUp(self):
        api._estados_por_thread.clear()
        api._locks_por_thread.clear()

    def test_swagger_includes_message_schema(self):
        with TestClient(api.app) as client:
            response = client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("MessageOut", response.json()["components"]["schemas"])

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


if __name__ == "__main__":
    unittest.main()
