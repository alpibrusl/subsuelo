# attribution_gate.lex — refuse to publish a build whose data terms don't allow it.
#
# This is the Lex half of the subsuelo boundary (Option B of the migration
# note). The Python pipeline does the geospatial work — GDAL, PROJ, GEOS, none
# of which Lex can reach — and emits `out/provenance.json`: one record per
# fetch, with the host it came from. This gate reads that log and answers the
# question the Python side cannot answer for itself:
#
#     given everything this build actually touched, may we publish it,
#     and what notices does the output owe?
#
# Two properties make this worth writing in Lex rather than adding to build.py:
#
#   1. The gate's authority is in its type. `check_build` declares [io] and
#      nothing else — it cannot fetch, cannot exec, cannot reach the network.
#      A reviewer knows that from the signature, without reading the body.
#   2. It refuses rather than downgrades. An undeclared host or a Restricted
#      source fails the build; there is no "publish anyway" path, because the
#      whole point is that the obligations are not optional.
#
# Run:
#   lex run --allow-effects io --allow-fs-read out/provenance.json \
#       box/attribution_gate.lex main
#
# Exit 0 = publishable, and attribution notices are printed for the artifact.
# Exit non-zero = refused, with the offending sources named.

import "std.io" as io

import "std.json" as json

import "std.list" as list

import "std.str" as str

import "./licence" as lic

import "./sources" as src

# One line of the provenance log written by ingest/net.py.
type Fetch = { tag :: Str, url :: Str, host :: Str, bytes :: Int, cache :: Bool }

type Verdict = { publishable :: Bool, share_alike :: Bool, notices :: List[Str], blocked :: List[Str], n_fetches :: Int }

# ---------------------------------------------------------------------------
# provenance -> sources
# ---------------------------------------------------------------------------
# Pull the host out of a URL. The provenance log records the full URL; the
# source registry is keyed by host.
fn host_of(url :: Str) -> Str
  examples {
    host_of("https://mapas.igme.es/wms?x=1") => "mapas.igme.es",
    host_of("http://ovc.catastro.meh.es/a/b") => "ovc.catastro.meh.es",
    host_of("https://api.idealista.com/3.5/es/search") => "api.idealista.com",
    host_of("not a url") => ""
  }
{
  let after_scheme := match str.contains(url, "://") {
    true => match list.head(list.tail(str.split(url, "://"))) {
      Some(rest) => rest,
      None => "",
    },
    false => "",
  }
  match list.head(str.split(after_scheme, "/")) {
    Some(h) => h,
    None => "",
  }
}

# The distinct hosts a build touched.
fn hosts_touched(fetches :: List[Fetch]) -> List[Str] {
  list.fold(fetches, [], fn (acc :: List[Str], f :: Fetch) -> List[Str] {
    let h := host_of(f.url)
    let seen := list.fold(acc, false, fn (s :: Bool, x :: Str) -> Bool {
      s or x == h
    })
    match seen {
      true => acc,
      false => match str.is_empty(h) {
        true => acc,
        false => list.concat(acc, [h]),
      },
    }
  })
}

# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------
# Pure: given the fetches, decide. Everything network- and disk-facing stays
# in `main`, so the decision itself is testable without any effects at all.
fn verdict_for(fetches :: List[Fetch]) -> Verdict {
  let hosts := hosts_touched(fetches)
  let sources := list.map(hosts, fn (h :: Str) -> lic.Source {
    src.source_for_host(h)
  })
  let blocked := list.map(lic.blocking_sources(sources), fn (s :: lic.Source) -> Str {
    str.concat(s.host, str.concat("  [", str.concat(s.attribution, "]")))
  })
  { publishable: lic.may_publish(sources), share_alike: lic.derived_is_share_alike(sources), notices: lic.required_notices(sources), blocked: blocked, n_fetches: list.len(fetches) }
}

# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
fn render_notices(notices :: List[Str]) -> Str {
  list.fold(notices, "", fn (acc :: Str, n :: Str) -> Str {
    str.concat(acc, str.concat("  · ", str.concat(n, "\n")))
  })
}

fn render_blocked(blocked :: List[Str]) -> Str {
  list.fold(blocked, "", fn (acc :: Str, b :: Str) -> Str {
    str.concat(acc, str.concat("  ✗ ", str.concat(b, "\n")))
  })
}

fn report(v :: Verdict) -> Str {
  let head := str.concat("provenance: ", str.concat(int_to_str(v.n_fetches), " fetches\n"))
  match v.publishable {
    false => str.concat(head, str.concat("REFUSED — these sources may not be redistributed:\n", str.concat(render_blocked(v.blocked), "\nDeclare the source in box/sources.lex, or exclude its values from\nthe published artifacts. There is no override.\n"))),
    true => str.concat(head, str.concat(match v.share_alike {
      true => "share-alike: YES — the derived database must be released under ODbL\n",
      false => "share-alike: no\n",
    }, str.concat("attribution notices required on the published artifact:\n", render_notices(v.notices)))),
  }
}

# `str` has no int formatter in the version this targets; fold digits by hand
# so the report stays pure.
fn int_to_str(n :: Int) -> Str
  examples {
    int_to_str(0) => "0",
    int_to_str(7) => "7",
    int_to_str(42) => "42",
    int_to_str(1234) => "1234"
  }
{
  match n == 0 {
    true => "0",
    false => digits(n, ""),
  }
}

fn digits(n :: Int, acc :: Str) -> Str {
  match n == 0 {
    true => acc,
    false => digits(n / 10, str.concat(digit_char(n % 10), acc)),
  }
}

fn digit_char(d :: Int) -> Str {
  match d {
    0 => "0",
    1 => "1",
    2 => "2",
    3 => "3",
    4 => "4",
    5 => "5",
    6 => "6",
    7 => "7",
    8 => "8",
    _ => "9",
  }
}

# ---------------------------------------------------------------------------
# entry point — the only effectful function, and it declares exactly [io]
# ---------------------------------------------------------------------------
fn main() -> [io] Str {
  match io.read("out/provenance.json") {
    Err(_) => "no out/provenance.json — run the pipeline first\n",
    Ok(raw) => {
      match json.parse(raw) {
        Err(e) => str.concat("provenance.json is not valid JSON: ", e),
        Ok(fetches) => report(verdict_for(fetches)),
      }
    },
  }
}

