# PostgreSQL 16 + PostGIS 3.4 이미지에 pgvector를 더한다(공식 이미지 중 둘 다 든 것이 없음).
# 기반 이미지는 Debian + PostgreSQL 공식 저장소(apt.postgresql.org)가 설정돼 있어 pgvector 패키지를 바로 받는다.
FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
