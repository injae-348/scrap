# 리뷰 결과

`security-reviewer`와 `qa-reviewer`가 결과 문서를 이 폴더에 작성합니다.

- 보안: `security-YYYYMMDD.md` — **공개 저장소이므로 커밋하지 않음** (`.gitignore`에 등록, 로컬에만 보관)
- QA: `qa-<phase>-YYYYMMDD.md` — 공개. 보안 관련 지적은 이 문서에 쓰지 않고 `security-qa-<phase>-YYYYMMDD.md`(비공개, 커밋 안 함)로 분리하며, QA 문서에는 건수만 적는다

마스터 세션이 읽고 조치한 뒤, 각 문서 맨 아래에 "조치 완료" 표시를 남깁니다.
