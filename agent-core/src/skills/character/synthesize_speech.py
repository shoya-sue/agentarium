"""
skills/character/synthesize_speech.py — TTS 音声合成 Skill

L3 感情状態（valence/arousal/dominance）を VOICEVOX 音声パラメータに変換し、
VOICEVOX REST API で音声（WAV）を生成する。

VOICEVOX REST API:
  POST /audio_query?text={text}&speaker={speaker_id}
  POST /synthesis?speaker={speaker_id}
  → application/x-wav

D14 決定: Style-Bert-VITS2（主）+ VOICEVOX（検証/フォールバック）

Skill 入出力スキーマ: config/skills/character/synthesize_speech.yaml
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# デフォルト VOICEVOX スピーカー ID
# 参考: https://voicevox.hiroshiba.jp/
_DEFAULT_SPEAKER_ID = 3  # ずんだもん（ノーマル）

# 感情→スピーカーIDマッピング（valence/arousal の組み合わせ）
# valence: ポジティブ/ネガティブ (-1.0〜1.0)
# arousal: 高覚醒/低覚醒 (-1.0〜1.0)
_EMOTION_SPEAKER_MAP: list[dict[str, Any]] = [
    {"valence_min": 0.3, "arousal_min": 0.3, "speaker_id": 3, "label": "happy_excited"},   # 喜び・興奮
    {"valence_min": 0.3, "arousal_max": -0.3, "speaker_id": 2, "label": "calm_happy"},      # 穏やか・嬉しい
    {"valence_max": -0.3, "arousal_min": 0.3, "speaker_id": 6, "label": "angry_upset"},      # 怒り・不安
    {"valence_max": -0.3, "arousal_max": -0.3, "speaker_id": 0, "label": "sad_tired"},       # 悲しみ・疲れ
]

# pitch/speed の調整幅（arousal/valence に比例）
_SPEED_BASE = 1.0
_PITCH_BASE = 0.0
_SPEED_RANGE = 0.3   # ±0.3
_PITCH_RANGE = 0.1   # ±0.1


class SynthesizeSpeechSkill:
    """
    synthesize_speech Skill の実装。

    1. L3 感情状態 → スピーカーID + pitch/speed を計算
    2. VOICEVOX API で audio_query を生成
    3. VOICEVOX API で音声を合成
    4. WAV ファイルを data/outputs/speech/ に保存
    5. ファイルパスを返す
    """

    def __init__(
        self,
        voicevox_url: str = "http://localhost:50021",
        output_dir: Path | str | None = None,
    ) -> None:
        self._voicevox_url = voicevox_url.rstrip("/")
        self._output_dir = Path(output_dir) if output_dir else Path("data/outputs/speech")
        self._http = httpx.AsyncClient(timeout=30.0)

    def _map_emotion_to_speaker(
        self,
        valence: float,
        arousal: float,
    ) -> int:
        """
        valence/arousal から VOICEVOX スピーカー ID を選択する。

        感情象限に基づくルールベースマッピング:
        - 高valence + 高arousal → 喜び・興奮 (speaker 3)
        - 高valence + 低arousal → 穏やか・嬉しい (speaker 2)
        - 低valence + 高arousal → 怒り・不安 (speaker 6)
        - 低valence + 低arousal → 悲しみ・疲れ (speaker 0)
        """
        for mapping in _EMOTION_SPEAKER_MAP:
            v_min = mapping.get("valence_min")
            v_max = mapping.get("valence_max")
            a_min = mapping.get("arousal_min")
            a_max = mapping.get("arousal_max")

            v_ok = (v_min is None or valence >= v_min) and (v_max is None or valence <= v_max)
            a_ok = (a_min is None or arousal >= a_min) and (a_max is None or arousal <= a_max)

            if v_ok and a_ok:
                return int(mapping["speaker_id"])

        return _DEFAULT_SPEAKER_ID

    def _calc_voice_params(
        self,
        valence: float,
        arousal: float,
        dominance: float,
    ) -> dict[str, float]:
        """
        感情パラメータから音声調整値を計算する。

        speed: arousal に比例（高覚醒 → 速く）
        pitch: valence + dominance に比例（ポジティブ・支配的 → 高め）
        """
        speed = _SPEED_BASE + arousal * _SPEED_RANGE
        pitch = _PITCH_BASE + (valence * 0.6 + dominance * 0.4) * _PITCH_RANGE

        # 範囲クランプ
        speed = max(0.5, min(2.0, speed))
        pitch = max(-0.15, min(0.15, pitch))

        return {"speed": round(speed, 3), "pitch": round(pitch, 3)}

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        テキストを感情状態に応じた音声に合成する。

        Args:
            params:
                text (str): 読み上げテキスト（必須）
                valence (float): 感情の快/不快 -1.0〜1.0（デフォルト: 0.0）
                arousal (float): 覚醒度 -1.0〜1.0（デフォルト: 0.0）
                dominance (float): 支配性 -1.0〜1.0（デフォルト: 0.0）
                speaker_id (int | None): スピーカーIDの上書き（省略時は感情から自動選択）
                output_filename (str | None): 出力ファイル名（省略時はUUID）

        Returns:
            {
                "file_path": str,        # 保存先パス
                "speaker_id": int,       # 使用したスピーカーID
                "speed": float,          # 音声速度
                "pitch": float,          # ピッチ調整値
                "duration_hint": None,   # 将来: 音声長(秒)
                "synthesized_at": str,
                "voicevox_available": bool,
            }
        """
        text: str = params["text"]
        valence: float = float(params.get("valence", 0.0))
        arousal: float = float(params.get("arousal", 0.0))
        dominance: float = float(params.get("dominance", 0.0))
        speaker_override: int | None = params.get("speaker_id")
        output_filename: str | None = params.get("output_filename")

        if not text.strip():
            raise ValueError("text が空です")

        # 感情パラメータの範囲チェック
        for name, val in [("valence", valence), ("arousal", arousal), ("dominance", dominance)]:
            if not (-1.0 <= val <= 1.0):
                raise ValueError(f"{name} は -1.0〜1.0 の範囲で指定してください: {val}")

        # スピーカーIDと音声パラメータを決定
        speaker_id = speaker_override if speaker_override is not None else self._map_emotion_to_speaker(valence, arousal)
        voice_params = self._calc_voice_params(valence, arousal, dominance)

        synthesized_at = datetime.now(timezone.utc).isoformat()

        # 出力パスを準備
        self._output_dir.mkdir(parents=True, exist_ok=True)
        filename = output_filename or f"{uuid.uuid4().hex}.wav"
        if not filename.endswith(".wav"):
            filename += ".wav"
        output_path = self._output_dir / filename

        # VOICEVOX API 呼び出し
        voicevox_available = True
        try:
            wav_data = await self._synthesize(text, speaker_id, voice_params)
            output_path.write_bytes(wav_data)
            logger.info(
                "synthesize_speech: speaker=%d speed=%.2f pitch=%.2f → %s",
                speaker_id,
                voice_params["speed"],
                voice_params["pitch"],
                output_path,
            )
        except httpx.ConnectError:
            logger.warning(
                "synthesize_speech: VOICEVOX サーバー接続失敗 (%s)。スキップします。",
                self._voicevox_url,
            )
            voicevox_available = False
            # フォールバック: 空の WAV ヘッダーを書き込む（ファイルが存在することだけ保証）
            output_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
        except Exception as exc:
            logger.error("synthesize_speech: 音声合成エラー: %s", exc)
            raise

        return {
            "file_path": str(output_path),
            "speaker_id": speaker_id,
            "speed": voice_params["speed"],
            "pitch": voice_params["pitch"],
            "duration_hint": None,
            "synthesized_at": synthesized_at,
            "voicevox_available": voicevox_available,
        }

    async def _synthesize(
        self,
        text: str,
        speaker_id: int,
        voice_params: dict[str, float],
    ) -> bytes:
        """
        VOICEVOX API を呼び出して WAV データを生成する。

        1. POST /audio_query → クエリJSON取得
        2. クエリJSON に speed/pitch を適用
        3. POST /synthesis → WAV データ取得
        """
        # Step 1: audio_query
        query_resp = await self._http.post(
            f"{self._voicevox_url}/audio_query",
            params={"text": text, "speaker": speaker_id},
        )
        query_resp.raise_for_status()
        audio_query = query_resp.json()

        # Step 2: パラメータ適用
        audio_query["speedScale"] = voice_params["speed"]
        audio_query["pitchScale"] = voice_params["pitch"]

        # Step 3: synthesis
        synth_resp = await self._http.post(
            f"{self._voicevox_url}/synthesis",
            params={"speaker": speaker_id},
            json=audio_query,
            headers={"Content-Type": "application/json"},
        )
        synth_resp.raise_for_status()
        return synth_resp.content

    async def close(self) -> None:
        """HTTP クライアントを閉じる"""
        await self._http.aclose()
