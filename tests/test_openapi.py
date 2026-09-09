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


class ApiDiffTest(unittest.TestCase):
    OLD = {"paths": {
        "/orders": {"get": {"parameters": [{"name": "page", "in": "query",
                                            "schema": {"type": "integer"}}],
                            "responses": {"200": {}, "400": {}}},
                    "delete": {"responses": {"204": {}}}}}}
    NEW = {"paths": {
        "/orders": {"get": {"parameters": [{"name": "page", "in": "query",
                                            "schema": {"type": "string"}},
                                           {"name": "size", "in": "query",
                                            "required": True,
                                            "schema": {"type": "integer"}}],
                            "responses": {"200": {}}}},
        "/users": {"get": {"responses": {"200": {}}}}}}

    def changes(self) -> dict:
        found = openapi.diff_specs(openapi.load(self.OLD), openapi.load(self.NEW))
        return {(c.kind, c.where): c for c in found}

    def test_removed_endpoint_is_breaking(self):
        change = self.changes()[("사라진 엔드포인트", "DELETE /orders")]
        self.assertTrue(change.breaking)

    def test_new_endpoint_is_not_breaking(self):
        self.assertFalse(self.changes()[("새 엔드포인트", "GET /users")].breaking)

    def test_new_required_parameter_is_breaking(self):
        change = self.changes()[("새 인자", "GET /orders")]
        self.assertTrue(change.breaking)
        self.assertIn("필수", change.detail)

    def test_optional_parameter_is_not_breaking(self):
        new = {"paths": {"/a": {"get": {"parameters": [{"name": "q", "in": "query",
                                                        "schema": {"type": "string"}}],
                                        "responses": {"200": {}}}}}}
        old = {"paths": {"/a": {"get": {"responses": {"200": {}}}}}}
        found = openapi.diff_specs(openapi.load(old), openapi.load(new))
        self.assertFalse(any(c.breaking for c in found))

    def test_type_change_and_lost_response_are_breaking(self):
        found = self.changes()
        self.assertTrue(found[("인자 타입 바뀜", "GET /orders")].breaking)
        self.assertTrue(found[("사라진 응답", "GET /orders")].breaking)

    def test_body_field_changes(self):
        old = {"paths": {"/a": {"post": {"requestBody": {"content": {"application/json": {
            "schema": {"type": "object", "properties": {"가": {}, "나": {}}}}}},
            "responses": {}}}}}
        new = {"paths": {"/a": {"post": {"requestBody": {"content": {"application/json": {
            "schema": {"type": "object", "properties": {"가": {}, "다": {}}}}}},
            "responses": {}}}}}
        found = {c.kind: c for c in openapi.diff_specs(openapi.load(old),
                                                       openapi.load(new))}
        self.assertTrue(found["사라진 본문 필드"].breaking)
        self.assertFalse(found["새 본문 필드"].breaking)

    def test_same_spec_has_no_changes(self):
        spec = openapi.load(self.OLD)
        self.assertEqual(openapi.diff_specs(spec, spec), [])


EXAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "주문 API", "version": "1.0"},
    "components": {"schemas": {
        "고객": {"type": "object", "properties": {
            "이름": {"type": "string"},
            "메일": {"type": "string", "format": "email"}}},
        "주문": {"type": "object", "properties": {
            "id": {"type": "integer", "example": 1024},
            "고객": {"$ref": "#/components/schemas/고객"},
            "금액": {"type": "number"},
            "상태": {"type": "string", "enum": ["대기", "완료"]},
            "만든때": {"type": "string", "format": "date-time"},
            "품목": {"type": "array", "items": {"type": "string"}}}}}},
    "paths": {
        "/orders": {
            "get": {"summary": "목록", "responses": {"200": {"content": {
                "application/json": {"schema": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/주문"}}}}}}},
            "post": {"requestBody": {"content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/주문"}}}},
                "responses": {"201": {"content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/주문"}}}}}}},
        "/orders/{id}": {"get": {
            "parameters": [{"name": "id", "in": "path", "required": True,
                            "schema": {"type": "integer"}}],
            "responses": {"200": {}, "404": {}}}},
    },
}


class MediaExampleTest(unittest.TestCase):
    """content 에 example 만 적어 둔 문서가 흔하다. 스키마가 없다고 비면
    가짜 서버가 «본문 없음» 만 돌려주어 쓸 데가 없다."""

    SPEC = {
        "openapi": "3.0.0", "info": {"title": "t", "version": "1"},
        "paths": {
            "/a": {"get": {"responses": {"200": {"description": "d", "content": {
                "application/json": {"example": {"id": 1, "name": "홍길동"}}}}}}},
            "/b": {"get": {"responses": {"200": {"description": "d", "content": {
                "application/json": {"examples": {"기본": {"value": [1, 2]}}}}}}}},
        },
    }

    def test_request_body_example_is_used(self):
        spec = openapi.load({
            "openapi": "3.0.0", "info": {"title": "t", "version": "1"},
            "paths": {"/a": {"post": {
                "requestBody": {"content": {"application/json": {
                    "example": {"name": "홍길동", "qty": 2}}}},
                "responses": {"201": {"description": "d"}}}}}})
        endpoint = spec.endpoints[0]
        self.assertEqual(endpoint.body_fields, ["name", "qty"])
        self.assertEqual(openapi.example(endpoint.body_schema),
                         {"name": "홍길동", "qty": 2})

    def test_media_example_is_used(self):
        spec = openapi.load(self.SPEC)
        by_path = {e.path: e for e in spec.endpoints}
        self.assertEqual(openapi.example(by_path["/a"].response_schemas["200"]),
                         {"id": 1, "name": "홍길동"})
        self.assertEqual(openapi.example(by_path["/b"].response_schemas["200"]),
                         [1, 2])


class ExampleTest(unittest.TestCase):
    def setUp(self):
        self.spec = openapi.load(EXAMPLE_SPEC)
        self.by_path = {f"{e.method} {e.path}": e for e in self.spec.endpoints}

    def test_nested_refs_are_followed(self):
        made = openapi.example(
            self.by_path["POST /orders"].body_schema)
        self.assertEqual(made["고객"],
                         {"이름": "문자열", "메일": "hong@example.com"})

    def test_written_example_wins(self):
        made = openapi.example(self.by_path["POST /orders"].body_schema)
        self.assertEqual(made["id"], 1024)          # 문서에 적힌 값

    def test_enum_takes_the_first(self):
        made = openapi.example(self.by_path["POST /orders"].body_schema)
        self.assertEqual(made["상태"], "대기")

    def test_format_gets_a_shaped_value(self):
        made = openapi.example(self.by_path["POST /orders"].body_schema)
        self.assertEqual(made["만든때"], "2026-03-04T14:30:00+09:00")

    def test_array_gets_one_item(self):
        made = openapi.example(self.by_path["POST /orders"].body_schema)
        self.assertEqual(made["품목"], ["문자열"])

    def test_response_schema_is_kept(self):
        endpoint = self.by_path["GET /orders"]
        made = openapi.example(endpoint.response_schemas["200"])
        self.assertIsInstance(made, list)
        self.assertEqual(made[0]["id"], 1024)

    def test_success_code(self):
        self.assertEqual(openapi.success_code(self.by_path["POST /orders"]),
                         "201")
        # 본문 스키마가 없어도 응답 코드에서 고른다
        self.assertEqual(openapi.success_code(self.by_path["GET /orders/{id}"]),
                         "200")

    def test_example_path_fills_in_params(self):
        self.assertEqual(
            openapi.example_path(self.by_path["GET /orders/{id}"]),
            "/orders/1")

    def test_recursive_schema_stops(self):
        # 스스로를 가리키는 스키마도 있다. 끊지 않으면 영영 돈다
        spec = openapi.load({
            "openapi": "3.0.0", "paths": {"/n": {"get": {"responses": {
                "200": {"content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/노드"}}}}}}}},
            "components": {"schemas": {"노드": {"type": "object", "properties": {
                "다음": {"$ref": "#/components/schemas/노드"}}}}}})
        made = openapi.example(spec.endpoints[0].response_schemas["200"])
        self.assertIsInstance(made, dict)

    def test_swagger2_response_schema(self):
        spec = openapi.load({
            "swagger": "2.0", "paths": {"/a": {"get": {"responses": {
                "200": {"description": "ok",
                        "schema": {"type": "object",
                                   "properties": {"n": {"type": "integer"}}}}}}}}})
        made = openapi.example(spec.endpoints[0].response_schemas["200"])
        self.assertEqual(made, {"n": 1})


if __name__ == "__main__":
    unittest.main()
