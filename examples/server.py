import asyncio
import datetime

from pydantic import BaseModel, StrictStr

from mkfst import HTML, Group, Service, endpoint


class MetadataV2(BaseModel):
    accessed: datetime.datetime


class MetadataV1(BaseModel):
    created: datetime.datetime
    updated: datetime.datetime


class User(BaseModel):
    username: StrictStr
    password: StrictStr
    metadata: MetadataV1 | MetadataV2


class UsersApiV1(Group):
    @endpoint("/get")
    async def get_service(self) -> User:
        return User(
            username="johnnyj",
            password="Password12345",
            metadata=MetadataV1(
                created=datetime.datetime.now(),
                updated=datetime.datetime.now(),
            ),
        )


class UsersApiV2(Group):
    @endpoint("/get")
    async def get_service(self) -> User:
        return User(
            username="johnnyj",
            password="Password12345",
            metadata=MetadataV2(accessed=datetime.datetime.now()),
        )


class ApiV1(Group):
    pass


class ApiV2(Group):
    pass


class TestService(Service):
    @endpoint("/home")
    async def get_home(self) -> HTML:
        return HTML(
            content="""
        <!DOCTYPE html>
        <html>
            <head>
                <title>Home</title>
            </head>
            <body>
                <h1>Hello from home!</h1>
            </body>
        </html>
        """
        )


async def run_server():
    server = TestService(
        "localhost",
        5019,
        groups=[
            ApiV1("/api/v1", groups=[UsersApiV1("/users")]),
            ApiV2("/api/v2", groups=[UsersApiV2("/users")]),
        ],
    )

    await server.start_server()
    await server.run_forever()


asyncio.run(run_server())
