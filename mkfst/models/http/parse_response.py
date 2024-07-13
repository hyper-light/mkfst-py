from typing import Any, Dict, Type

import orjson
from pydantic import BaseModel

from .file_upload import FileUpload
from .html import HTML


def parse_response(
    response: BaseModel | Dict[Any, Any] | str, 
    response_model: Type[BaseModel | FileUpload | HTML | dict | list | str | bytes ],
) -> str:

    if response_model == HTML or isinstance(response, HTML):
        return response.format()
    
    elif (
        response_model == FileUpload or isinstance(response, FileUpload) 
    ) and isinstance(response.data, bytes):
        return response.data.decode(response.encoding)
    
    elif response_model in FileUpload.__subclasses__():
        return response.data
    
    elif response_model == dict or response_model == list:
        return orjson.dumps(response).decode()
    
    if response_model in BaseModel.__subclasses__():
        return orjson.dumps(response.model_dump()).decode()


    return response
