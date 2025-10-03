import asyncio

from mkfst import (
    Service,
    endpoint,
    Env,
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
            upgrade_port=6100,
            env=Env(
                MERCURY_SYNC_ENABLE_REQUEST_CACHING=True,
            ),
        )

        await server.run()

    asyncio.run(run_server())
