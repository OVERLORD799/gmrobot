"""Sequence-level tactile dataloader for GRU-style training.

Each ``__getitem__`` returns ONE full sequence:
  tactile : (T, 32, 32) float32  — every frame in the sequence
  velocity: (T, 3)      float32  — smoothed finite-diff velocity per frame
  valid   : (T,)        float32  — 1 if velocity is computable at that step

Built on top of the time/velocity utilities in ``velocity_dataLoader_batch_32``
(``_compute_dt``, ``_load_sequence_timestamps``).
"""

import os
import pickle

import numpy as np
import torch
from torch.utils.data import Dataset

from velocity_dataLoader_batch_32 import _compute_dt, _load_sequence_timestamps


class sample_velocity_seq_data(Dataset):
    def __init__(self, path, fps_default=10.0, anchor_idx=8, head_idx=0,
                 position_scale=1.0, use_timestamps=True, smooth_radius=1):
        self.path = path
        self.log = pickle.load(open(os.path.join(self.path, "log.p"), "rb"))
        self.log = np.asarray(self.log, dtype=np.int64)
        self.starts = self.log[:-1].tolist()
        self.total = int(self.log[-1])
        self.num_seqs = len(self.starts)
        self.fps_default = float(fps_default)
        self.anchor_idx = int(anchor_idx)
        self.head_idx = int(head_idx)
        self.position_scale = float(position_scale)
        self.use_timestamps = bool(use_timestamps)
        self.smooth_radius = max(0, int(smooth_radius))
        self._ts_cache: dict = {}

    def __len__(self):
        return self.num_seqs

    # ---- helpers ----
    def _seq_dir_for(self, seq_idx):
        return os.path.join(self.path, str(self.starts[seq_idx]))

    def _seq_range(self, seq_idx):
        s = self.starts[seq_idx]
        e = self.starts[seq_idx + 1] if seq_idx + 1 < self.num_seqs else self.total
        return s, e

    def _ts_for(self, local_path):
        if not self.use_timestamps:
            return None
        if local_path in self._ts_cache:
            return self._ts_cache[local_path]
        ts = _load_sequence_timestamps(local_path)
        self._ts_cache[local_path] = ts
        return ts

    def _load_kp(self, local_path, idx):
        data = pickle.load(open(os.path.join(local_path, f"{idx}.p"), "rb"))
        return np.array(data[2], dtype=np.float32)

    def _pair_velocity(self, local_path, ts, min_len, idx_a, idx_b):
        kp_a = self._load_kp(local_path, idx_a)
        kp_b = self._load_kp(local_path, idx_b)
        dt, from_ts = _compute_dt(ts, idx_a, idx_b, min_len, self.fps_default)
        point_a = 0.5 * (kp_a[self.head_idx] + kp_a[self.anchor_idx]) * self.position_scale
        point_b = 0.5 * (kp_b[self.head_idx] + kp_b[self.anchor_idx]) * self.position_scale
        return ((point_b - point_a) / dt).astype(np.float32), float(dt), int(from_ts)

    def _compute_velocity_at(self, local_path, ts, min_len, max_len, idx):
        if idx < min_len or idx >= max_len:
            return np.zeros((3,), dtype=np.float32), 0
        velocities, weights = [], []
        for offset in range(-self.smooth_radius, self.smooth_radius + 1):
            a = idx + offset
            b = a + 1
            if a < min_len or b >= max_len:
                continue
            v, _, _ = self._pair_velocity(local_path, ts, min_len, a, b)
            velocities.append(v)
            weights.append(float(self.smooth_radius + 1 - abs(offset)))
        if not velocities:
            if idx > min_len:
                v, _, _ = self._pair_velocity(local_path, ts, min_len, idx - 1, idx)
                return v, 1
            return np.zeros((3,), dtype=np.float32), 0
        w = np.asarray(weights, dtype=np.float32)
        v = np.stack(velocities, axis=0)
        return (np.sum(v * w.reshape(-1, 1), axis=0) / np.sum(w)).astype(np.float32), 1

    # ---- main getter ----
    def __getitem__(self, seq_idx):
        local_path = self._seq_dir_for(seq_idx)
        s, e = self._seq_range(seq_idx)
        T = e - s
        ts = self._ts_for(local_path)

        tactile = np.empty((T, 32, 32), dtype=np.float32)
        for i in range(T):
            data = pickle.load(open(os.path.join(local_path, f"{s + i}.p"), "rb"))
            tactile[i] = data[0]

        velocity = np.zeros((T, 3), dtype=np.float32)
        valid = np.zeros((T,), dtype=np.float32)
        for i in range(T):
            v, ok = self._compute_velocity_at(local_path, ts, s, e, s + i)
            velocity[i] = v
            valid[i] = float(ok)

        return tactile, velocity, valid


def collate_pad(batch):
    """Pads variable-length sequences to the longest in the batch.

    Returns:
        tactile : (B, T_max, 32, 32) float32 tensor
        velocity: (B, T_max, 3)      float32 tensor
        valid   : (B, T_max)         float32 tensor (already 0 outside valid)
        lengths : (B,) long tensor of true lengths
    """
    lengths = [b[0].shape[0] for b in batch]
    T_max = max(lengths)
    B = len(batch)
    tac = np.zeros((B, T_max, 32, 32), dtype=np.float32)
    vel = np.zeros((B, T_max, 3), dtype=np.float32)
    val = np.zeros((B, T_max), dtype=np.float32)
    for i, (t, v, m) in enumerate(batch):
        T = t.shape[0]
        tac[i, :T] = t
        vel[i, :T] = v
        val[i, :T] = m
    return (
        torch.from_numpy(tac),
        torch.from_numpy(vel),
        torch.from_numpy(val),
        torch.tensor(lengths, dtype=torch.long),
    )
