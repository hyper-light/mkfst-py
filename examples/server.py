import asyncio
import datetime
from typing import Literal

from mkfst import Group, Service, endpoint
from pydantic import BaseModel, StrictInt, StrictStr, conlist


class Message(BaseModel):
    text: StrictStr
    priority: StrictInt


class Operation(BaseModel):
    messages: conlist(Message, min_length=1)
    username: StrictStr
    date: datetime.datetime


class OperationMetadata(BaseModel):
    created: datetime.datetime


class OperationResponse(BaseModel):
    status: Literal['OK', 'FAILED']
    metadata: OperationMetadata


class UpdateService(Group):

    @endpoint('/get')
    async def get_service(self) -> Literal['OK']:
        return 'OK'


class TestService(Service):
    pass

async def run_server():
    server = TestService(
        'localhost',
        5019,
    )

    await server.start_server()
    await server.run_forever()


asyncio.run(run_server())