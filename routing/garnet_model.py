"""GARNET — neural encoder–decoder TSP solver (Khriss et al., 2026).

A faithful, self-contained PyTorch implementation of the architecture described in
``garnet.pdf`` ("Garnet: integrating random walk encoding and graph rewiring for routing
optimization"). It is the *route-optimisation* engine the team originally planned: a graph
neural network that learns to construct a travelling-salesman tour, addressing the NP-hard
ordering problem with a learned policy instead of a hand-tuned metaheuristic.

The three architectural ingredients from the paper, in order:

  1. **D-RRWP** (Decomposed Relative Random-Walk Probabilities) — multi-hop structural
     positional encoding. Build a sparse k-NN graph, form its row-stochastic transition
     matrix ``T = D^{-1} A``, raise it to powers ``T^h`` for ``h = 1..walk_steps`` and read
     off node (diagonal/return) and edge (off-diagonal, forward||reverse) probabilities.
  2. **Random rewiring** — overlay a random r-regular graph to add long-range shortcut
     edges, widening receptive fields and fixing GNN under-reach. Added edges carry their
     own learnable embedding (Eq. 17).
  3. **GRASS** (graph-tailored additive sparse attention) — edge-feature additive attention
     with per-layer edge flipping (odd layers forward, even reversed) for bidirectional flow,
     then max+mean pooling combined by a sigmoid-gated MLP into a global graph embedding.

The decoder maintains a dynamic context (global embedding + first + last selected node),
refines it with multi-head attention, then a single-head attention layer with tanh clipping
(C=10) produces the next-node distribution over unvisited cities (Eqs. 25–30).

This module is **import-guarded behind torch** and is only ever loaded when the GARNET
toggle is on (see ``solver_garnet``). On the numpy-only dev box torch is absent and this file
is never imported, exactly like the cupy/cuopt/ortools optional rungs. The dense (N×N)
attention here is mathematically identical to the paper's sparse k-NN formulation — for the
modest node counts in a medical-courier replan (tens of stops) it is simpler and fast enough,
while ``Config`` keeps the published hyper-parameters so a checkpoint trained elsewhere loads
unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class Config:
    """Published GARNET hyper-parameters (Table 2 of the paper)."""

    d: int = 128            # embedding dimension
    layers: int = 3         # encoder GRASS layers (L)
    heads: int = 8          # attention heads (h)
    walk_steps: int = 3     # D-RRWP random-walk steps
    knn: int = 8            # k-NN encoder graph degree
    rewire_r: int = 2       # random-rewiring regular degree
    tanh_clip: float = 10.0  # SHA logit clipping (C)
    seed: int = 42


# ---------------------------------------------------------------------------- D-RRWP
def _knn_adjacency(coords: torch.Tensor, k: int) -> torch.Tensor:
    """Symmetric {0,1} k-NN adjacency (no self-loops) from 2-D coordinates."""
    n = coords.shape[0]
    k = min(k, max(1, n - 1))
    dist = torch.cdist(coords, coords)                       # (N, N) Euclidean
    dist = dist + torch.eye(n, device=coords.device) * 1e9    # exclude self
    idx = dist.topk(k, largest=False).indices                 # (N, k) nearest
    a = torch.zeros(n, n, device=coords.device)
    a.scatter_(1, idx, 1.0)
    a = ((a + a.t()) > 0).float()                             # symmetrise
    return a


def _rrwp(adjacency: torch.Tensor, steps: int) -> torch.Tensor:
    """Stack of h-step random-walk matrices ``P_h = T^h`` for ``h = 1..steps``.

    Returns ``(steps, N, N)`` where ``P[h-1, i, j]`` is the probability a walker at ``i``
    reaches ``j`` in exactly ``h`` steps (Eqs. 12–13). Row-stochastic transition matrix.
    """
    deg = adjacency.sum(1, keepdim=True).clamp_min(1.0)
    t = adjacency / deg                                       # T = D^{-1} A
    mats, p = [], t
    for _ in range(steps):
        mats.append(p)
        p = p @ t
    return torch.stack(mats, 0)                               # (steps, N, N)


def _random_regular(n: int, r: int, generator: torch.Generator) -> torch.Tensor:
    """A random r-regular-ish symmetric {0,1} graph for rewiring (Eq. 17).

    Exact r-regularity is not required by the method (it only needs random shortcut edges
    of degree ~r); we add ``r`` random partners per node and symmetrise, which is the
    cheap, robust construction used for shortcut injection.
    """
    r = min(r, max(0, n - 1))
    a = torch.zeros(n, n)
    if r == 0:
        return a
    for i in range(n):
        perm = torch.randperm(n, generator=generator)
        picked = perm[perm != i][:r]
        a[i, picked] = 1.0
    a = ((a + a.t()) > 0).float()
    a.fill_diagonal_(0.0)
    return a


# ---------------------------------------------------------------------------- encoder
class GrassLayer(nn.Module):
    """One GRASS additive-attention layer over a neighbour mask (Eqs. 20–22).

    ``alpha_{ij} = w_attn . phi_e(e_{ij})`` scored from edge features, softmax over
    neighbours, node update ``x'(i) = sum_j s_{ij} W_agg x(j)``, edge update from
    ``phi_e(e, x_i, x_j, s)``, then residual + norm. ``flip`` reverses edge orientation on
    even layers for bidirectional message passing on the directed edge embeddings.
    """

    def __init__(self, d: int, flip: bool):
        super().__init__()
        self.flip = flip
        self.edge_score = nn.Sequential(nn.Linear(d, d), nn.ReLU(), nn.Linear(d, 1))
        self.node_agg = nn.Linear(d, d)
        self.edge_update = nn.Linear(3 * d + 1, d)
        self.node_norm = nn.LayerNorm(d)
        self.edge_norm = nn.LayerNorm(d)

    def forward(self, x: torch.Tensor, e: torch.Tensor, mask: torch.Tensor):
        if self.flip:
            e = e.transpose(0, 1)                             # reverse edge orientation
        alpha = self.edge_score(e).squeeze(-1)               # (N, N)
        alpha = alpha.masked_fill(mask == 0, float("-inf"))
        s = torch.softmax(alpha, dim=1)                       # (N, N) per-row over neighbours
        s = torch.nan_to_num(s)                               # rows with no neighbour -> 0
        x_new = self.node_agg(s @ x)                          # (N, d) weighted aggregation
        n = x.shape[0]
        xi = x.unsqueeze(1).expand(n, n, -1)
        xj = x.unsqueeze(0).expand(n, n, -1)
        e_new = self.edge_update(torch.cat([e, xi, xj, s.unsqueeze(-1)], dim=-1))
        x_out = self.node_norm(x + x_new)                     # residual + norm (Eq. 22)
        e_out = self.edge_norm(e + e_new)
        return x_out, e_out


class Encoder(nn.Module):
    """D-RRWP + rewiring + stacked GRASS layers -> node embeddings + gated graph embedding."""

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        d = cfg.d
        self.coord_in = nn.Linear(2, d)
        self.node_rw = nn.Linear(cfg.walk_steps, d)           # W_node-enc (Eq. 14)
        self.deg_enc = nn.Linear(1, d)                        # W_deg (Eq. 16)
        self.edge_rw = nn.Linear(2 * cfg.walk_steps, d)       # W_edge-enc (Eq. 15)
        self.added_edge = nn.Linear(cfg.walk_steps, d)        # W_added-edge (Eq. 17)
        self.bn_node = nn.BatchNorm1d(cfg.walk_steps)
        self.bn_edge = nn.BatchNorm1d(2 * cfg.walk_steps)
        self.layers = nn.ModuleList(
            GrassLayer(d, flip=(i % 2 == 1)) for i in range(cfg.layers)
        )
        self.gate = nn.Sequential(nn.Linear(2 * d, d), nn.Sigmoid())
        self.gate_val = nn.Linear(2 * d, d)

    def forward(self, coords: torch.Tensor):
        cfg = self.cfg
        n = coords.shape[0]
        gen = torch.Generator(device=coords.device).manual_seed(cfg.seed)

        a_knn = _knn_adjacency(coords, cfg.knn)
        a_rewire = _random_regular(n, cfg.rewire_r, gen).to(coords.device)
        mask = ((a_knn + a_rewire) > 0).float()               # union neighbourhood (Eq. 11)

        p = _rrwp(a_knn, cfg.walk_steps)                      # (steps, N, N)
        node_walk = torch.diagonal(p, dim1=1, dim2=2).t()     # (N, steps) return probs
        deg = a_knn.sum(1, keepdim=True)                      # (N, 1)
        # forward||reverse off-diagonal walk probs -> edge features (N, N, 2*steps)
        fwd = p.permute(1, 2, 0)
        rev = p.permute(2, 1, 0)
        edge_walk = torch.cat([fwd, rev], dim=-1)

        x = self.coord_in(coords) + self.node_rw(self._bn(self.bn_node, node_walk)) \
            + self.deg_enc(deg)                               # x0 (Eq. 16)
        e = self.edge_rw(self._bn2d(self.bn_edge, edge_walk))  # e_RW (Eq. 15)
        # added (rewired) edges contribute their own embedding (Eq. 17)
        added = self.added_edge(fwd) * a_rewire.unsqueeze(-1)
        e = e + added

        for layer in self.layers:
            x, e = layer(x, e, mask)

        n_max = x.max(0).values
        n_mean = x.mean(0)
        pooled = torch.cat([n_max, n_mean], -1)
        graph_emb = self.gate(pooled) * self.gate_val(pooled)  # gated global embedding
        return x, graph_emb

    @staticmethod
    def _bn(bn: nn.BatchNorm1d, v: torch.Tensor) -> torch.Tensor:
        return bn(v) if v.shape[0] > 1 else v

    @staticmethod
    def _bn2d(bn: nn.BatchNorm1d, v: torch.Tensor) -> torch.Tensor:
        n, _, c = v.shape
        flat = v.reshape(n * n, c)
        flat = bn(flat) if flat.shape[0] > 1 else flat
        return flat.reshape(n, n, c)


# ---------------------------------------------------------------------------- decoder
class Decoder(nn.Module):
    """MHA -> SHA autoregressive tour constructor (Eqs. 25–30)."""

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        d = cfg.d
        self.placeholder = nn.Parameter(torch.randn(d) * 0.1)  # I_X for the first step
        self.ctx_proj = nn.Linear(3 * d, d)
        self.mha = nn.MultiheadAttention(d, cfg.heads, batch_first=True)
        self.q_sha = nn.Linear(d, d)
        self.k_sha = nn.Linear(d, d)

    def forward(self, node_emb: torch.Tensor, graph_emb: torch.Tensor,
                start: int = 0, sample: bool = False,
                generator: torch.Generator | None = None):
        """Construct one tour. Returns (tour_indices, sum_log_prob)."""
        n, d = node_emb.shape
        tour: list[int] = [start]
        first = node_emb[start]
        last = node_emb[start]
        logp = node_emb.new_zeros(())
        k_keys = self.k_sha(node_emb)                          # (N, d)

        for _ in range(n - 1):
            # Rebuild the visited mask fresh each step (no in-place mutation of a tensor
            # autograd has already consumed — keeps backward() valid during training).
            visited = torch.zeros(n, dtype=torch.bool, device=node_emb.device)
            visited[tour] = True
            ctx = self.ctx_proj(torch.cat([graph_emb, first, last], -1))  # (d,)
            q, _ = self.mha(ctx[None, None, :], node_emb[None], node_emb[None])
            q = self.q_sha(q.squeeze(0).squeeze(0))            # (d,)
            logits = self.cfg.tanh_clip * torch.tanh(k_keys @ q / (d ** 0.5))
            logits = logits.masked_fill(visited, float("-inf"))
            probs = torch.softmax(logits, -1)
            if sample:
                nxt = torch.multinomial(probs, 1, generator=generator).item()
            else:
                nxt = int(torch.argmax(probs).item())
            logp = logp + torch.log(probs[nxt] + 1e-12)
            last = node_emb[nxt]
            tour.append(nxt)
        return tour, logp


class GarnetTSP(nn.Module):
    """Full GARNET model: ``coords -> tour``. The route-optimisation policy network."""

    def __init__(self, cfg: Config | None = None):
        super().__init__()
        self.cfg = cfg or Config()
        torch.manual_seed(self.cfg.seed)
        self.encoder = Encoder(self.cfg)
        self.decoder = Decoder(self.cfg)

    def forward(self, coords: torch.Tensor, start: int = 0, sample: bool = False,
                generator: torch.Generator | None = None):
        node_emb, graph_emb = self.encoder(coords)
        return self.decoder(node_emb, graph_emb, start=start, sample=sample,
                            generator=generator)

    @torch.no_grad()
    def tour(self, coords: torch.Tensor, start: int = 0) -> list[int]:
        """Greedy decode — deterministic tour for inference."""
        self.eval()
        order, _ = self.forward(coords, start=start, sample=False)
        return order


def tour_length(coords: torch.Tensor, tour: list[int]) -> torch.Tensor:
    """Closed-tour Euclidean length (Eq. 9)."""
    pts = coords[tour]
    seg = pts - torch.roll(pts, -1, dims=0)
    return seg.norm(dim=1).sum()
