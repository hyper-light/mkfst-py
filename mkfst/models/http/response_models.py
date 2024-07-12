from pydantic import BaseModel, RootModel, StrictStr, conlist


class InternalError(BaseModel):
    error: StrictStr

class InternalErrorSet(RootModel):
    root: conlist(InternalError, min_length=1)
    