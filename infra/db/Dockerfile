# PostgreSQL 16 + pgvector 0.8 이미지에 PostGIS 3을 더한다(공식 이미지 중 둘 다 든 것이 없음).
# postgis/postgis:16-* 이미지는 Debian 11 기반이라 PostgreSQL 공식 저장소에서 pgvector를 더 받을 수 없다(404, 2026-11-17 확인).
# 그래서 Debian 12 기반 pgvector 이미지를 쓰고, 같은 공식 저장소에서 PostGIS 3(그 시점 최신, 2026-11 기준 3.7)을 받는다.
# PostGIS는 최신 PostgreSQL 16.x에 맞춰 빌드되므로 postgresql-16도 같이 올린다(안 올리면 postgis-3.so 로드 실패).
FROM pgvector/pgvector:0.8.0-pg16

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-16 postgresql-16-postgis-3 postgresql-16-postgis-3-scripts \
    && rm -rf /var/lib/apt/lists/*
