"""OpenAPI 문서 훑기 시험."""

import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.code import openapi


SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "주문 API", "version": "1.2.0"},
    "servers": [{"url": "https://api.example.com/v1"}],
    "components": {
        "parameters": {"페이지": {"name": "page", "in": "query",
                                  "schema": {"type": "integer"}}},
        "schemas": {"주문": {"type": "object",
                             "properties": {"금액": {"type": "integer"},
                                            "품목": {"type": "array",
                                                     "items": {"type": "string"}}}}},
    },
    "paths": {
        "/orders": {
            "parameters": [{"$ref": "#/components/parameters/페이지"}],
            "get": {"summary": "주문 목록", "tags": ["주문"],
                    "responses": {"200": {}, "400": {}}},
            "post": {"tags": ["주문"], "deprecated": True,
                     "requestBody": {"required": True, "content": {
                         "application/json": {
                             "schema": {"$ref": "#/components/schemas/주문"}}}},
                     "responses": {"201": {}}},
        },
        "/orders/{id}": {"get": {"summary": "주문 하나", "tags": ["주문"],
                                 "parameters": [{"name": "id", "in": "path",
                                                 "required": True,
                                                 "schema": {"type": "string"}}],
                                 "responses": {"200": {}, "404": {}}}},
    },
}


class OpenApiTest(unittest.TestCase):
    def setUp(self):
        self.spec = openapi.load(SPEC)

    def test_reads_title_servers_and_endpoints(self):
        self.assertEqual((self.spec.title, self.spec.version), ("주문 API", "1.2.0"))
        self.assertEqual(self.spec.servers, ["https://api.example.com/v1"])
        self.assertEqual([(e.method, e.path) for e in self.spec.endpoints],
                         [("GET", "/orders"), ("POST", "/orders"),
                          ("GET", "/orders/{id}")])

    def test_path_level_parameters_apply_to_every_method(self):
        got = {(e.method, tuple(p.name for p in e.params)) for e in self.spec.endpoints}
        self.assertIn(("POST", ("page",)), got)      # 경로에 붙은 인자도 센다

    def test_local_refs_are_followed(self):
        post = next(e for e in self.spec.endpoints if e.method == "POST")
        self.assertEqual(post.body_fields, ["금액", "품목"])
        self.assertTrue(post.body_required)
        page = next(p for p in post.params if p.name == "page")
        self.assertEqual(page.type, "integer")

    def test_array_type_is_shown_with_brackets(self):
        self.assertEqual(openapi._schema_type({"type": "array",
                                               "items": {"type": "string"}}), "string[]")

    def test_error_response_check(self):
        by_key = {(e.method, e.path): e for e in self.spec.endpoints}
        self.assertTrue(by_key[("GET", "/orders")].has_error_response)
        self.assertFalse(by_key[("POST", "/orders")].has_error_response)

    def test_undocumented_lists_missing_summary_or_errors(self):
        holes = [(e.method, e.path) for e in openapi.undocumented(self.spec)]
        self.assertEqual(holes, [("POST", "/orders")])

    def test_find_matches_path_or_summary(self):
        self.assertEqual([e.path for e in openapi.find(self.spec, "하나")],
                         ["/orders/{id}"])
        self.assertEqual(len(openapi.find(self.spec, "/orders")), 3)

    def test_tags_are_counted(self):
        self.assertEqual(self.spec.tags, {"주문": 3})

    def test_swagger2_host_becomes_server(self):
        spec = openapi.load({"swagger": "2.0", "host": "api.example.com",
                             "basePath": "/v2", "paths": {}})
        self.assertEqual(spec.servers, ["api.example.com/v2"])

    def test_missing_paths_is_reported(self):
        with self.assertRaises(openapi.SpecError):
            openapi.load({"info": {"title": "x"}})

    def test_broken_ref_is_left_alone(self):
        spec = openapi.load({"paths": {"/a": {"get": {
            "parameters": [{"$ref": "#/없는/자리"}], "responses": {}}}}})
        self.assertEqual(spec.endpoints[0].params, [])


if __name__ == "__main__":
    unittest.main()
