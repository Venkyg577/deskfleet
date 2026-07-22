import logging
from typing import Any, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field, PrivateAttr

from app.config import settings

log = logging.getLogger(__name__)


class FakeLLM(BaseChatModel):
    """Scripted deterministic LLM for tests.

    Pass responses=[r1, r2, ...] where each item is consumed in order.
    Items can be:
      - A Pydantic BaseModel instance  (for with_structured_output calls)
      - An AIMessage with tool_calls   (for bind_tools calls)
      - A plain string                 (for regular invoke calls)
    """

    responses: list[Any] = Field(default_factory=list)
    _index: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _pop(self) -> Any:
        if self._index >= len(self.responses):
            raise IndexError(
                f"FakeLLM exhausted after {self._index} call(s); "
                f"add more scripted responses."
            )
        item = self.responses[self._index]
        self._index += 1
        return item

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        item = self._pop()
        msg = item if isinstance(item, AIMessage) else AIMessage(content=str(item))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def with_structured_output(self, schema: type, **kwargs: Any) -> Any:
        llm = self

        def _invoke(input: Any) -> Any:
            item = llm._pop()
            if isinstance(item, schema):
                return item
            if isinstance(item, AIMessage):
                return schema.model_validate_json(item.content)
            raise TypeError(
                f"FakeLLM: structured output expected {schema.__name__}, "
                f"got {type(item).__name__}"
            )

        return RunnableLambda(_invoke)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "FakeLLM":
        # Tool-call responses are scripted as AIMessage(tool_calls=[...]).
        # Returning self keeps the same response queue.
        return self


def get_llm() -> BaseChatModel:
    if settings.LLM_PROVIDER == "fake":
        log.info("LLM provider: fake")
        return FakeLLM()

    from langchain_openai import ChatOpenAI

    log.info("LLM provider: openai model=%s", settings.LLM_MODEL)
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY,
    )
