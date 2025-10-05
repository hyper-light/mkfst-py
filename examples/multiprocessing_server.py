import asyncio

from mkfst import (
    Service,
    endpoint,
)


class TestService(Service):
    @endpoint("/")
    async def get_service(self) -> str:
        return "Hello World"

    @endpoint("/post")
    async def post_data(self, data: dict[str, str]) -> dict[str, str]:
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
