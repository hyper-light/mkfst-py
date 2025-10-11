import asyncio

from mkfst import (
    Service,
    endpoint,
    Parameters,
    Env,
)


class TestParams(Parameters):
    id: str


class TestService(Service):
    @endpoint("/")
    async def get_service(self) -> str:
        return "Hello World"

    # @endpoint(
    #     "/post",
    #     methods=["POST"],
    # )
    # async def post_data(self, data: dict) -> dict:
    #     return data

    # @endpoint("/get/:id")
    # async def get_by_id(self, params: TestParams) -> str:
    #     return params.id


if __name__ == "__main__":

    async def run_server():
        server = TestService(
            "localhost",
            6099,
            log_level="error",
            workers=18,
            env=Env(MERCURY_SYNC_CLEANUP_INTERVAL="0.25s"),
        )

        await server.run()

    asyncio.run(run_server())
