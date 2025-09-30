from __future__ import annotations

import inspect
from collections import defaultdict
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    List,
    Literal,
    Tuple,
    get_args,
    get_type_hints,
)

from pydantic import BaseModel

from mkfst.connection.tcp.fabricator import Fabricator
from mkfst.docs import (
    ParsedEndpoint,
    ParsedEndpointMetadata,
    ParsedOperationMetadata,
    ParsedTag,
)
from mkfst.env import Env
from mkfst.middleware.base import Middleware
from mkfst.middleware.base.base_wrapper import BaseWrapper
from mkfst.models.http import (
    HTML,
    FileUpload,
)
from mkfst.tasks import TaskRunner

Tag = Dict[Literal["value", "description", "docs_description", "docs_url"], str]


def join_paths(*paths: str):
    joined = "/".join([path.strip("/") for path in paths])

    return f"/{joined}"


class Group:
    def __init__(
        self,
        base: str,
        groups: List[Group] | None = None,
        middleware: List[Middleware] | None = None,
        tags: List[Tag] | None = None,
    ) -> None:
        if groups is None:
            groups = []

        if middleware is None:
            middleware = []

        self.service_name = self.__class__.__name__
        self._base = base
        self._groups = groups
        self._middleware: List[Middleware] = middleware
        self._supported_handlers: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}

        self.tags = tags or []

        if self.service_name != "Group":
            self.tags.append(
                ParsedTag(
                    value=self.service_name,
                    description=f"The {self.service_name} service group.",
                )
            )

        if groups:
            for group in groups:
                self.tags.extend(group.tags)

    def _assemble(
        self,
        instance_id: int,
        env: Env,
        parent_middleware: List[Middleware],
    ):
        self._middleware.extend(
            [
                middleware
                for middleware in parent_middleware
                if middleware not in self._middleware
            ]
        )

        task_runner = TaskRunner(instance_id, env)

        parsers: Dict[str, Any] = {}
        events: Dict[str, Coroutine] = {}
        match_routes: Dict[str, Dict[str, Callable[..., Awaitable[Any]]]] = {}

        request_parsers: Dict[str, BaseModel] = {}
        response_parsers: Dict[BaseModel, Tuple[Callable[[Any], str], int]] = {}

        middleware_enabled: Dict[str, bool] = {}

        routes: Dict[str, Dict[str, Callable[..., Awaitable[Any]]]] = {}

        (
            endpoints,
            tasks,
            fabricators,
            endpoint_docs,
            response_headers,
        ) = self._gather_hooks()

        for task in tasks.values():
            task_runner.add(task)

        for path, endpoint in endpoints.items():
            handler = endpoint
            has_middleware = len(self._middleware) > 0
            if has_middleware:
                middleware_enabled[path] = True

            if isinstance(endpoint, (Middleware, BaseWrapper)):
                handler = self._handlers[path]

            endpoint_signature = inspect.signature(handler)
            params = endpoint_signature.parameters.values()

            return_type = get_type_hints(handler).get("return")
            response_types = get_args(return_type)

            request_parsers.update(
                {
                    path: get_args(param_type.annotation)[0]
                    for param_type in params
                    if (
                        (args := get_args(param_type.annotation))
                        and len(args) > 0
                        and args[0] in BaseModel.__subclasses__()
                    )
                }
            )

            routes[handler.path] = {method: endpoint for method in handler.methods}

            if (
                len(response_types) > 1
                and inspect.isclass(response_types[0])
                and response_types[0] in BaseModel.__subclasses__()
            ):
                model = response_types[0]
                status_code = response_types[1]

                response_parsers[path] = (model, status_code)

            elif (
                len(response_types) > 0
                and response_types[0] in BaseModel.__subclasses__()
            ):
                model = response_types[0]

                response_parsers[path] = (model, 200)

            elif return_type in BaseModel.__subclasses__() or return_type in [
                HTML,
                FileUpload,
            ]:
                response_parsers[path] = (return_type, 200)

            if isinstance(handler.responses, dict):
                responses = handler.responses

                response_parsers.update(
                    {
                        path: (response_model, status)
                        for status, response_model in responses.items()
                        if (issubclass(response_model, BaseModel))
                    }
                )

        parsers.update(request_parsers)
        parsers.update(response_parsers)

        events.update(endpoints)
        match_routes.update(routes)

        for group in self._groups:
            group._base = join_paths(self._base, group._base)

        assembled_groups = self._gather_groups(
            instance_id,
            env,
        )

        group_middleware = list(self._middleware)

        for assembled in assembled_groups:
            routes.update(assembled["routes"])
            match_routes.update(assembled["match_routes"])
            events.update(assembled["events"])
            parsers.update(assembled["parsers"])
            middleware_enabled.update(assembled["middleware_enabled"])
            self._supported_handlers.update(assembled["supported_handlers"])
            request_parsers.update(assembled["request_parsers"])
            response_parsers.update(assembled["response_parsers"])
            fabricators.update(assembled["fabricators"])
            endpoint_docs.update(assembled["endpoint_docs"])
            response_headers.update(assembled["response_headers"])
            group_middleware.extend(
                [
                    middleware
                    for middleware in assembled["middleware"]
                    if middleware not in self._middleware
                ]
            )

        return {
            "routes": routes,
            "match_routes": match_routes,
            "events": events,
            "parsers": parsers,
            "middleware_enabled": middleware_enabled,
            "supported_handlers": self._supported_handlers,
            "request_parsers": request_parsers,
            "response_parsers": response_parsers,
            "fabricators": fabricators,
            "endpoint_docs": endpoint_docs,
            "middleware": group_middleware,
            "response_headers": response_headers,
        }

    def _gather_hooks(self):
        reserved = ["connect", "close"]
        endpoints: Dict[
            str, Callable[..., Awaitable[BaseModel | Dict[Any, Any] | str]]
        ] = {}
        tasks: Dict[str, Callable[[], Awaitable[Any]]] = {}
        fabricators: Dict[str, Fabricator] = {}
        endpoint_docs: Dict[str, ParsedEndpoint] = {}
        response_headers: Dict[str, Dict[str, Any]] = {}

        for _, call in inspect.getmembers(self, predicate=inspect.ismethod):
            hook_name: str = call.__name__
            not_internal = hook_name.startswith("__") is False
            not_reserved = hook_name not in reserved
            is_endpoint = hasattr(call, "as_endpoint")
            is_task = hasattr(call, "as_task")

            if not_internal and not_reserved and is_endpoint:
                methods: List[str] = call.methods
                path: str = call.path

                handler = call
                for middleware_operator in self._middleware:
                    call = middleware_operator.wrap(call)

                endpoint_path = join_paths(self._base, path)

                endpoints.update(
                    {f"{method}_{endpoint_path}": call for method in methods}
                )

                self._handlers.update(
                    {f"{method}_{endpoint_path}": handler for method in methods}
                )

                call_params = inspect.signature(handler).parameters

                required_params = [
                    (key, value.annotation)
                    for key, value in call_params.items()
                    if value.default == inspect._empty
                ]

                optional_params = {
                    key: get_args(value.annotation)
                    for key, value in call_params.items()
                    if value.default != inspect._empty
                }

                fabricator = Fabricator(required_params, optional_params)

                return_type = get_type_hints(handler).get("return")
                response_types = get_args(return_type)

                responses: Dict[int, Any] = {}

                if (
                    len(response_types) > 1
                    and inspect.isclass(response_types[0])
                    and response_types[0] in BaseModel.__subclasses__()
                ):
                    model = response_types[0]
                    status_code = response_types[1]

                    responses[status_code] = model

                elif len(response_types) == 1:
                    responses[200] = response_types[0]

                elif (
                    len(response_types) > 0
                    and response_types[0] in BaseModel.__subclasses__()
                ):
                    model = response_types[0]
                    responses[200] = model

                else:
                    responses[200] = return_type

                if isinstance(handler.responses, dict):
                    responses.update(handler.responses)

                additional_docs: Dict[Literal["docs_description", "docs_url"], str] = {}

                if isinstance(handler.additional_docs, dict):
                    additional_docs = handler.additional_docs

                method_metadata: Dict[
                    Literal[
                        "GET",
                        "HEAD",
                        "OPTIONS",
                        "POST",
                        "PUT",
                        "PATCH",
                        "DELETE",
                        "TRACE",
                    ],
                    Dict[
                        Literal[
                            "name",
                            "tags",
                            "description",
                            "summary",
                            "docs_url",
                            "docs_description",
                            "depreciated",
                        ],
                        str | List[str] | bool,
                    ],
                ] = handler.method_metadata

                call_response_headers = dict(handler.response_headers)
                response_headers.update(
                    {
                        f"{method}_{endpoint_path}": dict(handler.response_headers)
                        for method in methods
                    }
                )

                endpoint_docs[endpoint_path] = ParsedEndpoint(
                    path=endpoint_path,
                    methods=methods,
                    endpoint_metadata=ParsedEndpointMetadata(
                        description=handler.__doc__,
                        summary=handler.summary,
                        operations={
                            method: ParsedOperationMetadata(
                                group_name=self.service_name,
                                name=method_metadata[method].get(
                                    "name", handler.__name__
                                ),
                                tags=method_metadata[method].get("tags"),
                                description=method_metadata[method].get("description"),
                                docs_description=additional_docs.get(
                                    "docs_description"
                                ),
                                docs_url=additional_docs.get("docs_url"),
                                deprecated=method_metadata[method].get("depreciated"),
                            )
                            for method in methods
                        },
                    ),
                    responses=responses,
                    response_headers=call_response_headers,
                    headers=fabricator["headers"],
                    parameters=fabricator["parameters"],
                    query=fabricator["query"],
                    body=fabricator["body"],
                    required=fabricator.required_params,
                )

                for method in methods:
                    endpoint_method_key = f"{method}_{endpoint_path}"
                    fabricators[endpoint_method_key] = fabricator

                self._supported_handlers[endpoint_path] = {
                    method: handler for method in methods
                }

            if not_internal and not_reserved and is_task:
                hook_name = handler.__name__
                tasks[hook_name] = handler

        return (
            endpoints,
            tasks,
            fabricators,
            endpoint_docs,
            response_headers,
        )

    def _gather_groups(
        self, instance_id: int, env: Env
    ) -> List[
        Dict[
            Literal[
                "routes",
                "match_routes",
                "events",
                "parsers",
                "middleware_enabled",
                "supported_handlers",
                "response_parsers",
                "request_parsers",
                "fabricators",
                "endpoint_docs",
                "middleware",
                "response_headers",
            ],
            Dict[str, Any],
        ]
    ]:
        return [
            group._assemble(instance_id, env, self._middleware)
            for group in self._groups
        ]
