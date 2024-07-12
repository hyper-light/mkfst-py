import re
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Tuple,
    Type,
)

import orjson
from pydantic import BaseModel, ValidationError

from mkfst.models import HTML, Body, Cookies, FileUpload, Headers, Parameters, Query

KeyType = Literal['positional', 'keyword']


class Fabricator:

    __slots__ = (
        "optional",
        "required",
        'param_keys',
        "_params",
        "_http_pattern",
        "_args_count",
        "_body_type",
        "_ordered_params",
        "_unordered_params",
        '_headers_key',
        '_headers_key_type',
        '_params_key',
        '_params_key_type',
        '_query_key',
        '_query_key_type',
        '_cookies_key',
        '_cookie_key_type',
        '_body_key',
        '_body_key_type',  
        'headers',
        'params',
        'query',
        'cookies',
        'body', 
    )

    def __init__(
        self,
        required_params: List[
            Tuple[
                str, 
                Headers 
                | Parameters 
                | Query 
                | BaseModel 
                | HTML 
                | FileUpload 
                | Cookies,
            ]
        ],
        optional_params: Dict[
            str, 
            Headers 
            | Parameters 
            | Query 
            | BaseModel 
            | HTML 
            | FileUpload
            | Cookies,
        ],
    ) -> None:
        self.optional = {
            key: value[0] for key, value in optional_params.items() if len(value) > 0
        }

        self.required = required_params

        self._http_pattern = re.compile(r'https:\\\\|http:\\\\')
        self._args_count = len(required_params) + len(optional_params)
        
        self._headers_key: int | str | None = None
        self._headers_key_type: KeyType | None = None 

        self._params_key: int | str | None = None
        self._params_key_type: KeyType | None = None 

        self._query_key: int | str | None = None
        self._query_key_type: KeyType | None = None 

        self._cookies_key: int | str | None = None
        self._cookie_key_type: KeyType | None = None 
        
        self._body_key: int | str | None = None
        self._body_key_type: KeyType | None = None 
        
        self._body_type: Literal[
            'file',
            'html',
            'model',
            'raw',
        ] = 'model'
        
        self._params: Dict[
            Literal[
                'headers',
                'parameters',
                'query',
                'body',
                'cookies',
            ],
            Tuple[
                Headers 
                | Parameters 
                | Query 
                | BaseModel 
                | HTML 
                | FileUpload
                | Cookies, 
                int 
                | None
            ]
        ] = {}

        self._ordered_params: List[
            Tuple[
                Literal[
                    'headers',
                    'parameters',
                    'query',
                    'body',
                    'cookies',
                ],
                Headers 
                | Parameters 
                | Query 
                | BaseModel 
                | Body 
                | HTML 
                | FileUpload
                | Cookies
            ]
        ] = []

        self._unordered_params: List[
            Tuple[
                Literal[
                    'headers',
                    'parameters',
                    'query',
                    'body',
                    'cookies',
                ],
                Headers 
                | Parameters 
                | Query 
                | BaseModel 
                | Body 
                | HTML 
                | FileUpload
                | Cookies,
                str,
            ]
        ] = []

        self.param_keys: Dict[
            Literal[
                'headers',
                'parameters',
                'query',
                'body',
                'cookies',
            ],
            int | str
        ] = {}

        for position in range(len(self.required)):
            _, annotation = self.required[position]
            self._parse_to_param(annotation, position=position)

        for name, annotation in self.optional.items():
            self._parse_to_param(annotation, name=name)

        self.headers: Headers | None = None
        self.params: Parameters | None = None
        self.query: Query | None = None
        self.cookies: Cookies | None = None
        self.body: (
            BaseModel
            | Body 
            | HTML 
            | FileUpload
            | str
            | bytes
            | list
            | dict
        ) | None = None


    def __getitem__(
        self,
        param_name: Literal[
            'headers',
            'parameters',
            'query',
            'body',
            'cookies',
        ],
    ):
        if param := self._params.get(param_name):
            return param[0]
        
    @property
    def required_params(self):

        param_type_map = {
            Parameters: 'path',
            Query: 'query',
            Headers: 'headers',
        }

        return [
            param_type_map.get(
                value,
                'body'
            ) for _, value in self.required
        ]
          
    def _parse_to_param(
        self, 
        annotation: Type[Headers] 
        | Type[Parameters] 
        | Type[Query] 
        | Type[BaseModel] 
        | Type[Body] 
        | Type[HTML] 
        | Type[FileUpload]
        | Type[Cookies],
        position: int | None = None,
        name: str | None = None
    ):
        param_type: str | None = None

        if annotation in Headers.__subclasses__():
            self._params['headers'] = (
                annotation,
                position
            )
            
            self._headers_key = position if position is not None else name
            self._headers_key_type = 'positional' if position else 'keyword'

            param_type = 'headers'

        elif annotation in Cookies.__subclasses__():
            self._params['cookies'] = (
                annotation,
                position
            )

            self._cookies_key = position if position is not None else name
            self._cookie_key_type = 'positional' if position is not None else 'keyword'

            param_type = 'cookies'

        elif annotation in Parameters.__subclasses__():
            self._params['parameters'] = (
                annotation,
                position
            )

            self._params_key = position if position is not None else name
            self._params_key_type = 'positional' if position is not None else 'keyword'

            param_type = 'parameters'

        elif annotation in Query.__subclasses__():
            self._params['query'] = (
                annotation,
                position
            )

            self._query_key = position if position is not None else name
            self._query_key_type = 'positional' if position is not None else 'keyword'

            param_type = 'query'

        elif annotation == FileUpload or annotation in FileUpload.__subclasses__():
            self._params['body'] = (
                FileUpload,
                position,
            )

            self._body_key = position if position is not None else name
            self._body_key_type = 'positional' if position is not None else 'keyword'

            param_type = 'body'
            self._body_type = 'file'

        elif annotation == HTML or annotation in HTML.__subclasses__():
            self._params['body'] = (
                HTML,
                position,
            )

            self._body_key = position if position is not None else name
            self._body_key_type = 'positional' if position is not None else 'keyword'

            param_type = 'body'
            self._body_type = 'html'

        elif annotation in BaseModel.__subclasses__():
            self._params['body'] = (
                annotation,
                position,
            )

            self._body_key = position if position is not None else name
            self._body_key_type = 'positional' if position is not None else 'keyword'

            param_type = 'body'
            self._body_type = 'model'

        else:
            self._params['body'] = (
                Body,
                position,
            )

            self._body_key = position if position is not None else name
            self._body_key_type = 'positional' if position is not None else 'keyword'

            param_type = 'body'
            self._body_type = 'raw'

        if position is not None:
            self._ordered_params.append((
                param_type,
                annotation
            ))

            self.param_keys[param_type] = position

        else:
            self._unordered_params.append((
                param_type,
                annotation,
                name,
            ))

            self.param_keys[param_type] = name

    def parse(
        self,
        data: List[bytes],
        query: str | None=None,
        params: Dict[str, str | Tuple[str]] | None = None,
        has_middleware: bool = False,
    ):
        positional_args: List[
            Headers 
            | Parameters 
            | Query 
            | BaseModel 
            | Body 
            | HTML 
            | FileUpload
            | Cookies,
        ] = []

        keyword_args: Dict[
            str,
            Headers 
            | Parameters 
            | Query 
            | BaseModel 
            | Body 
            | HTML 
            | FileUpload
            | Cookies,
        ] = {}

        if self._args_count == 0:
            return (
                positional_args, 
                keyword_args,
                None,
            )

        data_line_idx = -1

        headers_dict: Dict[str, Any] = {}

        headers: Headers | None = None
        parameters: Parameters | None = None
        queries: Query | None = None
        cookies: Cookies | None = None
        body: Any | None = None

        if self._headers_key_type:
            (
                headers, 
                data_line_idx, 
                headers_dict,
                validation_error,
                positional
            ) = self._parse_headers(
                data,
                data_line_idx,
                headers_dict,
            )

            if positional and validation_error:
                return (
                    None,
                    None,
                    validation_error,
                )

            elif positional:
                positional_args.insert(self._headers_key, headers)
            
            else:
                keyword_args[self._headers_key] = headers

            self.headers = headers

        if self._body_key_type:
            (
                body,
                validation_error,
                positional

            ) = self._parse_body(
                data,
                data_line_idx,
                headers_dict,
                has_middleware=has_middleware
            )

            if positional and validation_error:

                return (
                    None,
                    None,
                    validation_error,
                )

            elif positional:
                positional_args.insert(
                    self._body_key,
                    body
                )
            
            else:
                keyword_args[self._body_key] = body

            self.body = body

        if self._cookie_key_type:
            (
                cookies,
                validation_error,
                positional

            ) = self._parse_cookies(
                data,
                data_line_idx,
                headers_dict,
                has_middleware=has_middleware
            )

            if positional and validation_error:
                return (
                    None,
                    None,
                    validation_error,
                )

            elif positional:
                positional_args.insert(self._cookies_key, cookies)
            
            else:
                keyword_args[self._cookies_key] = cookies

            self.cookies = cookies
        
        if self._params_key_type:
            (
                parameters,
                validation_error,
                positional

            ) = self._parse_params(params)

            if positional and validation_error:
                return (
                    None,
                    None,
                    validation_error,
                )

            elif positional:
                positional_args.insert(self._params_key, parameters)
            
            else:
                keyword_args[self._params_key] = parameters

            self.params = parameters
            
        if self._query_key_type:
            (
                queries,
                validation_error,
                positional

            ) = self._parse_query(query)

            if positional and validation_error:
                return (
                    None,
                    None,
                    validation_error,
                )

            elif positional:
                positional_args.insert(self._query_key, queries)
            
            else:
                keyword_args[self._query_key] = queries

            self.query = queries

        return (
            positional_args, 
            keyword_args,
            None
        )
    
    def _parse_headers(
        self,
        data: List[bytes],
        data_line_idx: int,
        headers_dict: Dict[str, Any],
    ):
        annotation = self._get_annotation(self._headers_key, self._headers_key_type)

        try:
            (
                headers, 
                data_line_idx, 
                headers_dict,
            ) = Headers.make(
                annotation,
                data,
                data_line_idx
            )

            return (
                headers,
                data_line_idx,
                headers_dict,
                None,
                self._headers_key_type == 'positional'
            )

        except ValidationError as validation_error:
        
            return (
                headers,
                data_line_idx,
                headers_dict,
                validation_error,
                self._headers_key_type == 'positional'
            )
        
    def _parse_body(
        self,
        data: List[bytes],
        data_line_idx: int,
        headers: Dict[str, Any],
        has_middleware: bool = False
    ):
        
        if headers is None:
            # Headers aren't a declared arg but we still need them to parse the data
            (
                data_line_idx, 
                headers,
            ) = Headers.make_raw(
                data,
                data_line_idx
            )

        annotation = self._get_annotation(self._body_key, self._body_key_type)

        if has_middleware:
            return (
                Body.read(
                    data,
                    data_line_idx,
                ),
                None,
                self._body_key_type == 'positional'
            )

        try:

            match self._body_key:

                case 'file':
                    body = annotation(
                        data=b''.join(
                            data[data_line_idx:]
                        ).strip(),
                        content_type=headers.get('content-type'),
                        content_encoding=headers.get('content-encoding')
                    )

                case 'html':
                    body = annotation(
                        content=b''.join(
                            data[data_line_idx:]
                        ).strip().decode()
                    )

                case 'model':
                    body = annotation(
                        **orjson.loads(
                            Body.make(
                                data,
                                data_line_idx,
                            )
                        )
                    )

                case _:
                    body = Body.make(
                        data,
                        data_line_idx,
                    )

            return (
                body,
                None,
                self._body_key_type == 'positional'
            )

        except ValidationError as validation_error:
            return (
                None,
                validation_error,
                self._body_key_type == 'positional'
            )
        
    def _parse_cookies(
        self,
        headers: Dict[str, Any],
    ):
        try:
            annotation = self._get_annotation(self._cookies_key, self._cookie_key_type)

            cookies = Cookies.make(
                annotation,
                headers,
            )

            return (
                cookies,
                None,
                self._body_key_type == 'positional'
            )

        except ValidationError as validation_error:
            return (
                None,
                validation_error,
                self._body_key_type == 'positional'
            )
        
    def _parse_params(
        self,
        params: Dict[str, Any]
    ):
        try:
            annotation: Type[Parameters] = self._get_annotation(self._params_key, self._params_key_type)
            parameters = annotation(**params)

            return (
                parameters,
                None,
                self._body_key_type == 'positional'
            )

        except ValidationError as validation_error:
            return (
                None,
                validation_error,
                self._body_key_type == 'positional'
            )
        
    def _parse_query(
        self,
        query: str
    ):
        try:
            annotation = self._get_annotation(self._query_key, self._query_key_type)
            parsed_query = Query.make(annotation, query)

            return (
                parsed_query,
                None,
                self._body_key_type == 'positional'
            )

        except ValidationError as validation_error:
            return (
                None,
                validation_error,
                self._body_key_type == 'positional'
            )
        
    def _get_annotation(
        self, 
        key: int | str, 
        key_type: KeyType,
    ):
        return (
            self._ordered_params[key] 
            if key_type== 'positional' 
            else self._unordered_params[key]
        )