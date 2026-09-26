"""A minimal stand-in for SciVisAgentBench's ``evaluation_framework`` (C9).

The real package lives in the gitignored ``SciVisAgentBench-main/`` checkout,
so CI can't import it.  ``install()`` registers three modules in
``sys.modules`` -- ``evaluation_framework``, ``.base_agent`` (``BaseAgent``,
``AgentResult``) and ``.agent_registry`` (``register_agent`` as an identity
decorator) -- but only when the real package is not importable.  That is
enough for ``integrations/scivisagentbench/vmd_ai_agent.py`` and
``integrations/explore_arm/explore_agent.py`` to import and run.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any, Callable, Dict, Optional

FAKE_MARKER = "_vmdai_fake_evaluation_framework"


class AgentResult:
    def __init__(
        self,
        success: bool,
        response: str = "",
        error: Optional[str] = None,
        output_files: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.success = success
        self.response = response
        self.error = error
        self.output_files = output_files or {}
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "response": self.response,
            "error": self.error,
            "output_files": self.output_files,
            "metadata": self.metadata,
        }


class BaseAgent:
    """The parts of the real BaseAgent that VmdAiAgent uses."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.agent_name = config.get("agent_name", self.__class__.__name__)
        self.eval_mode = config.get("eval_mode", "generic")
        backbone = str(config.get("model", "unknown_model")).replace("/", "-")
        experiment = config.get("experiment_number", "exp_default")
        self.agent_mode = f"{self.agent_name}_{backbone}_{experiment}"

    def count_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.33)

    async def setup(self) -> None:
        return None

    async def teardown(self) -> None:
        return None

    def get_result_directories(self, case_dir: str, case_name: str) -> Dict[str, Path]:
        case_path = Path(case_dir)
        return {
            "results_dir": case_path / "results" / self.agent_mode,
            "test_results_dir": case_path / "test_results" / self.agent_mode,
            "evaluation_dir": case_path / "evaluation_results" / self.agent_mode,
        }


_REGISTRY: Dict[str, type] = {}


def register_agent(name: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_agent(name: str) -> type:
    return _REGISTRY[name]


def _real_importable() -> bool:
    try:
        importlib.import_module("evaluation_framework.base_agent")
        importlib.import_module("evaluation_framework.agent_registry")
    except ImportError:
        return False
    return True


def install() -> bool:
    """Register the fake modules unless the real package imports.

    Returns True when the fake was installed by this call, False when the
    real package (or an earlier fake) is already importable.
    """
    if _real_importable():
        return False
    for name in list(sys.modules):
        if name == "evaluation_framework" or name.startswith("evaluation_framework."):
            del sys.modules[name]
    package = types.ModuleType("evaluation_framework")
    package.__path__ = []  # a package, so submodule imports resolve via sys.modules
    base_agent = types.ModuleType("evaluation_framework.base_agent")
    base_agent.BaseAgent = BaseAgent
    base_agent.AgentResult = AgentResult
    agent_registry = types.ModuleType("evaluation_framework.agent_registry")
    agent_registry.register_agent = register_agent
    agent_registry.get_agent = get_agent
    agent_registry._AGENT_REGISTRY = _REGISTRY
    for module in (package, base_agent, agent_registry):
        setattr(module, FAKE_MARKER, True)
    package.base_agent = base_agent
    package.agent_registry = agent_registry
    package.BaseAgent = BaseAgent
    package.register_agent = register_agent
    package.get_agent = get_agent
    sys.modules["evaluation_framework"] = package
    sys.modules["evaluation_framework.base_agent"] = base_agent
    sys.modules["evaluation_framework.agent_registry"] = agent_registry
    return True
