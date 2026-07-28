"""
LangGraph workflow:

   requirements -> architect -> developer -> reviewer --(revise)--> developer
                                                  |
                                            (approve)
                                                  v
                                               tester --(fail)--> developer
                                                  |
                                              (pass or
                                          max_revisions hit)
                                                  v
                                                 END
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.graph import StateGraph, END

import config
from src.agents import architect, developer, requirements_engineer, reviewer, tester
from src.llm_client import LLMCallStats
from src.schemas import (
    Architecture,
    CodeArtifact,
    ReviewFeedback,
    ReviewVerdict,
    Requirements,
    TestResults,
    WorkflowStatus,
)
from src import persistence


class WorkflowState(TypedDict, total=False):
    # Inputs
    task_id: str
    task_prompt: str
    run_dir: str
    stats: LLMCallStats

    # Artifacts
    requirements: Requirements
    architecture: Architecture
    code: CodeArtifact
    review_feedback: Optional[ReviewFeedback]
    test_results: Optional[TestResults]

    # Supervisor bookkeeping
    revision_count: int
    max_revisions: int
    status: str
    error: Optional[str]


def _node_requirements(state: WorkflowState) -> dict[str, Any]:
    reqs = requirements_engineer.run(state["task_prompt"], state["stats"])
    persistence.save_artifact(state["run_dir"], "01_requirements.json", reqs)
    persistence.append_log(
        state["run_dir"], "requirements_produced", model=config.REQUIREMENTS_MODEL
    )
    return {"requirements": reqs}


def _node_architect(state: WorkflowState) -> dict[str, Any]:
    arch = architect.run(state["requirements"], state["stats"])
    persistence.save_artifact(state["run_dir"], "02_architecture.json", arch)
    persistence.append_log(
        state["run_dir"], "architecture_produced", model=config.ARCHITECT_MODEL
    )
    return {"architecture": arch}


def _node_developer(state: WorkflowState) -> dict[str, Any]:
    revision = state.get("revision_count", 0)
    code = developer.run(
        state["requirements"],
        state["architecture"],
        state["stats"],
        previous_code=state.get("code"),
        review_feedback=state.get("review_feedback"),
        test_results=state.get("test_results"),
    )
    filename = f"03_code_v{code.revision}.json"
    persistence.save_artifact(state["run_dir"], filename, code)
    persistence.save_generated_project(state["run_dir"], code)
    persistence.append_log(
        state["run_dir"],
        "code_produced",
        revision=code.revision,
        model=config.DEVELOPER_MODEL,
    )
    return {"code": code, "revision_count": revision}


def _node_reviewer(state: WorkflowState) -> dict[str, Any]:
    feedback = reviewer.run(
        state["requirements"], state["architecture"], state["code"], state["stats"]
    )
    filename = f"04_review_v{state['code'].revision}.json"
    persistence.save_artifact(state["run_dir"], filename, feedback)
    persistence.append_log(
        state["run_dir"],
        "review_produced",
        verdict=feedback.verdict.value,
        model=config.REVIEWER_MODEL,
    )
    return {"review_feedback": feedback}


def _node_tester(state: WorkflowState) -> dict[str, Any]:
    results = tester.run(
        state["requirements"], state["architecture"], state["code"], state["stats"]
    )
    filename = f"05_test_results_v{state['code'].revision}.json"
    persistence.save_artifact(state["run_dir"], filename, results)
    persistence.save_qa_tests(state["run_dir"], results)
    persistence.append_log(
        state["run_dir"], "qa_tests_produced", passed=results.passed, model=config.TESTER_MODEL
    )
    return {"test_results": results}


def _route_after_review(state: WorkflowState) -> str:
    feedback = state["review_feedback"]
    if feedback.verdict == ReviewVerdict.APPROVE:
        return "tester"
    if state["revision_count"] >= state["max_revisions"]:
        return "end_failed"
    return "revise"


def _route_after_test(state: WorkflowState) -> str:
    if state["test_results"].passed:
        return "end_passed"
    if state["revision_count"] >= state["max_revisions"]:
        return "end_failed"
    return "revise"


def _node_prepare_revision(state: WorkflowState) -> dict[str, Any]:
    """Increment the supervisor's revision counter before looping back to
    the Developer. Kept as an explicit node so the increment is visible
    as a distinct, logged workflow step."""
    new_count = state["revision_count"] + 1
    persistence.append_log(
        state["run_dir"], "revision_loop", new_revision_count=new_count
    )
    return {"revision_count": new_count}


def _node_finish(state: WorkflowState) -> dict[str, Any]:
    test_results = state.get("test_results")
    if test_results is not None and test_results.passed:
        status = WorkflowStatus.PASSED
    else:
        status = WorkflowStatus.FAILED_MAX_REVISIONS
    persistence.append_log(state["run_dir"], "workflow_finished", status=status.value)
    return {"status": status.value}


def build_graph():
    graph = StateGraph(WorkflowState)

    graph.add_node("requirements", _node_requirements)
    graph.add_node("architect", _node_architect)
    graph.add_node("developer", _node_developer)
    graph.add_node("reviewer", _node_reviewer)
    graph.add_node("tester", _node_tester)
    graph.add_node("prepare_revision", _node_prepare_revision)
    graph.add_node("finish", _node_finish)

    graph.set_entry_point("requirements")
    graph.add_edge("requirements", "architect")
    graph.add_edge("architect", "developer")
    graph.add_edge("developer", "reviewer")

    graph.add_conditional_edges(
        "reviewer",
        _route_after_review,
        {"tester": "tester", "revise": "prepare_revision", "end_failed": "finish"},
    )
    graph.add_conditional_edges(
        "tester",
        _route_after_test,
        {
            "end_passed": "finish",
            "revise": "prepare_revision",
            "end_failed": "finish",
        },
    )
    graph.add_edge("prepare_revision", "developer")
    graph.add_edge("finish", END)

    return graph.compile()
