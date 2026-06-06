"""Train GARNET with policy-gradient RL on random Euclidean TSP instances.

The paper trains the actor–critic with PPO (Algorithm 1). Here we use the closely related,
lighter-weight **REINFORCE with a greedy-rollout baseline** (Kool et al. 2018): the same
policy-gradient objective ``∇J = E[(L(τ) − b) ∇log p(τ)]`` where the baseline ``b`` is the
deterministic greedy tour length — which is stable, needs no separate critic, and is enough
to produce a working checkpoint on a CPU box. The reward is the negative closed-tour length
(Eqs. 4–8), exactly the TSP objective GARNET optimises.

This is an **optional, offline** tool — it requires torch and is never imported by the
service. Run it once to produce ``routing/garnet.pt``, which ``solver_garnet`` then loads
when ``$GARNET_ENABLED`` is on.

    cd routing && python train_garnet.py --nodes 20 --steps 2000 --out garnet.pt

Defaults are tiny so a smoke run finishes in seconds; raise ``--nodes``/``--steps`` (and
ideally run on the GB10's GPU) for a model that actually shortens tours.
"""
from __future__ import annotations

import argparse

import torch

import garnet_model as gm


def train(nodes: int, steps: int, batch: int, lr: float, out: str, seed: int) -> None:
    torch.manual_seed(seed)
    gen = torch.Generator().manual_seed(seed)
    model = gm.GarnetTSP(gm.Config(seed=seed))
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.ExponentialLR(opt, gamma=0.96)

    for step in range(1, steps + 1):
        model.train()
        batch_loss = model.encoder.coord_in.weight.new_zeros(())
        sampled_len = greedy_len = 0.0
        for _ in range(batch):
            coords = torch.rand(nodes, 2, generator=gen)
            # sampled rollout (exploration) — carries the gradient
            tour_s, logp = model(coords, sample=True, generator=gen)
            len_s = gm.tour_length(coords, tour_s)
            # greedy rollout baseline (no grad)
            with torch.no_grad():
                tour_g = model.tour(coords)
                len_g = gm.tour_length(coords, tour_g)
            # REINFORCE: minimise (advantage * -logp); advantage = len_s - baseline
            batch_loss = batch_loss + (len_s.detach() - len_g.detach()) * logp
            sampled_len += float(len_s)
            greedy_len += float(len_g)
        loss = batch_loss / batch
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)  # paper: max-norm 1.0
        opt.step()
        if step % 50 == 0:
            sched.step()
        if step % max(1, steps // 20) == 0 or step == 1:
            print(f"step {step:5d}  sampled={sampled_len / batch:.3f}  "
                  f"greedy={greedy_len / batch:.3f}")

    torch.save(model.state_dict(), out)
    print(f"saved checkpoint -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Train the GARNET TSP policy network.")
    ap.add_argument("--nodes", type=int, default=20)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="garnet.pt")
    args = ap.parse_args()
    train(args.nodes, args.steps, args.batch, args.lr, args.out, args.seed)


if __name__ == "__main__":
    main()
