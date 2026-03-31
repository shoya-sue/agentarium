"""
tests/test_skill_trace.py — SkillTrace ユニットテスト
"""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.skill_trace import SkillTrace, TraceStatus


class TestSkillTrace:
    """SkillTrace の動作検証"""

    def test_start_creates_running_trace(self):
        """start() は RUNNING 状態のトレースを返す"""
        trace = SkillTrace.start("browse_source", {"source_id": "hacker_news"})

        assert trace.skill_name == "browse_source"
        assert trace.status == TraceStatus.RUNNING
        assert trace.input_params == {"source_id": "hacker_news"}
        assert trace.finished_at is None
        assert trace.error is None

    def test_finish_updates_status(self):
        """finish() は SUCCESS ステータスと duration_ms を設定する"""
        trace = SkillTrace.start("browse_source", {})
        trace.finish(result_count=15)

        assert trace.status == TraceStatus.SUCCESS
        assert trace.finished_at is not None
        assert trace.duration_ms is not None
        assert trace.duration_ms >= 0
        assert trace.result_count == 15

    def test_fail_updates_status(self):
        """fail() は FAILURE ステータスとエラーメッセージを設定する"""
        trace = SkillTrace.start("browse_source", {})
        trace.fail(error="ConnectionError: timeout")

        assert trace.status == TraceStatus.FAILURE
        assert trace.error == "ConnectionError: timeout"
        assert trace.duration_ms is not None

    def test_to_dict_contains_required_fields(self):
        """to_dict() は必須フィールドを全て含む"""
        trace = SkillTrace.start("store_episodic", {"skill": "browse_source"})
        trace.finish(result_count=1)

        d = trace.to_dict()

        assert "trace_id" in d
        assert "skill_name" in d
        assert "status" in d
        assert "started_at" in d
        assert "finished_at" in d
        assert "duration_ms" in d
        assert d["skill_name"] == "store_episodic"
        assert d["status"] == "success"

    def test_save_creates_json_file(self, tmp_path: Path):
        """save() はトレースファイルを JSON で保存する"""
        trace = SkillTrace.start("browse_source", {"source_id": "hacker_news"})
        trace.finish(result_count=10)

        saved_path = trace.save(tmp_path)

        assert saved_path.exists()
        content = json.loads(saved_path.read_text())
        assert content["skill_name"] == "browse_source"
        assert content["status"] == "success"
        assert content["result_count"] == 10

    def test_save_directory_structure(self, tmp_path: Path):
        """save() は data/traces/{date}/{skill_name}/ 構造を作成する"""
        trace = SkillTrace.start("store_semantic", {})
        trace.finish()

        saved_path = trace.save(tmp_path)

        # traces/{date}/store_semantic/{trace_id}.json
        assert saved_path.parent.name == "store_semantic"
        assert saved_path.suffix == ".json"

    def test_trace_id_is_unique(self):
        """各トレースは固有の trace_id を持つ"""
        t1 = SkillTrace.start("skill_a", {})
        t2 = SkillTrace.start("skill_a", {})
        assert t1.trace_id != t2.trace_id
