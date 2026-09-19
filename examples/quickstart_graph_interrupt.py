"""Checkpointed interrupt/resume using the reference state graph."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.reference.graph import (
    GraphCommand, GraphInterrupted, SQLiteGraphCheckpointer, StateGraph,
)

def gate(state):
    if "__resume__" in state:
        return {"approved": state["__resume__"]}
    return GraphCommand(interrupt={"question": "approve?"})

with TemporaryDirectory() as directory:
    path = Path(directory) / "graph.sqlite"
    checkpoint = SQLiteGraphCheckpointer(path)
    graph = StateGraph().add_node("gate", gate).set_entry_point("gate")
    compiled = graph.compile(checkpointer=checkpoint)
    try:
        tuple(compiled.stream({}, thread_id="demo"))
    except GraphInterrupted as paused:
        print(paused.snapshot.interrupts)
    checkpoint.close()

    checkpoint = SQLiteGraphCheckpointer(path)
    compiled = graph.compile(checkpointer=checkpoint)
    events = tuple(compiled.stream(None, thread_id="demo", resume="yes"))
    print(events[-1].event_type, events[-1].payload)
    checkpoint.close()
