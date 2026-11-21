#!/usr/bin/env bash
# 공개되는 프론트 빌드 결과물에 비밀값 형태가 섞였는지 검사한다 (CI 전용 — 서버에 설치하지 않는다).
#
#   bash deploy/scan-dist.sh <디렉터리>        예: frontend/dist (러너에서 빌드한 결과)
#   bash deploy/scan-dist.sh --image <이미지>  web 이미지 안의 /srv 를 꺼내 검사 (실제로 GHCR·브라우저로 나가는 파일)
#
# 쓰는 곳: .github/workflows/ci.yml (frontend 잡: dist, images 잡: 이미지), deploy.yml (build 잡: push 전에 이미지)
# 빌드 결과물은 공개 이미지(GHCR)와 브라우저에 그대로 나간다. 공개 Actions 로그이므로 찾은 **파일 이름만** 출력하고
# 일치한 내용은 찍지 않는다 (grep -l).
#
# 검사하는 것
#   - Anthropic 키(sk-ant-...), PEM 개인 키, age 개인 키, GitHub 토큰 형식
#   - 서버 비밀값 변수의 대입 형태(NAME=). 화면 문구에 변수 이름만 나오는 것은 허용한다.
#   - DuckDNS 도메인(실제 서버 주소는 번들에 들어갈 일이 없다)
#   - 비밀·데이터 파일 종류(.env*, 키, DB, age 파일 등)가 public/ 등을 거쳐 복사된 경우
# 종료 코드: 0 = 통과, 1 = 발견 또는 검사 오류, 2 = 사용법 오류
set -euo pipefail

usage() {
  echo "사용법: $0 <디렉터리> | --image <이미지>" >&2
  exit 2
}

TMP=""
CID=""
cleanup() {
  if [[ -n $CID ]]; then docker rm -f "$CID" >/dev/null 2>&1 || true; fi
  if [[ -n $TMP ]]; then rm -rf "$TMP"; fi
}
trap cleanup EXIT

case ${1-} in
  --image)
    [[ $# -eq 2 && -n $2 ]] || usage
    TMP="$(mktemp -d)"
    # 컨테이너는 만들기만 하고 실행하지 않는다.
    CID="$(docker create "$2")"
    docker cp "${CID}:/srv" "${TMP}/srv" >/dev/null
    DIR="${TMP}/srv"
    LABEL="이미지 /srv"
    ;;
  '' | -*) usage ;;
  *)
    [[ $# -eq 1 ]] || usage
    DIR="$1"
    LABEL="$1"
    ;;
esac

if [[ ! -f ${DIR}/index.html ]]; then
  echo "::error::${LABEL}/index.html 이 없습니다 (빌드 결과물을 검사할 수 없음)"
  exit 1
fi

status=0
files="$(grep -rlaE \
  -e 'sk-ant-[A-Za-z0-9_-]{8,}' \
  -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' \
  -e 'AGE-SECRET-KEY-1' \
  -e 'gh[pousr]_[A-Za-z0-9]{36}' \
  -e 'github_pat_[A-Za-z0-9_]{20,}' \
  -e '(SESSION_SECRET|SETUP_TOKEN|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|DEPLOY_SSH_KEY)=' \
  -e '[A-Za-z0-9-]+\.duckdns\.org' \
  "$DIR")" || status=$?
if [[ $status -eq 0 ]]; then
  echo "::error::${LABEL}: 빌드 결과물에 비밀값 형태가 있습니다. 아래 파일을 확인하세요 (내용은 출력하지 않음)."
  printf '%s\n' "${files//"$DIR"/.}"
  exit 1
elif [[ $status -ne 1 ]]; then
  echo "::error::${LABEL}: 비밀값 검사 실행 오류 (grep 종료 코드 ${status})"
  exit 1
fi

bad_names="$(find "$DIR" \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' \
  -o -name '*.p12' -o -name '*.pfx' -o -name 'id_rsa*' -o -name 'id_ed25519*' -o -name 'id_ecdsa*' \
  -o -name 'known_hosts' -o -name '.npmrc' -o -name '.git' -o -name '*.age' -o -name 'age-key*' \
  -o -name '*.db' -o -name '*.db-*' -o -name '*.sqlite*' \) -print)"
if [[ -n $bad_names ]]; then
  echo "::error::${LABEL}: 빌드 결과물에 비밀·데이터 파일 종류가 들어 있습니다."
  printf '%s\n' "${bad_names//"$DIR"/.}"
  exit 1
fi

echo "비밀값 검사 통과 (${LABEL}): $(find "$DIR" -type f | wc -l | tr -d ' ')개 파일"
