"""Contract check: every response must validate against the model its route declares in the
OpenAPI schema; error responses must be FastAPI's `{"detail": ...}` and carry no figures."""

from __future__ import annotations

from typing import Any, cast

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel


def route_for(app: FastAPI, method: str, path_template: str) -> APIRoute:
    for route in app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path_format == path_template
            and method.upper() in route.methods
        ):
            return route
    raise AssertionError(f"no route {method} {path_template}")


def checked(client: TestClient, response: httpx.Response, path_template: str) -> Any:
    app = cast(FastAPI, client.app)
    route = route_for(app, response.request.method, path_template)
    body = response.json()
    if response.is_success:
        model = route.response_model
        assert isinstance(model, type), path_template
        assert issubclass(model, BaseModel), path_template
        model.model_validate(body)
        documented = app.openapi()["paths"][path_template][response.request.method.lower()]
        assert str(response.status_code) in documented["responses"]
    else:
        assert set(body) == {"detail"}, body
    return body
