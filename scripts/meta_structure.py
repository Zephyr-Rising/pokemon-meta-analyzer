"""Structure of a matchup matrix: what a power ranking explains, and what it cannot.

Every function here takes the antisymmetric edge matrix `A = (W - W.T)/2` from
`meta_game.edge_matrix`, expressed in win-rate units -- `A[i,j] = 0.03` means
deck i is 3 percentage points above that matchup's break-even against deck j --
together with a symmetric matrix of games played, which is how much each edge is
allowed to matter.

Two questions, one object:

    hodge()               how much of the format is a power ranking, and how much
                          is rock-paper-scissors that no ranking can express
    profile_similarity()  which decks answer the format the same way

`cyclic_plane()` connects them: it draws the dominant cycle that `hodge()`
measures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _prep(A, Wt):
    """Antisymmetric flow and a symmetric, hollow, non-negative weight matrix."""
    A = np.asarray(A, dtype=float)
    A = (A - A.T) / 2.0            # idempotent for an already-antisymmetric A
    Wt = np.asarray(Wt, dtype=float)
    Wt = np.where(np.isfinite(Wt), Wt, 0.0)
    Wt = np.maximum(Wt, 0.0)
    Wt = (Wt + Wt.T) / 2.0
    np.fill_diagonal(Wt, 0.0)
    return A, Wt


# --- 2. transitive vs cyclic ------------------------------------------------

def hodge(A, Wt):
    """Split an edge flow into the closest power ranking plus what it cannot express.

    A flow is a *gradient* when a single score per deck reproduces it,
    `A[i,j] = s[i] - s[j]`. That condition is exactly a transitive power ranking:
    strength difference alone decides every matchup, so beating a deck that beats
    a third guarantees beating the third. Real matchup data never satisfies it.

    Fitting the closest ranking is weighted least squares,

        minimise  sum_ij  Wt[i,j] * (s[i] - s[j] - A[i,j])**2

    whose normal equations are a weighted graph Laplacian system, `L s = div(A)`
    with `L = D - Wt` and `div(A)[i] = sum_j Wt[i,j] * A[i,j]` -- deck i's total
    weighted margin. `L` is singular, because adding a constant to every score
    changes nothing, so solve with a pseudoinverse and mean-centre the result.

    On a complete unweighted graph this reduces to `s[i] = mean margin of deck i`.
    Game weighting and missing matchups are exactly what turn it into a real
    strength-of-schedule correction: a deck is rated on the margins it posted
    *against the opponents it actually played*.

    Because the fit is an orthogonal projection under the weight inner product,
    the energies add exactly, `||A||^2 = ||gradient||^2 + ||residual||^2`, and
    `cyclicity` is the share of the format's matchup structure that no power
    ranking can ever explain.

    (The full Hodge decomposition has a third, harmonic piece -- globally cyclic
    yet locally consistent. It exists only when the graph has holes, i.e. pairs
    that never met. A matchup matrix is near-complete, so every gap is still
    surrounded by triangles and the harmonic part is negligible; the residual
    returned here is effectively all curl.)
    """
    A, Wt = _prep(A, Wt)
    L = np.diag(Wt.sum(1)) - Wt
    score = np.linalg.pinv(L) @ (Wt * A).sum(1)
    score = score - score.mean()

    gradient = score[:, None] - score[None, :]
    residual = A - gradient

    up = np.triu(np.ones(A.shape, dtype=bool), 1)
    energy = lambda M: float((Wt * M ** 2)[up].sum())
    total, e_grad, e_cyc = energy(A), energy(gradient), energy(residual)

    return {
        'score': score,
        'gradient': gradient,
        'residual': residual,
        'energy_total': total,
        'energy_gradient': e_grad,
        'energy_cyclic': e_cyc,
        'cyclicity': (e_cyc / total) if total > 0 else 0.0,
    }


def schedule_strength(score, Wt):
    """Game-weighted mean opponent strength each deck actually faced.

    The difference between a deck's raw average margin and its fitted score is
    schedule: this is the number that explains it.
    """
    score = np.asarray(score, dtype=float)
    _, Wt = _prep(np.zeros((len(score), len(score))), Wt)
    played = Wt.sum(1)
    return (Wt @ score) / np.where(played > 0, played, 1.0)


def triads(residual, Wt, names=None, min_weight=0.0, top=None):
    """Rock-paper-scissors triangles, ranked by how strongly they cycle.

    The curl of a triangle is `R[i,j] + R[j,k] + R[k,i]`. It is zero when the
    three matchups are consistent with some ranking and grows as they close into
    a loop, so it is the per-triangle version of what `hodge()` totals up.

    `min_weight` gates on the *thinnest* edge of the triangle: a curl computed
    off a three-game matchup is mostly sampling noise. Rows come out oriented so
    the cycle reads i > j > k > i.
    """
    R, Wt = _prep(residual, Wt)
    n = R.shape[0]
    names = list(names) if names is not None else list(range(n))

    rows = []
    for i in range(n):
        for j in range(i + 1, n):
            if Wt[i, j] < min_weight or Wt[i, j] <= 0:
                continue
            for k in range(j + 1, n):
                w = min(Wt[i, j], Wt[j, k], Wt[i, k])
                if w < min_weight or w <= 0:
                    continue
                curl = R[i, j] + R[j, k] + R[k, i]
                a, b, c = (i, j, k) if curl >= 0 else (i, k, j)
                rows.append({
                    'a': names[a], 'b': names[b], 'c': names[c],
                    'curl': abs(curl), 'min_games': w,
                })

    df = pd.DataFrame(rows, columns=['a', 'b', 'c', 'curl', 'min_games'])
    df = df.sort_values('curl', ascending=False).reset_index(drop=True)
    return df.head(top) if top else df


# --- 7. profile structure ---------------------------------------------------

def profile_similarity(A):
    """Correlation between decks' matchup profiles, each pair's own matchup masked.

    Deck i's profile is its row of `A`: how it fares against every deck in the
    field. Two decks are similar when they beat and lose to the same opponents --
    which makes the choice between them a matter of preference rather than
    strategy.

    For each pair, the `(i,j)` and `(j,i)` columns are dropped before
    correlating. How two decks match up against *each other* says nothing about
    whether they answer the rest of the format alike, and leaving it in lets a
    single lopsided head-to-head drive the similarity.

    No explicit game weighting: `A` is built from shrunk rates, so a thin matchup
    has already been pulled to break-even and contributes little variance.
    """
    A = np.asarray(A, dtype=float)
    A = (A - A.T) / 2.0
    n = A.shape[0]
    sim = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            keep = [c for c in range(n) if c not in (i, j)]
            u, v = A[i, keep], A[j, keep]
            su, sv = u.std(), v.std()
            r = 0.0 if su == 0 or sv == 0 else float(np.corrcoef(u, v)[0, 1])
            sim[i, j] = sim[j, i] = r
    return sim


def nearest_twins(sim, names=None):
    """Each deck's closest match by profile, with mutual pairs listed once.

    "Closest" is not a symmetric relation: A's nearest profile may be B while B's
    nearest is C. So a **mutual** pair (A->B and B->A) is one fact reported twice
    and collapses to a single row, while a **one-way** row is kept -- "A's nearest
    is B, but B prefers C" says something the mutual case does not, and dropping
    it would hide a deck entirely.

    Returns deck / twin / r / mutual, plus the integer indices so a caller can
    attach its own per-deck columns, sorted by similarity.
    """
    sim = np.asarray(sim, dtype=float)
    n = sim.shape[0]
    names = list(names) if names is not None else list(range(n))

    nearest = []
    for i in range(n):
        others = [j for j in range(n) if j != i]
        nearest.append(max(others, key=lambda j: sim[i, j]) if others else None)

    rows, seen = [], set()
    for i, j in enumerate(nearest):
        if j is None:
            continue
        mutual = nearest[j] == i
        if mutual:
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
        rows.append({'deck': names[i], 'twin': names[j], 'r': float(sim[i, j]),
                     'mutual': bool(mutual), 'deck_idx': i, 'twin_idx': j})

    df = pd.DataFrame(rows, columns=['deck', 'twin', 'r', 'mutual',
                                     'deck_idx', 'twin_idx'])
    return df.sort_values('r', ascending=False).reset_index(drop=True)


def cluster_profiles(sim, n_clusters=None, threshold=None, method='average'):
    """Hierarchical clusters over `1 - similarity`, plus a dendrogram leaf order.

    Returns (labels, order). `order` is the leaf ordering, which is what makes a
    similarity heatmap readable -- clusters land in contiguous blocks.
    """
    from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
    from scipy.spatial.distance import squareform

    sim = np.asarray(sim, dtype=float)
    dist = 1.0 - sim
    dist = (dist + dist.T) / 2.0
    np.fill_diagonal(dist, 0.0)
    dist = np.clip(dist, 0.0, None)

    Z = linkage(squareform(dist, checks=False), method=method)
    if n_clusters:
        labels = fcluster(Z, t=n_clusters, criterion='maxclust')
    else:
        labels = fcluster(Z, t=threshold, criterion='distance')
    return labels, leaves_list(Z)


def cyclic_plane(residual):
    """The format's dominant rock-paper-scissors wheel.

    A real antisymmetric matrix has paired singular values, and each pair spans a
    plane on which the flow is a pure rotation. Projecting the decks onto the top
    pair lays them out on a circle where each deck beats those a short way
    **counter-clockwise** of it and loses to those clockwise -- the single
    strongest cycle the residual contains.

    Returns (x, y, strength), `strength` being the share of the residual's energy
    this one plane carries. A high value means the format's rock-paper-scissors
    really is one wheel; a low one means it is many small independent loops.
    """
    R = np.asarray(residual, dtype=float)
    R = (R - R.T) / 2.0
    U, S, _ = np.linalg.svd(R)
    total = float((S ** 2).sum())
    strength = float((S[0] ** 2 + S[1] ** 2) / total) if total > 0 else 0.0
    x, y = U[:, 0], U[:, 1]

    # An SVD basis for the plane is arbitrary up to rotation *and reflection*, so
    # the raw vectors decide the wheel's handedness by coin flip. Pin it, or the
    # "beats counter-clockwise" reading above is true only half the time. Flipping
    # y negates every angle, which reverses the direction of travel.
    theta = np.arctan2(y, x)
    if float((R * np.sin(theta[None, :] - theta[:, None])).sum()) < 0:
        y = -y
    return x, y, strength
