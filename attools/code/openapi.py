"""OpenAPI(Swagger) 문서 훑기. json 만 읽는다 - yaml 은 표준 라이브러리에 없다."""

from __future__ import annotations

from dataclasses import dataclass, field

METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


class SpecError(Exception):
    pass


@dataclass
class Param:
    name: str
    place: str          # query / path / header / cookie
    required: bool
    type: str


@dataclass
class Endpoint:
    method: str
    path: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    body_fields: list[str] = field(default_factory=list)
    body_required: bool = False
    responses: list[str] = field(default_factory=list)
    deprecated: bool = False
    body_schema: dict | None = None                  # 요청 본문 스키마 (참조를 편 것)
    response_schemas: dict = field(default_factory=dict)   # 상태코드 -> 스키마

    @property
    def required_params(self) -> list[Param]:
        return [p for p in self.params if p.required]

    @property
    def has_error_response(self) -> bool:
        """4xx·5xx 응답을 적어 뒀는가. 성공만 적힌 문서가 흔하다."""
        return any(code[:1] in ("4", "5") for code in self.responses)


@dataclass
class Spec:
    title: str = ""
    version: str = ""
    servers: list[str] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    openapi: str = ""

    @property
    def tags(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.endpoints:
            for tag in e.tags or ["(태그 없음)"]:
                out[tag] = out.get(tag, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _resolve(data: dict, node):
    """#/components/... 같은 내부 참조만 따라간다. 외부 파일은 따라가지 않는다."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 10:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return node
        target = data
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return node
            target = target[part]
        node = target
        seen += 1
    return node


def _deep(data: dict, node, depth: int = 0):
    """참조를 안쪽까지 편다. 스스로를 가리키는 스키마가 있어 깊이를 끊는다."""
    if depth > 6:
        return {}
    node = _resolve(data, node)
    if isinstance(node, dict):
        return {k: _deep(data, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_deep(data, v, depth + 1) for v in node]
    return node


def _schema_type(schema) -> str:
    if not isinstance(schema, dict):
        return ""
    if "type" in schema:
        kind = schema["type"]
        if kind == "array" and isinstance(schema.get("items"), dict):
            return f"{schema['items'].get('type', '?')}[]"
        return str(kind)
    for key in ("oneOf", "anyOf", "allOf"):
        if key in schema:
            return key
    return ""


def load(data) -> Spec:
    """파싱된 JSON 을 Spec 으로. OpenAPI 3 와 Swagger 2 를 모두 본다."""
    if not isinstance(data, dict) or "paths" not in data:
        raise SpecError("OpenAPI 문서로 보이지 않습니다 (paths 가 없습니다).")

    info = data.get("info") or {}
    spec = Spec(title=str(info.get("title", "")), version=str(info.get("version", "")),
                openapi=str(data.get("openapi") or data.get("swagger") or ""))
    for server in data.get("servers") or []:
        if isinstance(server, dict) and server.get("url"):
            spec.servers.append(str(server["url"]))
    if not spec.servers and data.get("host"):        # swagger 2
        base = str(data.get("basePath", ""))
        spec.servers.append(f"{data['host']}{base}")

    for path, item in (data.get("paths") or {}).items():
        item = _resolve(data, item)
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") or []
        for method in METHODS:
            body = item.get(method)
            if not isinstance(body, dict):
                continue
            endpoint = Endpoint(method.upper(), str(path),
                                summary=str(body.get("summary")
                                            or body.get("description") or "").strip(),
                                tags=[str(t) for t in body.get("tags") or []],
                                deprecated=bool(body.get("deprecated")))
            for raw in list(shared) + list(body.get("parameters") or []):
                raw = _resolve(data, raw)
                if not isinstance(raw, dict) or not raw.get("name"):
                    continue
                schema = _resolve(data, raw.get("schema") or {})
                endpoint.params.append(Param(
                    str(raw["name"]), str(raw.get("in", "")), bool(raw.get("required")),
                    _schema_type(schema) or str(raw.get("type", ""))))

            request = _resolve(data, body.get("requestBody") or {})
            if isinstance(request, dict) and request:
                endpoint.body_required = bool(request.get("required"))
                for media in (request.get("content") or {}).values():
                    media = _resolve(data, media) or {}
                    schema = _resolve(data, media.get("schema") or {})
                    props = schema.get("properties") if isinstance(schema, dict) else None
                    if isinstance(props, dict):
                        endpoint.body_fields = list(props)
                        endpoint.body_schema = _deep(data, schema)
                        break
                    # 스키마 없이 example 만 적어 둔 문서도 흔하다
                    shown = _media_example(data, media)
                    if shown is not None:
                        endpoint.body_schema = {"example": shown}
                        if isinstance(shown, dict):
                            endpoint.body_fields = list(shown)
                        break

            endpoint.responses = [str(code) for code in (body.get("responses") or {})]
            for code, response in (body.get("responses") or {}).items():
                response = _resolve(data, response)
                if not isinstance(response, dict):
                    continue
                for media, holder in (response.get("content") or {}).items():
                    if "json" not in str(media):
                        continue
                    holder = _resolve(data, holder) or {}
                    # 미디어 타입에 적은 example·examples 가 스키마보다 먼저다.
                    # 사람이 손으로 적어 둔 값이라 지어낸 값보다 진짜에 가깝다
                    shown = _media_example(data, holder)
                    if shown is not None:
                        endpoint.response_schemas[str(code)] = {"example": shown}
                        break
                    schema = holder.get("schema")
                    if schema:
                        endpoint.response_schemas[str(code)] = _deep(data, schema)
                    break
                else:                              # swagger 2 는 여기에 적는다
                    if response.get("schema"):
                        endpoint.response_schemas[str(code)] = _deep(
                            data, response["schema"])
            spec.endpoints.append(endpoint)

    spec.endpoints.sort(key=lambda e: (e.path, METHODS.index(e.method.lower())))
    return spec


def find(spec: Spec, needle: str) -> list[Endpoint]:
    """경로나 요약에 들어간 말로 고른다."""
    key = needle.lower()
    return [e for e in spec.endpoints
            if key in e.path.lower() or key in e.summary.lower()]


def undocumented(spec: Spec) -> list[Endpoint]:
    """요약이 없거나 오류 응답을 안 적은 것. 문서 구멍을 찾을 때."""
    return [e for e in spec.endpoints if not e.summary or not e.has_error_response]


# ------------------------------------------------------------ 두 문서 비교

@dataclass
class ApiChange:
    kind: str            # 사라진 엔드포인트 | 새 엔드포인트 | 인자 …
    where: str           # GET /orders
    detail: str = ""
    breaking: bool = False


def diff_specs(before: Spec, after: Spec) -> list[ApiChange]:
    """예전 문서와 새 문서를 견준다. 클라이언트가 깨질 만한 것을 가려낸다.

    깨지는 것: 엔드포인트가 사라짐, 필수 인자가 늘어남, 있던 인자가 사라짐,
    인자 타입이 바뀜, 있던 응답 코드가 사라짐. 나머지는 더해진 것들이다.
    """
    old = {(e.method, e.path): e for e in before.endpoints}
    new = {(e.method, e.path): e for e in after.endpoints}
    out: list[ApiChange] = []

    for key in old.keys() - new.keys():
        out.append(ApiChange("사라진 엔드포인트", f"{key[0]} {key[1]}", breaking=True))
    for key in new.keys() - old.keys():
        out.append(ApiChange("새 엔드포인트", f"{key[0]} {key[1]}"))

    for key in sorted(old.keys() & new.keys()):
        a, b = old[key], new[key]
        where = f"{key[0]} {key[1]}"
        old_params = {p.name: p for p in a.params}
        new_params = {p.name: p for p in b.params}

        for name in old_params.keys() - new_params.keys():
            out.append(ApiChange("사라진 인자", where, name, breaking=True))
        for name in new_params.keys() - old_params.keys():
            param = new_params[name]
            out.append(ApiChange("새 인자", where,
                                 f"{name} ({'필수' if param.required else '선택'})",
                                 breaking=param.required))
        for name in sorted(old_params.keys() & new_params.keys()):
            first, second = old_params[name], new_params[name]
            if first.type != second.type:
                out.append(ApiChange("인자 타입 바뀜", where,
                                     f"{name}: {first.type or '?'} -> "
                                     f"{second.type or '?'}", breaking=True))
            if not first.required and second.required:
                out.append(ApiChange("인자가 필수가 됨", where, name, breaking=True))

        gone = set(a.responses) - set(b.responses)
        if gone:
            out.append(ApiChange("사라진 응답", where,
                                 ", ".join(sorted(gone)), breaking=True))
        added = set(b.responses) - set(a.responses)
        if added:
            out.append(ApiChange("새 응답", where, ", ".join(sorted(added))))

        if b.deprecated and not a.deprecated:
            out.append(ApiChange("폐기 예정으로 표시됨", where))

        old_body, new_body = set(a.body_fields), set(b.body_fields)
        if old_body - new_body:
            out.append(ApiChange("사라진 본문 필드", where,
                                 ", ".join(sorted(old_body - new_body)),
                                 breaking=True))
        if new_body - old_body:
            out.append(ApiChange("새 본문 필드", where,
                                 ", ".join(sorted(new_body - old_body))))
    return out


# ------------------------------------------------------------- 예시 만들기

EXAMPLE_FORMATS = {
    "date-time": "2026-03-04T14:30:00+09:00",
    "date": "2026-03-04",
    "time": "14:30:00",
    "email": "hong@example.com",
    "uuid": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "uri": "https://example.com/a",
    "url": "https://example.com/a",
    "hostname": "example.com",
    "ipv4": "192.0.2.1",
    "password": "비밀번호",
    "binary": "(파일)",
    "byte": "YmFzZTY0",
}
EXAMPLE_FIELDS = 40           # 한 객체에서 만들 필드 수 한도


def _media_example(data, holder: dict):
    """content 의 media 항목에 적힌 example / examples 의 첫 값. 없으면 None."""
    if "example" in holder:
        return holder["example"]
    shown = holder.get("examples")
    if isinstance(shown, dict):
        for item in shown.values():
            item = _resolve(data, item)
            if isinstance(item, dict) and "value" in item:
                return item["value"]
    if isinstance(shown, list) and shown:
        return shown[0]
    return None


def example(schema, *, depth: int = 0):
    """스키마 하나에서 예시 값을 만든다.

    문서에 적힌 example·default·enum 이 있으면 그걸 그대로 쓰고, 없을 때만
    형식에 맞는 값을 채운다. 지어낸 값이라는 것은 부르는 쪽이 밝혀야 한다.
    """
    if not isinstance(schema, dict) or depth > 6:
        return None
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    if isinstance(schema.get("examples"), list) and schema["examples"]:
        return schema["examples"][0]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]

    for key in ("allOf", "oneOf", "anyOf"):
        parts = schema.get(key)
        if isinstance(parts, list) and parts:
            if key == "allOf":
                merged: dict = {}
                for part in parts:
                    value = example(part, depth=depth + 1)
                    if isinstance(value, dict):
                        merged.update(value)
                return merged or None
            return example(parts[0], depth=depth + 1)

    kind = schema.get("type")
    if kind == "array":
        item = example(schema.get("items") or {}, depth=depth + 1)
        return [item] if item is not None else []
    if kind == "object" or "properties" in schema:
        out: dict = {}
        for name, sub in list((schema.get("properties") or {}).items())[:EXAMPLE_FIELDS]:
            out[name] = example(sub, depth=depth + 1)
        return out
    if kind == "integer":
        return int(schema.get("minimum", 1) or 1)
    if kind == "number":
        return float(schema.get("minimum", 1.5) or 1.5)
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    if kind == "string" or kind is None:
        found = EXAMPLE_FORMATS.get(str(schema.get("format", "")))
        if found:
            return found
        return "문자열"
    return None


def success_code(endpoint: Endpoint) -> str:
    """예시로 쓸 성공 응답 코드. 없으면 빈 문자열."""
    codes = [c for c in endpoint.response_schemas if c.startswith("2")]
    if codes:
        return sorted(codes)[0]
    plain = [c for c in endpoint.responses if c.startswith("2")]
    return sorted(plain)[0] if plain else ""


def example_path(endpoint: Endpoint) -> str:
    """{id} 같은 자리를 예시 값으로 채운 경로."""
    out = endpoint.path
    for param in endpoint.params:
        if param.place != "path":
            continue
        value = "1" if param.type in ("integer", "number") else "예시"
        out = out.replace("{" + param.name + "}", value)
    return out
