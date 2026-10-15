from chronology.agents.loop import run_agent
from chronology.llm.base import ChatReply, MalformedToolCall, ToolCall
from chronology.llm.fake import FakeChatClient
from chronology.tools.registry import Registry, Tool


def registry():
    def finish(answer: str):
        if answer == "bad":
            raise ValueError("rejected")
        return {"ok": True}

    reg = Registry()
    reg.register(Tool("finish", "Finish", {"type": "object"}, finish))
    return reg


def call(arguments):
    return ChatReply(tool_calls=[ToolCall(id="1", name="finish", arguments=arguments)])


def run(client):
    return run_agent(client, registry(), "sys", "user", ["finish"], max_steps=4,
                     finish_tool="finish")


def test_a_successful_finish_call_ends_the_run_and_returns_its_arguments():
    result = run(FakeChatClient([call({"answer": "good"})]))
    assert result.output == {"answer": "good"} and result.steps == 1


def test_a_rejected_finish_call_goes_back_to_the_model_and_can_be_retried():
    result = run(FakeChatClient([call({"answer": "bad"}), call({"answer": "good"})]))
    assert result.output == {"answer": "good"}
    assert "rejected" in result.log[0].error


def test_plain_text_before_finishing_gets_one_nudge_then_the_run_ends():
    result = run(FakeChatClient([ChatReply(content="hm"), ChatReply(content="hm")]))
    assert result.output is None and result.stopped == "final" and result.steps == 2


def test_a_malformed_tool_call_is_a_failed_step_not_a_crash():
    class Flaky:
        calls = 0

        def chat(self, messages, tools=None, response_schema=None):
            self.calls += 1
            if self.calls == 1:
                raise MalformedToolCall("bad json")
            return call({"answer": "good"})

    result = run(Flaky())
    assert result.output == {"answer": "good"}
    assert result.log[0].error == "tool call was not valid JSON"
