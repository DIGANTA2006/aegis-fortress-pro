"""
rl_agent.py  -  AEGIS PRO v2
Deep Q-Network (DQN) reinforcement learning agent.

Architecture:
  - Custom TradingEnv (OpenAI Gym-compatible) driven by OHLCV + feature rows
  - DQN with experience replay buffer and target network
  - Reward  = portfolio Sharpe ratio contribution per step
  - Actions = 0: HOLD  |  1: BUY  |  2: SELL/EXIT
  - Online inference + periodic fine-tuning from live experience

Dependencies:
    pip install torch numpy pandas
    (torch is optional - falls back to rule-based action if unavailable)
"""

import logging
import math
import random
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import PATHS, AegisConfig

log = logging.getLogger("aegis.rl")

# ---------------------------------------------------------------------------
# Optional PyTorch import
# ---------------------------------------------------------------------------
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False
    log.warning("torch not installed - RL agent disabled. pip install torch")

ACTIONS = {0: "HOLD", 1: "BUY", 2: "SELL"}
MODEL_PATH = Path(PATHS.get("ml_model", ".")).parent / "dqn_model.pt"


# ---------------------------------------------------------------------------
# Trading environment (gym-compatible, no gym dependency)
# ---------------------------------------------------------------------------


class TradingEnv:
    """
    Single-asset episodic trading environment.

    Observation: feature vector (N,) at each bar
    Action:      0=HOLD, 1=BUY, 2=SELL
    Reward:      Sharpe-weighted per-step return minus transaction costs
    Episode:     one full OHLCV DataFrame (resets on done=True)
    """

    TAKER_FEE = 0.001
    SLIPPAGE = 0.0005
    REWARD_SCALE = 100.0  # scale rewards for gradient stability

    def __init__(
        self,
        feature_cols: List[str],
        initial_capital: float = 10_000.0,
    ):
        self.feature_cols = feature_cols
        self.initial_capital = initial_capital

        # Episode state (reset on each episode)
        self._df: Optional[pd.DataFrame] = None
        self._idx = 0
        self._cash = initial_capital
        self._position = 0.0  # units held
        self._entry_price = 0.0
        self._returns: List[float] = []
        self._equity_start = initial_capital

    # ------------------------------------------------------------------

    def reset(self, df: pd.DataFrame) -> np.ndarray:
        """Start a new episode. df must have feature_cols + 'c' column."""
        self._df = df.reset_index(drop=True)
        self._idx = 50  # skip warm-up bars
        self._cash = self.initial_capital
        self._position = 0.0
        self._entry_price = 0.0
        self._returns = []
        self._equity_start = self.initial_capital
        return self._obs()

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, dict]:
        """
        Apply action, advance one bar.
        Returns: (obs, reward, done, info)
        """
        assert self._df is not None, "Call reset() first"

        price = float(self._df["c"].iloc[self._idx])
        prev_eq = self._equity()

        # ---- Execute action ----
        reward_penalty = 0.0
        if action == 1 and self._position == 0:  # BUY
            buy_price = price * (1 + self.SLIPPAGE)
            units = (self._cash * 0.95) / buy_price
            cost = units * buy_price
            fee = cost * self.TAKER_FEE
            self._cash -= cost + fee
            self._position = units
            self._entry_price = buy_price
            reward_penalty = -fee / max(prev_eq, 1)

        elif action == 2 and self._position > 0:  # SELL
            sell_price = price * (1 - self.SLIPPAGE)
            proceeds = self._position * sell_price
            fee = proceeds * self.TAKER_FEE
            self._cash += proceeds - fee
            self._position = 0.0
            reward_penalty = -fee / max(prev_eq, 1)

        # ---- Advance bar ----
        self._idx += 1
        done = self._idx >= len(self._df) - 1

        # Force close at episode end
        if done and self._position > 0:
            close_price = float(self._df["c"].iloc[-1]) * (1 - self.SLIPPAGE)
            fee = self._position * close_price * self.TAKER_FEE
            self._cash += self._position * close_price - fee
            self._position = 0.0

        # ---- Reward: step Sharpe contribution ----
        new_eq = self._equity()
        step_ret = (new_eq - prev_eq) / max(prev_eq, 1)
        self._returns.append(step_ret)
        reward = self._sharpe_reward(step_ret) + reward_penalty

        info = {
            "equity": new_eq,
            "position": self._position,
            "price": price,
            "action": ACTIONS[action],
        }
        return self._obs(), reward * self.REWARD_SCALE, done, info

    # ------------------------------------------------------------------

    def _equity(self) -> float:
        price = float(self._df["c"].iloc[self._idx]) if self._df is not None else 0
        return self._cash + self._position * price

    def _obs(self) -> np.ndarray:
        row = self._df.iloc[self._idx]
        vals = []
        for col in self.feature_cols:
            v = float(row.get(col, 0.0))
            vals.append(0.0 if math.isnan(v) else v)
        # Append portfolio state features
        eq = self._equity()
        vals += [
            float(self._position > 0),  # in_position
            (eq - self.initial_capital) / max(self.initial_capital, 1),  # unrealised_pct
        ]
        return np.array(vals, dtype=np.float32)

    def _sharpe_reward(self, step_ret: float) -> float:
        """Running Sharpe estimate used as reward signal."""
        n = len(self._returns)
        if n < 5:
            return step_ret
        arr = np.array(self._returns[-50:])
        std = arr.std()
        mean = arr.mean()
        return float(mean / (std + 1e-8))

    @property
    def obs_dim(self) -> int:
        return len(self.feature_cols) + 2  # +2 for portfolio state

    @property
    def action_dim(self) -> int:
        return 3


# ---------------------------------------------------------------------------
# DQN neural network
# ---------------------------------------------------------------------------

if _HAS_TORCH:

    class DQNNet(nn.Module):
        def __init__(self, obs_dim: int, action_dim: int, hidden: int = 256):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(obs_dim, hidden),
                nn.LayerNorm(hidden),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(hidden, hidden),
                nn.LayerNorm(hidden),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(hidden, action_dim),
            )

        def forward(self, x):
            return self.net(x)


# ---------------------------------------------------------------------------
# Replay buffer
# ---------------------------------------------------------------------------


class ReplayBuffer:
    """Uniform experience replay buffer."""

    def __init__(self, capacity: int = 50_000):
        self._buf = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self._buf.append(
            (
                np.array(state, dtype=np.float32),
                int(action),
                float(reward),
                np.array(next_state, dtype=np.float32),
                float(done),
            )
        )

    def sample(self, batch_size: int):
        batch = random.sample(self._buf, batch_size)
        s, a, r, ns, d = zip(*batch, strict=False)
        return (
            np.array(s),
            np.array(a),
            np.array(r, dtype=np.float32),
            np.array(ns),
            np.array(d, dtype=np.float32),
        )

    def __len__(self):
        return len(self._buf)


# ---------------------------------------------------------------------------
# DQN Agent
# ---------------------------------------------------------------------------


class DQNAgent:
    """
    Deep Q-Network agent for autonomous trade decision making.

    Usage:
        agent = DQNAgent(cfg, feature_cols)
        agent.train_offline(ohlcv_frames)      # offline training on historical data
        action = agent.act(obs)                # online inference
        agent.remember(s, a, r, ns, done)      # collect live experience
        agent.fine_tune()                      # periodic online update
    """

    GAMMA = 0.99
    LR = 3e-4
    BATCH_SIZE = 128
    TARGET_SYNC = 500  # steps between target network sync
    EPS_START = 1.0
    EPS_END = 0.05
    EPS_DECAY = 5000  # steps for epsilon to decay from start ? end
    MIN_BUFFER = 1000  # minimum buffer size before training starts

    def __init__(self, cfg: AegisConfig, feature_cols: List[str]):
        self.cfg = cfg
        self.feature_cols = feature_cols
        self.env = TradingEnv(feature_cols)
        self.obs_dim = self.env.obs_dim
        self.action_dim = self.env.action_dim

        self.buffer = ReplayBuffer(50_000)
        self._steps = 0
        self._epsilon = self.EPS_START
        self.last_trained = 0.0
        self.episode_rewards: List[float] = []

        if not _HAS_TORCH:
            self._online = None
            self._target = None
            self._optim = None
            return

        device_name = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device_name)
        log.info(f"DQN using device: {device_name}")

        self._online = DQNNet(self.obs_dim, self.action_dim).to(self.device)
        self._target = DQNNet(self.obs_dim, self.action_dim).to(self.device)
        self._target.load_state_dict(self._online.state_dict())
        self._target.eval()
        self._optim = optim.Adam(self._online.parameters(), lr=self.LR)
        self._loss_fn = nn.SmoothL1Loss()

        self.load()

    # ------------------------------------------------------------------
    # Offline training on historical OHLCV data
    # ------------------------------------------------------------------

    def train_offline(
        self,
        ohlcv_frames: Dict[str, pd.DataFrame],
        episodes_per_symbol: int = 3,
    ) -> Dict[str, float]:
        """
        Train the DQN agent by running episodes over historical data.
        Returns {symbol: mean_episode_reward}.
        """
        if not _HAS_TORCH or self._online is None:
            log.warning("PyTorch not available - skipping RL training.")
            return {}

        results = {}
        for symbol, df in ohlcv_frames.items():
            feat_cols = [c for c in self.feature_cols if c in df.columns]
            if not feat_cols or len(df) < 200:
                continue

            ep_rewards = []
            for _ep in range(episodes_per_symbol):
                obs = self.env.reset(df)
                ep_total = 0.0
                done = False

                while not done:
                    action = self._epsilon_greedy(obs)
                    next_obs, r, done, _ = self.env.step(action)
                    self.buffer.push(obs, action, r, next_obs, done)
                    ep_total += r
                    obs = next_obs

                    if len(self.buffer) >= self.MIN_BUFFER:
                        self._update()
                        self._steps += 1
                        self._sync_target_if_needed()
                        self._decay_epsilon()

                ep_rewards.append(ep_total)

            mean_r = float(np.mean(ep_rewards)) if ep_rewards else 0.0
            results[symbol] = mean_r
            log.info(
                f"DQN train {symbol}: {episodes_per_symbol} episodes, "
                f"mean_reward={mean_r:.2f}, eps={self._epsilon:.3f}"
            )

        self.last_trained = time.time()
        self.save()
        return results

    # ------------------------------------------------------------------
    # Online inference
    # ------------------------------------------------------------------

    def act(self, obs: np.ndarray, deterministic: bool = False) -> int:
        """
        Choose action for the current observation.
        deterministic=True ? greedy (no exploration).
        Falls back to HOLD if torch unavailable.
        """
        if not _HAS_TORCH or self._online is None:
            return 0  # HOLD

        if not deterministic and random.random() < max(self._epsilon, self.EPS_END):
            return random.randint(0, self.action_dim - 1)

        with torch.no_grad():
            t = torch.FloatTensor(obs).unsqueeze(0).to(self.device)
            q = self._online(t)
            return int(q.argmax(dim=1).item())

    # ------------------------------------------------------------------
    # Live fine-tuning
    # ------------------------------------------------------------------

    def remember(self, state, action, reward, next_state, done):
        """Store a live transition for online fine-tuning."""
        self.buffer.push(state, action, reward, next_state, done)

    def fine_tune(self, steps: int = 50) -> float:
        """Run N gradient updates from live buffer. Returns mean loss."""
        if not _HAS_TORCH or self._online is None:
            return 0.0
        if len(self.buffer) < self.MIN_BUFFER:
            return 0.0
        losses = []
        for _ in range(steps):
            loss = self._update()
            if loss is not None:
                losses.append(loss)
            self._steps += 1
            self._sync_target_if_needed()
        return float(np.mean(losses)) if losses else 0.0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _epsilon_greedy(self, obs: np.ndarray) -> int:
        if random.random() < self._epsilon:
            return random.randint(0, self.action_dim - 1)
        return self.act(obs, deterministic=True)

    def _decay_epsilon(self):
        self._epsilon = self.EPS_END + (self.EPS_START - self.EPS_END) * math.exp(
            -self._steps / self.EPS_DECAY
        )

    def _sync_target_if_needed(self):
        if self._steps % self.TARGET_SYNC == 0:
            self._target.load_state_dict(self._online.state_dict())

    def _update(self) -> Optional[float]:
        if len(self.buffer) < self.BATCH_SIZE:
            return None

        s, a, r, ns, d = self.buffer.sample(self.BATCH_SIZE)

        s = torch.FloatTensor(s).to(self.device)
        a = torch.LongTensor(a).to(self.device)
        r = torch.FloatTensor(r).to(self.device)
        ns = torch.FloatTensor(ns).to(self.device)
        d = torch.FloatTensor(d).to(self.device)

        # Current Q values
        q_vals = self._online(s).gather(1, a.unsqueeze(1)).squeeze(1)

        # Target Q values (Double DQN: online selects action, target evaluates)
        with torch.no_grad():
            next_actions = self._online(ns).argmax(dim=1)
            next_q = self._target(ns).gather(1, next_actions.unsqueeze(1)).squeeze(1)
            target_q = r + self.GAMMA * next_q * (1 - d)

        loss = nn.functional.smooth_l1_loss(q_vals, target_q)
        self._optim.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self._online.parameters(), 1.0)
        self._optim.step()

        return float(loss.item())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        if not _HAS_TORCH or self._online is None:
            return
        try:
            torch.save(
                {
                    "online": self._online.state_dict(),
                    "target": self._target.state_dict(),
                    "steps": self._steps,
                    "epsilon": self._epsilon,
                    "obs_dim": self.obs_dim,
                    "act_dim": self.action_dim,
                },
                MODEL_PATH,
            )
            log.info(f"DQN model saved to {MODEL_PATH}")
        except Exception as exc:
            log.warning(f"DQN save failed: {exc}")

    def load(self) -> bool:
        if not _HAS_TORCH or not MODEL_PATH.exists():
            return False
        try:
            ckpt = torch.load(MODEL_PATH, map_location=self.device)
            if ckpt.get("obs_dim") != self.obs_dim:
                log.warning("DQN obs_dim mismatch - starting fresh.")
                return False
            self._online.load_state_dict(ckpt["online"])
            self._target.load_state_dict(ckpt["target"])
            self._steps = ckpt.get("steps", 0)
            self._epsilon = ckpt.get("epsilon", self.EPS_END)
            log.info(f"DQN model loaded (steps={self._steps}, eps={self._epsilon:.3f})")
            return True
        except Exception as exc:
            log.warning(f"DQN load failed: {exc}")
            return False

    def action_name(self, action: int) -> str:
        return ACTIONS.get(action, "HOLD")
