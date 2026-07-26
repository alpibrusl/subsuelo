# Does Lex 0.10.7 already have enough of an ndarray to run Weights-of-Evidence?
# posterior = sigmoid(prior_logit + sum_k [ mask_k ? w_plus_k : w_minus_k ])
#           = sigmoid(prior_logit + sum_k [ w_minus_k + (w_plus_k - w_minus_k) * mask_k ])
# so no elementwise multiply is needed — scale + add + sigmoid suffice.

import "std.list" as list

import "std.math" as math

import "std.str" as str

import "std.float" as float

type Layer = { mask :: Matrix, w_plus :: Float, w_minus :: Float }

# One evidence layer's contribution to the log-odds grid.
fn contribution(l :: Layer, r :: Int, c :: Int) -> Matrix {
  math.add(math.scale(l.w_minus, math.ones(r, c)), math.scale(l.w_plus - l.w_minus, l.mask))
}

fn posterior(prior_logit :: Float, layers :: List[Layer], r :: Int, c :: Int) -> Matrix {
  let base := math.scale(prior_logit, math.ones(r, c))
  let logit := list.fold(layers, base, fn (acc :: Matrix, l :: Layer) -> Matrix {
    math.add(acc, contribution(l, r, c))
  })
  math.sigmoid(logit)
}

fn main() -> [io] Str {
  let g := math.from_lists([[1.0, 0.0], [0.0, 1.0]])
  let h := math.from_lists([[1.0, 1.0], [0.0, 0.0]])
  let p := posterior(-4.6, [{ mask: g, w_plus: 2.1, w_minus: -0.3 }, { mask: h, w_plus: 1.4, w_minus: -0.2 }], 2, 2)
  list.fold(math.to_flat(p), "", fn (acc :: Str, x :: Float) -> Str {
    str.concat(acc, str.concat(float.to_str(x), "\n"))
  })
}

