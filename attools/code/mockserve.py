"""OpenAPI 문서로 가짜(목) API 서버를 띄운다.

백엔드가 아직 없을 때 프런트를 붙이는 자리에서 쓴다. 문서에 적힌 예시를
그대로 돌려주므로 **진짜 자료가 아니다** - 서버를 띄울 때와 응답 헤더에
그렇다고 적는다. 상태를 기억하지 않는다(POST 로 넣은 것이 GET 에 나오지
않는다). 기억하는 척하면 «되는 줄 알았는데» 가 된다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import openapi

NOT_FOUND = {"error": "문서에 없는 경로입니다", "hint": "at dev api 로 경로를 보세요"}


@dataclass
class Route:
    method: str
    parts: list          # ["orders", "{id}"] - 중괄호는 아무 값이나 받는다
    path: str            # 문서에 적힌 원래 경로
    status: int
    body: object = None
    summary: str = ""

    def matches(self, method: str, parts: list) -> bool:
        if method.upper() != self.method or len(parts) != len(self.parts):
            return False
        return all(mine.startswith("{") or mine == theirs
                   for mine, theirs in zip(self.parts, parts))


@dataclass
class Hit:
    method: str
    path: str
    status: int


@dataclass
class Log:
    hits: list = field(default_factory=list)

    def add(self, method: str, path: str, status: int) -> None:
        self.hits.append(Hit(method, path, status))


def split_path(path: str) -> list:
    return [p for p in path.split("?")[0].split("/") if p]


def make_routes(spec: openapi.Spec) -> list[Route]:
    """문서의 엔드포인트를 «경로 -> 예시 응답» 으로 바꾼다."""
    routes: list[Route] = []
    for endpoint in spec.endpoints:
        code = openapi.success_code(endpoint)
        schema = endpoint.response_schemas.get(code)
        body = openapi.example(schema) if schema is not None else None
        routes.append(Route(endpoint.method.upper(), split_path(endpoint.path),
                            endpoint.path, int(code) if code.isdigit() else 200,
                            body, endpoint.summary))
    # 고정 조각이 많은 경로를 먼저 본다. /orders/new 가 /orders/{id} 에 먹히지 않게
    routes.sort(key=lambda r: sum(1 for p in r.parts if not p.startswith("{")),
                reverse=True)
    return routes


def match(routes: list[Route], method: str, path: str) -> Route | None:
    parts = split_path(path)
    for route in routes:
        if route.matches(method, parts):
            return route
    return None


def make_server(routes: list[Route], *, port: int = 0, host: str = "127.0.0.1",
                delay: float = 0.0, cors: bool = False,
                log: Log | None = None) -> ThreadingHTTPServer:
    """서버를 만든다. 부르는 쪽이 serve_forever 와 닫기를 맡는다."""
    record = log or Log()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:      # 기본 로그는 영어라 끈다
            pass

        def _answer(self) -> None:
            if delay:
                time.sleep(delay)
            route = match(routes, self.command, self.path)
            status = route.status if route else 404
            body = route.body if route else NOT_FOUND
            if route and body is None:
                body = {"note": "문서에 응답 본문 스키마가 없습니다"}
            raw = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
            record.add(self.command, self.path, status)   # 보내기 전에 적는다

            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Mock", "attools")   # 진짜 서버가 아니라는 표시
            if cors:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Methods",
                                 "GET,POST,PUT,PATCH,DELETE,OPTIONS")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def do_GET(self) -> None:
            self._answer()

        do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_GET

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            if cors:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Methods",
                                 "GET,POST,PUT,PATCH,DELETE,OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
