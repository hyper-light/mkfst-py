from pydantic import AnyHttpUrl, BaseModel, StrictStr

from .models import ExternalDocumentation


class ParsedTag(BaseModel):
    value: StrictStr
    description: StrictStr | None = None
    docs_description: StrictStr | None = None
    docs_url: AnyHttpUrl | None = None

    def parse(self):

        tag = {
            "name": self.value,
            "description": self.description,
        }

        docs: ExternalDocumentation | None = None
        if self.docs_url:
            docs = {
                "description": self.docs_description,
                "url": self.docs_url.unicode_string()
            }
            
            tag["externalDocs"] = docs

        return tag