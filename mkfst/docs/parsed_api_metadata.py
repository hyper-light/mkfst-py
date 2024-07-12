from pydantic import AnyUrl, BaseModel, StrictStr

from .models import EmailStr


class ParsedAPIMetadata(BaseModel):
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

    class Config:
        arbitrary_types_allowed = True