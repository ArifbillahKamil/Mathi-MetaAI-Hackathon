"""Trusted subprocess bootstrap. Run only through local.run_code.

Generated code runs with a reduced builtins mapping. Mathematical libraries
remain powerful, so a deployment still requires OS/container isolation.
"""

import builtins
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys


class OutputLimit(BaseException):
    pass


class CappedText(io.TextIOBase):
    def __init__(self, budget):
        self.parts = []
        self.budget = budget

    def write(self, text):
        encoded = text.encode("utf-8")
        if len(encoded) > self.budget[0]:
            raise OutputLimit()
        self.budget[0] -= len(encoded)
        self.parts.append(text)
        return len(text)

    def text(self):
        return "".join(self.parts)


def main():
    request = json.loads(sys.stdin.read())
    # Import parent-reviewed policy by trusted file path, never from route code.
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("mathi_code_policy", Path(__file__).with_name("guard.py"))
    policy = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = policy
    spec.loader.exec_module(policy)
    checked = policy.check_code(request["code"], max_source_bytes=request["max_source_bytes"])
    if not checked.allowed:
        print(json.dumps({"status": "REJECTED", "error": checked.reason}))
        return

    controller, driver = None, None

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in policy.IMPORTS:
            raise ImportError("Import not permitted by route policy.")
        if controller is not None and not controller.allow_import(name):
            raise ImportError("Import does not match the assigned mathematical method.")
        return builtins.__import__(name, globals, locals, fromlist, level)

    names = (
        "abs", "all", "any", "bool", "complex", "dict", "enumerate", "float",
        "int", "isinstance", "len", "list", "max", "min", "print", "range",
        "round", "set", "sorted", "str", "sum", "tuple", "zip", "Exception",
        "ValueError", "RuntimeError", "ArithmeticError", "ZeroDivisionError",
    )
    safe_builtins = {name: getattr(builtins, name) for name in names}
    safe_builtins["__import__"] = safe_import
    namespace = {"__builtins__": safe_builtins}
    budget = [request["max_output_bytes"]]
    stdout, stderr = CappedText(budget), CappedText(budget)
    record = {"status": "SUCCESS", "result": None, "error": None}
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            verification = request.get("verification")
            if verification is not None:
                import re
                name = verification['driver']
                if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
                    raise ValueError("Invalid trusted driver name.")
                driver_path = Path(__file__).resolve().parents[1] / 'modules' / 'drivers' / f'{name}.py'
                driver_spec = importlib.util.spec_from_file_location('mathi_method_driver', driver_path)
                driver = importlib.util.module_from_spec(driver_spec)
                sys.modules[driver_spec.name] = driver
                driver_spec.loader.exec_module(driver)
                controller = driver.create(verification['parameters'])
            exec(compile(request["code"], "<route>", "exec"), namespace, namespace)
            from pint import Quantity
            result = namespace.get("result")
            if isinstance(result, dict) and set(result) == {'quantities'} and controller is not None:
                quantities = result['quantities']
                if not isinstance(quantities, (list, tuple)) or len(quantities) > 16 or any(not isinstance(item, Quantity) for item in quantities):
                    raise ValueError('Set results require a bounded list of Pint quantities.')
                if not hasattr(controller, 'finalize_collection'):
                    raise ValueError('This execution contract does not support collection results.')
                record['result'] = controller.finalize_collection(quantities)
            else:
                record['result'] = scalar_result(result, Quantity, controller)
    except OutputLimit:
        record.update(status="OUTPUT_LIMIT", error="OUTPUT_LIMIT_EXCEEDED")
    except BaseException as exc:
        status = 'INVALID_RESULT' if driver is not None and isinstance(exc, driver.MethodCheckError) else 'RUNTIME_ERROR'
        record.update(status=status, result=None, error=f"{type(exc).__name__}: {str(exc)[:1000]}")
    if controller is not None:
        record['method_evidence'] = controller.snapshot()
    record.update(stdout=stdout.text(), stderr=stderr.text())
    # Only trusted code writes the final protocol envelope to the real stdout.
    print(json.dumps(record, allow_nan=False))


def scalar_result(result, Quantity, controller):
    if not isinstance(result, dict) or set(result) != {"quantity", "absolute_error"}:
        raise ValueError("Set result to a dict containing quantity and absolute_error.")
    quantity, error = result["quantity"], result["absolute_error"]
    if not isinstance(quantity, Quantity) or (error is not None and not isinstance(error, Quantity)):
        raise ValueError("Result quantity and any error estimate must be Pint quantities.")
    if error is not None and error.units != quantity.units:
        raise ValueError("Error estimate must use exactly the result's unit.")
    output = {"value": str(quantity.magnitude), "unit": str(quantity.units),
              "absolute_error": str(error.magnitude) if error is not None else None}
    if controller is not None:
        output = controller.finalize(quantity, error)
    return output


if __name__ == "__main__":
    main()
