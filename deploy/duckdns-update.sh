#!/usr/bin/env bash
# DuckDNS 서브도메인의 IP를 이 서버의 현재 공인 IPv4로 갱신한다.
# 서버의 /opt/scrap-app/deploy/duckdns-update.sh 로 설치하고 cron(5분마다, deploy 사용자)으로 실행한다.
#
# 입력 (서버에만 있음, 저장소에 없음)
#   /opt/scrap-app/duckdns/token   DuckDNS 토큰 (비밀값, 권한 600)
#   /opt/scrap-app/duckdns/domain  서브도메인 이름 (예: <이름> 또는 <이름>.duckdns.org)
#
# 토큰 보호
#   - 토큰은 URL 쿼리에 들어가야 하므로 curl 인자로 넘기지 않고 `--config -`(표준입력)로 넘긴다.
#     → `ps` 프로세스 목록에 토큰이 보이지 않는다. printf는 bash 내장 명령이라 별도 프로세스가 생기지 않는다.
#   - 로그에는 URL·토큰·curl 오류 원문을 남기지 않고 결과(OK/실패)와 종료 코드만 남긴다.
#   - `set -x`를 쓰지 않는다.
#
# 종료 코드: 0 = 갱신 성공(OK), 그 외 = 실패
set -euo pipefail
umask 077

BASE_DIR="${SCRAP_APP_DIR:-/opt/scrap-app}"
DUCKDNS_DIR="${BASE_DIR}/duckdns"
TOKEN_FILE="${DUCKDNS_DIR}/token"
DOMAIN_FILE="${DUCKDNS_DIR}/domain"
LOCK_FILE="${DUCKDNS_DIR}/.lock"

log() {
  printf '%s duckdns: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  log "실패: $*" >&2
  exit 1
}

# 이전 실행이 아직 끝나지 않았으면(네트워크 지연 등) 이번 실행은 건너뛴다.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "이전 실행이 진행 중이라 건너뜀"
  exit 0
fi

[[ -f $TOKEN_FILE && -r $TOKEN_FILE ]] || fail "토큰 파일을 읽을 수 없음: $TOKEN_FILE"
[[ -f $DOMAIN_FILE && -r $DOMAIN_FILE ]] || fail "도메인 파일을 읽을 수 없음: $DOMAIN_FILE"

# 토큰 파일이 다른 사용자에게 열려 있으면 거부한다.
token_perm="$(stat -c '%a' "$TOKEN_FILE")"
case "$token_perm" in
  600 | 400) ;;
  *) fail "토큰 파일 권한이 ${token_perm} 임 (600 이어야 함: chmod 600 $TOKEN_FILE)" ;;
esac

token="$(tr -d '[:space:]' <"$TOKEN_FILE")"
domain="$(tr -d '[:space:]' <"$DOMAIN_FILE")"
domain="${domain,,}"
domain="${domain%.duckdns.org}"

# 형식 검사: curl 설정 문법(따옴표·줄바꿈)이나 URL 쿼리를 깨뜨리는 문자를 막는다.
# DuckDNS 토큰은 UUID 형식(16진수와 하이픈)이다. 실패 메시지에 값 자체는 쓰지 않는다.
[[ $token =~ ^[A-Za-z0-9-]{16,64}$ ]] || fail "토큰 형식이 올바르지 않음 (파일 내용 확인)"
[[ $domain =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || fail "서브도메인 형식이 올바르지 않음: ${domain}"

# ip= 를 비워 두면 DuckDNS가 요청을 보낸 주소(=서버 공인 IP)로 설정한다. IPv4로 강제한다.
set +e
response="$(
  printf 'url = "https://www.duckdns.org/update?domains=%s&token=%s&ip="\n' "$domain" "$token" |
    curl --config - \
      --ipv4 \
      --silent \
      --fail \
      --proto '=https' \
      --tlsv1.2 \
      --max-time 30 \
      --retry 2 \
      --retry-delay 5 \
      2>/dev/null
)"
rc=$?
set -e
unset token

if [[ $rc -ne 0 ]]; then
  fail "DuckDNS 요청 실패 (curl 종료 코드 ${rc}: 6=DNS, 7=연결, 22=HTTP 오류, 28=시간 초과)"
fi

response="$(printf '%s' "$response" | tr -d '[:space:]')"
if [[ $response != "OK" ]]; then
  # DuckDNS는 성공 시 OK, 실패 시 KO 만 돌려준다. 응답에 토큰은 없지만 길이를 제한해 남긴다.
  fail "DuckDNS 응답이 OK가 아님: '${response:0:16}' (토큰·서브도메인 확인)"
fi

log "OK (${domain}.duckdns.org)"
