"""Decoratori @workflow e @step per definire workflow nel Python SDK (Milestone M5)."""

import functools
from typing import Any, Callable, Dict, List, Optional


class StepMetadata:
    def __init__(
        self,
        func: Callable,
        name: str,
        step_id: Optional[str] = None,
        timeout_seconds: int = 60,
        requires_approval: bool = False,
        on_failure_step_id: Optional[str] = None,
    ):
        self.func = func
        self.name = name
        self.step_id = step_id or func.__name__
        self.timeout_seconds = timeout_seconds
        self.requires_approval = requires_approval
        self.on_failure_step_id = on_failure_step_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "timeout_seconds": self.timeout_seconds,
            "requires_approval": self.requires_approval,
            "on_failure_step_id": self.on_failure_step_id,
        }


class WorkflowMetadata:
    def __init__(
        self,
        target: Any,
        name: str,
        description: str = "",
        version: int = 1,
        timeout_seconds: int = 300,
    ):
        self.target = target
        self.name = name
        self.description = description
        self.version = version
        self.timeout_seconds = timeout_seconds
        self.steps: List[StepMetadata] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "timeout_seconds": self.timeout_seconds,
            "steps": [s.to_dict() for s in self.steps],
        }


def step(
    name: Optional[str] = None,
    step_id: Optional[str] = None,
    timeout_seconds: int = 60,
    requires_approval: bool = False,
    on_failure_step_id: Optional[str] = None,
):
    """Decoratore per marcare una funzione come step eseguibile di un workflow."""

    def decorator(func: Callable):
        meta = StepMetadata(
            func=func,
            name=name or func.__name__.replace("_", " ").title(),
            step_id=step_id or func.__name__,
            timeout_seconds=timeout_seconds,
            requires_approval=requires_approval,
            on_failure_step_id=on_failure_step_id,
        )
        func.__step_meta__ = meta

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        wrapper.__step_meta__ = meta
        return wrapper

    return decorator


def workflow(
    name: Optional[str] = None,
    description: str = "",
    version: int = 1,
    timeout_seconds: int = 300,
):
    """Decoratore per marcare una classe o funzione come workflow."""

    def decorator(cls_or_func: Any):
        wf_name = name or (
            cls_or_func.__name__.replace("_", " ").title()
            if hasattr(cls_or_func, "__name__")
            else "Workflow"
        )
        meta = WorkflowMetadata(
            target=cls_or_func,
            name=wf_name,
            description=description,
            version=version,
            timeout_seconds=timeout_seconds,
        )

        # Se applicato a una classe, estrae in ordine i metodi decorati con @step
        if isinstance(cls_or_func, type):
            for attr_name in dir(cls_or_func):
                attr = getattr(cls_or_func, attr_name)
                if hasattr(attr, "__step_meta__"):
                    meta.steps.append(attr.__step_meta__)

        cls_or_func.__workflow_meta__ = meta
        return cls_or_func

    return decorator
