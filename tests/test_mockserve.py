"""가짜 API 서버 시험. 실제로 띄워서 부른다."""

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.code import mockserve, openapi

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "주문 API", "version": "1.0"},
    "components": {"schemas": {"주문": {"type": "object", "properties": {
        "id": {"type": "integer", "example": 7},
        "상태": {"type": "string", "enum": ["대기"]}}}}},
    "paths": {
        "/orders": {
            "get": {"responses": {"200": {"content": {"application/json": {
                "schema": {"type": "array",
                           "items": {"$ref": "#/components/schemas/주문"}}}}}}},
            "post": {"responses": {"201": {"content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/주문"}}}}}}},
        "/orders/new": {"get": {"responses": {"200": {"content": {
            "application/json": {"schema": {"type": "object", "properties": {
                "새것": {"type": "boolean"}}}}}}}}},
        "/orders/{id}": {
            "get": {"parameters": [{"name": "id", "in": "path",
                                    "required": True,
                                    "schema": {"type": "integer"}}],
                    "responses": {"200": {"content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/주문"}}}}}},
            "delete": {"responses": {"204": {}}}},
    },
}


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.routes = mockserve.make_routes(openapi.load(SPEC))

    def test_static_path_wins_over_a_parameter(self):
        # /orders/new 가 /orders/{id} 에 먹히면 그 경로는 영영 못 부른다
        route = mockserve.match(self.routes, "GET", "/orders/new")
        self.assertEqual(route.path, "/orders/new")

    def test_parameter_matches_anything(self):
        route = mockserve.match(self.routes, "GET", "/orders/12345")
        self.assertEqual(route.path, "/orders/{id}")

    def test_method_matters(self):
        self.assertEqual(mockserve.match(self.routes, "POST", "/orders").status,
                         201)
        self.assertIsNone(mockserve.match(self.routes, "PUT", "/orders"))

    def test_query_string_is_ignored(self):
        route = mockserve.match(self.routes, "GET", "/orders?page=2")
        self.assertEqual(route.path, "/orders")

    def test_no_body_schema_is_kept_as_none(self):
        route = mockserve.match(self.routes, "DELETE", "/orders/1")
        self.assertEqual(route.status, 204)
        self.assertIsNone(route.body)


class ServeTest(unittest.TestCase):
    def setUp(self):
        self.log = mockserve.Log()
        self.server = mockserve.make_server(
            mockserve.make_routes(openapi.load(SPEC)), port=0, cors=True,
            log=self.log)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def get(self, path: str, method: str = "GET"):
        request = urllib.request.Request(self.base + path, method=method,
                                         data=b"{}" if method == "POST" else None)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()

    def test_answers_with_the_example(self):
        status, headers, body = self.get("/orders")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [{"id": 7, "상태": "대기"}])
        self.assertEqual(headers["X-Mock"], "attools")   # 진짜가 아니라는 표시
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_path_parameter(self):
        status, _headers, body = self.get("/orders/99")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["id"], 7)

    def test_created_status_is_kept(self):
        status, _headers, _body = self.get("/orders", method="POST")
        self.assertEqual(status, 201)

    def test_unknown_path_says_so_in_korean(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nope")
        self.assertEqual(ctx.exception.code, 404)
        self.assertIn("문서에 없는 경로", ctx.exception.read().decode("utf-8"))

    def test_requests_are_recorded(self):
        self.get("/orders")
        self.get("/orders/1")
        self.assertEqual([(h.method, h.status) for h in self.log.hits],
                         [("GET", 200), ("GET", 200)])


if __name__ == "__main__":
    unittest.main()
