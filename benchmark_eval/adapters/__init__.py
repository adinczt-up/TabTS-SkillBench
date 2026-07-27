from benchmark_eval.adapters.base import FrameworkAdapter
from benchmark_eval.adapters.external import ExternalCommandAdapter
from benchmark_eval.adapters.nanobot import NanobotAdapter


def make_adapter(name: str, **kwargs):
    if name == "nanobot":
        return NanobotAdapter(**kwargs)
    return ExternalCommandAdapter(framework=name, **kwargs)


__all__ = [
    "ExternalCommandAdapter",
    "FrameworkAdapter",
    "NanobotAdapter",
    "make_adapter",
]
