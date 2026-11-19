#!/usr/bin/env bash
# 배포 스크립트 — 서버의 /opt/scrap-app/deploy/deploy.sh (root 소유, 755)로 설치한다 (deploy/README.md 11절).
#
# 실행 경로: GitHub Actions(deploy.yml) → ssh deploy@서버 "<커밋 SHA>"
#   deploy 사용자의 authorized_keys 강제 명령(restrict,command="/opt/scrap-app/deploy/deploy.sh")으로 실행되므로,
#   클라이언트가 보낸 명령 문자열은 SSH_ORIGINAL_COMMAND 로만 들어온다. 이 값은 소문자 16진수 40자(커밋 SHA)만 허용한다.
#
# 하는 일 (이미지 태그만 바꾼다. compose 파일·이 스크립트·.env 는 고치지 않는다)
#   1. 상태 읽기: /opt/scrap-app/state/current(운영 중 SHA), previous(그 직전 SHA)
#   2. DB 백업: 운영 중 api 컨테이너 안에서 Python sqlite3 backup API로 일관된 사본을 만들어
#      /opt/scrap-app/backups/predeploy-*.db (600)로 꺼낸다. 최근 KEEP_BACKUPS 개만 보관.
#      DB·컨테이너가 없으면(첫 배포) 건너뛴다. 백업이 실패하면 배포를 중단한다 (데이터 보호 우선).
#   3. IMAGE_TAG=<SHA> docker compose pull → up -d --remove-orphans
#   4. 헬스체크: https://$SITE_DOMAIN/api/health (Caddy·인증서·프록시까지). 서버 자신의 공인 IP로
#      되돌아오는 경로(헤어핀)가 막혀 있을 수 있어 --resolve 로 127.0.0.1(로컬 Caddy)에 보내되 인증서 검증은 유지한다.
#   5. 성공 → state 갱신(previous ← 이전 current, current ← 새 SHA), 오래된 이미지 정리(current·previous는 보존)
#      실패 → 배포 직전 운영 버전(state/current)으로 되돌리고 헬스체크, 종료 코드 1
#
# 출력: 표준출력(= Actions 로그, 공개 저장소라 누구나 볼 수 있음)과 /opt/scrap-app/logs/deploy.log 에 함께 남긴다.
#   도메인·.env 내용·비밀값은 출력하지 않는다. (`docker compose config` 전체 출력 금지 — .env 값이 펼쳐진다)
#
# 종료 코드: 0 = 성공, 1 = 실패(롤백 여부는 로그 참고), 2 = 잘못된 요청(SHA 형식 아님)
#
# 수동 실행(긴급 시 사람만, README 12-6): sudo -u deploy -H env SSH_ORIGINAL_COMMAND=<SHA> /opt/scrap-app/deploy/deploy.sh
set -euo pipefail
umask 077
# 강제 명령으로 실행될 때의 환경을 믿지 않는다. (sshd는 클라이언트가 보낸 LANG/LC_* 를 받아들일 수 있다)
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C.UTF-8

# 경로는 고정한다 (환경변수로 바꿀 수 없게). 이 스크립트는 docker 그룹 사용자의 강제 명령으로 실행되므로
# 외부에서 다른 compose·.env 를 가리키게 할 여지를 남기지 않는다. 시험할 때는 복사본에서 이 줄을 바꾼다.
APP_DIR=/opt/scrap-app
STATE_DIR="${APP_DIR}/state"
LOG_DIR="${APP_DIR}/logs"
LOG_FILE="${LOG_DIR}/deploy.log"
BACKUP_DIR="${APP_DIR}/backups"
ENV_FILE="${APP_DIR}/.env"
COMPOSE_FILE="${APP_DIR}/docker-compose.yml"

KEEP_BACKUPS=14     # 배포 직전 백업 보관 개수
HEALTH_TIMEOUT=90   # 헬스체크 최대 대기(초)
HEALTH_INTERVAL=3   # 헬스체크 간격(초)

log() {
  # stderr 로 쓴다: $(...) 안에서 호출돼도 출력이 값에 섞이지 않는다 (stdout·stderr 모두 로그로 간다).
  printf '%s deploy: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" >&2
}

die() {
  log "실패: $*"
  exit 1
}

short() { printf '%s' "${1:0:12}"; }

# ── 로그 ──────────────────────────────────────────
if [[ -d $LOG_DIR && -w $LOG_DIR ]]; then
  exec > >(tee -a "$LOG_FILE") 2>&1
  TEE_PID=$!
  # 끝날 때 tee 가 마지막 줄까지 쓰고 나가도록 기다린다 (SSH 세션 출력이 잘리지 않게).
  trap 'exec 1>&- 2>&-; wait "$TEE_PID" 2>/dev/null || true' EXIT
else
  log "경고: 로그 디렉터리에 쓸 수 없어 표준출력에만 남김 (${LOG_DIR})"
fi

# ── 1. 요청 검증 (커밋 SHA만) ─────────────────────
NEW_SHA="${SSH_ORIGINAL_COMMAND-}"
if [[ ! $NEW_SHA =~ ^[0-9a-f]{40}$ ]]; then
  # 받은 값 자체는 남기지 않는다 (로그 오염·주입 방지). 길이만 남긴다.
  log "거부: 요청 값이 커밋 SHA(소문자 16진수 40자)가 아님 (길이 ${#NEW_SHA})"
  exit 2
fi

# ── 동시 실행 방지 ────────────────────────────────
[[ -d $STATE_DIR && -w $STATE_DIR ]] || die "상태 디렉터리에 쓸 수 없음: ${STATE_DIR} (README 11절로 만든다)"
exec 9>"${STATE_DIR}/deploy.lock"
flock -n 9 || die "다른 배포가 진행 중이다 (${STATE_DIR}/deploy.lock)"

cd "$APP_DIR"
[[ -r $COMPOSE_FILE ]] || die "compose 파일을 읽을 수 없음: ${COMPOSE_FILE}"
[[ -r $ENV_FILE ]] || die ".env 를 읽을 수 없음: ${ENV_FILE}"
for cmd in docker curl flock find; do
  command -v "$cmd" >/dev/null || die "명령 없음: ${cmd}"
done

# 모든 compose 명령의 기본 태그는 새 SHA. 다른 태그가 필요한 곳(백업·롤백)은 명령 앞에 따로 준다.
export IMAGE_TAG="$NEW_SHA"
dc() {
  docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" "$@"
}

# ── 상태 읽기 ─────────────────────────────────────
read_sha_file() {
  local f="${STATE_DIR}/$1" v
  [[ -e $f ]] || return 0
  v="$(tr -d '[:space:]' <"$f")"
  [[ $v =~ ^[0-9a-f]{40}$ ]] || die "상태 파일 형식 오류: ${f} (README 12-6 참고해 사람이 고친다)"
  printf '%s' "$v"
}

write_state() {
  # 임시 파일에 쓰고 mv 로 바꿔 끼운다 (중간에 끊겨도 반쯤 쓴 파일이 남지 않게).
  printf '%s\n' "$2" >"${STATE_DIR}/.$1.tmp"
  mv -f "${STATE_DIR}/.$1.tmp" "${STATE_DIR}/$1"
}

CUR_SHA="$(read_sha_file current)"
PREV_SHA="$(read_sha_file previous)"

# ── SITE_DOMAIN 읽기 (.env 를 source 하지 않고 이 키만 파싱) ──
read_site_domain() {
  local line v
  line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?SITE_DOMAIN[[:space:]]*=' "$ENV_FILE" | tail -n 1 || true)"
  v="${line#*=}"
  v="${v%%[[:space:]]#*}"                    # 줄 끝 주석 ( # ...)
  v="${v#"${v%%[![:space:]]*}"}"             # 앞 공백
  v="${v%"${v##*[![:space:]]}"}"             # 뒤 공백
  v="${v#[\"\']}"
  v="${v%[\"\']}"
  v="${v,,}"
  # 값은 로그에 쓰지 않는다 (공개 Actions 로그에 실제 도메인이 남지 않게).
  [[ $v =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || die ".env 의 SITE_DOMAIN 이 없거나 형식이 올바르지 않음"
  printf '%s' "$v"
}

SITE_DOMAIN="$(read_site_domain)"

log "배포 시작: ${NEW_SHA} (운영 중: $(short "${CUR_SHA:-없음}"), 그 직전: $(short "${PREV_SHA:-없음}"))"
if [[ $NEW_SHA == "$CUR_SHA" ]]; then
  log "같은 버전 재배포: 상태(state)는 바뀌지 않는다"
fi

# ── 2. DB 백업 ────────────────────────────────────
# 컨테이너 안(UID 10001)에서 실행할 파이썬. 표준입력으로 넘기고, 백업 파일 내용을 표준출력으로 받는다.
# - DB 파일이 없으면 만들지 않고 종료 코드 3 (건너뜀).
# - 임시 사본은 메모리(tmpfs)가 아니라 같은 디스크(/data)에 만들고 끝나면 지운다.
# - 사본에 integrity_check 를 돌려 "ok" 일 때만 내보낸다.
BACKUP_PY='
import os, sqlite3, sys
src_path = os.environ.get("DB_PATH", "/data/scrap.db")
if not os.path.isfile(src_path):
    print("DB 파일 없음", file=sys.stderr)
    sys.exit(3)
tmp = os.path.join(os.path.dirname(src_path) or ".", ".predeploy-backup.tmp")
try:
    if os.path.exists(tmp):
        os.unlink(tmp)
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
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
finally:
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
'

BACKUP_FILE=""

prune_backups() {
  local files i
  mapfile -t files < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'predeploy-*.db' -printf '%f\n' | sort -r)
  for ((i = KEEP_BACKUPS; i < ${#files[@]}; i++)); do
    rm -f "${BACKUP_DIR}/${files[i]}"
    log "오래된 백업 삭제: ${files[i]}"
  done
}

backup_db() {
  local mode out part rc size
  [[ -d $BACKUP_DIR && -w $BACKUP_DIR ]] || die "백업 디렉터리에 쓸 수 없음: ${BACKUP_DIR}"
  # 이전 실행이 남긴 조각 파일 정리
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'predeploy-*.part' -delete

  if [[ -n "$(dc ps --status running --quiet api 2>/dev/null)" ]]; then
    mode=exec   # 운영 중인 api 컨테이너 안에서
  elif [[ -n $CUR_SHA ]]; then
    # api가 멈췄거나 재시작을 반복하는 중: 운영 버전 이미지로 일회용 컨테이너를 띄워 백업한다.
    mode=run
  elif [[ -n "$(dc ps --all --quiet api 2>/dev/null)" ]]; then
    die "api 컨테이너는 있는데 실행 중이 아니고 배포 기록(state/current)도 없음 — 사람이 확인 후 백업 (README 12-6)"
  else
    log "DB 백업 건너뜀: api 컨테이너와 배포 기록이 없음 (첫 배포)"
    return 0
  fi

  out="${BACKUP_DIR}/predeploy-$(date -u +%Y%m%dT%H%M%SZ)-$(short "${CUR_SHA:-unknown}").db"
  part="${out}.part"
  log "DB 백업 중 (${mode})"
  if [[ $mode == exec ]]; then
    if printf '%s' "$BACKUP_PY" | dc exec -T api python - >"$part"; then rc=0; else rc=$?; fi
  else
    if printf '%s' "$BACKUP_PY" | IMAGE_TAG="$CUR_SHA" dc run --rm --no-deps -T api python - >"$part"; then rc=0; else rc=$?; fi
  fi

  if [[ $rc -eq 3 ]]; then
    rm -f "$part"
    log "DB 백업 건너뜀: DB 파일이 아직 없음"
    return 0
  fi
  if [[ $rc -ne 0 ]]; then
    rm -f "$part"
    die "DB 백업 실패 (종료 코드 ${rc}) — 배포를 중단한다. 운영 컨테이너는 그대로다"
  fi
  if [[ "$(head -c 15 "$part")" != "SQLite format 3" ]]; then
    rm -f "$part"
    die "DB 백업 결과가 SQLite 파일이 아님 — 배포를 중단한다"
  fi
  mv -f "$part" "$out"
  chmod 600 "$out"
  size="$(stat -c %s "$out")"
  BACKUP_FILE="$out"
  log "DB 백업 완료: $(basename "$out") (${size} bytes)"
  prune_backups
}

backup_db

# ── 3. 새 이미지 받기 ─────────────────────────────
log "이미지 받는 중: $(short "$NEW_SHA")"
if ! dc pull --quiet; then
  die "이미지 pull 실패 — GHCR 패키지가 공개(Public)인지, 빌드가 끝났는지 확인 (README 12-3). 운영 컨테이너는 그대로다"
fi

# ── 4. 헬스체크 ───────────────────────────────────
LAST_HEALTH=""
health_once() {
  local out rc
  if out="$(curl --silent --max-time 5 --proto '=https' \
    --resolve "${SITE_DOMAIN}:443:127.0.0.1" \
    --write-out '\n%{http_code}' \
    "https://${SITE_DOMAIN}/api/health" 2>/dev/null)"; then rc=0; else rc=$?; fi
  # curl 오류 메시지는 도메인을 담을 수 있어 버리고, 종료 코드와 HTTP 상태만 남긴다.
  LAST_HEALTH="curl=${rc} http=${out##*$'\n'}"
  [[ $rc -eq 0 && ${out##*$'\n'} == 200 ]] || return 1
  [[ ${out%$'\n'*} =~ \"status\"[[:space:]]*:[[:space:]]*\"ok\" ]]
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) n=0
  while ((SECONDS < deadline)); do
    n=$((n + 1))
    if health_once; then
      log "헬스체크 통과 (${n}번째 시도)"
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  log "헬스체크 실패: ${HEALTH_TIMEOUT}초 동안 정상 응답 없음 (${n}회, 마지막 ${LAST_HEALTH}; curl 60=인증서, 7=연결 거부, 28=시간 초과)"
  return 1
}

# ── 롤백 ──────────────────────────────────────────
rollback() {
  local target="$CUR_SHA"
  log "배포 실패: $(short "$NEW_SHA")"
  if [[ -n $BACKUP_FILE ]]; then
    log "배포 직전 DB 백업: ${BACKUP_FILE} (새 버전이 DB를 바꿨다면 사람이 복원 판단)"
  fi
  if [[ -z $target ]]; then
    log "되돌릴 직전 버전이 없음 (첫 배포). 컨테이너는 그대로 둔다 — 'docker compose logs' 로 원인 확인"
    exit 1
  fi
  if [[ $target == "$NEW_SHA" ]]; then
    log "같은 버전 재배포가 실패해 되돌릴 다른 버전이 없음 — README 12-6 수동 롤백(state/previous) 검토"
    exit 1
  fi
  log "롤백: $(short "$target") 로 되돌리는 중"
  if IMAGE_TAG="$target" dc up -d --remove-orphans && wait_healthy; then
    log "롤백 성공: $(short "$target") 운영 중 (state 는 바뀌지 않음)"
  else
    log "롤백도 실패 — 사이트가 내려가 있을 수 있다. 사람이 README 12-6 으로 복구"
  fi
  exit 1
}

# ── 5. 교체 ───────────────────────────────────────
log "컨테이너 교체: up -d (api healthy 후 web 시작)"
if ! dc up -d --remove-orphans; then
  log "docker compose up 실패 (api 가 healthy 가 되지 못했을 수 있음)"
  rollback
fi
log "헬스체크: https://<SITE_DOMAIN>/api/health (로컬 Caddy 경유, 최대 ${HEALTH_TIMEOUT}초)"
wait_healthy || rollback

# ── 6. 성공: 상태 기록 ────────────────────────────
if [[ $NEW_SHA != "$CUR_SHA" ]]; then
  if [[ -n $CUR_SHA ]]; then
    write_state previous "$CUR_SHA"
  fi
  write_state current "$NEW_SHA"
fi
PREV_SHA="$(read_sha_file previous)"

# ── 7. 오래된 이미지 정리 (current·previous 보존) ──
cleanup_images() {
  local img repo tag images=()
  mapfile -t images < <(dc config --images 2>/dev/null || true)
  if [[ ${#images[@]} -eq 0 ]]; then
    log "경고: 이미지 목록을 읽지 못해 정리를 건너뜀"
    return 0
  fi
  for img in "${images[@]}"; do
    repo="${img%:*}"
    while IFS= read -r tag; do
      [[ -z $tag || $tag == '<none>' || $tag == "$NEW_SHA" || $tag == "$PREV_SHA" ]] && continue
      if docker image rm "${repo}:${tag}" >/dev/null 2>&1; then
        log "이미지 삭제: ${repo##*/}:$(short "$tag")"
      else
        log "이미지 삭제 건너뜀 (사용 중일 수 있음): ${repo##*/}:$(short "$tag")"
      fi
    done < <(docker image ls --format '{{.Tag}}' "$repo" 2>/dev/null || true)
  done
  # 같은 태그를 다시 받아 이름이 떨어진 옛 이미지(<none>) 정리. 태그가 있는 이미지는 지우지 않는다.
  docker image prune -f >/dev/null 2>&1 || true
}
cleanup_images

dc ps --format 'table {{.Service}}\t{{.Status}}' || true
log "배포 성공: $(short "$NEW_SHA") 운영 중 (직전: $(short "${PREV_SHA:-없음}"))"
exit 0
