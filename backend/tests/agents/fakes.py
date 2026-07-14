from collections.abc import Callable
from typing import Any


class FakeSdkRunner:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[object, str]] = []

    def __call__(self, agent: object, prompt: str) -> Any:
        self.calls.append((agent, prompt))
        if self.error is not None:
            raise self.error
        return self.result


class FakeNarrativeRunner:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.questions: list[str] = []

    def run(self, question: str, context: object) -> Any:
        self.questions.append(question)
        return self.result
