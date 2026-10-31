"""Conservative Python pre-check; this is not an OS security boundary."""

import ast
from dataclasses import dataclass


IMPORTS = {
    "math": {"sqrt", "sin", "cos", "tan", "exp", "log", "log10", "pi", "e", "fabs", "fsum", "isfinite", "factorial", "comb"},
    "sympy": {"Symbol", "symbols", "Integer", "Rational", "Float", "pi", "E", "I", "sin", "cos", "tan", "exp", "log", "sqrt", "Abs", "Matrix", "Eq", "Function", "Derivative", "Integral", "integrate", "diff", "solve", "solveset", "simplify", "factor", "expand", "cancel", "together", "det", "eye", "zeros", "dsolve", "N", "limit"},
    "numpy": {"array", "linspace", "zeros", "ones", "eye", "dot", "cross", "matmul", "sum", "max", "min", "abs", "sqrt", "sin", "cos", "exp", "log", "pi", "float64", "complex128", "linalg", "isfinite", "all", "mean"},
    "numpy.linalg": {"solve", "lstsq", "eigvals", "eig", "det", "inv", "norm", "svd"},
    "scipy.integrate": {"quad", "solve_ivp", "trapezoid", "simpson"},
    "scipy.linalg": {"solve", "lu_factor", "lu_solve", "solve_triangular", "svd", "eig"},
    "scipy.optimize": {"root", "root_scalar", "brentq", "newton"},
    "pint": {"UnitRegistry", "Quantity"},
}
MODULE_ATTRIBUTES = {part for module in IMPORTS for part in module.split(".")}
SAFE_ATTRIBUTES = set().union(*IMPORTS.values()) | MODULE_ATTRIBUTES | {
    "to", "to_base_units", "magnitude", "units", "dimensionality", "Quantity",
    "subs", "evalf", "diff", "integrate", "simplify", "det", "inv", "norm",
    "shape", "T", "tolist", "item", "real", "imag", "conjugate", "reshape",
    "success", "message", "y", "t", "sol", "x", "fun", "error", "append",
}
FORBIDDEN_NAMES = {
    "open", "eval", "exec", "compile", "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr", "type", "object", "super", "input",
    "help", "breakpoint", "exit", "quit", "memoryview", "classmethod",
    "staticmethod", "property", "bytes", "bytearray", "chr", "get_ipython",
}
FORBIDDEN_NODES = (
    ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith,
    ast.With, ast.Try, ast.TryStar, ast.Global, ast.Nonlocal, ast.Delete,
)


@dataclass(frozen=True)
class CodeCheck:
    allowed: bool
    reason: str


def check_code(code: str, *, max_source_bytes: int = 32768) -> CodeCheck:
    if not isinstance(code, str) or not code.strip():
        return CodeCheck(False, "EMPTY_CODE")
    if len(code.encode("utf-8")) > max_source_bytes:
        return CodeCheck(False, "SOURCE_TOO_LARGE")
    try:
        tree = ast.parse(code)
        compile(tree, "<route>", "exec")
    except (SyntaxError, ValueError, RecursionError):
        return CodeCheck(False, "INVALID_SYNTAX")
    registry_aliases = {"UnitRegistry"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pint":
            registry_aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "UnitRegistry")
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_NODES):
            return CodeCheck(False, "FORBIDDEN_SYNTAX")
        if isinstance(node, ast.Name) and (node.id.startswith("_") or node.id in FORBIDDEN_NAMES):
            return CodeCheck(False, "FORBIDDEN_NAME")
        if isinstance(node, ast.arg) and (node.arg.startswith("_") or node.arg in FORBIDDEN_NAMES):
            return CodeCheck(False, "FORBIDDEN_NAME")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.decorator_list or node.name.startswith("_") or node.name in FORBIDDEN_NAMES:
                return CodeCheck(False, "FORBIDDEN_FUNCTION")
        if isinstance(node, ast.Import):
            if any(alias.name not in IMPORTS for alias in node.names):
                return CodeCheck(False, "IMPORT_NOT_ALLOWED")
            if any((alias.asname or alias.name).startswith("_") for alias in node.names):
                return CodeCheck(False, "FORBIDDEN_NAME")
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in IMPORTS:
                return CodeCheck(False, "IMPORT_NOT_ALLOWED")
            if any(alias.name not in IMPORTS[node.module] for alias in node.names):
                return CodeCheck(False, "IMPORT_MEMBER_NOT_ALLOWED")
            if any((alias.asname or alias.name).startswith("_") for alias in node.names):
                return CodeCheck(False, "FORBIDDEN_NAME")
        if isinstance(node, ast.Attribute) and node.attr not in SAFE_ATTRIBUTES:
            return CodeCheck(False, "ATTRIBUTE_NOT_ALLOWED")
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            return CodeCheck(False, "ATTRIBUTE_MUTATION_NOT_ALLOWED")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, (ast.Name, ast.Attribute)):
                return CodeCheck(False, "INDIRECT_CALL_NOT_ALLOWED")
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if (name in registry_aliases or name == "UnitRegistry") and (node.args or node.keywords):
                return CodeCheck(False, "CUSTOM_UNIT_REGISTRY_NOT_ALLOWED")
    return CodeCheck(True, "CODE_ALLOWED")
