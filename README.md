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

Development in this workspace began on October 29, 2026. Current components are
a deterministic **real scalar comparator**, an **independence guard**, a bounded
**local execution backend**, a stateless **Meta Model API client**, and
schema-constrained **dual intake and planning**, and an audited **two-route
execution workflow** for finite polynomial integrals, polynomial real-root sets,
and ideal vertical lifting work with physical units, with bounded **blind self-correction**.
See [the build log](docs/BUILD_LOG.md).

There is no runnable web application yet. The owner supplied one successful
live Meta-generated calculation. Self-correction is tested with mocked model
responses and real solver processes; a live correction still needs validation.
Other problem modules, symbolic/non-scalar comparison, container deployment,
and UI remain pending. No product accuracy evaluation has been performed.

## Setup and tests (PowerShell)

Python 3.11 or later; CPU only. The first component was tested on Python 3.12.9.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

After installing runtime requirements, tests also run with Python's built-in runner:

```powershell
python -m unittest discover -s tests -v
```

No key or network access is needed for tests or the offline demo. The app
stack remains Python, FastAPI, a static frontend, and pytest. Local validation
uses unittest because pytest is not installed. Dependencies are added with
their components.

## Scalar comparison contract

- Each `ScalarRoute` carries an executed value, an explicit unit (including
  `dimensionless`), and an absolute error estimate in that route's unit.
- `ComparisonContext` requires an expected unit, evidence from the
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

The scalar comparator supports finite real scalars and multiplicative
conversions with rational factors. Root sets use the separate set comparator
described below. Complex numbers, general expressions, vectors, matrices,
and functions cannot receive a verified verdict yet. Offset/log conversions
and fractional unit powers are withheld until their error handling is
implemented. Conversions that fall back to floating-point factors are also
withheld. Numeric representations are capped at 256
characters and decimal exponents at +/-1000.

The comparator consumes evidence; it does not itself establish that two routes
are independent, that their code really ran, or that error estimates are valid.
Tests supply explicit fixture evidence and do not represent verified product
runs. Those guarantees must be enforced by the execution pipeline before this
component is exposed through an API.

## Independence guard

The guard checks distinct controlled method IDs, normalized Python ASTs, and
fresh request payloads containing only the problem and each route's own method.
Layout, comments, and docstrings do not establish code difference. Attached
other-route fields and extra history are rejected. The planner's rationale is
audit-only and is not sent to either route.

These are necessary static checks, not proof of method fidelity or execution.
Different code may implement the same algorithm. Orchestration must enforce
separate model calls and executions using audited inputs. LLMs and API callers
must not supply trusted prerequisite evidence. Blind repairs use controlled
reason codes and fixed guidance; arbiter prose and peer results stay in audit.

## Local execution

`run_code(code, timeout, limits)` launches a separate Python process with an
allowlisted environment, a throwaway directory, AST pre-check, restricted
builtins/imports, deadline, and stdout/stderr cap. Execution records store code,
output, status, timing, and limits. Success alone does not verify an answer.

Generated code must assign `result` to a dict containing a Pint `quantity` and
an `absolute_error` Pint quantity in exactly the same unit. `None` is accepted
for a missing error estimate, but cannot establish numeric verification.
Reflective/file APIs and string-to-code parsers, including SymPy sympify and
lambdify and NumPy load/save, are deliberately excluded from the local policy.

This is a development backend, **not a complete sandbox**. Local memory limits
and network isolation are not enforced; libraries remain powerful. Keep this
backend local. Public deployment requires the planned container backend with
enforced resource limits and no network.

## Offline demo and live API check

```powershell
python -m app.demo
python -m app.llm.check
```

The demo runs curated SymPy and SciPy quadrature code for the integral of x
squared from 0 to 3 in separate processes. The executed quadrature error sets
the comparison limit. Its JSON includes both routes and the deterministic
comparison. No model requests are sent. This is explicitly a fixture-code
component demo, not a full natural-language solve. Reports go in gitignored
`artifacts/`.

The API check makes one live request, capped at 512 completion tokens, without
automatic retries. Put `META_API_KEY` in .env; the official `MODEL_API_KEY` name
is also accepted. Environment values override dotenv. Secrets are not exported
to child environments. Use only placeholders in .env.example.

The connectivity command uses only Python's standard library and can run before
installing mathematical dependencies. To run the mathematical components, use
the setup commands above, or install into the currently selected interpreter:

```powershell
python -m pip install -r requirements.txt
```

Use `python -m pip` so installation targets the same interpreter as the app.

The client uses the documented HTTPS Chat Completions endpoint and Standard-mode
`muse-spark-1.3`. It supports strict JSON-schema output, fresh message arrays,
request fingerprints, response size caps, sanitized errors, and redirect
rejection. Headers and credentials do not enter audit fingerprints or reprs.

On October 31, the owner reported a successful check from their normal terminal:
CONNECTED, muse-spark-1.3, ready=true, with 16 prompt and 19 completion tokens
(35 total). This confirms that terminal's key/model access. Agent-side socket
access remains restricted (WinError 10013). The owner later supplied two live
schema-valid intake responses for the integral example. They agreed but both
left expected_unit null, correctly stopping before planning. After explicit
unit confirmation, the owner supplied a successful live plan and execution:
Meta-generated quadrature returned 9.000000000000002 and symbolic integration
returned exactly 9. The difference, 2e-15, was below the executed quadrature
error estimate, 9.992007221626411e-14. Both method receipts passed and Comparator
returned VERIFIED. Route generation used 2955 model-reported tokens. This is
one successful live case, not a measured accuracy or false-verified rate.

API references: [Meta quickstart](https://dev.meta.ai/docs/quickstart),
[Chat Completions](https://dev.meta.ai/docs/protocols/chat-completions), and
[structured output](https://dev.meta.ai/docs/structured-output).

## Local files and measured validation

.gitignore excludes AGENTS.md, local agent configuration, environments, secrets,
and generated reports. .env.example, source, tests, and build documentation
remain versionable. Git ignore checks confirm that AGENTS.md, .env, and
artifacts/ remain excluded from the existing repository.

October 31: **253 unittest tests passed in 121.869 seconds** on Python 3.12.9,
Pint 0.24.4, and Pydantic 2.10.3: the previous 227 tests plus 11 set-comparator
and 15 algebra workflow tests. API tests mock transport; execution tests run
real processes.
pytest is not installed locally. No accuracy or false-verified rate is claimed.
Production tolerance calibration still requires evaluation on real problems.

## Try dual intake and planning

Install updated requirements into the same interpreter, then run:

```powershell
python -m pip install -r requirements.txt
python -m app.prepare "integral of x^2 from 0 to 3" --output artifacts/preparation.json
```

This is a live preparation command, with two separately prompted intake calls
and normally one planning call. Planning may retry once after schema/method
rejection, for at most four total calls. Each completion is capped at 2048
tokens; transport failures do not trigger automatic planner retries.

The report includes both raw parse responses, validated Problem records,
request hashes, model-reported usage, comparison fields, confirmation origin,
planning attempts, and rejection reasons. Extra fields such as answers, code,
and verdicts are rejected by local schemas. Expressions stay data and are not
evaluated during intake or planning.

`READY_FOR_ROUTES` means interpretation and planning passed their gates. It
does not mean the problem has been solved or verified. `NEEDS_CONFIRMATION`
stops before planning; both candidates and differing fields are returned.
Added assumptions, missing expected units/domains, and unresolved uncertainties
also require confirmation, even when the parses agree. CLI exit code 2 marks
this condition. New reports list specific `confirmation_reasons`, such as
`MISSING_EXPECTED_UNIT`, separately from interpretation differences.

Review the saved interpretations, then explicitly select one to resume without
another two intake calls. For the pure-math example whose only missing field is
the expected unit, selecting interpretation 1 and confirming a dimensionless
answer uses:

```powershell
python -m app.prepare --confirm-report artifacts/preparation.json --choice 1 --expected-unit dimensionless --output artifacts/preparation-confirmed.json
```

This calls only the Planner (with its existing bounded replanning policy).
Original candidates and raw responses remain in the audit unchanged; the
separate confirmation record identifies the chosen interpretation and the
unit supplied by the user. The original report file is preserved by writing a
new output path. No calculation verdict is produced.

There is no blanket null-to-dimensionless conversion. The intake prompt and
schema distinguish abstract mathematics from missing physical units; a null
still stops processing. Confirmation cannot clear unresolved uncertainties or
overwrite a conflicting known unit. Those cases need a clarified input. Saved
reports are editable local data, not authenticated model evidence: the selected
candidate is revalidated and its provenance is explicitly user-confirmed.

Human summary wording is excluded from agreement checks; collection order and
finite decimal given values are normalized. Other math/unit spellings are
compared conservatively and may request confirmation rather than assume
semantic equivalence. Agreement between parsers is not proof that an input was
understood correctly; the interpretation remains visible in the audit.

The planning catalog covers definite/indefinite integrals, roots, linear
systems, initial-value ODEs, and work/energy formulations. A plan can decline
an unsupported instance. Catalog entries describe method choices, not completed
execution modules. Current modules execute scalar polynomial integrals, real
polynomial root sets, and ideal vertical lifting work. General symbolic,
vector/matrix, and function comparison and other modules remain pending.
Planner checks select different known methods, preserve the confirmed class
and unit, and constrain sanity bounds. Those bounds never raise a verdict.

The basic API connectivity check still uses only the standard library. The
preparation command needs Pydantic; if missing, it returns a setup message
instead of a traceback.

## Generate and execute the first two routes

From a reviewed preparation report with status READY_FOR_ROUTES:

```powershell
python -m app.execute artifacts/preparation-confirmed.json --output artifacts/solution.json
```

The command revalidates the saved problem, confirmation, input hash, and plan.
Saved reports are editable local input, not authenticated model evidence. It
then constructs two fresh independent requests, collects both code generations
before executing either, checks their independence, and runs separate local
processes. Ordinarily this makes two Meta calls, each capped at 2048 completion
tokens, without repeating intake or the successful Planner call. One guard
rejection can trigger one reason-only replan and a new pair of generations:
at most five model calls, with no route execution before a guard passes.

The first calculus module supports real, dimensionless, one-variable polynomial
integrands with rational coefficients and finite decimal bounds. Expression
parsing walks an allowlisted AST without eval/sympify. Complexity is capped at
256 AST nodes and degree 100. Other inputs return UNVERIFIED before generation.
Execution modules live under app/modules with plan, route_a, route_b, and
sanity_checks entry points; selection is outside the core orchestrator.

Trusted worker-side method receipts require an actual SciPy quad call or SymPy
integrate call for the original bounds and expression. Numerical function
values are checked at every node visited by quad against the confirmed
polynomial; symbolic coefficients are checked against it exactly. These checks
do not claim symbolic proof of arbitrary numeric functions. Reported values
and errors must match the called routine. Hard-coded answers without a solver,
invented errors, wrong integrands, and wrong bounds cannot establish agreement.
Module attribute mutation is blocked by the AST policy.

Exact rational symbolic results use a 50-digit decimal encoding with an error
bound computed from the exact rational difference and rounded upward. Numerical
estimates come from quad. The first module's tight comparison limit is their
combined budget, capped exactly by Comparator; it has no extra agreement floor
or looser fallback. A solver estimate is still an estimate, not an absolute
correctness guarantee. Sanity bounds only lower verdicts. Wrong physical
dimensions are CONFLICT; shared wrong scales such as labeling 9 as percent
cannot bypass method-result checks.

The JSON stores the preparation, generation attempts, replans, code, limits,
solver receipts, raw outputs, check results, comparison, and final answer when
agreement succeeds. Failures remain UNVERIFIED or CONFLICT. Keep this backend
local until container isolation is implemented.

An offline replay of the owner's saved preparation is in
artifacts/execution-offline.json. It explicitly uses curated generation fixtures
and real solver executions, with zero live route-generation calls; its VERIFIED
result is component evidence, not proof that Meta generated valid code live.

## Bounded self-correction

Execution failures select only the failed route for a fresh generation. When
both routes run but conflict numerically, dimensionally, or against a sanity
bound, a separate arbiter can inspect both codes and results. Its explanation
is audit-only. The repaired route receives only the original Problem, its own
method, and a controlled bug code with fixed instructions. It never receives
the peer's code, answer, arbiter explanation, or prior conversation.

Every repair passes the independence guard and method receipts again, then
recomputes sanity checks and comparison. After any executed correction, only
tight agreement can produce VERIFIED. The loop does not relax bounds or
tolerances to obtain agreement. Unknown diagnoses stop; failed repair guards
stop and record that fresh replanning is required.

Defaults are two correction attempts and a 90-second correction budget. Each
attempt makes one generation call, plus one arbiter call when needed. Remaining
time caps subsequent request/socket and process timeouts; operating-system
cleanup and transport overhead can exceed the nominal budget. Successful
initial runs make no correction calls. Transport failures are not retried.

The existing execution command enables this behavior. Optional controls:

```powershell
python -m app.execute artifacts/preparation-confirmed.json --max-corrections 2 --correction-time-budget 90 --output artifacts/solution.json
```

Use --max-corrections 0 for a single-pass run. Correction history retains each
classification, both prior results, diagnosis, repair request/code, guard,
execution, and comparison. Self-correction has been tested with mocked model
responses and actual solver processes; a live Meta correction is not yet
claimed. The owner's successful live case required no correction.

An offline correction audit is saved locally as artifacts/correction-offline.json.
It labels model/arbiter responses as mocked and records real executions: a unit
conflict, a blind repair of A, and tight verified agreement after three total
route executions. It made zero live API calls.

## Engineering work with physical units

The engineering module computes work **by a lifting force** during ideal vertical
motion at constant speed, with constant positive gravity and no energy losses.
It requires explicit mass, gravity, and signed height_change quantities. It does
not infer Earth gravity or apply this model to net work, work by gravity,
acceleration, friction, or an inclined plane. Missing information and additional
physical assumptions must pass the existing intake confirmation gate.

The interpreted model is work_energy / vertical_lift_constant_speed. Energy
balance evaluates the exact symbolic potential-energy change; force balance
numerically integrates the constant lifting force over displacement. Separate
processes bind the energy formula, input quantities, actual force evaluations,
integration bounds, returned values, and method errors to trusted receipts.
The worker supplies exact rational unit factors while generated code still
constructs UnitRegistry() without arguments. No sandbox import or constructor
restrictions were relaxed.

The numerical receipt separates QUADPACK's estimate from a computed bound on
representing the original exact inputs as binary floats. Comparison uses their
sum, plus any exact-result decimal conversion bound; no agreement floor is
added. A wrong physical dimension produces CONFLICT, and simply relabeling
joules as kilojoules without converting the magnitude is rejected. Lowering
uses negative height_change and can produce negative lifting-force work.

An offline run with 5000 g, height change 200 cm, and gravity 981 cm/s**2 returned
98.1 joule with VERIFIED. Its audit is artifacts/lift-offline.json, explicitly
labeled as mocked model generation with actual solver executions and zero live
API calls. Live Meta behavior for this new module remains to be validated.

To try it live, prepare the explicit physical problem and execute only after
the preparation status is READY_FOR_ROUTES:

```powershell
python -m app.prepare "Find the work by the lifting force for an ideal vertical lift at constant speed with no energy losses. Mass=5000 g, height change=200 cm, constant gravity=981 cm/s**2. Return joules." --output artifacts/lift-preparation.json
python -m app.execute artifacts/lift-preparation.json --output artifacts/lift-solution.json
```

If intake requests confirmation, review its candidates and use the existing
--confirm-report workflow before execution. The final answer is selected using
the smaller audited method error after converting errors to a common unit;
selection never changes the comparator verdict.

Implementation references: [SciPy quad](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.integrate.quad.html)
and [SymPy expansion](https://docs.sympy.org/latest/modules/core.html#sympy.core.function.expand).

## Real polynomial root sets

The algebra module admits dimensionless univariate polynomials of degree one
through six, with bounded rational coefficients and domain real. It solves the
polynomial equal to zero and returns all **distinct real roots**. Multiplicities
are recorded separately. Constant/zero polynomials, complex-domain requests,
physical-unit roots, and nonpolynomial expressions remain unsupported.

The symbolic route executes SymPy solve with a real variable and retains exact
algebraic results. The numerical route executes SciPy brentq separately for each
root, using independently selected brackets and the original polynomial function.
An even-multiplicity root must be found at a bracket endpoint for this first
numerical implementation; sign-change scanning does not prove completeness.
Some admitted polynomials can therefore remain UNVERIFIED, rather than having
roots omitted or guessed.

Both worker receipts use exact root isolation of the original polynomial as an
audit-only coverage check. They verify that every distinct real root is covered
once. This is a shared verifier dependency, not a third independent model
route. Isolation intervals and peer outputs never enter generation requests.
Numerical function values are checked at every solver evaluation. Close roots
that cannot be distinguished within a solver error neighborhood are rejected;
they are never silently merged. Empty real-root sets cannot currently establish
numerical verification without an executed numerical method.

Numerical bounds follow the executed Brent termination settings (xtol=1e-12,
rtol=1e-14), plus the exact binary-to-decimal representation difference. Exact
root isolation must also confirm those bounds against the original polynomial;
a solver claim alone is insufficient. Symbolic roots are decimal-encoded with
a computed bound from their exact isolating intervals, and exact expressions
remain in the receipts. No sampled-expression equivalence is presented as proof.

The set comparator finds a complete one-to-one match using each root pair's
error budget. Order and exact duplicates do not affect mathematical set equality;
nearby distinct values are not deduplicated. Missing roots, unmatched roots,
unit mismatches, and correction strictness remain deterministic decisions.
The worker rejects omitted or duplicate solver results before comparison.

Collection reports use result.values, result.absolute_errors, and answer_shape
set. Scalar reports retain their existing fields. Generation returns a bounded
list of Pint quantities; only the trusted worker supplies error bounds.
The existing correction loop handles root sets and uses fixed coverage or
expression repair guidance without peer answers.

To try the module live:

```powershell
python -m app.prepare "Find all distinct real roots of x**2 - 3*x + 2 = 0." --output artifacts/roots-preparation.json
python -m app.execute artifacts/roots-preparation.json --output artifacts/roots-solution.json
```

Review any requested intake confirmation before execution. Live Meta generation
for this module has not yet been validated. Offline audits in
artifacts/roots-quadratic-offline.json, roots-repeated-offline.json, and
roots-irrational-offline.json use mocked model responses and actual solver
executions, with zero live API calls.

References: [SciPy Brent solver and termination criterion](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.optimize.brentq.html),
[SymPy polynomial root solving](https://docs.sympy.org/latest/guides/solving/find-roots-polynomial.html),
and [exact polynomial root isolation](https://docs.sympy.org/latest/modules/polys/reference.html#sympy.polys.polytools.Poly.intervals).

References used for the scalar implementation: [Pint tutorial](https://pint.readthedocs.io/en/stable/getting/tutorial.html)
and [Python decimal documentation](https://docs.python.org/3/library/decimal.html).
