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
                    schema = _resolve(data, (media or {}).get("schema") or {})
                    props = schema.get("properties") if isinstance(schema, dict) else None
                    if isinstance(props, dict):
                        endpoint.body_fields = list(props)
                        break

            endpoint.responses = [str(code) for code in (body.get("responses") or {})]
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
