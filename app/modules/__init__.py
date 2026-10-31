"""Execution module registry; add modules here without editing orchestration."""


def select_module(problem):
    from app.modules import calculus, engineering, algebra
    for module in (calculus, engineering, algebra):
        if module.supports(problem):
            return module
    return None
