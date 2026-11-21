#!/usr/bin/env bash
# 일일 DB 백업 (암호화) — 서버의 /opt/scrap-app/deploy/backup.sh (root 소유, 755)로 설치한다 (deploy/README.md 11절).
# deploy 사용자의 cron 으로 하루 한 번 실행한다 (README 13-4). 사람이 시험할 때: sudo -u deploy /opt/scrap-app/deploy/backup.sh
#
# 하는 일
#   1. 잠금: deploy.sh·rollback.sh 와 같은 잠금(state/deploy.lock)을 기다렸다가 쥔다 → 배포·롤백과 겹치지 않는다.
#      (백업은 몇 초 걸린다. 그 사이에 시작된 배포는 "다른 배포가 진행 중"으로 바로 끝난다 → Re-run, README 13-4)
#   2. api 컨테이너 안에서 Python sqlite3 backup API 로 일관된 사본을 만든다. 배포 직전 백업(deploy.sh)과 같은 방식이고
#      표준 라이브러리만 쓰므로 어떤 이미지 버전에서도 동작한다 (앱의 관리 명령에 기대지 않는다).
#      사본에 integrity_check 를 돌려 "ok" 일 때만 내보낸다. WAL 모드여도 backup API 가 커밋된 내용까지 일관되게 복사한다.
#      api 가 멈춰 있으면 운영 버전(state/current) 이미지로 일회용 컨테이너를 띄워 같은 일을 한다. 이 컨테이너는
#      compose 를 거치지 않고 docker run 으로 띄운다: 로그 드라이버 none(표준출력이 Docker 로그 파일에 남지 않음),
#      네트워크 없음, .env 없음(백업에는 앱 비밀값이 필요 없다), api 와 같은 실행 사용자·/data 마운트·읽기 전용·권한 제한.
#   3. 컨테이너가 표준출력으로 내보낸 사본을 그대로 gzip → age(공개키 암호화)로 흘려 보낸다.
#      평문 사본은 호스트에 파일로 남지 않는다 (exec 출력과 로그 끈 일회용 컨테이너 출력은 Docker 로그에 기록되지 않는다.
#      컨테이너 안 임시 파일은 DB 와 같은 data/ 안에 만들고 끝나면 지운다).
#   4. backups/daily/daily-<UTC 시각>.db.gz.age (600) 로 원자적으로 이름을 바꾸고, 최근 KEEP 개만 남긴다.
#
# 복호화 개인키는 서버에 두지 않는다. 서버에는 공개키(수신자 파일 RECIPIENTS)만 있다 → 서버에서는 이 백업을 풀 수 없다.
# 복원은 Mac에서 개인키로 푼 뒤에 한다 (README 15절). 외부 보관은 Mac이 backup-send.sh 로 가져간다 (README 14절).
# DB·컨테이너가 없으면(첫 배포 전) 건너뛰고 0 으로 끝난다.
#
# 출력: 표준출력과 /opt/scrap-app/logs/backup.log. 도메인·.env 값·비밀값은 출력하지 않는다.
# 종료 코드: 0 = 성공 또는 건너뜀, 1 = 실패, 2 = 사용법 오류(인자를 받지 않는다)
set -euo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C.UTF-8

# 경로는 고정한다 (deploy.sh 와 같은 이유). 시험할 때는 복사본에서 이 줄들을 바꾼다.
APP_DIR=/opt/scrap-app
STATE_DIR="${APP_DIR}/state"
LOG_DIR="${APP_DIR}/logs"
LOG_FILE="${LOG_DIR}/backup.log"
DAILY_DIR="${APP_DIR}/backups/daily"
# age 수신자(공개키) 파일. 서버에서 사람이 만든다 (README 13-2). 저장소에는 넣지 않는다.
RECIPIENTS="${APP_DIR}/age/recipients.txt"
ENV_FILE="${APP_DIR}/.env"
COMPOSE_FILE="${APP_DIR}/docker-compose.yml"

KEEP=14            # 보관 개수 (하루 1회 → 약 2주)
LOCK_WAIT=1800     # 배포·롤백이 끝나기를 기다리는 최대 시간(초)
RUN_TIMEOUT=900    # 컨테이너 안 사본 만들기 상한(초)
MIN_FREE_MB=300    # 디스크 여유가 이보다 적으면 백업하지 않는다 (DB와 같은 디스크 보호)

NAME_RE='^daily-[0-9]{8}T[0-9]{6}Z\.db\.gz\.age$'
AGE_MAGIC='age-encryption.org/v1'

log() {
  printf '%s backup: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" >&2
}
die() {
  log "실패: $*"
  exit 1
}

PART=""
TEE_PID=""
RUN_NAME=""
# shellcheck disable=SC2317  # trap 으로 불린다
on_exit() {
  # 실패로 끝나도 조각 파일(암호화된 .part)은 남기지 않는다.
  if [[ -n $PART && -e $PART ]]; then rm -f -- "$PART"; fi
  # 시간 초과로 docker 클라이언트만 죽었을 때 남은 일회용 컨테이너를 지운다.
  if [[ -n $RUN_NAME ]]; then docker rm -f "$RUN_NAME" >/dev/null 2>&1 || true; fi
  if [[ -n $TEE_PID ]]; then
    exec 1>&- 2>&-
    wait "$TEE_PID" 2>/dev/null || true
  fi
}
trap on_exit EXIT

# ── 로그 ──────────────────────────────────────────
if [[ -d $LOG_DIR && -w $LOG_DIR ]]; then
  exec > >(tee -a "$LOG_FILE") 2>&1
  TEE_PID=$!
else
  log "경고: 로그 디렉터리에 쓸 수 없어 표준출력에만 남김 (${LOG_DIR})"
fi

if [[ $# -ne 0 ]]; then
  log "사용법: $0 (인자 없음)"
  exit 2
fi

# ── 준비 확인 ─────────────────────────────────────
for cmd in docker flock age gzip timeout tee; do
  command -v "$cmd" >/dev/null || die "명령 없음: ${cmd} (age 는 README 13-2)"
done
[[ -r $COMPOSE_FILE ]] || die "compose 파일을 읽을 수 없음: ${COMPOSE_FILE}"
[[ -r $ENV_FILE ]] || die ".env 를 읽을 수 없음: ${ENV_FILE}"
[[ -f $RECIPIENTS && -r $RECIPIENTS ]] || die "수신자(공개키) 파일이 없음: ${RECIPIENTS} (README 13-2)"
if grep -q 'AGE-SECRET-KEY-' "$RECIPIENTS"; then
  die "수신자 파일에 개인키 형식이 들어 있음 — 서버에는 공개키(age1...)만 둔다. 파일을 고치고 개인키는 교체한다 (README 16-5)"
fi
grep -qE '^age1[0-9a-z]+$' "$RECIPIENTS" || die "수신자 파일에 공개키(age1...) 줄이 없음 (README 13-2)"
[[ -d $STATE_DIR && -w $STATE_DIR ]] || die "상태 디렉터리에 쓸 수 없음: ${STATE_DIR} (README 3-2)"
if [[ ! -d $DAILY_DIR ]]; then
  mkdir -m 700 -- "$DAILY_DIR" || die "백업 폴더를 만들 수 없음: ${DAILY_DIR} (README 13-3)"
fi
[[ -w $DAILY_DIR ]] || die "백업 폴더에 쓸 수 없음: ${DAILY_DIR}"
free_mb="$(df -Pm -- "$DAILY_DIR" | awk 'NR==2 {print $4}')"
[[ $free_mb =~ ^[0-9]+$ ]] || die "디스크 여유 공간을 읽지 못함"
((free_mb >= MIN_FREE_MB)) || die "디스크 여유 ${free_mb}MB < ${MIN_FREE_MB}MB — 백업하지 않음 (README 12-4 디스크 확인)"

shopt -s nullglob
# 이전 실행이 남긴 조각 정리
for f in "$DAILY_DIR"/daily-*.part; do rm -f -- "$f"; done

# ── 잠금 (deploy.sh·rollback.sh 와 같은 파일) ──────
exec 9>>"${STATE_DIR}/deploy.lock" || die "잠금 파일을 열 수 없음: ${STATE_DIR}/deploy.lock"
if ! flock -n 9; then
  log "배포·롤백이 진행 중 — 끝나기를 기다린다 (최대 ${LOCK_WAIT}초)"
  flock -w "$LOCK_WAIT" 9 || die "배포·롤백이 ${LOCK_WAIT}초 안에 끝나지 않음 — 다음 실행에 다시 시도"
fi

# ── 상태 읽기 ─────────────────────────────────────
CUR_SHA=""
if [[ -e ${STATE_DIR}/current ]]; then
  CUR_SHA="$(tr -d '[:space:]' <"${STATE_DIR}/current")"
  [[ $CUR_SHA =~ ^[0-9a-f]{40}$ ]] || die "상태 파일 형식 오류: ${STATE_DIR}/current (README 12-6)"
fi
# compose 파일의 ${IMAGE_TAG:?} 를 채운다. exec·ps 에는 태그가 쓰이지 않고, run 모드의 이미지 이름 계산에 운영 버전 태그가 쓰인다.
export IMAGE_TAG="${CUR_SHA:-0000000000000000000000000000000000000000}"

dc() {
  docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" "$@"
}

if [[ -n "$(dc ps --status running --quiet api 2>/dev/null)" ]]; then
  mode="exec"
elif [[ -n $CUR_SHA ]]; then
  mode="run"
elif [[ -n "$(dc ps --all --quiet api 2>/dev/null)" ]]; then
  die "api 컨테이너는 있는데 실행 중이 아니고 배포 기록(state/current)도 없음 — 사람이 확인 (README 12-6)"
else
  log "건너뜀: api 컨테이너와 배포 기록이 없음 (첫 배포 전)"
  exit 0
fi

# ── 사본 만들기 (컨테이너 안, UID 10001) ──────────
# deploy.sh 의 BACKUP_PY 와 같은 방식. 임시 파일 이름만 다르다 (배포 직전 백업과 부딪히지 않게).
# 종료 코드: 3 = DB 파일 없음(건너뜀), 4 = integrity_check 실패, 5 = SQLite 머리말이 아님
BACKUP_PY='
import os, sqlite3, sys
src_path = os.environ.get("DB_PATH", "/data/scrap.db")
if not os.path.isfile(src_path):
    print("DB 파일 없음", file=sys.stderr)
    sys.exit(3)
tmp = os.path.join(os.path.dirname(src_path) or ".", ".daily-backup.tmp")
def cleanup():
    for p in (tmp, tmp + "-wal", tmp + "-shm", tmp + "-journal"):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass
try:
    cleanup()
    src = sqlite3.connect(src_path, timeout=30)
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    src.close()
    result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
    if result != "ok":
        print("백업 사본 integrity_check 실패", file=sys.stderr)
        sys.exit(4)
    with open(tmp, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            print("백업 사본이 SQLite 파일이 아님", file=sys.stderr)
            sys.exit(5)
        f.seek(0)
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
finally:
    cleanup()
'

NAME="daily-$(date -u +%Y%m%dT%H%M%SZ).db.gz.age"
OUT="${DAILY_DIR}/${NAME}"
[[ ! -e $OUT ]] || die "같은 이름의 백업이 이미 있음: ${NAME} (1초 뒤 다시 실행)"
PART="${OUT}.part"

if [[ $mode == exec ]]; then
  py_cmd=(docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" exec -T api python -)
else
  # api 가 멈췄거나 재시작을 반복하는 중: 운영 버전 이미지로 일회용 컨테이너.
  # 이미지 이름은 compose 파일에서 읽는다 (config --images 는 이미지 이름만 출력한다 — .env 값은 출력하지 않는다).
  api_image="$(dc config --images 2>/dev/null | grep -E '/scrap-api:[0-9a-f]{40}$' | head -n 1 || true)"
  [[ $api_image == *":${CUR_SHA}" ]] || die "compose 파일에서 api 이미지 이름을 읽지 못함"
  RUN_NAME="scrap-backup-$(date -u +%Y%m%dT%H%M%SZ)"
  # docker-compose.yml 의 api 와 같은 실행 조건(사용자 10001, /data 마운트, 읽기 전용, 권한 제한, 메모리 한도).
  # 다른 점: 로그 드라이버 none, 네트워크 없음, .env 없음, 이미지를 새로 받지 않음(--pull never — 운영 이미지는 서버에 있다).
  py_cmd=(docker run --rm -i --name "$RUN_NAME" --pull never
    --log-driver none --network none
    --user 10001:10001 --read-only --tmpfs "/tmp:size=32m,mode=1777"
    --cap-drop ALL --security-opt no-new-privileges:true
    --memory 384m --pids-limit 256
    --mount "type=bind,source=${APP_DIR}/data,target=/data"
    -e DB_PATH=/data/scrap.db
    "$api_image" python -)
fi

log "백업 중 (${mode}, 운영 버전 ${CUR_SHA:0:12})"
# 평문은 파이프 안에서만 흐른다: 컨테이너 표준출력 → gzip → age → 암호화된 .part 파일
set +e
printf '%s' "$BACKUP_PY" |
  timeout --kill-after=30 "$RUN_TIMEOUT" "${py_cmd[@]}" |
  gzip -6 -n |
  age -R "$RECIPIENTS" -o "$PART"
st=("${PIPESTATUS[@]}")
set -e
py_rc=${st[1]}
gz_rc=${st[2]}
age_rc=${st[3]}

# 사본 만들기가 끝났으므로 잠금을 놓는다 (이후는 daily/ 안에서만 일한다).
flock -u 9
exec 9>&-

if [[ $py_rc -eq 3 ]]; then
  log "건너뜀: DB 파일이 아직 없음"
  exit 0
fi
if [[ $py_rc -eq 124 || $py_rc -eq 137 ]]; then
  die "사본 만들기가 ${RUN_TIMEOUT}초 안에 끝나지 않아 중단함"
fi
[[ $py_rc -eq 0 ]] || die "사본 만들기 실패 (종료 코드 ${py_rc}; 3=DB 없음 4=integrity_check 5=형식)"
[[ $gz_rc -eq 0 ]] || die "gzip 실패 (종료 코드 ${gz_rc})"
[[ $age_rc -eq 0 ]] || die "age 암호화 실패 (종료 코드 ${age_rc}) — 수신자 파일 확인 (README 13-2)"
[[ -s $PART ]] || die "암호화 결과가 비어 있음"
[[ "$(head -c ${#AGE_MAGIC} -- "$PART")" == "$AGE_MAGIC" ]] || die "암호화 결과가 age 형식이 아님"

chmod 600 -- "$PART"
mv -f -- "$PART" "$OUT"
PART=""
size="$(stat -c %s -- "$OUT")"

# ── 오래된 백업 정리 (이름 = UTC 시각 → 이름순 = 시간순) ──
files=()
for f in "$DAILY_DIR"/daily-*.db.gz.age; do
  [[ ${f##*/} =~ $NAME_RE ]] && files+=("$f")
done
for ((i = 0; i < ${#files[@]} - KEEP; i++)); do
  rm -f -- "${files[i]}"
  log "오래된 백업 삭제: ${files[i]##*/}"
done

log "백업 완료: ${NAME} (${size} bytes, 보관 최대 ${KEEP}개)"
exit 0
