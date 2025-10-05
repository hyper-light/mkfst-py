import textwrap
from .model import Model


class HTML(Model):
    content: str

    def format(self):
        return textwrap.dedent(self.content)
