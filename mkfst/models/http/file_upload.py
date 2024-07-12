import asyncio
import functools
from typing import Literal

from pydantic import BaseModel, StrictBytes, StrictStr


class FileUpload(BaseModel):
    data: StrictBytes | StrictStr
    content_type: StrictStr | None = None
    encoding: StrictStr | None = None

    async def upload(
        self, 
        path: str, 
        read_type: Literal['string', 'binary']='string',
    ):
        upload_file = await asyncio.to_thread(
            functools.partial(
                self._upload,
                path,
                read_type
            )
        )

        return FileUpload(
            data=upload_file
        )

    def _upload( 
        self, 
        path: str, 
        read_type: Literal['string', 'binary']='string',
    ):
        
        read_mode = 'r'
        if read_type == 'binary':
            read_mode = 'rb'

        with open(path, read_mode) as upload_file:
            return upload_file.read()
         