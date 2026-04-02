"""
tests/skills/character/test_synthesize_speech.py — SynthesizeSpeechSkill ユニットテスト

VOICEVOX API をモックして感情→音声パラメータ変換と API 呼び出しを検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


class TestSynthesizeSpeechSkill:
    """SynthesizeSpeechSkill のテスト"""

    def test_import(self):
        """モジュールが正常にインポートできる"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill
        assert SynthesizeSpeechSkill is not None

    def test_map_emotion_happy_excited(self):
        """高valence + 高arousal → happy_excited スピーカー"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill.__new__(SynthesizeSpeechSkill)
        speaker = skill._map_emotion_to_speaker(valence=0.8, arousal=0.7)
        assert speaker == 888753762  # まお/あまあま

    def test_map_emotion_sad_tired(self):
        """低valence + 低arousal → sad_tired スピーカー"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill.__new__(SynthesizeSpeechSkill)
        speaker = skill._map_emotion_to_speaker(valence=-0.8, arousal=-0.7)
        assert speaker == 888753765  # まお/せつなめ

    def test_map_emotion_angry_upset(self):
        """低valence + 高arousal → angry_upset スピーカー"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill.__new__(SynthesizeSpeechSkill)
        speaker = skill._map_emotion_to_speaker(valence=-0.8, arousal=0.7)
        assert speaker == 888753764  # まお/からかい

    def test_calc_voice_params_high_arousal(self):
        """高arousal → speed が速くなる"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill.__new__(SynthesizeSpeechSkill)
        params = skill._calc_voice_params(valence=0.5, arousal=1.0, dominance=0.0)
        assert params["speed"] > 1.0

    def test_calc_voice_params_low_arousal(self):
        """低arousal → speed が遅くなる"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill.__new__(SynthesizeSpeechSkill)
        params = skill._calc_voice_params(valence=0.0, arousal=-1.0, dominance=0.0)
        assert params["speed"] < 1.0

    def test_calc_voice_params_speed_clamped(self):
        """speed は 0.5〜2.0 の範囲に収まる"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill.__new__(SynthesizeSpeechSkill)
        # 極端なパラメータでもクランプされる
        params_fast = skill._calc_voice_params(0.0, 10.0, 0.0)
        params_slow = skill._calc_voice_params(0.0, -10.0, 0.0)
        assert 0.5 <= params_fast["speed"] <= 2.0
        assert 0.5 <= params_slow["speed"] <= 2.0

    def test_calc_voice_params_positive_valence_raises_pitch(self):
        """高valence → pitch が上がる"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill.__new__(SynthesizeSpeechSkill)
        params_pos = skill._calc_voice_params(valence=1.0, arousal=0.0, dominance=0.0)
        params_neg = skill._calc_voice_params(valence=-1.0, arousal=0.0, dominance=0.0)
        assert params_pos["pitch"] > params_neg["pitch"]

    @pytest.mark.asyncio
    async def test_run_raises_on_empty_text(self, tmp_path):
        """text が空の場合は ValueError"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill(output_dir=tmp_path)

        with pytest.raises(ValueError, match="text"):
            await skill.run({"text": ""})

    @pytest.mark.asyncio
    async def test_run_raises_on_out_of_range_valence(self, tmp_path):
        """valence が範囲外の場合は ValueError"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill(output_dir=tmp_path)

        with pytest.raises(ValueError, match="valence"):
            await skill.run({"text": "テスト", "valence": 1.5})

    @pytest.mark.asyncio
    async def test_run_voicevox_unavailable_fallback(self, tmp_path):
        """VOICEVOX 接続失敗時はフォールバックして voicevox_available=False を返す"""
        import httpx
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill(
            voicevox_url="http://localhost:50021",
            output_dir=tmp_path,
        )
        skill._http = AsyncMock()
        skill._http.post = AsyncMock(side_effect=httpx.ConnectError("接続拒否"))

        result = await skill.run({
            "text": "こんにちは",
            "valence": 0.5,
            "arousal": 0.3,
        })

        assert result["voicevox_available"] is False
        assert "file_path" in result
        # フォールバックファイルが存在する
        assert Path(result["file_path"]).exists()

    @pytest.mark.asyncio
    async def test_run_success_with_mock_voicevox(self, tmp_path):
        """VOICEVOX API が正常な場合は WAV ファイルを保存して返す"""
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        # VOICEVOX API モック
        mock_query_resp = MagicMock()
        mock_query_resp.raise_for_status = MagicMock()
        mock_query_resp.json = MagicMock(return_value={
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "accent_phrases": [],
        })

        mock_synth_resp = MagicMock()
        mock_synth_resp.raise_for_status = MagicMock()
        mock_synth_resp.content = b"RIFF\x24\x00\x00\x00WAVEfmt "  # ダミーWAV

        call_count = [0]

        async def mock_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_query_resp
            return mock_synth_resp

        skill = SynthesizeSpeechSkill(
            voicevox_url="http://localhost:50021",
            output_dir=tmp_path,
        )
        skill._http = AsyncMock()
        skill._http.post = AsyncMock(side_effect=mock_post)

        result = await skill.run({
            "text": "こんにちは、世界",
            "valence": 0.8,
            "arousal": 0.6,
            "dominance": 0.2,
        })

        assert result["voicevox_available"] is True
        assert result["speaker_id"] == 888753762  # happy_excited (まお/あまあま)
        assert result["speed"] > 1.0  # 高arousal → 速い
        assert Path(result["file_path"]).exists()

    @pytest.mark.asyncio
    async def test_speaker_id_override(self, tmp_path):
        """speaker_id パラメータで感情マッピングを上書きできる"""
        import httpx
        from skills.character.synthesize_speech import SynthesizeSpeechSkill

        skill = SynthesizeSpeechSkill(output_dir=tmp_path)
        skill._http = AsyncMock()
        skill._http.post = AsyncMock(side_effect=httpx.ConnectError("unavailable"))

        result = await skill.run({
            "text": "テスト",
            "valence": -0.9,  # 通常は sad_tired (0) になる
            "arousal": -0.9,
            "speaker_id": 5,  # 上書き
        })

        assert result["speaker_id"] == 5
