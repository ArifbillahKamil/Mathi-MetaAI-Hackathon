"""Immutable, schema-constrained intake records. Expressions remain data."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, str_strip_whitespace=True)

    @model_validator(mode="after")
    def bounded_strings(self):
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, str) and (not value or len(value) > 8192):
                raise ValueError("Record strings must be nonempty and bounded.")
            if isinstance(value, tuple):
                if len(value) > 100:
                    raise ValueError("Record collections must be bounded.")
                if any(isinstance(item, str) and (not item.strip() or len(item) > 8192) for item in value):
                    raise ValueError("Collection strings must be nonempty and bounded.")
        return self


class ProblemClass(str, Enum):
    CALCULUS = "calculus"
    ALGEBRA = "algebra"
    LINEAR_ALGEBRA = "linear_algebra"
    ODE = "ode"
    ENGINEERING = "engineering"
    UNSUPPORTED = "unsupported"


class Task(str, Enum):
    DEFINITE_INTEGRAL = "definite_integral"
    INDEFINITE_INTEGRAL = "indefinite_integral"
    ROOTS = "roots"
    LINEAR_SYSTEM = "linear_system"
    INITIAL_VALUE_ODE = "initial_value_ode"
    WORK_ENERGY = "work_energy"
    OTHER = "other"


class AnswerShape(str, Enum):
    SCALAR = "scalar"
    SYMBOLIC = "symbolic"
    SET = "set"
    VECTOR = "vector"
    MATRIX = "matrix"
    FUNCTION = "function"


class Domain(str, Enum):
    REAL = "real"
    COMPLEX = "complex"
    UNSPECIFIED = "unspecified"


TASK_CLASSES = {
    Task.DEFINITE_INTEGRAL: ProblemClass.CALCULUS,
    Task.INDEFINITE_INTEGRAL: ProblemClass.CALCULUS,
    Task.ROOTS: ProblemClass.ALGEBRA,
    Task.LINEAR_SYSTEM: ProblemClass.LINEAR_ALGEBRA,
    Task.INITIAL_VALUE_ODE: ProblemClass.ODE,
    Task.WORK_ENERGY: ProblemClass.ENGINEERING,
}


class Given(StrictRecord):
    name: str
    value: str
    unit: str


class Problem(StrictRecord):
    interpretation: str
    problem_class: ProblemClass
    task: Task
    expression: str | None
    variables: tuple[str, ...]
    givens: tuple[Given, ...]
    unknowns: tuple[str, ...]
    expected_unit: str | None = Field(description=(
        "Use dimensionless for abstract mathematics without physical quantities. "
        "Use null only when physical unit information is genuinely missing; explain that in uncertainties."
    ))
    answer_shape: AnswerShape
    domain: Domain
    assumptions: tuple[str, ...]
    uncertainties: tuple[str, ...]

    @model_validator(mode="after")
    def consistent_structure(self):
        if not self.unknowns:
            raise ValueError("At least one unknown must be named.")
        for names in (self.variables, self.unknowns, tuple(item.name for item in self.givens)):
            if len(names) != len(set(names)):
                raise ValueError("Variable, unknown, and given names must be unique.")
        required_class = TASK_CLASSES.get(self.task)
        if required_class is not None and self.problem_class != required_class:
            raise ValueError("Problem class and task disagree.")
        return self
