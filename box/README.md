# box/ — the Lex boundary around the Python pipeline

Subsuelo's computation stays in Python: it leans on GDAL, PROJ and GEOS
(`gpd.read_file` ×25, `.to_crs` ×32, `rasterio.rasterize`/`reproject`), and no
amount of enthusiasm makes those reachable from Lex today. What *is* worth
moving is the part that has nothing to do with geometry — **what the pipeline
is allowed to touch, and what the output owes** — because that is exactly the
kind of property a type system can carry and a supervisor can enforce.

So the split is:

```
  lex-os grant  ──supervises──▶  python build.py  ──emits──▶  out/provenance.json
  (what it may reach)            (GDAL/PROJ/GEOS)                     │
                                                                      ▼
                                                        lex attribution gate
                                                                      │
                                                    publish  ◀───┴───▶  REFUSE
```

Neither half needs the other rewritten.

---

## A. `subsuelo.manifest.json` — what the pipeline may reach

A lex-os manifest whose `egress` list enumerates **every host subsuelo
legitimately fetches** — 18 of them, from IGME and EGDI through five national
cadastres to Eurostat and Natural Earth. Outside that list the box simply
cannot open a connection.

```sh
# run the pipeline inside a supervised box
lex-os run --manifest box/subsuelo.manifest.json

# what does the manifest resolve to?
lex-os resolve --manifest box/subsuelo.manifest.json

# verify the audit chain afterwards
lex-os audit verify --log out/audit.json
```

The grant is `filesystem: ReadWrite` (it writes `out/`), `network: Allowlist`
(the egress list), `exec: Sandboxed` (it runs one interpreter, not arbitrary
binaries), with `isolation_floor: Namespace` — adequate here because the box
never gets `exec: full`.

**What this buys, concretely:**

- A new ingestor pointed at an undeclared host **fails at the perimeter**
  rather than silently adding a dependency nobody reviewed.
- The egress list is honest documentation: it cannot drift from reality,
  because reality is enforced against it.
- `api.idealista.com` being in the list is a *visible* decision rather than a
  line buried in a 1,194-line module — which is the practical half of
  [#4](https://github.com/alpibrusl/subsuelo/issues/4).
- A compromised or confused dependency cannot exfiltrate to anywhere else.

**Budget** is set to 90 minutes wall clock and 4,000 API calls — a full
multi-region cold build with an empty cache. Tighten it once you know the real
number for your regions; a budget that never binds is not a budget.

---

## B. The attribution gate — what the output owes

Three Lex modules, all pure except one `[io]` entry point:

| File | What it is |
| --- | --- |
| `licence.lex` | Licences as a lattice, and the obligations a join inherits |
| `sources.lex` | The licence classification for all 18 hosts — the single place terms are declared |
| `attribution_gate.lex` | Reads `out/provenance.json`, decides, refuses or reports |

```sh
lex check box/licence.lex box/sources.lex box/attribution_gate.lex
lex fmt --check box/*.lex
lex run --allow-effects io box/attribution_gate.lex main
```

All three modules type-check against **lex 0.10.7**, and the `examples {}`
blocks run as tests at check time — verified by breaking one deliberately and
watching `lex check` report `example_mismatch`. `lex check` also confirms the
gate's effect row is exactly `io`, which is the claim the next paragraph makes.

Against the fixtures in `testdata/`:

```
$ lex run --allow-effects io box/attribution_gate.lex main   # clean build
provenance: 6 fetches
share-alike: no
attribution notices required on the published artifact:
  · © Instituto Geológico y Minero de España (IGME-CSIC)
  · Dirección General del Catastro (España)
  · DVF — data.gouv.fr, Licence Ouverte / Etalab 2.0
  · © GeoSN, dl-de/by-2-0
  · © European Union, Eurostat

$ ...                                                        # restricted build
provenance: 3 fetches
REFUSED — these sources may not be redistributed:
  ✗ api.idealista.com  [idealista (commercial API — not redistributable)]
  ✗ opendata.example-region.gov  [UNDECLARED SOURCE]

Declare the source in box/sources.lex, or exclude its values from
the published artifacts. There is no override.
```

The second case shows both refusal modes working: a source classified
`Restricted`, and an ingestor pointed at a host nobody declared.

The gate answers the question the Python side cannot answer about itself:
*given everything this build actually touched, may we publish it, and what
notices does the output owe?*

**Why this is worth writing in Lex specifically:**

1. **The authority is in the signature.** `main` declares `[io]` and nothing
   else — it cannot fetch, exec, or reach the network. A reviewer knows that
   without reading the body. That is the manifesto's claim applied to a
   compliance check, where "I read it and it looked fine" is exactly the kind
   of assurance you don't want.
2. **It refuses rather than downgrades.** An undeclared host, or one
   classified `Restricted`, fails the build. There is no override flag,
   because obligations are not optional.
3. **Unknown is not permissive.** `parse_licence` maps anything unrecognised to
   `Unknown`, and `Unknown` blocks publication. Adding a source without
   classifying its terms therefore *fails* rather than slipping through — the
   failure mode points the right way.

### What it computes

- **Attribution notices** — the deduplicated union of every notice the touched
  sources require (`required_notices`).
- **Share-alike** — true if any input is ODbL, since that obligation
  propagates into a derived database.
- **Blocking sources** — anything `Restricted` or `Unknown`, named in the
  refusal so the fix is obvious.

### Keeping the two halves honest

`ingest/net.py` now records `host` on every provenance entry, using the same
extraction rule as `host_of` in `attribution_gate.lex`; both were checked
against the real URL shapes. The gate keys off `host` rather than re-parsing
URLs, so the two sides cannot drift on that detail.

---

## What is deliberately *not* here

No attempt to port the geospatial pipeline. That would mean reimplementing or
binding GDAL, PROJ and GEOS — decades of C/C++ for no gain to this project.
The interesting question is not "can subsuelo be written in Lex" but "which
parts of subsuelo benefit from being typed", and the answer turned out to be:
the perimeter and the obligations, neither of which involve a single polygon.

### The numeric core is a closer call than it looks

An earlier draft of this file said the pure-numeric core would need "a numeric
array type Lex does not have". That was wrong. Lex 0.10.7 ships `std.math`
with a built-in `Matrix` — a dense row-major `f64` array (`Value::F64Array`)
with `zeros` / `ones` / `from_lists` / `from_flat` / `rows` / `cols` / `get` /
`to_flat` / `transpose` / `matmul` / `add` / `sub` / `scale` / `sigmoid`, all
pure. Alongside it, `std.arrow` (Apache Arrow `RecordBatch` as a first-class
value, with `read_csv`) and `std.df` (Polars-backed filter / sort /
`group_by_agg` / `read_parquet`) cover the tabular half.

That is enough for Weights-of-Evidence *today*, in both directions:

- **Applying** weights. `posterior = sigmoid(prior + Σ_k [mask_k ? w⁺_k : w⁻_k])`
  looks like it needs an elementwise multiply, but the branch rewrites to
  `w⁻·ones + (w⁺ − w⁻)·mask` — which is `scale` + `add` + `sigmoid`.
- **Fitting** weights. Every term in `w⁺ = ln(n(B∩D)/n(D)) − ln(n(B∩D̄)/n(D̄))`
  is a count of overlapping pixels, i.e. `sum(a ⊙ b)` — which is a 1×N by N×1
  `matmul` once `to_flat` / `from_flat` reshape the grids.

Both are in `box/numeric/` — `wofe.lex` (apply) and `counts.lex` (fit) — and
were run against the real 0.10.7 binary, reproducing `wofe.py`'s numpy output
to the last digit:

```sh
lex check box/numeric/wofe.lex box/numeric/counts.lex
lex run --allow-effects io box/numeric/wofe.lex main    # 0.24973989440488245, …
lex run --allow-effects io box/numeric/counts.lex main  # w+ = 1.203972804325936
```

What is genuinely missing is not the array type but the *convenience* around
it: no elementwise multiply or divide, no comparison-to-mask, no `where`, no
reductions over a `Matrix`, no slicing or indexed assignment, and no nodata
handling distinct from `NaN`. Each is expressible via the matmul trick above,
at the cost of code that reads nothing like the numpy it replaces. `Matrix` is
also undocumented in `docs/AGENT.md`; the only worked use in the toolchain
repo is `examples/ml_app.lex`.

So the honest statement is: `model/wofe.py` and `model/validate.py` (~600
lines, no geospatial dependency) are portable now, and what stands in the way
is ergonomics and dense-in-memory sizing rather than a missing primitive.
`ingest/live.py` never will be, and that is fine.

### The geospatial half: decided, not deferred

For GDAL / PROJ / GEOS there were three options, and only one of them was
close:

1. **Rust in the runtime** — a new `std.geo` builtin, the way `std.arrow` and
   `std.df` were added. Lex has **no FFI** (stated twice in
   `docs/AGENT_GUIDELINES.md`) and builtin modules are a closed hardcoded set
   in the compiler and runtime, so this is the *only* way a real binding could
   exist. The catch: `gdal-sys` / `proj-sys` / `geos-sys` are C bindings
   needing system libraries, which would cost `lex` its single-binary release.
2. **Shell out under `[proc]`** — works today with no runtime change, but
   `[proc]` is the widest grant in the effect system, so the function doing it
   forfeits exactly the property that makes the attribution gate worth having.
3. **Keep it in Python.**

**We went with 3.** The geospatial half is where GDAL earns its keep and
nothing about the type system helps there, so porting it buys no safety and
costs a rewrite. Option 1 is worth revisiting if the goal ever becomes *Lex
having geo* rather than *subsuelo being in Lex* — and if so the sequencing is
`std.df` first, then a narrow `std.geo` covering reproject, rasterize and
point-in-polygon, not a wholesale GDAL wrap.

This is the decision, not a placeholder: `box/` is the finished shape of the
boundary.
