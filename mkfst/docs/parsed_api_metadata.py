from pydantic import AnyUrl, BaseModel, ConfigDict, StrictStr

from .models import EmailStr


class ParsedAPIMetadata(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: StrictStr
    version: StrictStr
    summary: StrictStr | None = None
    terms_of_service: StrictStr | None = None
    description: StrictStr | None = None
    owner: StrictStr | None = None
    owner_url: AnyUrl | None = None
    owner_email: EmailStr | None = None
    license: StrictStr | None = None
    license_identifier: StrictStr | None = None
    license_url: AnyUrl | None = None