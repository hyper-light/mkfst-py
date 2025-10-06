from pydantic import BaseModel, RootModel, StrictStr, conlist


class InternalError(BaseModel):
    error: StrictStr


class InternalErrorSet(RootModel):
    root: conlist(InternalError, min_length=1)


class BadRequestError(BaseModel):
    error: str


class BadRequestErrorSet(RootModel):
    root: conlist(BadRequestError, min_length=1)
