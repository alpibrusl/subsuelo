# licence.lex — data licences as a lattice, and the obligations a join inherits.
#
# The problem this solves (subsuelo#2): subsuelo fetches from ~19 open data
# sources whose licences differ. Attribution and share-alike terms propagate
# into derivative works, so a published buy-list inherits the *union* of its
# inputs' obligations. Today those licences live as prose comments in
# ingest/live.py, which means nobody — human or machine — can enumerate what a
# given artifact actually owes.
#
# The idea is the one Lex already applies to code, pointed at data: a licence
# is a property that travels through transformations and is checked before
# publication. Everything here is pure, so `lex check` runs the examples as
# tests and the whole module is verifiable without touching the network.
#
# Deliberately NOT legal advice: this encodes the mechanical part (which
# notices must appear, whether share-alike is triggered, whether a source is
# safe to combine) so a human can spend attention on the parts that need
# judgement.

import "std.list" as list

import "std.str" as str

# The licences actually present across subsuelo's sources, plus the two
# outcomes that must never be silently treated as permissive.
#   Unknown  — a source we have not classified yet. Refuse, don't guess.
#   Restricted — a commercial or non-redistributable source (e.g. idealista).
type Licence = CC0 | DlDeZero | CCBy | DlDeBy20 | EtalabOpen | OdbL | Restricted | Unknown

type Obligation = AttributionRequired | ShareAlike | NoRedistribution

type Source = { tag :: Str, host :: Str, licence :: Licence, attribution :: Str }

# ---------------------------------------------------------------------------
# licence -> obligations
# ---------------------------------------------------------------------------
# Public-domain dedications carry nothing; attribution licences carry a notice;
# ODbL additionally makes a derived database share-alike; Restricted and
# Unknown block publication outright (see `blocks_publication`).
fn obligations(l :: Licence) -> List[Obligation]
  examples {
    obligations(CC0) => [],
    obligations(DlDeZero) => [],
    obligations(CCBy) => [AttributionRequired],
    obligations(DlDeBy20) => [AttributionRequired],
    obligations(OdbL) => [AttributionRequired, ShareAlike],
    obligations(Restricted) => [NoRedistribution],
    obligations(Unknown) => [NoRedistribution]
  }
{
  match l {
    CC0 => [],
    DlDeZero => [],
    CCBy => [AttributionRequired],
    DlDeBy20 => [AttributionRequired],
    EtalabOpen => [AttributionRequired],
    OdbL => [AttributionRequired, ShareAlike],
    Restricted => [NoRedistribution],
    Unknown => [NoRedistribution],
  }
}

# A licence we may not publish a derivative of. Unknown counts: an
# unclassified source is refused rather than assumed permissive — the
# "refuse, don't downgrade" rule, applied to data terms.
fn blocks_publication(l :: Licence) -> Bool
  examples {
    blocks_publication(CC0) => false,
    blocks_publication(CCBy) => false,
    blocks_publication(OdbL) => false,
    blocks_publication(Restricted) => true,
    blocks_publication(Unknown) => true
  }
{
  match l {
    Restricted => true,
    Unknown => true,
    _ => false,
  }
}

# Does a derived work built from this licence have to be share-alike?
fn is_share_alike(l :: Licence) -> Bool
  examples {
    is_share_alike(OdbL) => true,
    is_share_alike(CCBy) => false,
    is_share_alike(CC0) => false
  }
{
  match l {
    OdbL => true,
    _ => false,
  }
}

fn needs_attribution(l :: Licence) -> Bool
  examples {
    needs_attribution(CCBy) => true,
    needs_attribution(DlDeBy20) => true,
    needs_attribution(EtalabOpen) => true,
    needs_attribution(CC0) => false,
    needs_attribution(DlDeZero) => false
  }
{
  match l {
    CCBy => true,
    DlDeBy20 => true,
    EtalabOpen => true,
    OdbL => true,
    _ => false,
  }
}

# ---------------------------------------------------------------------------
# parsing — the string a fetch records -> the lattice
# ---------------------------------------------------------------------------
# Unrecognised spellings map to Unknown, which blocks publication. That is the
# point: adding a source without classifying its licence fails the gate rather
# than slipping through.
fn parse_licence(s :: Str) -> Licence
  examples {
    parse_licence("CC0") => CC0,
    parse_licence("cc0-1.0") => CC0,
    parse_licence("dl-de/zero-2-0") => DlDeZero,
    parse_licence("CC-BY-4.0") => CCBy,
    parse_licence("dl-de/by-2-0") => DlDeBy20,
    parse_licence("etalab-2.0") => EtalabOpen,
    parse_licence("ODbL-1.0") => OdbL,
    parse_licence("proprietary") => Restricted,
    parse_licence("") => Unknown,
    parse_licence("something we have never seen") => Unknown
  }
{
  let k := str.to_lower(str.trim(s))
  match str.contains(k, "zero") {
    true => DlDeZero,
    false => match str.starts_with(k, "cc0") {
      true => CC0,
      false => match str.contains(k, "odbl") {
        true => OdbL,
        false => match str.contains(k, "dl-de/by") {
          true => DlDeBy20,
          false => match str.starts_with(k, "cc-by") {
            true => CCBy,
            false => match str.contains(k, "etalab") {
              true => EtalabOpen,
              false => match str.contains(k, "proprietary") {
                true => Restricted,
                false => Unknown,
              },
            },
          },
        },
      },
    },
  }
}

# ---------------------------------------------------------------------------
# the union over a join
# ---------------------------------------------------------------------------
# Every attribution notice a set of sources requires, deduplicated. This is
# what has to appear on the published artifact.
fn required_notices(sources :: List[Source]) -> List[Str] {
  let needing := list.filter(sources, fn (s :: Source) -> Bool {
    needs_attribution(s.licence)
  })
  let notices := list.map(needing, fn (s :: Source) -> Str {
    s.attribution
  })
  list.fold(notices, [], fn (acc :: List[Str], n :: Str) -> List[Str] {
    let seen := list.fold(acc, false, fn (f :: Bool, x :: Str) -> Bool {
      f or x == n
    })
    match seen {
      true => acc,
      false => list.concat(acc, [n]),
    }
  })
}

# Does the combined output have to be released share-alike? True if any input
# is ODbL — the obligation propagates through the join.
fn derived_is_share_alike(sources :: List[Source]) -> Bool {
  list.fold(sources, false, fn (f :: Bool, s :: Source) -> Bool {
    f or is_share_alike(s.licence)
  })
}

# Sources that must not appear in anything published.
fn blocking_sources(sources :: List[Source]) -> List[Source] {
  list.filter(sources, fn (s :: Source) -> Bool {
    blocks_publication(s.licence)
  })
}

# The whole question in one call: may we publish a derivative of these sources?
fn may_publish(sources :: List[Source]) -> Bool {
  list.len(blocking_sources(sources)) == 0
}

