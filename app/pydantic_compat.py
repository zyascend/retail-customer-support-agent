from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional


try:
    from pydantic import BaseModel, Field
except ModuleNotFoundError:

    class _FieldInfo:
        def __init__(
            self,
            default: Any = None,
            default_factory: Optional[Callable[[], Any]] = None,
            **_: Any,
        ) -> None:
            self.default = default
            self.default_factory = default_factory

        def value(self) -> Any:
            if self.default_factory is not None:
                return self.default_factory()
            return copy.deepcopy(self.default)

    def Field(default: Any = None, **kwargs: Any) -> _FieldInfo:
        return _FieldInfo(default=default, **kwargs)

    class BaseModel:
        def __init__(self, **kwargs: Any) -> None:
            annotations: Dict[str, Any] = {}
            for cls in reversed(type(self).mro()):
                annotations.update(getattr(cls, "__annotations__", {}))
            for name in annotations:
                if name in kwargs:
                    value = kwargs[name]
                else:
                    default = getattr(type(self), name, None)
                    if isinstance(default, _FieldInfo):
                        value = default.value()
                    else:
                        value = copy.deepcopy(default)
                setattr(self, name, value)
            for name, value in kwargs.items():
                if name not in annotations:
                    setattr(self, name, value)

        @classmethod
        def model_validate(cls, data: Dict[str, Any]) -> "BaseModel":
            return cls(**data)

        def model_dump(self, **_: Any) -> Dict[str, Any]:
            return {
                key: self._dump_value(value)
                for key, value in self.__dict__.items()
                if not key.startswith("_")
            }

        @classmethod
        def _dump_value(cls, value: Any) -> Any:
            if hasattr(value, "model_dump"):
                return value.model_dump()
            if isinstance(value, dict):
                return {key: cls._dump_value(item) for key, item in value.items()}
            if isinstance(value, list):
                return [cls._dump_value(item) for item in value]
            return value
