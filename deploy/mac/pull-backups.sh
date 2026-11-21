#!/bin/bash
# 서버의 암호화 백업을 이 Mac 으로 가져온다 — deploy/README.md 14절. launchd 가 하루 한 번 실행한다.
# macOS 기본 /bin/bash(3.2)로 동작하게 쓴다 (mapfile·${var,,}·연관 배열을 쓰지 않는다).
#
# 설정: ~/.config/scrap-backup/config (KEY=값 줄. 예시: deploy/mac/config.example). 같은 이름의 환경변수가 있으면 그 값이 우선한다.
#   SCRAP_BACKUP_HOST         서버 주소 (<이름>.duckdns.org) ← 필수. 저장소 파일에는 실제 주소를 쓰지 않는다
#   SCRAP_BACKUP_USER         서버 사용자 (기본 deploy)
#   SCRAP_BACKUP_KEY          백업 수신 전용 SSH 키 (기본 ~/.ssh/scrap_backup_ed25519)
#   SCRAP_BACKUP_KNOWN_HOSTS  서버 호스트 키 한 줄 파일 (기본 ~/.ssh/scrap_backup_known_hosts, README 14-3)
#   SCRAP_BACKUP_DIR          보관 폴더 (기본 ~/ScrapBackups — Desktop·Documents 는 macOS 개인정보 보호 권한 문제로 피한다)
#   SCRAP_BACKUP_KEEP_DAYS    이 날수보다 오래된 백업은 지운다 (기본 30)
#   SCRAP_BACKUP_KEEP_MIN     날짜와 상관없이 최근 이 개수는 남긴다 (기본 7 — 서버가 멈춰도 마지막 백업이 사라지지 않게)
#   SCRAP_BACKUP_STALE_DAYS   가장 최근 백업이 이 날수보다 오래되면 실패로 알린다 (기본 3)
#   SCRAP_BACKUP_KEEP_MONTHLY 매월 첫 백업은 이 개월 수만큼 보관한다 (기본 12, 0 이면 끔) — 30일 삭제에서 빠진다
#   SCRAP_BACKUP_MAX_MB       백업 하나를 받을 때의 크기 상한(MB). 넘으면 받지 않는다 (기본 500)
#   SCRAP_BACKUP_NOTIFY       1 이면 실패할 때 macOS 알림을 띄운다 (기본 1)
#
# 하는 일
#   1. 서버에 "list" → "<sha256> <이름>" 목록
#   2. 이 Mac 에 없는 백업만 "get <이름>" → 임시 파일(.이름.part)에 받아(크기 상한) sha256·age 머리말 확인 → 원자적 이름 변경(mv), 600
#      이름의 날짜가 이 Mac 의 오늘(UTC)보다 1일 넘게 미래면 받지 않고 실패로 알린다 (서버 시계 이상 등).
#   3. KEEP_DAYS 일이 지난 백업 삭제 (최근 KEEP_MIN 개, 최근 KEEP_MONTHLY 개월의 매월 첫 백업은 남김)
#      최신 백업이 STALE_DAYS 일보다 오래되면 실패
# 복호화하지 않는다. age 개인키는 이 스크립트도 이 폴더도 쓰지 않는다 (복원할 때만 사람이 쓴다, README 15절).
# SSH: 전용 키만(IdentitiesOnly), 호스트 키는 미리 등록한 파일로만 확인(StrictHostKeyChecking=yes), ~/.ssh/config 무시.
#
# 기록: ~/Library/Logs/scrap-backup.log (1MB 넘으면 .1 로 돌린다). 서버 주소는 기록에 남기지 않는다.
# 종료 코드: 0 = 성공, 1 = 실패(일부 받기 실패·오래된 백업 포함), 2 = 설정 오류
set -euo pipefail
umask 077
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export LC_ALL=C

CONFIG="${SCRAP_BACKUP_CONFIG:-$HOME/.config/scrap-backup/config}"
LOG="$HOME/Library/Logs/scrap-backup.log"

NAME_RE='^daily-([0-9]{8})T[0-9]{6}Z\.db\.gz\.age$'
LINE_RE='^([0-9a-f]{64}) (daily-[0-9]{8}T[0-9]{6}Z\.db\.gz\.age)$'
AGE_MAGIC='age-encryption.org/v1'

log() {
  local line
  line="$(date '+%Y-%m-%d %H:%M:%S') pull: $*"
  printf '%s\n' "$line" >&2
  { printf '%s\n' "$line" >>"$LOG"; } 2>/dev/null || true
}

NOTIFY=1
notify() {
  [ "$NOTIFY" = 1 ] || return 0
  /usr/bin/osascript -e "display notification \"$1\" with title \"스크랩 백업\"" >/dev/null 2>&1 || true
}

config_error() {
  log "설정 오류: $* (README 14-4)"
  notify "설정 오류: $*"
  exit 2
}

expand_home() {
  # shellcheck disable=SC2088  # 글자 그대로의 ~/ 를 찾아 $HOME 으로 바꾼다
  case $1 in
    "~") printf '%s' "$HOME" ;;
    "~/"*) printf '%s/%s' "$HOME" "${1#"~/"}" ;;
    *) printf '%s' "$1" ;;
  esac
}

# 로그 돌리기 (1MB)
if [ -f "$LOG" ] && [ "$(wc -c <"$LOG" | tr -d ' ')" -gt 1048576 ]; then
  mv -f "$LOG" "$LOG.1" 2>/dev/null || true
fi

# ── 설정 읽기 (source 하지 않고 아는 키만 받는다) ──
C_HOST="" C_USER="" C_KEY="" C_KH="" C_DIR="" C_KEEP_DAYS="" C_KEEP_MIN="" C_STALE="" C_NOTIFY="" C_MONTHLY="" C_MAX_MB=""
if [ -f "$CONFIG" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case $line in '' | '#'*) continue ;; esac
    case $line in *=*) ;; *) config_error "설정 파일에 KEY=값 형식이 아닌 줄이 있음" ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    val="${val#\"}" val="${val%\"}"
    val="${val#\'}" val="${val%\'}"
    case $key in
      SCRAP_BACKUP_HOST) C_HOST=$val ;;
      SCRAP_BACKUP_USER) C_USER=$val ;;
      SCRAP_BACKUP_KEY) C_KEY=$val ;;
      SCRAP_BACKUP_KNOWN_HOSTS) C_KH=$val ;;
      SCRAP_BACKUP_DIR) C_DIR=$val ;;
      SCRAP_BACKUP_KEEP_DAYS) C_KEEP_DAYS=$val ;;
      SCRAP_BACKUP_KEEP_MIN) C_KEEP_MIN=$val ;;
      SCRAP_BACKUP_STALE_DAYS) C_STALE=$val ;;
      SCRAP_BACKUP_NOTIFY) C_NOTIFY=$val ;;
      SCRAP_BACKUP_KEEP_MONTHLY) C_MONTHLY=$val ;;
      SCRAP_BACKUP_MAX_MB) C_MAX_MB=$val ;;
      *) log "경고: 모르는 설정 이름은 무시: ${key}" ;;
    esac
  done <"$CONFIG"
fi

HOST="${SCRAP_BACKUP_HOST:-$C_HOST}"
RUSER="${SCRAP_BACKUP_USER:-${C_USER:-deploy}}"
KEY="$(expand_home "${SCRAP_BACKUP_KEY:-${C_KEY:-~/.ssh/scrap_backup_ed25519}}")"
KNOWN_HOSTS="$(expand_home "${SCRAP_BACKUP_KNOWN_HOSTS:-${C_KH:-~/.ssh/scrap_backup_known_hosts}}")"
DEST="$(expand_home "${SCRAP_BACKUP_DIR:-${C_DIR:-~/ScrapBackups}}")"
KEEP_DAYS="${SCRAP_BACKUP_KEEP_DAYS:-${C_KEEP_DAYS:-30}}"
KEEP_MIN="${SCRAP_BACKUP_KEEP_MIN:-${C_KEEP_MIN:-7}}"
STALE_DAYS="${SCRAP_BACKUP_STALE_DAYS:-${C_STALE:-3}}"
NOTIFY="${SCRAP_BACKUP_NOTIFY:-${C_NOTIFY:-1}}"
KEEP_MONTHLY="${SCRAP_BACKUP_KEEP_MONTHLY:-${C_MONTHLY:-12}}"
MAX_MB="${SCRAP_BACKUP_MAX_MB:-${C_MAX_MB:-500}}"

HOST_RE='^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'
[[ $HOST =~ $HOST_RE ]] || config_error "SCRAP_BACKUP_HOST 가 없거나 도메인 형식이 아님 (소문자 도메인만)"
[[ $RUSER =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || config_error "SCRAP_BACKUP_USER 형식이 아님"
for n in "$KEEP_DAYS" "$KEEP_MIN" "$STALE_DAYS" "$MAX_MB"; do
  [[ $n =~ ^[1-9][0-9]{0,3}$ ]] || config_error "보관·경고 날수와 크기 상한은 1~9999 정수"
done
[[ $KEEP_MONTHLY =~ ^[0-9]{1,3}$ ]] || config_error "SCRAP_BACKUP_KEEP_MONTHLY 는 0~999 정수"
MAX_BYTES=$((MAX_MB * 1024 * 1024))
case $DEST in /*) ;; *) config_error "SCRAP_BACKUP_DIR 는 절대경로(또는 ~/...)" ;; esac
if [ ! -f "$KEY" ] || [ ! -r "$KEY" ]; then config_error "SSH 키 파일이 없음 (README 14-1)"; fi
[ -s "$KNOWN_HOSTS" ] || config_error "호스트 키 파일이 없거나 비어 있음 (README 14-3)"

# 기록에서 서버 주소를 가린다 (ssh 오류 문구에 들어갈 수 있다).
HOST_SED="${HOST//./\\.}"
scrub() { sed -e "s/${HOST_SED}/<서버>/g" -e 's/[0-9]\{1,3\}\(\.[0-9]\{1,3\}\)\{3\}/x.x.x.x/g'; }

mkdir -p "$DEST"
chmod 700 "$DEST"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/scrap-backup.XXXXXX")"
LOCK="$DEST/.pull.lock"
LOCKED=0
# shellcheck disable=SC2317  # trap 으로 불린다
cleanup() {
  rm -rf "$TMP"
  # 잠금을 쥔 실행만 조각을 지운다 (건너뛴 실행이 진행 중인 다른 실행의 조각을 지우지 않게).
  if [ "$LOCKED" = 1 ]; then
    rm -f "$DEST"/.daily-*.part 2>/dev/null || true
    rm -rf "$LOCK"
  fi
}
trap cleanup EXIT

# ── 동시 실행 방지 (mkdir 은 원자적) ──────────────
if ! mkdir "$LOCK" 2>/dev/null; then
  old_pid="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [[ $old_pid =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
    log "다른 실행이 진행 중 (pid ${old_pid}) — 이번 실행은 건너뜀"
    exit 0
  fi
  rm -rf "$LOCK"
  mkdir "$LOCK" || {
    log "잠금을 만들 수 없음: $LOCK"
    exit 1
  }
fi
LOCKED=1
echo $$ >"$LOCK/pid"

remote() {
  # $1 = 요청 문자열 (list | get <이름>). 표준출력 = 데이터. -n: 표준입력을 쓰지 않는다 (while read 루프 보호).
  ssh -F /dev/null -T -n \
    -i "$KEY" \
    -o IdentitiesOnly=yes \
    -o IdentityAgent=none \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS" \
    -o GlobalKnownHostsFile=/dev/null \
    -o ConnectTimeout=20 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=4 \
    -o LogLevel=ERROR \
    -- "${RUSER}@${HOST}" "$1"
}

errors=0

# ── 1. 목록 ───────────────────────────────────────
if ! remote list >"$TMP/list" 2>"$TMP/err"; then
  log "실패: 서버 목록을 받지 못함 — $(scrub <"$TMP/err" | tr '\n' ' ')"
  notify "서버에서 백업 목록을 받지 못했습니다 (로그 확인)"
  exit 1
fi

# 보관 기준 날짜 (BSD date)
cutoff="$(date -v-"${KEEP_DAYS}"d +%Y%m%d)"
stale_cutoff="$(date -v-"${STALE_DAYS}"d +%Y%m%d)"
future_limit="$(date -u -v+1d +%Y%m%d)"
month_cutoff="$(date -v-"${KEEP_MONTHLY}"m +%Y%m)"

listed=0 new=0 skipped=0
while IFS= read -r line || [ -n "$line" ]; do
  if [[ ! $line =~ $LINE_RE ]]; then
    log "경고: 형식이 다른 목록 줄은 무시 (길이 ${#line})"
    continue
  fi
  hash="${BASH_REMATCH[1]}"
  name="${BASH_REMATCH[2]}"
  listed=$((listed + 1))
  [[ $name =~ $NAME_RE ]]
  day="${BASH_REMATCH[1]}"
  if [ -e "$DEST/$name" ]; then
    skipped=$((skipped + 1))
    continue
  fi
  if [ "$day" -gt "$future_limit" ]; then
    log "실패: 이름의 날짜가 미래라 받지 않음 ${name} — 서버 시각 확인 (README 14-7)"
    errors=$((errors + 1))
    continue
  fi
  if [ "$day" -lt "$cutoff" ]; then
    continue # 받아도 바로 지울 오래된 것
  fi
  part="$DEST/.${name}.part"
  # 크기 상한: 상한 + 1 바이트까지만 받는다 (넘으면 head 가 끊고 ssh 는 실패로 끝난다).
  set +e
  remote "get $name" 2>"$TMP/err" | head -c $((MAX_BYTES + 1)) >"$part"
  st="${PIPESTATUS[0]} ${PIPESTATUS[1]}"
  set -e
  size="$(wc -c <"$part" | tr -d ' ')"
  if [ "$size" -gt "$MAX_BYTES" ]; then
    rm -f "$part"
    log "실패: 크기 상한(${MAX_MB}MB)을 넘어 받지 않음 ${name}"
    errors=$((errors + 1))
    continue
  fi
  if [ "$st" != "0 0" ]; then
    rm -f "$part"
    log "실패: 받기 실패 ${name} — $(scrub <"$TMP/err" | tr '\n' ' ')"
    errors=$((errors + 1))
    continue
  fi
  got="$(shasum -a 256 "$part" | awk '{print $1}')"
  if [ "$got" != "$hash" ]; then
    rm -f "$part"
    log "실패: sha256 이 목록과 다름 ${name} — 버림"
    errors=$((errors + 1))
    continue
  fi
  if [ "$(head -c ${#AGE_MAGIC} "$part")" != "$AGE_MAGIC" ]; then
    rm -f "$part"
    log "실패: age 암호화 파일이 아님 ${name} — 버림"
    errors=$((errors + 1))
    continue
  fi
  chmod 600 "$part"
  mv -f "$part" "$DEST/$name"
  new=$((new + 1))
  log "받음: ${name} ($(wc -c <"$DEST/$name" | tr -d ' ') bytes)"
done <"$TMP/list"

if [ "$listed" -eq 0 ]; then
  log "경고: 서버에 암호화 백업이 하나도 없음 (README 13-5)"
fi

# ── 2. 오래된 백업 정리 (이름의 날짜 기준, 최근 KEEP_MIN 개·최근 KEEP_MONTHLY 개월의 매월 첫 백업은 남김) ──
files=()
for f in "$DEST"/daily-*.db.gz.age; do
  [ -f "$f" ] || continue
  [[ ${f##*/} =~ $NAME_RE ]] && files+=("$f")
done
total=${#files[@]}
deleted=0 monthly=0
last_month=""
i=0
while [ "$i" -lt "$total" ]; do
  f="${files[$i]}"
  [[ ${f##*/} =~ $NAME_RE ]]
  day="${BASH_REMATCH[1]}"
  month="${day:0:6}"
  first_of_month=0
  if [ "$month" != "$last_month" ]; then
    first_of_month=1
    last_month=$month
  fi
  if [ "$first_of_month" = 1 ] && [ "$KEEP_MONTHLY" -gt 0 ] && [ "$month" -gt "$month_cutoff" ]; then
    monthly=$((monthly + 1)) # 장기 보관본 (매월 첫 백업)
  elif [ $((total - deleted)) -gt "$KEEP_MIN" ] && [ "$day" -lt "$cutoff" ]; then
    rm -f "$f"
    deleted=$((deleted + 1))
    log "오래된 백업 삭제: ${f##*/}"
  fi
  i=$((i + 1))
done

# ── 3. 최신 백업 확인 ─────────────────────────────
remaining=$((total - deleted))
newest_day=""
if [ "$total" -gt 0 ]; then
  [[ ${files[$((total - 1))]##*/} =~ $NAME_RE ]]
  newest_day="${BASH_REMATCH[1]}"
fi

log "완료: 서버 ${listed}개, 새로 받음 ${new}개, 이미 있음 ${skipped}개, 받기 실패 ${errors}개, 삭제 ${deleted}개, 보관 ${remaining}개 (월간 장기 보관 ${monthly}개, 최신 ${newest_day:-없음})"

if [ "$errors" -gt 0 ]; then
  notify "백업 ${errors}개를 받지 못했습니다 (로그 확인)"
  exit 1
fi
if [ -z "$newest_day" ] || [ "$newest_day" -lt "$stale_cutoff" ]; then
  log "실패: 가장 최근 백업이 ${STALE_DAYS}일보다 오래됨 — 서버 일일 백업 확인 (README 13-5)"
  notify "최근 ${STALE_DAYS}일 동안 새 백업이 없습니다 (서버 확인)"
  exit 1
fi
exit 0
