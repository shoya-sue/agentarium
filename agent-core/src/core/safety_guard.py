"""
core/safety_guard.py — サーキットブレーカー + レート制限

Skill 実行の安全制限を管理する。
- config/safety.yaml の設定に基づいてサーキットブレーカーとレート制限を適用
- 登録されていない Skill は制限なし（allowed=True）として扱う
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from utils.config import load_yaml_config

logger = logging.getLogger(__name__)

# レート制限のウィンドウ定義
_ONE_HOUR = timedelta(hours=1)
_ONE_DAY = timedelta(hours=24)


@dataclass(frozen=True)
class SafetyResult:
    """
    safety_guard.check の結果。

    Attributes:
        allowed: 実行を許可するか
        reason: 拒否理由（allowed=True の場合は None）
        wait_seconds: 待機推奨秒数（0 は即時再試行可能）
    """

    allowed: bool
    reason: str | None = None
    wait_seconds: int = 0


class SafetyGuard:
    """
    Skill 実行のサーキットブレーカーとレート制限を管理する。

    config/safety.yaml を読み込み、Skill ごとの実行制限を適用する。
    登録されていない Skill は制限なしとして扱う。

    Args:
        config_dir: config/ ディレクトリのパス
    """

    def __init__(self, config_dir: Path | str) -> None:
        self._config_dir = Path(config_dir)
        self._config: dict[str, Any] = {}

        # Skill ごとの連続失敗数
        self._failure_counts: dict[str, int] = {}

        # サーキットが開いた時刻（Skill → datetime）
        self._circuit_open_at: dict[str, datetime] = {}

        # 直近1時間の実行時刻リスト（Skill → list[datetime]）
        self._hourly_counts: dict[str, list[datetime]] = {}

        # 直近24時間の実行時刻リスト（Skill → list[datetime]）
        self._daily_counts: dict[str, list[datetime]] = {}

        self._load_config()

    def _load_config(self) -> None:
        """safety.yaml を読み込む。"""
        config_path = self._config_dir / "safety.yaml"
        self._config = load_yaml_config(config_path)
        logger.info("SafetyGuard 設定読み込み完了: %s", config_path)

    def check(self, skill_name: str) -> SafetyResult:
        """
        Skill の実行を許可するか判定する。

        判定順序:
          1. サーキットブレーカーチェック（開いていれば拒否）
          2. 時間制限チェック（max_per_hour 超過で拒否）
          3. 日次制限チェック（max_per_day 超過で拒否）
          4. 全て通過したら allowed=True

        Args:
            skill_name: 実行する Skill 名

        Returns:
            SafetyResult: 許可 / 拒否の結果
        """
        # 古い記録を除去してからチェック
        self._cleanup_old_records(skill_name)

        # 1. サーキットブレーカーチェック
        if self.is_circuit_open(skill_name):
            recovery_timeout = self._get_recovery_timeout()
            logger.warning(
                "サーキットブレーカー開放中のため拒否: %s", skill_name
            )
            return SafetyResult(
                allowed=False,
                reason=f"サーキットブレーカー開放中: {skill_name}",
                wait_seconds=recovery_timeout,
            )

        # skill_limits に登録されていない Skill は制限なし
        skill_limits = self._config.get("skill_limits", {})
        if skill_name not in skill_limits:
            return SafetyResult(allowed=True)

        limits = skill_limits[skill_name]
        max_per_hour: int | None = limits.get("max_per_hour")
        max_per_day: int | None = limits.get("max_per_day")

        # 2. 時間制限チェック
        if max_per_hour is not None:
            hourly_count = len(self._hourly_counts.get(skill_name, []))
            if hourly_count >= max_per_hour:
                logger.warning(
                    "時間制限超過のため拒否: %s (%d/%d 回/時)",
                    skill_name,
                    hourly_count,
                    max_per_hour,
                )
                return SafetyResult(
                    allowed=False,
                    reason=f"時間あたり実行制限超過: {skill_name} ({hourly_count}/{max_per_hour})",
                    wait_seconds=60,
                )

        # 3. 日次制限チェック
        if max_per_day is not None:
            daily_count = len(self._daily_counts.get(skill_name, []))
            if daily_count >= max_per_day:
                logger.warning(
                    "日次制限超過のため拒否: %s (%d/%d 回/日)",
                    skill_name,
                    daily_count,
                    max_per_day,
                )
                return SafetyResult(
                    allowed=False,
                    reason=f"日次実行制限超過: {skill_name} ({daily_count}/{max_per_day})",
                    wait_seconds=3600,
                )

        return SafetyResult(allowed=True)

    def record_success(self, skill_name: str) -> None:
        """
        Skill 実行成功を記録する。

        連続失敗数をリセットし、実行時刻を hourly/daily カウントに追加する。
        """
        # 連続失敗数リセット
        self._failure_counts[skill_name] = 0

        # 実行時刻を記録
        now = datetime.now(timezone.utc)
        if skill_name not in self._hourly_counts:
            self._hourly_counts[skill_name] = []
        if skill_name not in self._daily_counts:
            self._daily_counts[skill_name] = []

        self._hourly_counts[skill_name].append(now)
        self._daily_counts[skill_name].append(now)

        logger.debug("Skill 実行成功記録: %s", skill_name)

    def record_failure(self, skill_name: str) -> None:
        """
        Skill 実行失敗を記録する。

        連続失敗数をインクリメントし、閾値を超えたらサーキットを開く。
        """
        current = self._failure_counts.get(skill_name, 0)
        self._failure_counts[skill_name] = current + 1

        threshold = self._get_failure_threshold()

        if self._failure_counts[skill_name] >= threshold:
            # サーキットを開く
            self._circuit_open_at[skill_name] = datetime.now(timezone.utc)
            logger.warning(
                "サーキットブレーカー開放: %s（連続失敗数: %d）",
                skill_name,
                self._failure_counts[skill_name],
            )

        logger.debug(
            "Skill 実行失敗記録: %s（連続失敗数: %d）",
            skill_name,
            self._failure_counts[skill_name],
        )

    def is_circuit_open(self, skill_name: str) -> bool:
        """
        サーキットブレーカーが開いているか判定する。

        recovery_timeout 経過後は自動リセットして False を返す。

        Args:
            skill_name: 判定する Skill 名

        Returns:
            True: サーキットが開いている（実行不可）
            False: サーキットが閉じている（実行可能）
        """
        opened_at = self._circuit_open_at.get(skill_name)
        if opened_at is None:
            return False

        recovery_timeout = self._get_recovery_timeout()
        elapsed = (datetime.now(timezone.utc) - opened_at).total_seconds()

        if elapsed >= recovery_timeout:
            # recovery_timeout 経過後は自動リセット
            del self._circuit_open_at[skill_name]
            self._failure_counts[skill_name] = 0
            logger.info(
                "サーキットブレーカー自動リセット: %s（%d 秒経過）",
                skill_name,
                elapsed,
            )
            return False

        return True

    def _cleanup_old_records(self, skill_name: str) -> None:
        """
        1時間 / 24時間以前の実行記録を除去する。

        メモリを節約するため、check / record_* の前に呼ぶ。
        """
        now = datetime.now(timezone.utc)
        one_hour_ago = now - _ONE_HOUR
        one_day_ago = now - _ONE_DAY

        # 時間制限カウントの古い記録を除去
        if skill_name in self._hourly_counts:
            self._hourly_counts[skill_name] = [
                ts for ts in self._hourly_counts[skill_name]
                if ts > one_hour_ago
            ]

        # 日次カウントの古い記録を除去
        if skill_name in self._daily_counts:
            self._daily_counts[skill_name] = [
                ts for ts in self._daily_counts[skill_name]
                if ts > one_day_ago
            ]

    def _get_failure_threshold(self) -> int:
        """circuit_breaker.failure_threshold を取得する（デフォルト: 5）。"""
        cb_config = self._config.get("circuit_breaker", {})
        return int(cb_config.get("failure_threshold", 5))

    def _get_recovery_timeout(self) -> int:
        """circuit_breaker.recovery_timeout を取得する（デフォルト: 300）。"""
        cb_config = self._config.get("circuit_breaker", {})
        return int(cb_config.get("recovery_timeout", 300))
