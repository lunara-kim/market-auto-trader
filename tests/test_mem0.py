#!/usr/bin/env python3
"""
mem0 기본 동작 테스트 (완전 로컬 - API 키 불필요)
- 임베딩: fastembed (로컬 ONNX 모델)
- 벡터 DB: Qdrant (Docker)
- LLM: 없음 (직접 벡터 저장/검색만 테스트)

mem0의 add()는 내부적으로 LLM을 호출하여 기억을 추출하므로,
LLM 없이 순수 벡터 저장/검색을 직접 테스트합니다.
"""

import uuid

import pytest

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct
    from fastembed import TextEmbedding
except ImportError:
    pytest.skip("qdrant_client/fastembed not installed", allow_module_level=True)


def main():
    print("=" * 60)
    print("mem0 인프라 동작 테스트 (Qdrant + FastEmbed)")
    print("=" * 60)

    # 1. Qdrant 연결 확인
    print("\n[1] Qdrant 연결 확인...")
    client = QdrantClient(host="localhost", port=6333)
    collections = client.get_collections()
    print(f"    ✅ Qdrant 연결 성공! 기존 컬렉션: {[c.name for c in collections.collections]}")

    # 2. FastEmbed 임베딩 모델 로드
    print("\n[2] FastEmbed 임베딩 모델 로드...")
    embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    print("    ✅ 임베딩 모델 로드 완료 (BAAI/bge-small-en-v1.5)")

    # 3. 테스트 컬렉션 생성
    collection_name = "mem0_test"
    print(f"\n[3] 테스트 컬렉션 '{collection_name}' 생성...")

    # 기존 컬렉션 삭제 후 재생성
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)

    # bge-small-en-v1.5 임베딩 차원: 384
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )
    print("    ✅ 컬렉션 생성 완료")

    # 4. 기억 추가 (임베딩 → Qdrant 저장)
    print("\n[4] 기억 추가 (add)...")
    memories = [
        {"text": "나는 매일 아침 7시에 비트코인 시세를 확인한다.", "category": "habit"},
        {"text": "이더리움은 장기 보유 전략으로 접근하고 있다.", "category": "strategy"},
        {"text": "주말에는 트레이딩을 하지 않고 분석만 한다.", "category": "habit"},
        {"text": "RSI가 30 이하일 때 매수 신호로 판단한다.", "category": "strategy"},
        {"text": "포트폴리오의 60%는 비트코인으로 유지한다.", "category": "allocation"},
    ]

    texts = [m["text"] for m in memories]
    embeddings = list(embedding_model.embed(texts))

    points = []
    for i, (mem, emb) in enumerate(zip(memories, embeddings)):
        point_id = str(uuid.uuid4())
        points.append(
            PointStruct(
                id=point_id,
                vector=emb.tolist(),
                payload={
                    "memory": mem["text"],
                    "category": mem["category"],
                    "user_id": "test_user_001",
                },
            )
        )
        print(f"    ✅ [{i+1}] '{mem['text'][:30]}...' 추가")

    client.upsert(collection_name=collection_name, points=points)
    print(f"    ✅ 총 {len(points)}개 기억 저장 완료")

    # 5. 기억 검색 (search)
    print("\n[5] 기억 검색 (search)...")

    queries = [
        "비트코인 투자 습관",
        "매매 전략은 어떻게 되나요?",
        "자산 배분 비율",
    ]

    for query in queries:
        query_embedding = list(embedding_model.embed([query]))[0]
        results = client.query_points(
            collection_name=collection_name,
            query=query_embedding.tolist(),
            limit=3,
        )
        print(f"\n    🔍 검색어: '{query}'")
        for j, r in enumerate(results.points, 1):
            score = r.score
            memory_text = r.payload.get("memory", "N/A")
            print(f"       [{j}] (score: {score:.4f}) {memory_text}")

    # 6. 컬렉션 통계
    print("\n[6] 컬렉션 통계...")
    info = client.get_collection(collection_name)
    print(f"    📊 벡터 수: {info.points_count}")
    print(f"    📊 벡터 차원: {info.config.params.vectors.size}")
    print(f"    📊 거리 메트릭: {info.config.params.vectors.distance}")

    print("\n" + "=" * 60)
    print("✅ 모든 테스트 통과! mem0 인프라 정상 동작 확인")
    print("=" * 60)
    print("\n📝 다음 단계:")
    print("   - LLM(OpenAI/Anthropic) API 키 설정 시 mem0 Memory.add()/search() 풀 기능 사용 가능")
    print("   - 현재 Qdrant + FastEmbed 벡터 저장/검색 인프라 완료")


if __name__ == "__main__":
    main()
