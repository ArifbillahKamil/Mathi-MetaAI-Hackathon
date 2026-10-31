# Build log

## 2026-10-29 — Scalar comparator

- Confirmed solo Indie Developer entry and the Push the Frontier theme.
- Confirmed Meta US$150 credit only; retained the proposed Python/FastAPI/static
  frontend stack. Only Pint is needed by the current runtime component.
- Built the deterministic real scalar comparator, explicit tolerance config,
  bounded decimal input parsing, and JSON-safe comparison evidence.
- Added unit conversion and dimensional mismatch handling, solver-error caps,
  prerequisite evidence gates, and strict comparison after correction.
- Added behavioral tests for numerical boundaries, precision preservation,
  missing evidence, invalid units and values, and correction policy.
- Dependency downloads were blocked by the session's network restrictions.
  Used locally installed Pint 0.24.4 and Python 3.12.9 with the standard-library
  unittest runner. pytest remains the planned runner; it was not available in
  this session. No Meta API calls or inference credits were used.
- Initial execution: 44 unittest tests passed. Subsequent malformed-unit
  probing exposed a tokenizer exception; fixed it and added regression coverage
  plus a test for fractional unit powers. That test exposed Pint's Fraction
  formatting limitation and approximated fractional-power conversion factors;
  fractional unit powers now explicitly yield UNVERIFIED until separate
  conversion-error handling is implemented.
- Final validation: `python -m unittest discover -s tests -q` passed all 46
  tests on Python 3.12.9 with Pint 0.24.4. Python compilation checks passed for
  the initial component and tests; no pytest execution is claimed.
- No end-to-end evaluation, baseline accuracy, or false-verified rate is claimed.

## 2026-10-30 - Independence guard and local-file exclusions

- Updated .gitignore for AGENTS.md, agent configuration, environments, secrets,
  and generated files; preserved .env.example.
- Built the controlled-method/AST/payload guard and blind request builder.
  Added 18 tests; actual validation passed 64 tests including 46 comparator tests.
- Git ignore behavior passed 15 path checks in a temporary repository. The
  project workspace was not initialized as a Git repository.
- Tool access errors prevented documentation updates. Preserved these results
  in BUILD_LOG_PENDING.md, now merged here on October 31. No Meta calls made.

## 2026-10-31 - Local execution and Meta API boundary

- Detected META_API_KEY in .env without printing it.
- Built run_code with AST policy, restricted builtins/imports, environment
  allowlisting, temporary cwd, isolated Python processes, deadlines, output caps,
  Pint result extraction, and execution audit records. Added 18 tests.
- Used installed SymPy 1.14.0, NumPy 2.4.4, SciPy 1.15.3, and Pint 0.24.4;
  pinned mathematical dependencies. No HTTP/SDK dependencies were added.
- Checked official Meta docs for endpoint, authentication, models, token limits,
  stateless Chat Completions, and strict structured output. Built the client and
  connectivity command; added 19 offline tests using mocked transport.
- Live connectivity failed before HTTP. An unauthenticated diagnostic confirmed
  PermissionError / WinError 10013. Key validity, model access, and real API
  responses remain unverified; no successful completion or usage was measured.
- Added a curated offline two-route demo and real-process integration test.
  SymPy returned 9; quadrature returned 9.000000000000002. Difference: 2e-15;
  executed quadrature error estimate: 9.992007221626411e-14. The deterministic
  comparator produced VERIFIED. This is not a live model evaluation.
- Final suite: 102 unittest tests passed (46 comparator + 18 guard + 18 sandbox
  + 19 client + 1 integration). pytest was not installed or run.
- Saved audit in gitignored artifacts/offline-demo.json. Updated documentation
  and merged the pending October 30 entry.
- Container isolation, intake/planner, symbolic/non-scalar comparison,
  correction orchestration, and UI remain pending. No product accuracy or
  false-verified rate is claimed.
- Final file hygiene: Git ignore checks passed on 16 paths; the configured
  API credential was absent from 25 inspected source/documentation/config files.

### API check dependency correction

- The owner reported ModuleNotFoundError for Pint when checking API connectivity
  from another Python environment. The request had not reached the API.
- Moved shared check evidence records to a standard-library-only module. Kept
  comparator imports compatible while removing the API client's indirect Pint
  dependency through the independence guard.
- Added two regression tests launching Python with -S (no site-packages),
  covering API-check imports and the CLI with mocked transport. No live API
  requests are made by these tests.
- Full suite after the correction: 104 unittest tests passed. Documented
  python -m pip install -r requirements.txt for the full mathematical runtime;
  the API connectivity command itself needs only the Python standard library.

### Dual intake and planning

- Owner supplied a successful live connectivity JSON from their normal terminal:
  muse-spark-1.3, ready=true, prompt_tokens=16, completion_tokens=19, total=35.
  This is owner-reported API evidence, not an agent-side live measurement.
- Built immutable Pydantic Problem records, strict JSON/schema validation,
  duplicate-key rejection, two blind intake prompts, deterministic specification
  comparison, and explicit confirmation gates. Prose summaries are retained but
  excluded from comparison; finite decimal givens and collection order normalize.
- Added 20 intake tests, including differing bounds/units/domains, missing data,
  assumptions, schema injection, failed calls, immutable data, audit retention,
  and proof that parse two receives no output from parse one.
- Built schema-constrained planning with a controlled task/method catalog,
  class/unit checks, validated sanity bounds, unsupported results, a default
  two-attempt planning budget, and reason-only replanning. Added a manual
  integration method ID for planning; its execution module is still pending.
- Added 17 planner tests and 6 preparation/CLI tests. Preparation stops before
  planning on ambiguity, records all attempts, and never executes route code
  or emits a calculation verdict. Added python -m app.prepare with JSON output.
- Pinned the already selected Pydantic dependency to the installed/tested 2.10.3.
  The basic API check remains independent of Pydantic and all math packages.
- Final validation after these additions: 147 unittest tests passed (previous
  104 + 20 intake + 17 planner + 6 preparation). These new model calls are mocked;
  live structured-output behavior is not claimed. No paid agent-side requests
  were added during this step, and no accuracy/false-verified rate is claimed.

### Missing expected-unit regression and saved confirmation

- Owner supplied the live integral preparation result: both schema-valid parses
  agreed on x**2 over 0..3, but both returned expected_unit=null with no listed
  uncertainty. Intake stopped with AMBIGUITY_OR_ASSUMPTIONS; Planner did not run.
  Reported usage was 1125 and 1257 total tokens for the two calls.
- Clarified prompt/schema guidance: abstract mathematics uses dimensionless;
  missing physical units remain unknown. Did not add automatic unit inference.
- Added specific confirmation reasons, including MISSING_EXPECTED_UNIT.
- Added --confirm-report, --choice, and --expected-unit to explicitly continue
  from a reviewed audit. Original candidates/responses are preserved; supplied
  units and selection are recorded as user confirmation. No intake calls repeat.
- Revalidate loaded candidates; reject invalid/executed reports, conflicting
  known units, duplicate JSON keys, and unresolved uncertainty before planning.
  Saved files are treated as user-editable data, not authenticated evidence.
- Added 17 regression/CLI tests. Full suite: 164 unittest tests passed.
- Also replayed the actual saved owner report with a simulated user selection
  and mocked Planner: READY_FOR_ROUTES, dimensionless, one mocked planner call,
  zero live calls, and original report unchanged. This is an offline regression,
  not a claim of live Planner success or an actual user confirmation.

### First generated-route execution workflow

- Owner supplied READY_FOR_ROUTES after explicit unit confirmation. The live
  Planner selected numerical quadrature for A and symbolic integration for B,
  with a 0..27 sanity bound. Reported usage: 807 prompt + 881 completion = 1688
  tokens. This is owner-reported Planner evidence; no routes had run yet.
- Added an execution-module registry and the first calculus capability: finite,
  dimensionless univariate polynomial integrals with rational coefficients.
  Module interface supplies plan, route_a, route_b, and sanity_checks.
- Added an allowlisted polynomial AST interpreter and trusted worker-side solver
  receipts. Require original bounds/integrand, an executed solver, and matching
  result/error fields; no LLM-generated error estimate is accepted as evidence.
- Exact rational output is decimal-encoded with its computed upward-rounded
  conversion-error bound. Quad estimates come from the actual solver. Comparator
  uses the combined error budget without an arbitrary agreement floor.
- Added per-method imports, module-attribute mutation rejection, and checks that
  compatible but scaled dimensionless units cannot manufacture agreement.
  Retained hard CONFLICT behavior for physical dimension mismatches.
- Added blind concurrent code generation, normalized-code guard checks, one
  bounded reason-only Planner replan on independence rejection, separate local
  executions, sanity bounds, deterministic comparison, and full JSON audit.
- Added app.execute to resume a ready preparation without redoing intake or
  successful planning. Reports distinguish method execution from code generation
  and mark the not-yet-implemented self-correction loop explicitly.
- Validation: 192 unittest tests passed (previous 164 + 14 method-receipt/parser
  + 14 execution-workflow/CLI). New tests use mocked generation and real child
  processes, including fabricated errors, wrong units/scales, wrong problems,
  generation failures, guard-budget exhaustion, and actual rational integration.
- Revalidated the owner's actual saved preparation and replayed it using curated
  generation fixtures: two solver processes, final value 9 dimensionless,
  absolute difference 2e-15, and quad error estimate 9.992007221626411e-14.
  Comparator returned VERIFIED. Saved artifacts/execution-offline.json clearly
  labels the fixture generation and zero live route-generation calls.
- No live route generation was tested by the agent. Other execution modules,
  general symbolic/non-scalar comparison, self-correction, container deployment,
  and UI remain pending. No product accuracy/false-verified rate is claimed.

### First owner-reported live verified calculation

- Owner supplied the complete live executed report for x**2 integrated over
  0..3. Meta-generated Route A used SciPy quad and Route B used SymPy integrate
  in separate processes, each with one audited solver call. The numerical
  receipt checked 21 function evaluations against the original polynomial.
- A returned 9.000000000000002 with solver error 9.992007221626411e-14; B
  returned exact 9 with zero method error. Difference 2e-15 was within the
  tight method budget; units, independence, and sanity checks passed.
  Comparator returned VERIFIED, final value 9 dimensionless.
- Model-reported route-generation usage: 1323 + 1632 = 2955 total tokens.
  No corrections or replans were required. This validates one live case, not
  an accuracy or false-verified rate. No additional paid requests by the agent.

### Bounded blind self-correction

- Added deterministic failure classification, failed-route-only regeneration,
  and a separate schema-constrained conflict arbiter. Its free-text explanation
  is retained only in audit. Blind fixes receive the original Problem, own
  method, and an enum reason mapped to fixed guidance; no peer results/code or
  arbiter prose enter a correction request.
- Recheck guards and executed method receipts after every rewrite. Corrections
  must pass tight comparison. Unknown diagnoses stop without changing checks;
  rejected repair guards stop and flag the need for fresh replanning.
- Defaults: at most two corrections and a 90-second phase budget. Remaining
  time caps request and process timeouts. Added CLI controls and no automatic
  transport retries. Successful initial runs issue no correction calls.
- Added 9 contract tests and 11 workflow tests, each group passing separately.
  These use mocked model responses and real child processes; live Meta
  self-correction has not been tested. Fixed correction budget timing to use
  Windows' high-resolution performance counter.
- Full regression suite: 212 unittest tests passed in 53.248 seconds. Replayed
  a dimensional conflict with mocked generation/diagnosis and actual solver
  processes: CONFLICT -> VERIFIED, three total route executions, zero live API
  calls. Saved the explicitly labeled artifacts/correction-offline.json audit.
- Checked 57 source, test, documentation, and local report files for the actual
  configured credential without printing it: zero matches. AGENTS.md and all
  generated reports remain excluded by .gitignore.

### First engineering module with physical units

- Added ideal constant-speed vertical lifting work, with explicit mass,
  constant gravity, and signed height_change. Intake distinguishes lifting-force
  work from net work or gravity work and does not invent gravity or silently
  add physical conditions. Other engineering models remain unsupported.
- Energy balance evaluates the symbolic potential-energy change with exact
  rational quantities. Force balance performs actual numerical quadrature of
  lifting force over displacement. Worker receipts bind formulas, input unit
  conversions, function evaluations, bounds, results, and error estimates.
- The worker supplies rational unit factors; generated code still uses an
  argument-free UnitRegistry. Existing sandbox restrictions remain intact.
  Numerical receipts separately expose solver error and a calculated bound
  for input representation in binary floats, rather than an agreement floor.
- Added a generic answer-source selector using audited errors in a common unit,
  removing the orchestrator's assumption that only symbolic integration can
  supply an exact answer. Added the module through the execution registry.
- Fourteen new engineering tests passed in 36.311 seconds, using mocked model
  responses and real subprocesses. Then added a preparation-gate regression
  for missing gravity and added assumptions before the full regression run.
- Full regression: 227 unittest tests passed in 90.198 seconds. Saved
  artifacts/lift-offline.json with explicit mocked-model provenance: exact energy
  and numerical force methods each returned 98.1 joule in separate processes;
  Comparator returned VERIFIED. Zero live API calls were made for this module.
- Scanned 63 code, test, documentation, and local report files for the configured
  credential without displaying it: zero matches. No new dependencies added.

### Polynomial real-root sets

- Added a deterministic set comparator with complete one-to-one matching,
  order-independent equality, exact duplicate handling, per-root error budgets,
  existing prerequisite/unit gates, and tight-only correction behavior. The first
  10 tests passed; added an exponent-encoding regression before the full suite.
- Extended the worker protocol with bounded Pint quantity collections while
  preserving scalar reports. Collection error bounds come only from trusted
  receipts. The common orchestrator dispatches comparison by answer shape;
  final-answer selection now also handles per-root errors.
- Added polynomial roots up to degree six with bounded rational coefficients,
  real domain, and dimensionless variables. Independent computations execute
  exact symbolic solve and numerical Brent bracketing in separate processes.
- Worker-side exact root isolation checks complete coverage, multiplicities,
  and each numerical error neighborhood against the original polynomial. This
  is a shared audit dependency, never data sent to either route's model call.
  Every numerical function evaluation is checked against the original AST.
- Keep exact symbolic expressions in receipts; decimal encoding uses a proven
  interval bound. Numerical errors follow actual Brent termination settings
  and representation error, with no arbitrary agreement floor. Missing roots,
  duplicates, wrong functions, altered results, and ambiguous close roots fail.
- Thirteen execution tests passed in 25.218 seconds, then added coverage-repair
  and inflated-tolerance regressions. Fixed repair enums convey coverage or
  expression problems without peer code, answers, or free-form diagnosis.
- Complex-domain problems, constants, nonpolynomials, and empty-set numerical
  verification remain unsupported. Even-multiplicity roots require suitable
  endpoint brackets for the first numeric method. No new dependencies added.
- Full regression: 253 unittest tests passed in 121.869 seconds (previous 227
  plus 11 set-comparator and 15 algebra workflow tests). Existing scalar,
  engineering, sandbox, API, independence, and correction regressions passed.
- Saved three labeled offline audits: quadratic roots {1, 2}, repeated-root
  answers {-2, 1} with multiplicity recorded, and irrational roots +/-sqrt(2)
  with encoding bounds. Each used two actual solver processes and mocked model
  responses, returned VERIFIED, and made zero live API calls. Live Meta root
  generation is not claimed, nor any product accuracy/false-verified rate.
- Credential scan across 72 code, test, documentation, and local audit files
  found zero configured-key matches without displaying the key. Generated
  audits remain gitignored; no secrets or dependencies were added.
