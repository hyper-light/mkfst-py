import asyncio

from mkfst import (
    Service,
)
from pydantic import BaseModel


class Greeting(BaseModel):
    message: str


class TestService(Service):
    pass
    
if __name__ == '__main__':
    async def run_server():
        server = TestService(
            'localhost',
            6099,
        )

        await server.start_server()
        await server.run_forever()


    asyncio.run(run_server())