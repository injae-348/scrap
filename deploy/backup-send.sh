#!/usr/bin/env bash
# 암호화 백업 내보내기 — 서버의 /opt/scrap-app/deploy/backup-send.sh (root 소유, 755)로 설치한다 (deploy/README.md 11절).
#
# 실행 경로: 사용자 Mac 의 pull-backups.sh(deploy/mac/) → ssh deploy@서버 "list" 또는 "get <이름>"
#   백업 수신 전용 키의 authorized_keys 강제 명령(restrict,command="/opt/scrap-app/deploy/backup-send.sh")으로만 실행된다.
#   (CI 배포 키와 같은 방식, 별도 줄 — README 14-2). 클라이언트가 보낸 명령 문자열은 SSH_ORIGINAL_COMMAND 로만 들어온다.
#
# 요청 (이 두 가지 말고는 모두 거부한다)
#   list         → backups/daily/ 의 암호화 백업을 "<sha256> <이름>" 한 줄씩, 이름순으로
#   get <이름>   → 그 파일 내용을 표준출력으로
# 이름은 daily-YYYYMMDDTHHMMSSZ.db.gz.age 형식만 받는다 (경로 문자·공백 불가 → 다른 파일을 가리킬 수 없다).
# 평문은 보내지 않는다: 이름 형식에 더해 파일 머리말이 age 암호화 형식인지 확인하고, 심볼릭 링크는 따라가지 않는다.
#
# 표준출력은 데이터 통로다 → 기록은 logs/backup.log 파일에만, 오류 안내는 표준오류로 보낸다. 받은 요청 값은 기록하지 않는다.
# 종료 코드: 0 = 성공, 1 = 없는 파일·형식 오류·설정 오류, 2 = 잘못된 요청
set -euo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C

# 경로는 고정한다. 시험할 때는 복사본에서 이 줄들을 바꾼다.
DAILY_DIR=/opt/scrap-app/backups/daily
LOG_FILE=/opt/scrap-app/logs/backup.log

NAME_RE='^daily-[0-9]{8}T[0-9]{6}Z\.db\.gz\.age$'
GET_RE='^get (daily-[0-9]{8}T[0-9]{6}Z\.db\.gz\.age)$'
AGE_MAGIC='age-encryption.org/v1'

log() {
  # 이미 있는 로그 파일이나 쓸 수 있는 로그 폴더일 때만. 실패해도 요청 처리는 계속한다.
  { printf '%s backup-send: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" >>"$LOG_FILE"; } 2>/dev/null || true
}
reject() {
  log "거부: $1"
  printf 'backup-send: 거부: %s\n' "$1" >&2
  exit 2
}
fail() {
  log "실패: $1"
  printf 'backup-send: 실패: %s\n' "$1" >&2
  exit 1
}
is_age_file() {
  [[ -f $1 && ! -L $1 ]] || return 1
  # 바이트 비교 (평문 DB 의 NUL 바이트가 셸 변수로 들어가지 않게 cmp 로 비교한다)
  head -c ${#AGE_MAGIC} -- "$1" 2>/dev/null | cmp -s - <(printf '%s' "$AGE_MAGIC")
}

REQ="${SSH_ORIGINAL_COMMAND-}"
# 받은 값 자체는 남기지 않는다 (로그 오염 방지). 길이만 남긴다.
((${#REQ} <= 64)) || reject "요청이 너무 김 (길이 ${#REQ})"

if [[ $REQ == list ]]; then
  [[ -d $DAILY_DIR && ! -L $DAILY_DIR ]] || fail "백업 폴더가 없음 (README 13-3)"
  shopt -s nullglob
  n=0
  for f in "$DAILY_DIR"/daily-*.db.gz.age; do
    b="${f##*/}"
    [[ $b =~ $NAME_RE ]] || continue
    is_age_file "$f" || continue
    h="$(sha256sum -- "$f")"
    printf '%s %s\n' "${h%% *}" "$b"
    n=$((n + 1))
  done
  log "목록: ${n}개"
  exit 0
fi

if [[ $REQ =~ $GET_RE ]]; then
  name="${BASH_REMATCH[1]}"
  f="${DAILY_DIR}/${name}"
  [[ -e $f ]] || fail "없는 백업: ${name}"
  is_age_file "$f" || fail "age 암호화 파일이 아니어서 보내지 않음: ${name}"
  size="$(stat -c %s -- "$f")"
  cat -- "$f"
  log "전송: ${name} (${size} bytes)"
  exit 0
fi

reject "알 수 없는 요청 (길이 ${#REQ}) — 허용: list, get <이름>"
