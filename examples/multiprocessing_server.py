import asyncio

from mkfst import (
    Service,
    endpoint,
)
from pydantic import BaseModel


class Greeting(BaseModel):
    message: str


class TestService(Service):
    @endpoint("/")
    async def get_service(self) -> str:
        return "Hello World"

    @endpoint("/post", methods=["POST"])
    async def get_data(self, data: dict) -> dict:
        return data


if __name__ == "__main__":

    async def run_server():
        server = TestService(
            "localhost",
            6099,
            log_level="error",
        )

        await server.run()

    asyncio.run(run_server())
