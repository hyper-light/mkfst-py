import textwrap

from pydantic import BaseModel, StrictStr


class HTML(BaseModel):
    content: StrictStr

    def format(self):
        return textwrap.dedent(self.content)