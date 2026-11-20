-- Phase 5: 출처·주제·스크랩 + 검색 색인 (docs/API.md "스크랩·출처·주제 세부 규칙 (v1.3)").
-- 추가만 한다 (기존 테이블은 건드리지 않음 → 이전 이미지로 롤백해도 동작).
-- 시각은 0001과 같은 형식(ISO 8601, +09:00, 초 단위) 문자열이라 문자열 비교로 순서를 비교할 수 있다.

-- 출처. name_key = 앞뒤 공백 제거 + casefold 한 이름 (대소문자 무시 중복 검사용, 앱이 계산).
-- AUTOINCREMENT: 지운 id를 다시 쓰지 않는다 (다른 기기 화면에 남은 옛 id와 혼동 방지).
CREATE TABLE sources (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    name_key   TEXT    NOT NULL UNIQUE,
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    sort_order INTEGER NOT NULL
);
-- 기본 출처는 정확히 1개.
CREATE UNIQUE INDEX sources_single_default ON sources (is_default) WHERE is_default = 1;

-- 출처의 도메인 패턴. 패턴은 모든 출처를 통틀어 하나만 있을 수 있다 (UNIQUE).
CREATE TABLE source_patterns (
    pattern   TEXT    PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    position  INTEGER NOT NULL
);
CREATE INDEX source_patterns_source_id ON source_patterns (source_id, position);

CREATE TABLE topics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    name_key   TEXT    NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL
);

-- source_id 는 ON DELETE 동작 없음: 출처를 지우기 전에 앱이 스크랩을 기본 출처로 옮긴다
-- (옮기지 않고 지우려 하면 외래 키 오류로 막힌다).
CREATE TABLE scraps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT    NOT NULL,
    title      TEXT    NOT NULL,
    memo       TEXT    NOT NULL DEFAULT '',
    source_id  INTEGER NOT NULL REFERENCES sources (id),
    liked      INTEGER NOT NULL DEFAULT 0 CHECK (liked IN (0, 1)),
    due_date   TEXT,                             -- YYYY-MM-DD 또는 NULL
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE INDEX scraps_created ON scraps (created_at DESC, id DESC);
CREATE INDEX scraps_due ON scraps (due_date, created_at DESC, id DESC);
CREATE INDEX scraps_source_id ON scraps (source_id);
CREATE INDEX scraps_liked ON scraps (liked, created_at DESC, id DESC);

CREATE TABLE scrap_topics (
    scrap_id INTEGER NOT NULL REFERENCES scraps (id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics (id) ON DELETE CASCADE,
    PRIMARY KEY (scrap_id, topic_id)
) WITHOUT ROWID;
CREATE INDEX scrap_topics_topic_id ON scrap_topics (topic_id, scrap_id);

-- 검색 색인. rowid = scraps.id. topics 열은 그 스크랩의 주제 이름을 줄바꿈으로 이은 값.
-- trigram: 3글자 이상 부분 일치(대소문자 무시). 색인은 아래 트리거가 항상 맞춰 둔다.
CREATE VIRTUAL TABLE scraps_fts USING fts5 (title, memo, url, topics, tokenize = 'trigram');

CREATE TRIGGER scraps_fts_after_insert AFTER INSERT ON scraps BEGIN
    INSERT INTO scraps_fts (rowid, title, memo, url, topics)
    VALUES (
        NEW.id, NEW.title, NEW.memo, NEW.url,
        (SELECT coalesce(group_concat(t.name, char(10)), '')
           FROM scrap_topics st JOIN topics t ON t.id = st.topic_id
          WHERE st.scrap_id = NEW.id)
    );
END;

CREATE TRIGGER scraps_fts_after_update AFTER UPDATE OF title, memo, url ON scraps BEGIN
    UPDATE scraps_fts SET title = NEW.title, memo = NEW.memo, url = NEW.url WHERE rowid = NEW.id;
END;

CREATE TRIGGER scraps_fts_after_delete AFTER DELETE ON scraps BEGIN
    DELETE FROM scraps_fts WHERE rowid = OLD.id;
END;

CREATE TRIGGER scrap_topics_fts_after_insert AFTER INSERT ON scrap_topics BEGIN
    UPDATE scraps_fts SET topics = (
        SELECT coalesce(group_concat(t.name, char(10)), '')
          FROM scrap_topics st JOIN topics t ON t.id = st.topic_id
         WHERE st.scrap_id = NEW.scrap_id
    ) WHERE rowid = NEW.scrap_id;
END;

-- 주제 삭제(ON DELETE CASCADE)로 지워질 때도 실행된다.
CREATE TRIGGER scrap_topics_fts_after_delete AFTER DELETE ON scrap_topics BEGIN
    UPDATE scraps_fts SET topics = (
        SELECT coalesce(group_concat(t.name, char(10)), '')
          FROM scrap_topics st JOIN topics t ON t.id = st.topic_id
         WHERE st.scrap_id = OLD.scrap_id
    ) WHERE rowid = OLD.scrap_id;
END;

CREATE TRIGGER topics_fts_after_rename AFTER UPDATE OF name ON topics BEGIN
    UPDATE scraps_fts SET topics = (
        SELECT coalesce(group_concat(t.name, char(10)), '')
          FROM scrap_topics st JOIN topics t ON t.id = st.topic_id
         WHERE st.scrap_id = scraps_fts.rowid
    ) WHERE rowid IN (SELECT scrap_id FROM scrap_topics WHERE topic_id = NEW.id);
END;

-- 기본 출처 5개 (docs/API.md "기본 출처").
INSERT INTO sources (id, name, name_key, is_default, sort_order) VALUES
    (1, '유튜브', '유튜브', 0, 1),
    (2, 'X', 'x', 0, 2),
    (3, '일반사이트', '일반사이트', 1, 3),
    (4, '당근', '당근', 0, 4),
    (5, '커뮤니티', '커뮤니티', 0, 5);

INSERT INTO source_patterns (pattern, source_id, position) VALUES
    ('youtube.com', 1, 0),
    ('youtu.be', 1, 1),
    ('x.com', 2, 0),
    ('twitter.com', 2, 1),
    ('daangn.com', 4, 0);
