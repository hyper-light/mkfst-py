from typing import Any, Dict, List

from pydantic import BaseModel, RootModel, StrictStr


class PydanticValidationError(BaseModel):
    type: StrictStr | None = None
    loc: List[StrictStr] | None = None
    msg: StrictStr | None = None
    input: Dict[StrictStr, Any]
    url: StrictStr


class ValidationErrorGroup(RootModel):
    root: List[PydanticValidationError]