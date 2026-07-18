"""Temporal velocity regressor: per-frame CNN + GRU.

Drop-in replacement for VelocityRegressor when training on stacked-tactile
windows. Same input shape ``(batch, 2*window_size, H, W)`` and output ``(batch, 3)``,
but inside it processes each timestep through a shared CNN, then aggregates
the resulting feature sequence with a GRU. Designed for the 32x32 tactile
grid produced by PressureMat-Walk-G1-Deploy-v0.

Architecture:
    input  : (B, T, H, W)             T = 2 * window_size
    CNN    : applied per timestep -> (B, T, F)
    GRU    : 1 layer, hidden=F        -> (B, T, F)
    pool   : take the last hidden     -> (B, F)
    head   : MLP F -> 128 -> 3
"""

import torch
import torch.nn as nn


class TactileTemporalRegressor(nn.Module):
    def __init__(self, window_size, cnn_feat=256, gru_hidden=256,
                 num_gru_layers=1, dropout=0.2):
        super().__init__()
        self.window_size = window_size

        # Per-frame CNN backbone (single-channel input, 32x32 -> feature vector)
        # Uses the same conv-bn-leakyrelu pattern as the original CNN, but with
        # one input channel and a smaller depth.
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32), nn.LeakyReLU(),

            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64), nn.LeakyReLU(),
            nn.MaxPool2d(kernel_size=2),                # 32 -> 16

            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128), nn.LeakyReLU(),
            nn.MaxPool2d(kernel_size=2),                # 16 -> 8

            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256), nn.LeakyReLU(),
            nn.MaxPool2d(kernel_size=2),                # 8 -> 4

            nn.Conv2d(256, cnn_feat, kernel_size=3, padding=1),
            nn.BatchNorm2d(cnn_feat), nn.LeakyReLU(),

            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),                                # -> (B*T, cnn_feat)
        )

        self.gru = nn.GRU(
            input_size=cnn_feat,
            hidden_size=gru_hidden,
            num_layers=num_gru_layers,
            batch_first=True,
            dropout=dropout if num_gru_layers > 1 else 0.0,
        )

        self.head = nn.Sequential(
            nn.Linear(gru_hidden, 128),
            nn.LeakyReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(128, 3),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, T, H, W) — T frames stacked as the channel dim by the loader.
        B, T, H, W = x.shape
        x = x.reshape(B * T, 1, H, W)
        feat = self.cnn(x)                             # (B*T, F)
        feat = feat.reshape(B, T, -1)                  # (B, T, F)
        seq, _ = self.gru(feat)                        # (B, T, H_g)
        last = seq[:, -1, :]                           # (B, H_g)
        return self.head(last)


class SequentialTactileTemporalRegressor(TactileTemporalRegressor):
    """Same backbone as ``TactileTemporalRegressor`` but emits a velocity
    prediction at EVERY timestep of the input sequence.

    Use with the sequence-level dataloader: feed full episodes, train with
    masked loss across all valid frames. Output shape: (B, T, 3).
    """

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, H, W = x.shape
        x = x.reshape(B * T, 1, H, W)
        feat = self.cnn(x)
        feat = feat.reshape(B, T, -1)
        seq, _ = self.gru(feat)                        # (B, T, H_g)
        out = self.head(seq.reshape(B * T, -1))        # (B*T, 3)
        return out.reshape(B, T, 3)


class SequentialTactileCausalLookaheadRegressor(nn.Module):
    """Causal GRU with a fixed N-frame future lookahead.

    At every step t the GRU input is the concatenation of the CNN features for
    frames ``[t, t+1, ..., t+N]``. The GRU itself is unidirectional (forward
    only) so the hidden state at step t depends on past frames + the t..t+N
    future block. Lookahead is bounded to N frames; past memory is unbounded
    (whatever the GRU's hidden state retains).

    For the last N frames of a sequence, the future window is clamped:
    feat[t+i] uses feat[T-1] when t+i >= T (sticky-edge padding).

    Output: (B, T, 3) — velocity prediction per timestep.
    """

    def __init__(self, lookahead: int = 4, cnn_feat: int = 1024,
                 gru_hidden: int = 256, num_gru_layers: int = 1,
                 dropout: float = 0.2):
        super().__init__()
        self.lookahead = int(lookahead)
        self.cnn_feat = int(cnn_feat)

        # Same per-frame CNN backbone as SequentialTactileBigBiRegressor.
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(32),

            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(64),
            nn.MaxPool2d(2),

            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(128),

            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(256),
            nn.MaxPool2d(2),

            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(512),

            nn.Conv2d(512, 1024, kernel_size=5),
            nn.LeakyReLU(), nn.BatchNorm2d(1024),

            nn.Conv2d(1024, cnn_feat, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(cnn_feat),
            nn.MaxPool2d(2),

            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),                              # (B*T, cnn_feat)
        )

        # Causal GRU. Input dim = (lookahead + 1) * cnn_feat (current + N future).
        gru_input_size = (self.lookahead + 1) * cnn_feat
        self.gru = nn.GRU(
            input_size=gru_input_size,
            hidden_size=gru_hidden,
            num_layers=num_gru_layers,
            batch_first=True,
            dropout=dropout if num_gru_layers > 1 else 0.0,
            bidirectional=False,
        )

        self.head = nn.Sequential(
            nn.Linear(gru_hidden, 128),
            nn.LeakyReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(128, 3),
        )

    @staticmethod
    def _shift_left_clamp(x: torch.Tensor, k: int) -> torch.Tensor:
        """Shift along dim=1 by -k with sticky-edge padding.
        After the shift, index t holds the value originally at min(t+k, T-1).
        """
        if k == 0:
            return x
        pad = x[:, -1:, :].expand(-1, k, -1)
        return torch.cat([x[:, k:, :], pad], dim=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, H, W = x.shape
        x = x.reshape(B * T, 1, H, W)
        feat = self.cnn(x).reshape(B, T, -1)            # (B, T, F)

        # Build (B, T, (N+1)*F) where each step has [feat[t], feat[t+1], ..., feat[t+N]]
        shifted = [self._shift_left_clamp(feat, k) for k in range(self.lookahead + 1)]
        gru_in = torch.cat(shifted, dim=-1)             # (B, T, (N+1)*F)

        seq, _ = self.gru(gru_in)                       # (B, T, H_g)
        out = self.head(seq.reshape(B * T, -1))         # (B*T, 3)
        return out.reshape(B, T, 3)


class SequentialTactileHybridRegressor(nn.Module):
    """Hybrid early- + late-fusion sequential model.

    Per-frame CNN takes a *small local stack* of (2*local_window + 1) frames
    centred on the current timestep — restoring the early temporal fusion that
    made the stacked-channel CNN strong. The CNN feature sequence is then fed
    through a causal GRU with an N-frame future lookahead block, exactly like
    ``SequentialTactileCausalLookaheadRegressor``.

    Default config (local_window=1, lookahead=4) means each timestep's CNN sees
    [t-1, t, t+1] as 3 channels, then the GRU input concatenates the
    [t, t+1, ..., t+4] future feature block. Total future visibility:
    +1 from local stack + +4 from lookahead = up to t+4 frames ahead.
    Past visibility: 1 frame from local stack + unbounded GRU memory.

    Output: (B, T, 3) per-timestep velocity prediction.
    """

    def __init__(self, local_window: int = 1, lookahead: int = 4,
                 cnn_feat: int = 1024, gru_hidden: int = 256,
                 num_gru_layers: int = 1, dropout: float = 0.2):
        super().__init__()
        self.local_window = int(local_window)
        self.lookahead = int(lookahead)
        self.cnn_feat = int(cnn_feat)
        in_ch = 2 * self.local_window + 1

        # Per-frame CNN — same backbone as SequentialTactileBigBiRegressor but
        # with `in_ch` input channels (early-fusion stack) instead of 1.
        self.cnn = nn.Sequential(
            nn.Conv2d(in_ch, 32, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(32),

            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(64),
            nn.MaxPool2d(2),

            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(128),

            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(256),
            nn.MaxPool2d(2),

            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(512),

            nn.Conv2d(512, 1024, kernel_size=5),
            nn.LeakyReLU(), nn.BatchNorm2d(1024),

            nn.Conv2d(1024, cnn_feat, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(cnn_feat),
            nn.MaxPool2d(2),

            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),                              # (B*T, cnn_feat)
        )

        gru_input_size = (self.lookahead + 1) * cnn_feat
        self.gru = nn.GRU(
            input_size=gru_input_size,
            hidden_size=gru_hidden,
            num_layers=num_gru_layers,
            batch_first=True,
            dropout=dropout if num_gru_layers > 1 else 0.0,
            bidirectional=False,
        )

        self.head = nn.Sequential(
            nn.Linear(gru_hidden, 128),
            nn.LeakyReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(128, 3),
        )

    @staticmethod
    def _shift_dim1_clamp(x: torch.Tensor, k: int) -> torch.Tensor:
        """Shift along dim=1 by k with sticky-edge padding.
        After the shift, index t holds value at clamp(t+k, 0, T-1).

        Works for tensors of shape (B, T, ...) with any trailing dims.
        """
        if k == 0:
            return x
        if k > 0:                                       # shift LEFT (look ahead)
            pad = x[:, -1:].expand(-1, k, *([-1] * (x.dim() - 2)))
            return torch.cat([x[:, k:], pad], dim=1)
        kk = -k                                         # shift RIGHT (look back)
        pad = x[:, :1].expand(-1, kk, *([-1] * (x.dim() - 2)))
        return torch.cat([pad, x[:, :-kk]], dim=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, H, W = x.shape

        # ---- Early fusion: build local-window channel stack at each timestep ----
        # For each k in [-local_window, +local_window], shift the sequence and
        # stack the resulting (B, T, H, W) tensors along a new channel dim →
        # (B, T, 2*local_window + 1, H, W).
        local = [self._shift_dim1_clamp(x, k)
                 for k in range(-self.local_window, self.local_window + 1)]
        local_stack = torch.stack(local, dim=2)         # (B, T, in_ch, H, W)

        # CNN per-timestep with the local stack as channels
        in_ch = local_stack.shape[2]
        cnn_in = local_stack.reshape(B * T, in_ch, H, W)
        feat = self.cnn(cnn_in).reshape(B, T, -1)       # (B, T, cnn_feat)

        # ---- Late fusion: lookahead block + causal GRU ----
        shifted = [self._shift_dim1_clamp(feat, k) for k in range(self.lookahead + 1)]
        gru_in = torch.cat(shifted, dim=-1)             # (B, T, (N+1)*cnn_feat)

        seq, _ = self.gru(gru_in)                       # (B, T, gru_hidden)
        out = self.head(seq.reshape(B * T, -1))         # (B*T, 3)
        return out.reshape(B, T, 3)


class SequentialTactileBigBiRegressor(nn.Module):
    """Per-frame CNN (1024 features, matches original VelocityRegressor backbone)
    + BIDIRECTIONAL GRU + per-timestep head.

    Restores the larger CNN capacity that was lost when the temporal head was
    introduced, and gives every timestep both past AND future context — matching
    the centered-window behavior of the stacked-channel CNN baseline.

    Output: (B, T, 3) — velocity prediction per timestep.
    """

    def __init__(self, cnn_feat: int = 1024, gru_hidden: int = 256,
                 num_gru_layers: int = 1, dropout: float = 0.2):
        super().__init__()

        # Per-frame CNN backbone — same shape progression as the original
        # VelocityRegressor:
        #   32x32 -> 16 (pool) -> 8 (pool) -> 4 (5x5, no pad) -> 2 (pool) -> 1 (gap)
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(32),

            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(64),
            nn.MaxPool2d(2),

            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(128),

            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(256),
            nn.MaxPool2d(2),

            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(512),

            nn.Conv2d(512, 1024, kernel_size=5),
            nn.LeakyReLU(), nn.BatchNorm2d(1024),

            nn.Conv2d(1024, cnn_feat, kernel_size=3, padding=1),
            nn.LeakyReLU(), nn.BatchNorm2d(cnn_feat),
            nn.MaxPool2d(2),

            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),                              # (B*T, cnn_feat)
        )

        # Bidirectional GRU — output dim is 2 * gru_hidden after concat.
        self.gru = nn.GRU(
            input_size=cnn_feat,
            hidden_size=gru_hidden,
            num_layers=num_gru_layers,
            batch_first=True,
            dropout=dropout if num_gru_layers > 1 else 0.0,
            bidirectional=True,
        )

        self.head = nn.Sequential(
            nn.Linear(2 * gru_hidden, 128),
            nn.LeakyReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(128, 3),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, H, W = x.shape
        x = x.reshape(B * T, 1, H, W)
        feat = self.cnn(x)                             # (B*T, cnn_feat)
        feat = feat.reshape(B, T, -1)
        seq, _ = self.gru(feat)                        # (B, T, 2*H_g)
        out = self.head(seq.reshape(B * T, -1))        # (B*T, 3)
        return out.reshape(B, T, 3)
