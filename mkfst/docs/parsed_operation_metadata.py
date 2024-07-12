from typing import List

from pydantic import BaseModel, StrictBool, StrictStr


class ParsedOperationMetadata(BaseModel):
    group_name: StrictStr
    name: StrictStr
    tags: List[StrictStr] | None = None
    description: StrictStr | None = None
    summary: StrictStr | None = None
    docs_url: StrictStr | None = None
    docs_description: StrictStr | None = None
    deprecated: StrictBool | None = None

