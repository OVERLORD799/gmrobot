import os
import pickle
import numpy as np
from torch.utils.data import Dataset


def _read_timestamp_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.txt':
        with open(path, 'r') as file_obj:
            lines = file_obj.readlines()
        values = []
        for line in lines:
            line = line.strip()
            if line == '':
                continue
            values.append(float(line))
        return np.array(values, dtype=np.float32)

    data = pickle.load(open(path, 'rb'))
    if isinstance(data, list):
        data = np.array(data, dtype=np.float32)
    return data


def _load_sequence_timestamps(local_path):
    names = [
        'timestamps.p', 'timestamp.p', 'touch_ts.p', 'webcam_ts.p', 'ts.p',
        'timestamps.txt', 'webcam0.txt', 'webcam1.txt', 'webcam.txt'
    ]
    for name in names:
        candidate = os.path.join(local_path, name)
        if os.path.exists(candidate):
            try:
                return _read_timestamp_file(candidate)
            except Exception:
                continue
    return None


def _lookup_timestamp(ts_data, frame_idx, min_len):
    if ts_data is None:
        return None

    local_idx = frame_idx - min_len
    if isinstance(ts_data, dict):
        if frame_idx in ts_data:
            return float(ts_data[frame_idx])
        if str(frame_idx) in ts_data:
            return float(ts_data[str(frame_idx)])
        if local_idx in ts_data:
            return float(ts_data[local_idx])
        if str(local_idx) in ts_data:
            return float(ts_data[str(local_idx)])
        return None

    if isinstance(ts_data, np.ndarray):
        if local_idx >= 0 and local_idx < ts_data.shape[0]:
            return float(ts_data[local_idx])
        if frame_idx >= 0 and frame_idx < ts_data.shape[0]:
            return float(ts_data[frame_idx])
        return None

    if isinstance(ts_data, list):
        if local_idx >= 0 and local_idx < len(ts_data):
            return float(ts_data[local_idx])
        if frame_idx >= 0 and frame_idx < len(ts_data):
            return float(ts_data[frame_idx])
        return None

    return None


def _compute_dt(ts_data, idx_a, idx_b, min_len, default_fps):
    t_a = _lookup_timestamp(ts_data, idx_a, min_len)
    t_b = _lookup_timestamp(ts_data, idx_b, min_len)

    if t_a is not None and t_b is not None:
        dt = float(t_b - t_a)
        if dt > 1e-6:
            return dt, 1

    return 1.0 / float(default_fps), 0


def get_subsample(touch, subsample):
    for x in range(0, touch.shape[1], subsample):
        for y in range(0, touch.shape[2], subsample):
            value = np.mean(touch[:, x:x + subsample, y:y + subsample], (1, 2))
            touch[:, x:x + subsample, y:y + subsample] = value.reshape(-1, 1, 1)
    return touch


def window_select(log, path, f, idx, window):
    if window == 0:
        data = pickle.load(open(os.path.join(path, str(idx) + '.p'), 'rb'))
        return np.reshape(data[0], (1, 32, 32)), np.reshape(data[0], (1, 32, 32))

    max_len = log[f + 1]
    min_len = log[f]
    left = max([min_len, idx - window])
    right = min([max_len, idx + window])

    data_center = pickle.load(open(os.path.join(path, str(idx) + '.p'), 'rb'))
    tactile_frame = np.reshape(data_center[0], (1, 32, 32))
    tactile = np.empty((2 * window, 32, 32), dtype=np.float32)

    if left == min_len:
        for i in range(min_len, min_len + 2 * window):
            data = pickle.load(open(os.path.join(path, str(i) + '.p'), 'rb'))
            tactile[i - min_len, :, :] = data[0]
        return tactile, tactile_frame

    if right == max_len:
        for i in range(max_len - 2 * window, max_len):
            data = pickle.load(open(os.path.join(path, str(i) + '.p'), 'rb'))
            tactile[i - (max_len - 2 * window), :, :] = data[0]
        return tactile, tactile_frame

    for i in range(left, right):
        data = pickle.load(open(os.path.join(path, str(i) + '.p'), 'rb'))
        tactile[i - left, :, :] = data[0]

    return tactile, tactile_frame


class sample_velocity_data(Dataset):
    def __init__(self, path, window, mask, subsample, fps_default=10.0,
                 anchor_idx=8, head_idx=0, position_scale=1900.0, use_timestamps=True,
                 smooth_radius=1):
        self.mask = mask
        self.path = path
        self.window = window
        self.subsample = subsample
        self.log = pickle.load(open(self.path + 'log.p', 'rb'))
        self.fps_default = float(fps_default)
        self.anchor_idx = int(anchor_idx)
        self.head_idx = int(head_idx)
        self.position_scale = float(position_scale)
        self.use_timestamps = bool(use_timestamps)
        self.smooth_radius = max(0, int(smooth_radius))
        self._timestamp_cache = {}

    def __len__(self):
        if self.mask != []:
            return self.log[-1] + self.mask[-1]
        return self.log[-1]

    def _get_sequence_timestamps(self, local_path):
        if not self.use_timestamps:
            return None
        if local_path in self._timestamp_cache:
            return self._timestamp_cache[local_path]
        ts_data = _load_sequence_timestamps(local_path)
        self._timestamp_cache[local_path] = ts_data
        return ts_data

    def _load_keypoint(self, local_path, idx):
        data = pickle.load(open(os.path.join(local_path, str(idx) + '.p'), 'rb'))
        return np.array(data[2], dtype=np.float32)

    def _compute_velocity(self, local_path, f, idx):
        min_len = self.log[f]
        max_len = self.log[f + 1]
        ts_data = self._get_sequence_timestamps(local_path)

        def pair_velocity(idx_a, idx_b):
            keypoint_a = self._load_keypoint(local_path, idx_a)
            keypoint_b = self._load_keypoint(local_path, idx_b)
            dt_local, from_timestamp_local = _compute_dt(ts_data, idx_a, idx_b, min_len, self.fps_default)

            point_a = 0.5 * (keypoint_a[self.head_idx, :] + keypoint_a[self.anchor_idx, :]) * self.position_scale
            point_b = 0.5 * (keypoint_b[self.head_idx, :] + keypoint_b[self.anchor_idx, :]) * self.position_scale
            velocity_local = (point_b - point_a) / dt_local
            return velocity_local.astype(np.float32), float(dt_local), int(from_timestamp_local)

        if idx < min_len or idx >= max_len:
            return np.zeros((3,), dtype=np.float32), 0.0, 0, 0

        velocities = []
        weights = []
        dts = []
        from_timestamps = []

        for offset in range(-self.smooth_radius, self.smooth_radius + 1):
            idx_a = idx + offset
            idx_b = idx_a + 1
            if idx_a < min_len or idx_b >= max_len:
                continue

            velocity_local, dt_local, from_timestamp_local = pair_velocity(idx_a, idx_b)
            weight = float(self.smooth_radius + 1 - abs(offset))

            velocities.append(velocity_local)
            weights.append(weight)
            dts.append(dt_local)
            from_timestamps.append(from_timestamp_local)

        if len(velocities) == 0:
            if idx > min_len:
                velocity_local, dt_local, from_timestamp_local = pair_velocity(idx - 1, idx)
                return velocity_local, dt_local, from_timestamp_local, 1
            return np.zeros((3,), dtype=np.float32), 0.0, 0, 0

        weights = np.array(weights, dtype=np.float32)
        velocities = np.stack(velocities, axis=0)
        velocity = np.sum(velocities * weights.reshape(-1, 1), axis=0) / np.sum(weights)

        dt = float(np.sum(np.array(dts, dtype=np.float32) * weights) / np.sum(weights))
        from_timestamp = int(max(from_timestamps))
        return velocity.astype(np.float32), dt, from_timestamp, 1

    def __getitem__(self, idx):
        if self.mask != []:
            f = np.where((self.log + self.mask) <= idx)[0][-1]
            local_path = os.path.join(self.path, str(self.log[f]))
            query_idx = idx - self.mask[f]
        else:
            f = np.where(self.log <= idx)[0][-1]
            local_path = os.path.join(self.path, str(self.log[f]))
            query_idx = idx

        tactile, tactile_frame = window_select(self.log, local_path, f, query_idx, self.window)
        keypoint = self._load_keypoint(local_path, query_idx)
        velocity, dt, dt_from_timestamp, valid_velocity = self._compute_velocity(local_path, f, query_idx)

        if self.subsample > 1:
            tactile = get_subsample(tactile, self.subsample)

        return tactile, velocity, tactile_frame, keypoint, idx, dt, dt_from_timestamp, valid_velocity