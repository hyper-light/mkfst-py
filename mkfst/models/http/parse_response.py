from typing import Any, Dict, Type

import orjson

from .file_upload import FileUpload
from .html import HTML
from .request_models import Body
from .model import Model


def parse_response(
    response: Model | Dict[Any, Any] | str,
    response_model: Type[Model | Body | FileUpload | HTML | dict | list | str | bytes],
) -> str:
    if response_model == HTML or isinstance(response, HTML):
        return response.format()

    elif (
        response_model == FileUpload or response_model in FileUpload.__subclasses__()
    ) or isinstance(response, FileUpload):
        return response.data.decode(response.encoding)

    elif (
        response_model == Body
        or response_model in Body.__subclasses__()
        or isinstance(response, Body)
    ):
        return response.content.decode()

    elif response_model == dict or response_model == list:
        return orjson.dumps(response).decode()

    elif response_model in Model.__subclasses__():
        return orjson.dumps(response.model_dump()).decode()

    return response
