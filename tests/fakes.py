"""Test doubles for AIProvider."""

from typing import Optional


class FakeProvider:
    """AIProvider stub that returns a fixed response, recording the call it received."""

    def __init__(self, response: str, name: str = "fake", model: str = "fake-model") -> None:
        self.response = response
        self.last_system_prompt: Optional[str] = None
        self.last_user_prompt: Optional[str] = None
        self.call_count = 0
        self._name = name
        self._model = model

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        return self.response
