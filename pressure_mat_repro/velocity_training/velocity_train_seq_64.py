"""Sequence-level GRU training for the tactile -> CoM velocity task.

Each training sample is one full episode (variable length, 20-54 frames).
The model produces a velocity prediction at every timestep; loss is the
masked MSE averaged over all valid frames in the batch.

This unlocks the GRU's recurrent capacity: hidden state accumulates the full
episode history instead of being reset per fixed-length window.
"""

import argparse
import os
import pickle

import numpy as np
import torch
import torch.optim as optim
from progressbar import ProgressBar
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader

from velocity_dataLoader_seq_64 import sample_velocity_seq_data, collate_pad
from velocity_temporal_model import SequentialTactileHybridRegressor


def str2bool(value):
    if isinstance(value, bool):
        return value
    return value.lower() in ("true", "1", "yes", "y", "t")


parser = argparse.ArgumentParser()
parser.add_argument("--exp_dir", type=str, default="./train/")
parser.add_argument("--exp", type=str, default="g1_walk_deploy_v1_seq")
parser.add_argument("--lr", type=float, default=1e-4)
parser.add_argument("--batch_size", type=int, default=8,
                    help="Sequences per batch. Smaller than frame batches "
                         "since each sample is a full episode.")
parser.add_argument("--weightdecay", type=float, default=1e-3)
parser.add_argument("--epoch", type=int, default=15)
parser.add_argument("--train_dir", type=str, required=True)
parser.add_argument("--val_dir", type=str, required=True)
parser.add_argument("--device", type=str, default="cuda:0")
parser.add_argument("--num_workers", type=int, default=4)
parser.add_argument("--fps_default", type=float, default=10.0)
parser.add_argument("--anchor_idx", type=int, default=8)
parser.add_argument("--head_idx", type=int, default=0)
parser.add_argument("--position_scale", type=float, default=1.0)
parser.add_argument("--smooth_radius", type=int, default=1)
parser.add_argument("--velocity_norm", type=float, default=1.0)
args = parser.parse_args()


def ensure_dirs(exp_dir):
    for sub in ("ckpts", "log"):
        p = os.path.join(exp_dir, sub)
        if not os.path.exists(p):
            os.makedirs(p)


def get_lr(opt):
    for g in opt.param_groups:
        return g["lr"]


def make_loader(path, shuffle):
    dataset = sample_velocity_seq_data(
        path=path,
        fps_default=args.fps_default,
        anchor_idx=args.anchor_idx,
        head_idx=args.head_idx,
        position_scale=args.position_scale,
        smooth_radius=args.smooth_radius,
    )
    return DataLoader(
        dataset, batch_size=args.batch_size, shuffle=shuffle,
        num_workers=args.num_workers, collate_fn=collate_pad,
    )


def masked_seq_mse(pred, gt, mask, lengths):
    """pred / gt: (B, T, 3); mask: (B, T); lengths: (B,)."""
    B, T, _ = pred.shape
    # Build padding mask: 1 inside true length, 0 in pad region.
    range_t = torch.arange(T, device=pred.device).unsqueeze(0)
    pad_mask = (range_t < lengths.unsqueeze(1)).float()
    valid = mask * pad_mask  # (B, T)
    diff = (pred - gt) ** 2 * valid.unsqueeze(-1)
    denom = torch.clamp(valid.sum() * 3.0, min=1.0)
    return diff.sum() / denom


def metrics_per_axis(pred, gt, mask, lengths):
    B, T, _ = pred.shape
    range_t = torch.arange(T, device=pred.device).unsqueeze(0)
    pad_mask = (range_t < lengths.unsqueeze(1)).float()
    valid = mask * pad_mask                         # (B, T)
    diff = (pred - gt) * valid.unsqueeze(-1)        # (B, T, 3)
    denom = torch.clamp(valid.sum(), min=1.0)
    mae_xyz = diff.abs().sum(dim=(0, 1)) / denom    # (3,)
    speed_p = pred.norm(dim=-1)
    speed_g = gt.norm(dim=-1)
    speed_mae = ((speed_p - speed_g).abs() * valid).sum() / denom
    return mae_xyz, speed_mae


if __name__ == "__main__":
    np.random.seed(0)
    torch.manual_seed(0)

    ensure_dirs(args.exp_dir)
    device = args.device if torch.cuda.is_available() and "cuda" in args.device else "cpu"

    train_loader = make_loader(args.train_dir, shuffle=True)
    val_loader = make_loader(args.val_dir, shuffle=False)
    print(f"train sequences: {len(train_loader.dataset)}, val sequences: {len(val_loader.dataset)}",
          flush=True)

    # Hybrid: per-frame CNN takes local 3-channel stack [t-1, t, t+1] for
    # early temporal fusion, then a causal GRU with lookahead=4 future block
    # adds late-fusion + unbounded past memory.
    model = SequentialTactileHybridRegressor(local_window=1, lookahead=4).to(device)
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"trainable params: {n_params}", flush=True)

    opt = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weightdecay)
    sched = ReduceLROnPlateau(opt, "min", factor=0.8, patience=5, verbose=True)

    best_val = np.inf
    train_losses = []
    val_losses = []

    for epoch in range(args.epoch):
        model.train(True)
        ep_train = []
        bar = ProgressBar(max_value=len(train_loader))
        for i, (tac, vel, val_m, lens) in bar(enumerate(train_loader, 0)):
            tac = tac.to(device)
            vel_norm = (vel.to(device) / args.velocity_norm)
            val_m = val_m.to(device)
            lens = lens.to(device)

            pred_norm = model(tac)                            # (B, T, 3)
            loss = masked_seq_mse(pred_norm, vel_norm, val_m, lens)

            opt.zero_grad()
            loss.backward()
            opt.step()
            ep_train.append(loss.item())

            if i % 50 == 0 and i > 0:
                print(f"[{i}/{len(train_loader)}] epoch {epoch} lr {get_lr(opt):.6f} "
                      f"loss {loss.item():.6f}", flush=True)

        # ---- validation ----
        model.eval()
        val_loss_list = []
        mae_sum = torch.zeros(3, device=device)
        speed_sum = torch.tensor(0.0, device=device)
        n_batches = 0
        with torch.no_grad():
            for tac, vel, val_m, lens in val_loader:
                tac = tac.to(device)
                vel_dev = vel.to(device)
                vel_norm = vel_dev / args.velocity_norm
                val_m = val_m.to(device)
                lens = lens.to(device)
                pred_norm = model(tac)
                loss = masked_seq_mse(pred_norm, vel_norm, val_m, lens)
                pred = pred_norm * args.velocity_norm
                mae_xyz, speed_mae = metrics_per_axis(pred, vel_dev, val_m, lens)
                val_loss_list.append(loss.item())
                mae_sum += mae_xyz
                speed_sum += speed_mae
                n_batches += 1

        train_loss = float(np.mean(ep_train))
        val_loss = float(np.mean(val_loss_list))
        mae_xyz = (mae_sum / max(n_batches, 1)).cpu().numpy()
        speed_mae = float((speed_sum / max(n_batches, 1)).item())
        sched.step(val_loss)

        print(f"Epoch {epoch} | Train Loss {train_loss:.6f} | Val Loss {val_loss:.6f} "
              f"| Val MAE xyz {mae_xyz} | Val speed MAE {speed_mae:.6f}", flush=True)

        train_losses.append(train_loss)
        val_losses.append(val_loss)
        with open(os.path.join(args.exp_dir, "log",
                               f"{args.exp}_{args.lr}_seq.p"), "wb") as fh:
            pickle.dump([train_losses, val_losses], fh)

        latest = f"{args.exp}_{args.lr}_seq_cp{epoch}"
        torch.save({
            "epoch": epoch,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": opt.state_dict(),
            "loss": val_loss,
        }, os.path.join(args.exp_dir, "ckpts", f"{latest}.path.tar"))

        if val_loss < best_val:
            best_val = val_loss
            best = f"{args.exp}_{args.lr}_seq_best"
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": opt.state_dict(),
                "loss": val_loss,
            }, os.path.join(args.exp_dir, "ckpts", f"{best}.path.tar"))
