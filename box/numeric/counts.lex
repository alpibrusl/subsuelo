# Can the WofE *weights* be computed too, not just applied?
# w+ = ln( (n(B∩D)/n(D)) / (n(B∩D̄)/n(D̄)) ) — every term is a count of
# pixels where two binary grids overlap, i.e. sum(a ⊙ b). Lex has no
# elementwise multiply, but sum(a ⊙ b) is exactly a 1×N · N×1 matmul.

import "std.math" as math

import "std.float" as float

import "std.str" as str

# sum over a matrix: ones(1,N) · flat(N,1)
fn total(m :: Matrix) -> Float {
  let n := math.rows(m) * math.cols(m)
  math.get(math.matmul(math.ones(1, n), math.from_flat(n, 1, math.to_flat(m))), 0, 0)
}

# sum(a ⊙ b) — the overlap count of two binary grids, as a dot product.
fn overlap(a :: Matrix, b :: Matrix) -> Float {
  let n := math.rows(a) * math.cols(a)
  math.get(math.matmul(math.from_flat(1, n, math.to_flat(a)), math.from_flat(n, 1, math.to_flat(b))), 0, 0)
}

fn complement(m :: Matrix) -> Matrix {
  math.sub(math.ones(math.rows(m), math.cols(m)), m)
}

# The positive weight of evidence for binary pattern B against deposits D.
fn w_plus(b :: Matrix, d :: Matrix) -> Float {
  let n_d := total(d)
  let n_nd := total(complement(d))
  math.log(overlap(b, d) / n_d) - math.log(overlap(b, complement(d)) / n_nd)
}

fn main() -> [io] Str {
  let b := math.from_lists([[1.0, 1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]])
  let d := math.from_lists([[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 1.0]])
  str.concat("w+ = ", float.to_str(w_plus(b, d)))
}

