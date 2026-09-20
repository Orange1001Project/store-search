"""임베딩 모델 하나를 인코딩 → exact cosine 검색 → 공식 evaluator 채점까지 돌리는
scripts/14_run_model_eval.py의 오케스트레이션 로직 일부.

이 스크립트는 이미 BEIR 스타일로 관심사가 잘 나뉘어 있었다(인코더는
`store_search_ai.models.*`, 검색은 `store_search_ai.retrieval.exact_search`, 채점은
`scripts/13_evaluate_run.py`를 서브프로세스로 호출) — 여기서는 argparse.Namespace에
묶여 있던 나머지 조각(인코더 선택, model_manifest 갱신 엔트리 조립)만 테스트 가능한
순수 함수로 뺐다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

TEMPLATE_COLUMNS = {
    "t1_minimal": "search_text_t1_minimal",
    "t2_market": "search_text_t2_market",
    "t3_market_type": "search_text_t3_market_type",
}


def build_encoder(dummy: bool, model_config_path: str | None):
    if dummy:
        from store_search_ai.models.random_encoder import RandomEncoder

        return RandomEncoder()

    if not model_config_path:
        raise SystemExit("--model-config이 필요합니다 (또는 --dummy로 배관만 검증)")

    from store_search_ai.models.sentence_transformer_encoder import (
        SentenceTransformerEncoder,
    )

    return SentenceTransformerEncoder.from_yaml(model_config_path)


def build_evaluate_run_cmd(python: str, evaluate_script: Path, qrels_path: Path, run_path: Path, eval_tag: str) -> list[str]:
    return [
        python, str(evaluate_script),
        "--qrels", str(qrels_path),
        "--run", str(run_path),
        "--tag", eval_tag,
    ]


def build_manifest_entry(
    split: str, template: str, eval_tag: str, aggregate_metrics: dict, evaluated_at: str | None = None
) -> dict:
    """model_manifest.json의 evaluations 리스트에 이어붙일 엔트리를 만든다.

    `evaluated_at`을 생략하면 현재 UTC 시각을 쓴다(테스트에서는 고정값을 넘겨 결정적으로 검증).
    """

    return {
        "evaluated_at": evaluated_at or datetime.now(UTC).isoformat(),
        "split": split,
        "template": template,
        "tag": eval_tag,
        "metrics": aggregate_metrics,
    }
