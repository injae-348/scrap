#!/usr/bin/env bash
# 수동 롤백·복구 스크립트 (긴급 시 사람만) — 서버의 /opt/scrap-app/deploy/rollback.sh (root 소유, 755)로 설치한다 (README 11절).
# CI 키로는 실행되지 않는다 (강제 명령은 deploy.sh 뿐). root 로 실행한다: DB 복원에 data/(10001, 700) 접근이 필요하다.
#
#   sudo /opt/scrap-app/deploy/rollback.sh                       상태만 보기 (아무것도 바꾸지 않음)
#   sudo /opt/scrap-app/deploy/rollback.sh previous              state/previous 버전으로 되돌린다 → 성공 시 state 교환
#   sudo /opt/scrap-app/deploy/rollback.sh current               state/current 버전을 다시 올린다 (자동 롤백까지 실패했을 때). state 그대로
#   ... previous|current --restore-db <백업 파일 이름>           ⚠️ 위에 더해 DB를 backups/ 의 그 백업으로 되돌린다
#
# 순서 (전 과정에서 deploy.sh 와 같은 잠금을 쥔다 → CI 배포와 겹치지 않는다. 한 단계라도 실패하면 그 자리에서 멈춘다)
#   1. 잠금 → state 읽기·검증
#   2. (--restore-db) api 정지 → 현재 DB(scrap.db, -wal, -shm)를 /root/db-before-restore-<시각>/ 에 복사하고 cmp 로 확인
#      → 확인된 뒤에만 -wal/-shm 삭제 + 백업 파일 설치
#   3. IMAGE_TAG=<대상> docker compose up -d (상한 UP_TIMEOUT초)
#   4. https://$SITE_DOMAIN/api/health 확인 (로컬 Caddy 경유, 인증서 검증 유지)
#   5. state 를 실제 운영 버전에 맞춘다 (previous 로 되돌렸을 때만: current ↔ previous 교환)
#
# 출력: 단계마다 ✅/❌ 줄. 도메인·.env 값·비밀값은 출력하지 않는다. 같은 내용을 logs/deploy.log 에도 남긴다.
# 종료 코드: 0 = 성공(또는 상태 보기), 1 = 실패, 2 = 사용법 오류
set -euo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C.UTF-8

APP_DIR=/opt/scrap-app
STATE_DIR="${APP_DIR}/state"
LOG_FILE="${APP_DIR}/logs/deploy.log"
BACKUP_DIR="${APP_DIR}/backups"
DATA_DIR="${APP_DIR}/data"
DB_FILE="${DATA_DIR}/scrap.db"   # docker-compose.yml 의 DB_PATH=/data/scrap.db 와 같은 파일
ENV_FILE="${APP_DIR}/.env"
COMPOSE_FILE="${APP_DIR}/docker-compose.yml"
APP_UID=10001

UP_TIMEOUT=300
HEALTH_TIMEOUT=90
HEALTH_INTERVAL=3

say() {
  local line
  line="$(date '+%Y-%m-%d %H:%M:%S %Z') rollback: $*"
  printf '%s\n' "$line"
  # 이미 있는 deploy.log 에만 덧붙인다 (root 가 새로 만들면 root 소유가 되어 deploy.sh 가 못 쓴다).
  if [[ -f $LOG_FILE ]]; then printf '%s\n' "$line" >>"$LOG_FILE" 2>/dev/null || true; fi
}
ok() { say "✅ $*"; }
fail() {
  say "❌ $*"
  exit 1
}
short() { printf '%s' "${1:0:12}"; }

usage() {
  sed -n '5,8p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

# ── 인자 ──────────────────────────────────────────
MODE="${1:-status}"
RESTORE_NAME=""
case $MODE in
  status | previous | current) ;;
  *) usage ;;
esac
if [[ $# -ge 2 ]]; then
  [[ $MODE != status && $# -eq 3 && $2 == --restore-db ]] || usage
  RESTORE_NAME=$3
fi

[[ $EUID -eq 0 ]] || {
  echo "❌ root 로 실행한다: sudo $0 $*" >&2
  exit 2
}

# ── 1. 잠금·상태 ──────────────────────────────────
# 잠금 파일이 없으면 deploy 소유로 만든다 (root 소유가 되면 deploy.sh 가 열지 못한다).
if [[ ! -e ${STATE_DIR}/deploy.lock ]]; then
  install -m 600 -o deploy -g deploy /dev/null "${STATE_DIR}/deploy.lock" || fail "잠금 파일을 만들 수 없음: ${STATE_DIR}/deploy.lock"
fi
exec 9>>"${STATE_DIR}/deploy.lock" || fail "잠금 파일을 열 수 없음: ${STATE_DIR}/deploy.lock"
flock -n 9 || fail "배포(deploy.sh) 또는 다른 롤백이 진행 중 — 끝난 뒤 다시 실행"
ok "잠금 획득 (끝날 때까지 CI 배포가 겹치지 않음)"

read_sha() {
  local f="${STATE_DIR}/$1" v
  [[ -e $f ]] || return 0
  v="$(tr -d '[:space:]' <"$f")"
  [[ $v =~ ^[0-9a-f]{40}$ ]] || fail "상태 파일 형식 오류: ${f} — 내용을 사람이 확인"
  printf '%s' "$v"
}
C="$(read_sha current)"
P="$(read_sha previous)"
say "state: current=$(short "${C:-없음}") previous=$(short "${P:-없음}")"

dc() { docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" "$@"; }

if [[ $MODE == status ]]; then
  IMAGE_TAG="${C:-0000000000000000000000000000000000000000}" dc ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}' || true
  ls -1 "$BACKUP_DIR" 2>/dev/null | grep -E '^predeploy-.*\.db$' | tail -n 5 | sed 's/^/  백업: /' || true
  exit 0
fi

case $MODE in
  previous)
    [[ -n $P ]] || fail "state/previous 가 없어 되돌릴 버전이 없음"
    TARGET=$P
    ;;
  current)
    [[ -n $C ]] || fail "state/current 가 없음"
    TARGET=$C
    ;;
esac
export IMAGE_TAG="$TARGET"
ok "대상 버전: ${TARGET}"

SITE_DOMAIN="$(
  line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?SITE_DOMAIN[[:space:]]*=' "$ENV_FILE" | tail -n 1 || true)"
  v="${line#*=}"
  v="${v%%[[:space:]]#*}"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  v="${v#[\"\']}"
  v="${v%[\"\']}"
  printf '%s' "${v,,}"
)"
[[ $SITE_DOMAIN =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || fail ".env 의 SITE_DOMAIN 이 없거나 형식이 올바르지 않음"

# ── 2. (선택) DB 복원 ─────────────────────────────
if [[ -n $RESTORE_NAME ]]; then
  # 파일 이름만 받는다 (경로·../ 금지). backups/ 안의 일반 파일이어야 한다.
  [[ $RESTORE_NAME =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.db$ ]] || fail "백업 파일 이름 형식이 아님 (backups/ 안의 *.db 이름만): ${RESTORE_NAME}"
  SRC="${BACKUP_DIR}/${RESTORE_NAME}"
  [[ -f $SRC && ! -L $SRC && -s $SRC ]] || fail "백업 파일이 없음: ${SRC}"
  [[ "$(head -c 15 "$SRC")" == "SQLite format 3" ]] || fail "SQLite 파일이 아님: ${SRC}"
  ok "복원할 백업 확인: ${RESTORE_NAME}"

  dc stop api || fail "api 정지 실패 — DB 는 건드리지 않았다"
  ok "api 정지"

  KEEP="/root/db-before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
  install -d -m 700 -o root -g root "$KEEP" || fail "보존 폴더를 만들 수 없음: ${KEEP}"
  for f in "$DB_FILE" "${DB_FILE}-wal" "${DB_FILE}-shm"; do
    [[ -e $f ]] || continue
    cp -a -- "$f" "$KEEP/" || fail "현재 DB 복사 실패: $(basename "$f") — DB 는 건드리지 않았다 (api 는 정지 상태: 'sudo $0 current' 로 다시 올린다)"
    cmp -s -- "$f" "$KEEP/$(basename "$f")" || fail "복사본이 원본과 다름: $(basename "$f") — DB 는 건드리지 않았다"
  done
  ok "현재 DB 보존 (-wal/-shm 포함, 내용 비교 일치): ${KEEP}"

  # 여기부터 파괴적 단계. 위 보존이 모두 확인된 뒤에만 도달한다.
  rm -f -- "${DB_FILE}-wal" "${DB_FILE}-shm" || fail "-wal/-shm 삭제 실패 — 보존본: ${KEEP}"
  install -m 600 -o "$APP_UID" -g "$APP_UID" -- "$SRC" "$DB_FILE" || fail "백업 설치 실패 — 보존본: ${KEEP} 에서 되돌린다"
  cmp -s -- "$SRC" "$DB_FILE" || fail "설치한 DB 가 백업과 다름 — 보존본: ${KEEP}"
  ok "DB 복원: ${RESTORE_NAME} → data/scrap.db (소유 ${APP_UID}, 600)"
fi

# ── 3. 컨테이너 교체 ──────────────────────────────
if timeout --kill-after=30 "$UP_TIMEOUT" \
  docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" up -d --remove-orphans; then
  ok "docker compose up ($(short "$TARGET"))"
else
  fail "docker compose up 실패 또는 ${UP_TIMEOUT}초 초과 — state 는 바꾸지 않았다. 로그: sudo docker compose -f ${COMPOSE_FILE} logs --tail 60 api web"
fi

# ── 4. 헬스체크 ───────────────────────────────────
healthy=0
deadline=$((SECONDS + HEALTH_TIMEOUT))
while ((SECONDS < deadline)); do
  if out="$(curl --silent --max-time 5 --proto '=https' \
    --resolve "${SITE_DOMAIN}:443:127.0.0.1" --write-out '\n%{http_code}' \
    "https://${SITE_DOMAIN}/api/health" 2>/dev/null)" &&
    [[ ${out##*$'\n'} == 200 && ${out%$'\n'*} =~ \"status\"[[:space:]]*:[[:space:]]*\"ok\" ]]; then
    healthy=1
    break
  fi
  sleep "$HEALTH_INTERVAL"
done
[[ $healthy -eq 1 ]] || fail "헬스체크 실패 (${HEALTH_TIMEOUT}초) — state 는 바꾸지 않았다"
ok "헬스체크 통과 (https://<SITE_DOMAIN>/api/health)"

# ── 5. state 를 실제 운영 버전에 맞춘다 ───────────
# deploy.sh 가 읽고 쓸 수 있게 deploy 소유로 둔다. 임시 파일을 다 쓴 뒤 current 먼저 rename.
if [[ $TARGET == "$C" ]]; then
  ok "state 변경 없음 (운영 버전 = state/current)"
else
  t_cur="${STATE_DIR}/.current.tmp" t_prev="${STATE_DIR}/.previous.tmp"
  { printf '%s\n' "$TARGET" >"$t_cur" && printf '%s\n' "$C" >"$t_prev" &&
    chown deploy:deploy "$t_cur" "$t_prev" && chmod 600 "$t_cur" "$t_prev"; } ||
    { rm -f "$t_cur" "$t_prev"; fail "state 임시 파일 쓰기 실패 — state 그대로 (운영 중: ${TARGET})"; }
  mv -f "$t_cur" "${STATE_DIR}/current" ||
    { rm -f "$t_cur" "$t_prev"; fail "state/current 교체 실패 — state 그대로 (운영 중: ${TARGET})"; }
  mv -f "$t_prev" "${STATE_DIR}/previous" ||
    { rm -f "$t_prev"; fail "state/previous 교체 실패 — current 는 맞음 (${TARGET}), previous 를 ${C} 로 사람이 고친다"; }
  ok "state 갱신: current=$(short "$TARGET") previous=$(short "$C")"
fi

say "완료 — 운영 중: ${TARGET}"
exit 0
