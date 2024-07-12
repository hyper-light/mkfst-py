from typing import Dict, List

from pydantic import AnyHttpUrl, BaseModel, StrictStr


class ParsedServerVariable(BaseModel):
    options: List[StrictStr] | None = None
    default: StrictStr
    description: StrictStr | None = None


class ParsedAPIServer(BaseModel):
    server_url: AnyHttpUrl
    server_description: StrictStr | None
    server_variables: Dict[StrictStr, ParsedServerVariable] | None