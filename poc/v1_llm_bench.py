"""
V1: Ollama/MLX 推論速度・JSON 出力品質の検証
合格基準:
  - Ollama tok/s > 25
  - JSON 出力成功率 >= 8/10
"""

import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

OLLAMA_BASE_URL = "http://localhost:11434"
MODEL = "qwen3.5:35b-a3b"
FALLBACK_MODEL = "qwen3.5:4b"
# Ollama に存在する代替モデル（qwen3.5 未インストール時に使用）
AVAILABLE_FALLBACKS = ["gemma3:27b", "llama3.1:latest", "gemma3:latest"]

JSON_PROMPT = """\
以下の記事リストから、AIに関連するものを選択してJSON形式で回答してください。
{"articles": [{"title": "新型AIエージェントの登場", "id": 1}, {"title": "天気予報", "id": 2}, {"title": "LLM推論速度の改善", "id": 3}]}
出力形式のみで回答: {"selected": [{"id": <number>, "reason": "<string>"}]}
"""

JA_SUMMARY_PROMPT = """\
以下の文章を100字以内で日本語要約してください。
「Mixture of Experts（MoE）は、複数の専門モデルを組み合わせることで、
パラメータ数を増やしながら計算コストを抑える手法です。Qwen3.5-35B-A3BはこのMoEを採用し、
実質的な活性パラメータ数を大幅に削減しています。」
"""


@dataclass
class BenchResult:
    model: str
    tokens_per_sec: float
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float


def ollama_generate(prompt: str, model: str, stream: bool = False) -> dict:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {"num_ctx": 4096},
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def check_ollama_alive() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def bench_speed(model: str) -> Optional[BenchResult]:
    print(f"  モデル: {model}")
    try:
        t_start = time.perf_counter()
        resp = ollama_generate("Hello, please respond in one sentence.", model)
        elapsed_ms = (time.perf_counter() - t_start) * 1000

        eval_count: int = resp.get("eval_count", 0)
        eval_duration_ns: int = resp.get("eval_duration", 1)
        tps = eval_count / (eval_duration_ns / 1e9)

        result = BenchResult(
            model=model,
            tokens_per_sec=tps,
            prompt_tokens=resp.get("prompt_eval_count", 0),
            completion_tokens=eval_count,
            duration_ms=elapsed_ms,
        )
        print(f"  tok/s: {tps:.1f}  completion_tokens: {eval_count}  elapsed: {elapsed_ms:.0f}ms")
        return result

    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def bench_json_stability(model: str, trials: int = 10) -> int:
    """JSON 出力が有効なレスポンスの件数を返す"""
    success = 0
    for i in range(trials):
        try:
            resp = ollama_generate(JSON_PROMPT, model)
            text: str = resp.get("response", "")
            # 最初の { ... } を抽出して parse
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if "selected" in parsed and isinstance(parsed["selected"], list):
                    success += 1
                    print(f"  [{i+1}/{trials}] OK")
                else:
                    print(f"  [{i+1}/{trials}] FAIL (構造不正): {text[:80]}")
            else:
                print(f"  [{i+1}/{trials}] FAIL (JSON なし): {text[:80]}")
        except Exception as e:
            print(f"  [{i+1}/{trials}] ERROR: {e}")
    return success


def bench_japanese(model: str, trials: int = 3) -> None:
    print(f"  {trials} 回実行（目視確認）:")
    for i in range(trials):
        resp = ollama_generate(JA_SUMMARY_PROMPT, model)
        text = resp.get("response", "").strip()
        print(f"  [{i+1}] {text[:120]}")


def main() -> None:
    print("=" * 60)
    print("V1: LLM 推論速度・JSON 出力品質")
    print("=" * 60)

    if not check_ollama_alive():
        print("ERROR: Ollama が起動していません。`ollama serve` を実行してください。")
        return

    # 1. 速度ベンチマーク
    print("\n--- 1. 推論速度ベンチマーク ---")
    result = bench_speed(MODEL)
    if result is None:
        print(f"  {MODEL} が利用できません。{FALLBACK_MODEL} にフォールバックします。")
        result = bench_speed(FALLBACK_MODEL)
        model_to_use = FALLBACK_MODEL
    else:
        model_to_use = MODEL

    # Qwen3.5 系がどちらも未インストールなら、利用可能な代替モデルを試す
    if result is None:
        for alt in AVAILABLE_FALLBACKS:
            print(f"  代替モデルで試行: {alt}")
            result = bench_speed(alt)
            if result is not None:
                model_to_use = alt
                print(f"  ※ これは暫定ベンチ。Phase 1 前に qwen3.5:35b-a3b のインストールが必要。")
                break

    if result is None:
        print("ERROR: 利用可能なモデルが見つかりません。`ollama pull qwen3.5:35b-a3b` を実行してください。")
        return

    tps_ok = result.tokens_per_sec > 25
    print(f"  [{'OK' if tps_ok else 'FAIL'}] tok/s {result.tokens_per_sec:.1f} (基準: > 25)")

    # 2. JSON 出力安定性
    print(f"\n--- 2. JSON 出力安定性（10回）---")
    json_success = bench_json_stability(model_to_use, trials=10)
    json_ok = json_success >= 8
    print(f"  [{'OK' if json_ok else 'FAIL'}] 成功 {json_success}/10 (基準: >= 8)")

    # 3. 日本語品質（目視確認）
    print(f"\n--- 3. 日本語品質（3回、目視確認）---")
    bench_japanese(model_to_use, trials=3)

    # 判定
    print("\n--- 判定 ---")
    if tps_ok and json_ok:
        print("合格: Ollama で Phase 1 に進めます。")
    elif not tps_ok and result.tokens_per_sec > 0:
        print(f"注意: tok/s が低い ({result.tokens_per_sec:.1f})。MLX での追加検証を推奨。")
    if not json_ok:
        print("注意: JSON 安定性が低い。プロンプト調整が必要。")


if __name__ == "__main__":
    main()
