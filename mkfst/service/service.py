from __future__ import annotations

import asyncio
import functools
import inspect
import multiprocessing
import os
import random
import signal
import socket
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from inspect import signature
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_args,
    get_type_hints,
)

from pydantic import BaseModel

from mkfst.connection.tcp.fabricator import Fabricator
from mkfst.connection.tcp.mercury_sync_http_connection import (
    MercurySyncHTTPConnection,
)
from mkfst.docs import (
    ParsedAPIMetadata,
    ParsedAPIServer,
    ParsedEndpoint,
    ParsedEndpointMetadata,
    ParsedOperationMetadata,
    ParsedServerVariable,
    ParsedTag,
    create_api_definition,
    get_redoc_html,
    get_swagger_ui_html,
)
from mkfst.env import Env, load_env
from mkfst.hooks import endpoint
from mkfst.logging import Logger, LogLevelName, LoggingConfig
from mkfst.middleware.base import Middleware
from mkfst.middleware.base.base_wrapper import BaseWrapper
from mkfst.models.http import HTML, FileUpload
from mkfst.models.logging import Event

from mkfst.tasks import TaskRunner

from .group import Group
from .socket import bind_tcp_socket


multiprocessing.allow_connection_pickling()
spawn = multiprocessing.get_context("spawn")


E = TypeVar("E", bound=Env)

ServerVariable = Dict[Literal["options", "default", "description"], List[str] | str]

Tag = Dict[Literal["value", "description", "docs_description", "docs_url"], str]


async def run(
    service_name: str,
    tcp_connection: MercurySyncHTTPConnection,
    env: BaseModel,
    groups: List[Group],
    config: Dict[str, Union[int, socket.socket, str]] = {},
):
    try:
        tcp_connection.from_env(env)

        services = {cls.__name__: cls for cls in Service.__subclasses__()}
        service: Type[Service] = services.get(service_name)

        server = service(
            tcp_connection.host,
            tcp_connection.port,
            upgrade_port=config.get("upgrade_port"),
            cert_path=config.get("cert_path"),
            key_path=config.get("key_path"),
            groups=groups,
            env=env,
            log_level=config.get("log_level", "info"),
            middleware=config.get("middleware"),
        )

        await server.run(
            worker_socket=config.get("tcp_socket"),
            upgrade_socket=config.get("upgrade_socket"),
        )

    except Exception:
        pass

    current_task = asyncio.current_task()

    tasks = asyncio.all_tasks()
    for task in tasks:
        if task != current_task:
            try:
                task.cancel()

            except (
                Exception,
                asyncio.InvalidStateError,
                asyncio.CancelledError,
                asyncio.TimeoutError,
                AssertionError,
            ):
                pass

    try:
        await asyncio.gather(
            *[task for task in tasks if task != current_task], return_exceptions=True
        )

    except Exception:
        pass


def start_pool(
    tcp_connection: MercurySyncHTTPConnection,
    service_name: str,
    custom_env: BaseModel,
    groups: List[Group],
    config: Dict[str, Union[int, socket.socket, str]] = {},
):
    import asyncio

    try:
        import uvloop

        uvloop.install()

    except ImportError:
        pass

    try:
        loop = asyncio.get_event_loop()

    except Exception:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    stdin_fileno = config.get("stdin_fileno")

    if stdin_fileno is not None:
        sys.stdin = os.fdopen(os.dup(stdin_fileno))

    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            run(
                service_name,
                tcp_connection,
                custom_env,
                groups,
                config,
            )
        )

    except Exception:
        pass


class Service(Generic[E]):
    def __init__(
        self,
        host: str,
        port: int,
        upgrade_port: int | None = None,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        workers: int = os.cpu_count(),
        env: Optional[E] = None,
        engine: Literal["process", "async"] = "process",
        groups: List[Group] | None = None,
        log_level: LogLevelName = "info",
        middleware: List[Middleware] | None = None,
        service_metadata: Dict[
            Literal[
                "name",
                "version",
                "summary",
                "owner",
                "owner_url",
                "owner_email",
                "license",
                "license_identifier",
                "license_url",
                "server_url",
                "server_description",
                "server_variables",
            ],
            str | Dict[str, ServerVariable],
        ]
        | None = None,
        tags: List[Tag] | None = None,
    ) -> None:
        self.env = load_env(Env, existing=env)

        self.name = self.__class__.__name__
        self._logging_config = LoggingConfig(level=log_level)
        self.logger = Logger()
        self.logger.configure(
            name=self.name,
            level=log_level,
        )

        self._instance_id = random.randint(0, 2**16)

        if service_metadata is None:
            service_metadata = {}

        self._service_metadata = service_metadata
        self._tags = tags or []

        self._service_name = self._service_metadata.get("name", self.name)

        self._tags.append(
            ParsedTag(
                value=self._service_name,
                description=f"The {self._service_name} service group.",
            )
        )

        if groups:
            for group in groups:
                self._tags.extend(group.tags)

        if workers < 1:
            workers = 1

        self._workers = workers

        self.host = host
        self.port = port

        self.upgrade_port: int | None = None
        if upgrade_port and upgrade_port != port:
            self.upgrade_port = upgrade_port

        self.cert_path = cert_path
        self.key_path = key_path

        if groups is None:
            groups = []

        if middleware is None:
            middleware = []

        self.middleware = middleware
        self.groups = groups

        self._is_worker = False
        self._engine: Union[ProcessPoolExecutor, None] = None
        self._tcp_queue: Dict[Tuple[str, int], asyncio.Queue] = defaultdict(
            asyncio.Queue
        )
        self._cleanup_task: Union[asyncio.Task, None] = None
        self._waiter: Union[asyncio.Future, None] = None

        self.engine_type = engine

        self.instance_ids = [self._instance_id + idx for idx in range(0, workers)]
        self._tcp = MercurySyncHTTPConnection(
            self.host,
            self.port,
            self._instance_id,
            upgrade_port=upgrade_port,
            env=self.env,
        )

        self.tasks = TaskRunner(self._instance_id, env)

        self._handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._response_headers: Dict[str, Dict[str, Any]] = {}

        self._endpoint_docs: Dict[str, ParsedEndpoint] = {}
        self._docs_json: str | None = None
        self._group_middleware: List[Middleware] = []
        self._reserved_urls = [
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
        ]

        self._loop: asyncio.AbstractEventLoop | None = None

        self._setup()
        self._apply_groups()
        self._create_docs()

    @endpoint("/api/status")
    async def status(self) -> Literal["OK"]:
        return "OK"

    @endpoint("/openapi.json")
    async def get_openapi_json(self) -> dict:
        return self._docs_json

    @endpoint("/docs")
    async def get_docs(self) -> HTML:
        title = self._service_metadata.get("name", self.name)

        return get_swagger_ui_html(
            openapi_url="/openapi.json", title=f"{title} - Swagger UI"
        )

    @endpoint("/redoc")
    async def get_redocs(self) -> HTML:
        title = self._service_metadata.get("name", self.name)

        return get_redoc_html(
            openapi_url="/openapi.json", title=f"{title} - Swagger UI"
        )

    @endpoint("/docs/oauth2-redirect", response_headers={"Content-Type": "text/html"})
    async def get_docs_auth_redirect(self) -> HTML:
        return

    def _create_docs(self):
        server_url = self._service_metadata.get("server_url")
        if server_url is None and self.env.MERCURY_SYNC_SERVER_URL:
            server_url = self.env.MERCURY_SYNC_SERVER_URL.unicode_string()

        elif self.cert_path and self.key_path:
            server_url = f"https://{self.host}:{self.port}"

        else:
            server_url = f"http://{self.host}:{self.port}"

        server_variables: Dict[str, ParsedServerVariable] | None = None
        variables_config: Dict[str, ServerVariable] = self._service_metadata.get(
            "server_variables"
        )
        if isinstance(variables_config, dict) and len(variables_config) > 0:
            server_variables = {
                variable_name: ParsedServerVariable(
                    options=variable_config.get("options"),
                    default=variable_config.get("default"),
                    description=variable_config.get("description"),
                )
                for variable_name, variable_config in variables_config.items()
            }

        self._docs_json = create_api_definition(
            ParsedAPIMetadata(
                title=self._service_metadata.get("name", self.name),
                version=self._service_metadata.get(
                    "version", self.env.MERCURY_SYNC_API_VERISON
                ),
                summary=self._service_metadata.get("summary"),
                description=self.__doc__,
                owner=self._service_metadata.get("owner"),
                owner_url=self._service_metadata.get("owner_url"),
                owner_email=self._service_metadata.get("owner_email"),
                license=self._service_metadata.get("license"),
                license_identifier=self._service_metadata.get("license_identifier"),
                license_url=self._service_metadata.get("license_url"),
            ),
            ParsedAPIServer(
                server_url=server_url,
                server_description=self._service_metadata.get("server_description"),
                server_variables=server_variables,
            ),
            self._endpoint_docs,
            tags=self._tags,
        )

    def _apply_groups(self):
        for group in self.groups:
            assembled: Dict[
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
            ] = group._assemble(self._instance_id, self.env, self.middleware)

            self._apply_group(assembled)

    def _apply_group(
        self,
        assembled: Dict[
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
        ],
    ):
        for route, methods in assembled["routes"].items():
            self._tcp.routes.add(route, methods)

        for key, parser in assembled["response_parsers"].items():
            self._tcp._response_parsers[key] = parser

        self._tcp.events.update(assembled["events"])
        self._tcp.parsers.update(assembled["parsers"])
        self._tcp.match_routes.update(assembled["match_routes"])
        self._tcp._supported_handlers.update(assembled["supported_handlers"])
        self._tcp._middleware_enabled.update(assembled["middleware_enabled"])
        self._tcp.fabricators.update(assembled["fabricators"])
        self._tcp._response_headers.update(assembled["response_headers"])
        self._endpoint_docs.update(assembled["endpoint_docs"])

        self._group_middleware.extend(
            [
                middleware
                for middleware in assembled["middleware"]
                if middleware not in self._group_middleware
            ]
        )

    def _setup(self):
        response_parsers: Dict[BaseModel, Tuple[Callable[[Any], str], int]] = {}
        request_parsers: Dict[str, BaseModel] = {}

        routes = {}

        (
            endpoints,
            tasks,
            fabricators,
        ) = self._gather_hooks()

        for task in tasks.values():
            self.tasks.add(task)

        for path, path_endpoint in endpoints.items():
            handler = path_endpoint
            has_middleware = len(self.middleware) > 0
            if has_middleware and handler.path not in self._reserved_urls:
                self._tcp._middleware_enabled[path] = True

            if isinstance(path_endpoint, (Middleware, BaseWrapper)):
                handler = self._handlers.get(path)

            endpoint_signature = signature(handler)
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

            routes[handler.path] = {method: path_endpoint for method in handler.methods}

            methods = handler.methods

            if (
                len(response_types) > 1
                and inspect.isclass(response_types[0])
                and response_types[0] in BaseModel.__subclasses__()
            ):
                model = response_types[0]
                status_code = response_types[1]

                response_parsers.update(
                    {
                        f"{method}_{handler.path}": (model, status_code)
                        for method in methods
                    }
                )

            elif (
                len(response_types) > 0
                and response_types[0] in BaseModel.__subclasses__()
            ):
                model = response_types[0]

                response_parsers.update(
                    {f"{method}_{handler.path}": (model, 200) for method in methods}
                )

            elif (
                return_type
                and return_type in BaseModel.__subclasses__()
                or (inspect.isclass(return_type) and issubclass(return_type, BaseModel))
            ):
                response_parsers.update(
                    {
                        f"{method}_{handler.path}": (return_type, 200)
                        for method in methods
                    }
                )

            elif return_type is dict or return_type is list:
                response_parsers.update(
                    {
                        f"{method}_{handler.path}": (return_type, 200)
                        for method in methods
                    }
                )

            elif (
                return_type
                and return_type in BaseModel.__subclasses__()
                or return_type in [HTML, FileUpload]
            ):
                response_parsers.update(
                    {
                        f"{method}_{handler.path}": (return_type, 200)
                        for method in methods
                    }
                )

            if isinstance(handler.responses, dict):
                responses = handler.responses

                response_parsers.update(
                    {
                        f"{method}_{handler.path}": (response_model, status)
                        for method in methods
                        for status, response_model in responses.items()
                        if (issubclass(response_model, BaseModel))
                    }
                )

        self._tcp.parsers.update(request_parsers)
        self._tcp.parsers.update(response_parsers)

        self._tcp.events.update(endpoints)
        self._tcp.match_routes.update(routes)
        self._tcp.fabricators.update(fabricators)
        self._tcp._response_headers.update(self._response_headers)

        for route, methods in routes.items():
            self._tcp.routes.add(route, methods)

        for key, parser in response_parsers.items():
            self._tcp._response_parsers[key] = parser

    def _gather_hooks(self):
        reserved = ["connect", "close"]

        endpoints: Dict[
            str, Callable[..., Awaitable[BaseModel | Dict[Any, Any] | str]]
        ] = {}
        fabricators: Dict[str, Fabricator] = {}
        tasks: Dict[str, Callable[[], Awaitable[Any]]] = {}

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
                for middleware_operator in self.middleware:
                    if path not in self._reserved_urls:
                        call = middleware_operator.wrap(call)

                endpoints.update({f"{method}_{path}": call for method in methods})

                self._handlers.update(
                    {f"{method}_{path}": handler for method in methods}
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

                self._response_headers.update(
                    {
                        f"{method}_{path}": dict(call_response_headers)
                        for method in methods
                    }
                )

                if path not in self._reserved_urls:
                    self._endpoint_docs[path] = ParsedEndpoint(
                        path=path,
                        methods=methods,
                        endpoint_metadata=ParsedEndpointMetadata(
                            description=handler.__doc__,
                            summary=handler.summary,
                            operations={
                                method: ParsedOperationMetadata(
                                    group_name=self._service_name,
                                    name=handler.__name__,
                                    tags=method_metadata[method].get("tags"),
                                    description=method_metadata[method].get(
                                        "description"
                                    ),
                                    docs_description=additional_docs.get(
                                        "docs_description"
                                    ),
                                    docs_url=additional_docs.get("docs_url"),
                                    deprecated=method_metadata[method].get(
                                        "depreciated"
                                    ),
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
                    endpoint_method_key = f"{method}_{path}"
                    fabricators[endpoint_method_key] = fabricator

                self._tcp._supported_handlers[path] = {
                    method: handler for method in methods
                }

            if not_internal and not_reserved and is_task:
                hook_name = handler.__name__
                tasks[hook_name] = handler

        return (endpoints, tasks, fabricators)

    async def run(
        self,
        upgrade_socket: Optional[socket.socket] = None,
        worker_socket: Optional[socket.socket] = None,
    ):
        self._loop = asyncio.get_event_loop()
        for signame in ("SIGINT", "SIGTERM", "SIG_IGN"):
            self._loop.add_signal_handler(
                getattr(
                    signal,
                    signame,
                ),
                self.abort,
            )

        self._is_worker = worker_socket is not None

        async with self.logger.context(
            name=self.name,
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            if worker_socket is None:
                await ctx.log(Event(message="Startiworker_socketng server"))

            await asyncio.gather(
                *[middleware.__setup__() for middleware in self.middleware]
            )

            await asyncio.gather(
                *[middleware.__setup__() for middleware in self._group_middleware]
            )

            pool: List[asyncio.Future] = []

            loop = asyncio.get_event_loop()

            try:
                stdin_fileno = sys.stdin.fileno()
            # The `sys.stdin` can be `None`, see https://docs.python.org/3/library/sys.html#sys.__stdin__.
            except (AttributeError, OSError):
                stdin_fileno = None

            if (
                self.engine_type == "process"
                and worker_socket is None
                and self._workers > 1
            ):
                await ctx.log(
                    Event(message=f"Initializing - {self._workers} - workers")
                )

                engine = ProcessPoolExecutor(
                    max_workers=self._workers,
                    mp_context=spawn,
                )

                tcp_socket = bind_tcp_socket(self.host, self.port)
                upgrade_socket: socket.socket | None = None
                if self.upgrade_port and upgrade_socket is None:
                    upgrade_socket = bind_tcp_socket(self.host, self.upgrade_port)

                config = {
                    "tcp_socket": tcp_socket,
                    "upgrade_socket": upgrade_socket,
                    "stdin_fileno": stdin_fileno,
                    "cert_path": self.cert_path,
                    "key_path": self.key_path,
                    "log_level": self._logging_config.level.name.lower(),
                    "middleware": self.middleware,
                    "upgrade_port": self.upgrade_port,
                }

                for _ in range(self._workers):
                    connection = MercurySyncHTTPConnection(
                        self.host,
                        self.port,
                        self._instance_id,
                        upgrade_port=self.upgrade_port,
                        env=self.env,
                    )

                    service_name = self.__class__.__name__

                    service_worker = loop.run_in_executor(
                        engine,
                        functools.partial(
                            start_pool,
                            connection,
                            service_name,
                            self.env,
                            self.groups,
                            config=config,
                        ),
                    )

                    pool.append(service_worker)

                try:
                    await asyncio.gather(*pool)

                except (
                    asyncio.CancelledError,
                    BrokenPipeError,
                    OSError,
                    KeyboardInterrupt,
                    Exception,
                ):
                    pass

                await self.close()

            else:
                if self.upgrade_port and upgrade_socket is None:
                    upgrade_socket = bind_tcp_socket(self.host, self.upgrade_port)

                await self._tcp.connect_async(
                    cert_path=self.cert_path,
                    key_path=self.key_path,
                    worker_socket=worker_socket,
                    upgrade_socket=upgrade_socket,
                )

                self.start_tasks()

                if worker_socket:
                    await ctx.log(
                        Event(message=f"Worker running on - {self.host}:{self.port}")
                    )

                self._waiter = self._loop.create_future()
                try:
                    if self._is_worker is False:
                        await self.logger.log(
                            Event(message=f"Main running on - {self.host}:{self.port}"),
                            template="{timestamp} - {level} - {thread_id} - {message}",
                        )

                    await self._waiter

                except Exception:
                    pass

                await self.close()

    def start_tasks(self):
        self.tasks.start_cleanup()
        for task in self.tasks.all_tasks():
            task.call = task.call.__get__(self, self.__class__)
            setattr(self, task.name, task.call)

            if task.trigger == "ON_START":
                self.tasks.start(task.name)

    async def close(self) -> None:
        async with self.logger.context(
            name=self.name, template="{timestamp} - {level} - {thread_id} - {message}"
        ) as ctx:
            if self._engine and not self._is_worker:
                await ctx.log(
                    Event(message=f"Shutting down - {self._workers} - workers")
                )
                self._engine.shutdown(cancel_futures=True)

            await ctx.log(
                Event(message=f"Shutting down tcp at - {self.host}:{self.port}")
            )
            await self._tcp.close()

            if self._waiter and not self._waiter.done():
                self._waiter.set_result(None)

        await asyncio.gather(*[middleware.close() for middleware in self.middleware])

        await asyncio.gather(
            *[middleware.close() for middleware in self._group_middleware]
        )

        if not self._is_worker:
            await ctx.log(Event(message="Graceful shutdown complete. Goodbye!"))

        await self.logger.close()

    def abort(self, *args):
        if self._engine:
            self._engine.shutdown(cancel_futures=True)

        self._tcp.abort()

        if self._waiter:
            self._waiter.set_result(None)

        self.logger.abort()

        for middleware in self.middleware:
            middleware.abort()

        for middleware in self._group_middleware:
            middleware.abort()
