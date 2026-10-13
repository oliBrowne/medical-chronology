from chronology.agents.loop import run_agent
from chronology.llm.base import ChatReply, ToolCall
from chronology.llm.fake import FakeChatClient
from chronology.tools.registry import Registry, Tool


def registry():
    reg = Registry()
    reg.register(Tool("echo", "Echo text", {"type": "object"}, lambda text: text))
    reg.register(Tool("secret", "Not allowed", {"type": "object"}, lambda: "leak"))
    return reg


def test_runs_tool_then_returns_final_answer():
    client = FakeChatClient([
        ChatReply(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "hi"})]),
        ChatReply(content="done"),
    ])
    result = run_agent(client, registry(), "sys", "user", ["echo"], max_steps=3)
    assert (result.stopped, result.content, result.steps) == ("final", "done", 2)
    assert result.log[0].result == "hi"
    assert client.calls[1]["messages"][-1]["role"] == "tool"


def test_stops_at_step_cap():
    looping = ChatReply(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "x"})])
    client = FakeChatClient([looping] * 5)
    result = run_agent(client, registry(), "sys", "user", ["echo"], max_steps=2)
    assert result.stopped == "step_cap"
    assert len(result.log) == 2


def test_disallowed_tool_is_refused_not_run():
    client = FakeChatClient([
        ChatReply(tool_calls=[ToolCall(id="1", name="secret")]),
        ChatReply(content="ok"),
    ])
    result = run_agent(client, registry(), "sys", "user", ["echo"], max_steps=3)
    assert result.log[0].result is None
    assert "not allowed" in result.log[0].error
