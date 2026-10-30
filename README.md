# Mathi

Math that checks itself.

Mathi is being built to solve and cross-check quantitative problems for engineers,
scientists, analysts, and advanced students. Its central rule is that a verified
answer requires two independent methods executed as real code, with matching
results and completed unit and sanity checks.

Solo entry in the **Indie Developer** track of the Meta Global AI Developer
Hackathon, under the **Push the Frontier** theme. Available inference credit:
Meta US$150; no partner credits are assumed.

## Built during the hackathon

Development in this workspace began on October 29, 2026. The current component is
a deterministic **real scalar comparator**, with unit tests and JSON-safe
comparison evidence. See [the build log](docs/BUILD_LOG.md).

There is no runnable web application yet. The Meta client, route executor,
independence guard, intake, planner, symbolic comparison, non-scalar comparison,
self-correction orchestration, and UI are pending. No baseline evaluation or
product accuracy measurement has been performed.

## Setup and tests (PowerShell)

Python 3.11 or later; CPU only. The first component was tested on Python 3.12.9.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The tests also run with Python's built-in runner when Pint is already installed:

```powershell
python -m unittest discover -s tests -v
```

No API key or network access is needed to run the comparator. The planned app
stack is Python, FastAPI, a static frontend, and pytest; dependencies are added as
their components are implemented. `.env.example` reserves a future credential
setting; no Meta endpoint or model ID is configured yet.

## Scalar comparison contract

- Each `ScalarRoute` carries an executed value, an explicit unit (including
  `dimensionless`), and an absolute error estimate in that route's unit.
- `ComparisonContext` requires an expected unit, evidence from the future
  independence guard, and completed applicable sanity checks. `None` means checks
  did not run; an empty sanity-check tuple explicitly means no bounds apply.
- The caller must provide all four `ScalarTolerance` settings. There are no
  production defaults and test tolerances are synthetic, not calibrated.
- Tight and loose thresholds each use `absolute + relative * max(abs(A), abs(B))`.
  Both are capped by the **sum of the methods' absolute error estimates**, after
  unit conversion. This is not a guarantee that a solver's estimate is correct.
- `VERIFIED_WITH_DEVIATION` also requires a documented likely cause. Following a
  correction, only tight agreement can produce a verified verdict.
- Failed execution or missing prerequisite evidence gives `UNVERIFIED`. A known
  dimension mismatch or failed sanity check gives `CONFLICT`. Passing a sanity
  check cannot turn numerical disagreement into agreement.

Values may be integers, floats, or decimal strings. Floats are interpreted by
their serialized decimal representation; solvers should return decimal strings
when more precision is needed. Arithmetic uses fractions and Pint conversion
factors without binary floating-point rounding. Evidence stores **exact rational
strings**, such as `1/2000`, for values, differences, and limits; relative
differences are dimensionless. `ComparisonResult.to_dict()` is JSON-safe.

Only finite real scalars and multiplicative conversions with rational factors
are currently supported. Complex numbers, expressions, sets, vectors, matrices,
and functions cannot receive a verified verdict here. Offset/log conversions
and fractional unit powers are withheld until their error handling is
implemented. Conversions that fall back to floating-point factors are also
withheld. Numeric representations are capped at 256
characters and decimal exponents at +/-1000.

The comparator consumes evidence; it does not itself establish that two routes
are independent, that their code really ran, or that error estimates are valid.
Tests supply explicit fixture evidence and do not represent verified product
runs. Those guarantees must be enforced by the execution pipeline before this
component is exposed through an API.

References used for the implementation: [Pint tutorial](https://pint.readthedocs.io/en/stable/getting/tutorial.html)
and [Python decimal documentation](https://docs.python.org/3/library/decimal.html).
