from typing import Any, Type

from pydantic import BaseModel

from mkfst.models import HTML, FileUpload


def get_content_type(return_type: Type[Any]):
    if return_type == FileUpload or return_type in FileUpload.__subclasses__():
        return 'application/octet-stream'

    elif return_type == HTML or return_type in HTML.__subclasses__():
        return 'text/html'

    elif return_type in BaseModel.__subclasses__():
        return 'application/json'
    
    elif return_type == str or isinstance(return_type, str):
        return 'text/plain'
    
    elif return_type == bytes or isinstance(return_type, bytes):
        return 'application/octet-stream'
    
    else:
        return 'application/json'
