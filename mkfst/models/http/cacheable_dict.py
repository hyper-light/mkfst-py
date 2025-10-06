from __future__ import annotations


class CacheableDict:
    __slots__ = "data"

    def __init__(self, data: dict[str, str] | None = None):
        self.data = {}

        if data:
            self.data = data

    def __getitem__(self, key: str):
        return self.data[key]

    def __len__(self):
        return len(self.data)

    def __setitem__(self, key: str, value: str):
        self.data[key] = value

    def get(self, key: str, default: str | None = None):
        return self.data.get(key, default)

    def clear(self):
        return self.data.clear()

    def update(self, data: dict[str, str]):
        self.data.update(data)

    def __hash__(self):
        return hash(tuple(sorted(self.data.items())))

    def __eq__(self, value: CacheableDict):
        return self.__hash__() == value.__hash__()
