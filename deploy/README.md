# 서버 운영 문서 (서버 구성 · 서버 파일 갱신 · 배포 · 롤백)

사람이 서버(와 GitHub 화면)에서 직접 실행하는 절차서다. 명령은 복사해 그대로 실행한다.
AI(마스터·서브에이전트)는 서버에 접속하지 않는다. "결과를 마스터에게" 라고 적힌 단계는 출력을 마스터에게 전달한다.

## 읽기 전에

- **서버 고유 기록과 일회성 작업은 로컬 `deploy/README.local.md`(커밋하지 않음)에 있다.** 최초 구축 때의 서버 현황, 기존 서비스 정리, 첫 HTTPS 발급 같은 다시 할 일이 없는 작업이다. 이 공개 문서에는 앞으로도 쓰는 일반 운영 절차만 둔다.
  - 7~9절은 그 로컬 문서로 옮기고 번호만 남겼다. 다른 파일(서버에 설치된 스크립트 포함)이 "README N절"로 이 문서를 가리키므로 나머지 절 번호는 바꾸지 않는다.
- 대상: Oracle Cloud 무료 인스턴스(1 OCPU / RAM 1GB + 스왑 2GB), Ubuntu 24.04 (OCI 이미지).
- 80/443은 **이 앱의 web 컨테이너(Caddy)**만 쓴다. 같은 서버의 다른 웹 서버(systemd Caddy·nginx, 다른 compose 프로젝트)가 80/443을 잡으면 안 된다.
- 데이터(SQLite, Caddy 인증서)는 Docker 볼륨이 아니라 **서버 폴더** `/opt/scrap-app/...`에 저장한다 (3-2).
- 관리 사용자(OCI Ubuntu 이미지 기본값 `ubuntu`)로 SSH 접속해 `sudo`로 실행한다고 가정한다.
- `<이름>` = DuckDNS 서브도메인 (`<이름>.duckdns.org`). `<...>`는 직접 바꿔 넣는다.
- ⚠️ 표시 단계는 **되돌리기 어렵다.** 바로 앞의 백업·확인을 끝낸 뒤 진행한다.
- 이 문서는 공개 저장소에 있다. **공인 IP, 실제 도메인, 토큰, 이메일, 서버 고유 상태·이력**을 이 문서나 저장소 파일에 적지 않는다 (필요하면 로컬 문서에 적는다).
- 비밀값(토큰·키)은 `echo 토큰 > 파일`처럼 명령줄에 쓰지 않는다 (셸 기록에 남는다). 이 문서의 방법(붙여넣기 후 Ctrl+D, 편집기)을 쓴다.
- 진단할 때 비밀값을 화면에 펼치는 명령(`docker inspect` 전체 출력, `docker compose config`, 컨테이너 `env` 등)은 쓰지 않는다. 목록과 대신 쓰는 방법은 17절.

### 확인 명령(✅/❌) 쓰는 법

확인 블록은 결과를 `✅`/`❌` 줄로 판정한다. 출력 전체를 붙일 필요 없이 **❌ 줄만** 마스터에게 알린다.
비밀값(토큰·키·`.env` 값)은 판정 줄에도 출력하지 않는다. 새 터미널을 열 때마다 아래 한 줄을 먼저 붙여넣는다.

```bash
chk() { local m=$1; shift; if "$@" >/dev/null 2>&1; then echo "✅ $m"; else echo "❌ $m"; fi; }
```

## 언제 어느 절을 보나

| 할 일 | 절 |
|---|---|
| 평소 배포 (PR 병합 → 승인) | 12 "평소 배포" |
| 서버 파일(compose, `deploy.sh` 등)이 바뀐 PR을 병합했을 때 — **승인 전에** | 11 |
| 배포 후 앱이 이상하다 / 사이트가 내려갔다 | 12-6 (수동 롤백·복구) |
| 배포 후 상태 점검 | 12-4, 메모리는 12-7 |
| 매일 백업이 되고 있는지 (서버 / Mac) | 13-5 / 14-7 |
| DB를 백업으로 되돌리기, 정기 복원 연습 | 15 |
| 비밀값(세션 비밀값·API 키·SSH 키·age 키·DuckDNS 토큰) 교체, CI 키 정기 교체 | 16 |
| 서버 침해가 의심될 때 | 16-8 |
| 진단할 때 쓰면 안 되는 명령 | 17 |
| AI 모델·한도 바꾸기, AI 사용량 보기 | 18 |
| 인증 앱과 복구 코드를 모두 잃음 / 비밀번호를 잊음 / 검색 결과가 이상함 | 19 |
| 아이폰 홈 화면 앱·PC 브라우저가 새 버전으로 안 바뀜 | 20 |
| GHCR 옛 이미지 정리, 의존성 정기 검사(Dependency audit)가 실패함 | 21 |
| HTTPS 인증서 문제, 외부에서 접속이 안 됨 | 10 |
| DuckDNS IP 갱신 확인 | 4-4 |
| 서버를 처음부터 다시 만들 때 | 1 → 2 → 3 → 4 → 5 → 6 → 12-0 → 12-1 → 12-2 → 12-3 → 12-4 → 13 → 14 (아래 "서버를 새로 만들 때") |

### 서버를 새로 만들 때

1. 1·2절로 서버 기본 상태를 확인·설정한다.
2. 3절(배포 사용자·폴더·저장소 파일) → 4절(DuckDNS) → 5절(CI 키 등록) → 6절(`.env`) 순서로 한다.
3. 12-0으로 서버 요구 사항을 확인한다.
4. 새 서버는 호스트 키가 다르므로 12-1 (b)의 `DEPLOY_KNOWN_HOSTS`를 다시 만들어 넣는다 (CI 키를 새로 만들었으면 `DEPLOY_SSH_KEY`도). 12-2 (c)로 접속을 시험한다.
5. 첫 배포: Actions → Deploy → **가장 최근 성공 실행** → `deploy` 잡 **Re-run this job** → 승인 (새 커밋이 없어도 배포할 수 있다. GitHub은 30일이 지난 실행은 다시 실행하지 못하므로, 그때는 작은 PR을 병합해 새 배포를 만든다). `state/current`가 없으므로 DB 백업 없이 첫 배포로 진행되고, web 컨테이너가 인증서를 새로 받는다.
6. 12-4로 확인한다. 이전 서버의 DB를 옮길 때는 첫 배포 전에 `data/scrap.db`(소유 10001, 600)로 넣는다 (Mac의 암호화 백업에서 옮기는 방법은 15-3).
7. 13절(일일 백업: age 설치·수신자 파일·cron)을 하고, 14-2(백업 수신 키 등록)를 다시 한다. 서버 호스트 키가 바뀌었으므로 Mac의 14-3(호스트 키 파일)도 다시 만든다.

---

## 1. 서버 상태 확인 (읽기 전용)

아무것도 바꾸지 않는 명령이다. 서버를 새로 만들었거나 상태가 의심될 때 실행한다. (최초 구축 때 확인한 결과 기록은 로컬 문서 1절.)

```bash
uname -m                                   # x86_64 → 이미지 플랫폼 linux/amd64 (deploy.yml 설정과 같아야 한다)
swapon --show; df -h /
sudo ss -tlnp | grep -E ':(80|443)\b'      # 운영 중이면 docker-proxy(= scrap-app web)만
sudo docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
sudo docker volume ls
sudo docker images
crontab -l; sudo crontab -l; ls /etc/cron.d/
```

- `uname -m`이 `aarch64`면 `.github/workflows/deploy.yml`의 `platforms`를 `linux/arm64`로 바꿔야 한다 (배포 경로 변경 PR).
- 이 앱의 compose 프로젝트 이름은 `scrap-app`이고 이름 있는 Docker 볼륨을 쓰지 않는다 (데이터는 `/opt/scrap-app` 아래 폴더). 다른 compose 프로젝트와 이름이 겹치지 않게 한다.

---

## 2. 서버 기본 설정 확인 (체크리스트)

한 줄씩 실행해 기대값과 같은지 본다. 다르면 그 줄의 결과를 마스터에게 알린다.

| 확인 | 명령 | 기대값 |
|---|---|---|
| 스왑 | `swapon --show` | 약 2G 스왑 한 줄 |
| Docker 실행·부팅 시 시작 | `systemctl is-active docker; systemctl is-enabled docker` | `active`, `enabled` |
| compose 플러그인 | `docker compose version` | `Docker Compose version v2.x` 이상 (정확한 요구 버전은 12-0) |
| iptables 80/443 | `sudo iptables -S INPUT \| grep -E 'dport (80\|443)'` | 80, 443 ACCEPT 두 줄 (REJECT 규칙이 없는 이미지면 빈 출력도 정상) |
| 규칙 영구 저장 | `sudo grep -cE -- '--dport (80\|443) ' /etc/iptables/rules.v4` | `2` |
| OCI 보안 목록 | PC에서 `curl -sI http://<이름>.duckdns.org \| head -n 1` | 응답이 옴 (운영 중이면 web Caddy의 HTTPS 리다이렉트) |
| 자동 보안 업데이트 | `cat /etc/apt/apt.conf.d/20auto-upgrades` | 두 줄 모두 `"1"` |
| Docker 로그 크기 제한 | `sudo docker info --format '{{.LoggingDriver}}'; sudo cat /etc/docker/daemon.json` | `json-file`, `max-size`·`max-file` 있음 (없으면 2-1) |
| 필요한 도구 | `sudo apt-get install -y git curl dnsutils sqlite3 cron` | 오류 없음 (`dig`·DB 백업에 사용) |

- 자동 보안 업데이트가 꺼져 있으면:
  ```bash
  printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' | sudo tee /etc/apt/apt.conf.d/20auto-upgrades
  ```
- ufw는 쓰지 않는다 (OCI 이미지는 `/etc/iptables/rules.v4`로 관리하고, Docker가 게시한 포트는 ufw를 우회한다).
- OCI 보안 목록(또는 NSG)에는 TCP 80·443 수신 규칙이 있어야 한다 (HTTP/3를 끄므로 UDP 443은 필요 없다).

### 2-1. Docker 로그 크기 제한 (아직 없을 때만)

**무엇을:** 컨테이너 로그를 파일당 10MB × 3개로 제한한다 (디스크 보호). Docker 재시작이 필요하다.

> 운영 중인 서버에서 하면 Docker 재시작 동안 사이트가 잠깐 끊긴다 (컨테이너는 `restart: unless-stopped`로 다시 올라온다). 한가한 시간에 하고 끝나면 12-4로 확인한다.
> 이미 있는 컨테이너에는 적용되지 않고, 다음 배포로 컨테이너가 새로 만들어질 때부터 적용된다.

```bash
if sudo test -e /etc/docker/daemon.json; then
  echo "이미 있음 — 덮어쓰지 않음. 내용:"; sudo cat /etc/docker/daemon.json
else
  sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
  sudo systemctl restart docker
fi
sudo docker info --format '{{.LoggingDriver}}'
```

**확인:** `json-file`. 이미 있던 파일에 `log-opts`가 없으면 그 내용을 마스터에게 알린다.

---

## 3. 배포 사용자 `deploy`, `/opt/scrap-app` 구조, 저장소 파일 설치

### 3-1. `deploy` 사용자

**무엇을:** 비밀번호 없는(잠긴) 배포 전용 사용자를 만들고 docker 그룹에 넣는다.

```bash
getent passwd deploy || sudo useradd --create-home --shell /bin/bash deploy
sudo usermod -aG docker deploy
id deploy
sudo passwd -S deploy
```

**확인:** `id deploy`에 `docker`가 있다. `passwd -S`의 두 번째 칸이 `L`(비밀번호 잠김).

> docker 그룹 구성원은 Docker를 통해 root와 같은 일을 할 수 있다. 그래서 이 사용자에게는 셸을 주지 않는다: 비밀번호는 잠겨 있고 sudo 권한이 없으며, 유일한 SSH 키(5-2)는 `restrict` + 강제 명령으로 **`deploy.sh`만** 실행한다 (셸·포워딩·pty 불가, 인자는 커밋 SHA 형식만 받음). 배포 스크립트·compose 파일은 root 소유라 이 사용자가 고칠 수 없다 (11절).

### 3-2. 디렉터리 구조 (데이터는 서버 폴더에 저장)

**무엇을:** 앱 폴더를 만든다. 데이터는 이름 있는 Docker 볼륨이 아니라 **서버 폴더(bind mount)**에 둔다 — 부트 디스크를 그대로 쓰고, Docker 정리 명령에 지워지지 않으며, 백업이 파일 복사로 끝난다.
compose 파일은 이 폴더들을 **절대경로**로 붙이고, 폴더가 없으면 Docker가 대신 만들지 않고 오류로 멈추게 해 두었다 (`create_host_path: false`). 그래서 여기서 소유권까지 맞춰 만들어야 한다.

```bash
APP_UID=10001     # api 컨테이너 실행 UID (backend/Dockerfile·docker-compose.yml 에서 10001로 고정)

# 스크립트·설정: root 소유 (deploy가 고칠 수 없음)
sudo install -d -m 755 -o root   -g root   /opt/scrap-app /opt/scrap-app/deploy /opt/scrap-app/caddy
# SQLite: api 컨테이너(non-root, APP_UID)만 읽고 쓴다
sudo install -d -m 700 -o "$APP_UID" -g "$APP_UID" /opt/scrap-app/data
# Caddy 인증서·설정: caddy 공식 이미지는 root로 실행 → root 소유, 인증서 개인키가 있으므로 700
sudo install -d -m 700 -o root   -g root   /opt/scrap-app/caddy/data /opt/scrap-app/caddy/config
# 백업·로그·배포 상태·DuckDNS 토큰: deploy 사용자(배포 스크립트·cron)가 쓴다
sudo install -d -m 750 -o deploy -g deploy /opt/scrap-app/backups /opt/scrap-app/logs /opt/scrap-app/state
sudo install -d -m 700 -o deploy -g deploy /opt/scrap-app/duckdns
# 일일 암호화 백업(13절): 백업 폴더는 deploy 전용, age 수신자(공개키) 폴더는 root 소유 (deploy 가 바꿀 수 없음)
sudo install -d -m 700 -o deploy -g deploy /opt/scrap-app/backups/daily
sudo install -d -m 755 -o root   -g root   /opt/scrap-app/age

sudo ls -la /opt/scrap-app /opt/scrap-app/caddy
```

**확인:** 아래 표와 소유자·권한이 같다 (`data`의 소유자는 이름 대신 숫자 `10001`로 보이는 것이 정상).

최종 구조:

```
/opt/scrap-app/                 root     755
├── docker-compose.yml          root     644   운영 구성 (저장소의 docker-compose.yml)
├── .env                        deploy   600   서버에서 직접 작성 (6절)
├── deploy/                     root     755   스크립트 (deploy가 고칠 수 없음)
│   ├── duckdns-update.sh                755
│   ├── deploy.sh                        755   배포 스크립트 (CI 키의 강제 명령, 11절로 설치)
│   ├── rollback.sh                      755   수동 롤백·DB 복원 (사람이 sudo로, 12-6)
│   ├── backup.sh                        755   일일 암호화 백업 (deploy 의 cron, 13절)
│   └── backup-send.sh                   755   암호화 백업 내보내기 (백업 수신 키의 강제 명령, 14절)
├── data/                       APP_UID  700   SQLite → api 컨테이너 /data
├── caddy/                      root     755
│   ├── data/                   root     700   인증서·ACME 계정 → web 컨테이너 /data  (절대 지우지 않음)
│   └── config/                 root     700   Caddy 자동 설정 → web 컨테이너 /config
├── backups/                    deploy   750   predeploy-*.db (600, 배포 직전 자동 백업 — 평문, 최근 14개)
│   └── daily/                  deploy   700   daily-*.db.gz.age (600, 일일 백업 — age 암호화, 최근 14개, 13절)
├── age/                        root     755   recipients.txt (644, age 공개키 — 개인키는 서버에 두지 않는다, 13-2)
├── logs/                       deploy   750   duckdns.log, deploy.log, backup.log
├── state/                      deploy   750   current, previous (운영 중·직전 커밋 SHA), deploy.lock — deploy.sh만 쓴다
├── duckdns/                    deploy   700   token(600), domain
└── src/                        root           저장소 사본 (파일 설치용, 11절)
```

(`deploy/bootstrap/`이 있으면 최초 구축 때만 쓴 임시 구성이다. 운영에는 쓰지 않는다.)

> `data/`는 APP_UID 전용(700)이라 호스트의 `deploy`는 읽지 못한다. 그래서 배포 직전 DB 백업은 `deploy.sh`가 **api 컨테이너 안에서** Python `sqlite3` backup API로 만들고 표준출력으로 꺼내 `backups/`에 저장한다.
>
> `/opt/scrap-app` 아래 폴더(특히 `caddy/data` 인증서, `data` DB)는 Docker 정리 명령(`docker system prune` 등)과 무관하지만, **직접 지우지 않는다.** 인증서 폴더를 지우면 다음 시작 때 새로 발급받아야 하고 발급 횟수 제한에 걸릴 수 있다 (10절).

### 3-3. 저장소 파일 설치

**무엇을:** 공개 저장소를 받아 필요한 파일만 정해진 위치에 복사한다 (서버에서 빌드하지 않는다). 설치 목록은 11절 표와 같다.

```bash
REPO_URL="https://github.com/injae-348/scrap.git"
BRANCH="main"

sudo git clone --depth 1 --branch "$BRANCH" "$REPO_URL" /opt/scrap-app/src

sudo install -m 644 -o root -g root /opt/scrap-app/src/docker-compose.yml       /opt/scrap-app/docker-compose.yml
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/deploy.sh         /opt/scrap-app/deploy/deploy.sh
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/rollback.sh       /opt/scrap-app/deploy/rollback.sh
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/duckdns-update.sh /opt/scrap-app/deploy/duckdns-update.sh
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/backup.sh         /opt/scrap-app/deploy/backup.sh
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/backup-send.sh    /opt/scrap-app/deploy/backup-send.sh
sudo install -m 644 -o root -g root /opt/scrap-app/src/deploy/logrotate.conf    /etc/logrotate.d/scrap-app

sudo ls -la /opt/scrap-app /opt/scrap-app/deploy
sudo logrotate -d /etc/logrotate.d/scrap-app 2>&1 | tail -n 5
```

**확인:** 파일이 위 구조대로 있고, `logrotate -d`(시험 실행) 출력에 `error`가 없다.

> 이후 저장소에서 서버 파일이 바뀌면 **11절(서버 파일 갱신 절차)**을 실행한다. `.env`(6절)를 만든 뒤에는 11-2로 전체를 확인할 수 있다.

---

## 4. DuckDNS IP 자동 갱신

토큰 파일 + 갱신 스크립트 + cron으로 서브도메인이 서버 공인 IP를 가리키게 유지한다.

### 4-1. 서브도메인과 토큰 확인 (브라우저)

1. https://www.duckdns.org 에 로그인한다.
2. 쓸 서브도메인이 없으면 `sub domain` 칸에 이름을 넣고 **add domain**. 이미 있으면 그대로 쓴다.
3. 도메인 목록에서 `<이름>`의 `current ip`가 서버 공인 IP(OCI 콘솔 → 인스턴스 상세 → 공용 IP 주소)인지 본다 (달라도 4-3에서 갱신된다).
4. 페이지 상단의 **token**을 복사한다. **비밀값이다.** 저장소·채팅·스크린샷에 남기지 않는다.

### 4-2. 서브도메인 이름과 토큰을 서버에 저장

```bash
echo '<이름>' | sudo -u deploy tee /opt/scrap-app/duckdns/domain >/dev/null

sudo -u deploy sh -c 'umask 077; cat > /opt/scrap-app/duckdns/token'
# ↑ 실행 후 커서가 멈추면: 토큰을 붙여넣고 → Enter → Ctrl+D

sudo ls -l /opt/scrap-app/duckdns
```

**확인:** `token`이 `-rw------- 1 deploy deploy`, `sudo cat /opt/scrap-app/duckdns/domain`이 `<이름>`. **token 파일은 `cat`으로 출력하지 않는다.**

토큰을 바꿀 때(DuckDNS에서 재발급)도 같은 `cat >` 명령으로 덮어쓴 뒤 4-3을 실행한다.

### 4-3. 갱신 스크립트 시험 실행

```bash
sudo -u deploy /opt/scrap-app/deploy/duckdns-update.sh; echo "exit=$?"
```

**확인:** `... duckdns: OK (<이름>.duckdns.org)` 와 `exit=0`. `실패: ...`면 메시지대로 확인한다 (`KO` 응답 = 토큰 또는 서브도메인이 틀림).

### 4-4. 5분마다 자동 갱신 (cron)

**무엇을:** `deploy` 사용자로 5분마다 실행한다. cron 파일에는 토큰이 없다 (스크립트가 파일에서 읽음).

```bash
sudo tee /etc/cron.d/scrap-app-duckdns >/dev/null <<'EOF'
# DuckDNS IP 갱신 — 토큰은 /opt/scrap-app/duckdns/token 에서 읽는다 (여기에 쓰지 않는다)
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/5 * * * * deploy /opt/scrap-app/deploy/duckdns-update.sh >> /opt/scrap-app/logs/duckdns.log 2>&1
EOF
sudo chmod 644 /etc/cron.d/scrap-app-duckdns
```

**확인 (5분 이상 지난 뒤, 이후에도 수시로):**

```bash
sudo tail -n 3 /opt/scrap-app/logs/duckdns.log                               # OK 줄이 쌓인다
sudo grep -cFf /opt/scrap-app/duckdns/token /opt/scrap-app/logs/duckdns.log  # 0 (로그에 토큰 없음)
dig +short <이름>.duckdns.org @1.1.1.1                                         # 서버 공인 IP
curl -4s https://checkip.amazonaws.com                                        # 위와 같은 IP
```


## 5. CI 전용 SSH 키 등록, SSH 설정 점검

> 강제 명령이 `deploy.sh`를 가리키므로, `deploy.sh`를 설치(3-3 또는 11절)하기 전에는 이 키로 접속하면 실패하는 것이 정상이다. 실제 접속 확인은 12-2 (c)에서 한다.

### 5-1. 키 생성 — **사용자 PC에서** (서버 아님)

**무엇을:** GitHub Actions 전용 키를 새로 만든다. 개인 키를 재사용하지 않는다 (CI 키와 사람의 키를 따로 두어야 한쪽만 교체·폐기할 수 있다). CI가 쓰므로 암호(passphrase)는 비운다.

```bash
# PC 터미널. 저장소 폴더 안에 만들지 않는다.
ssh-keygen -t ed25519 -a 100 -N '' -C 'scrap-ci-deploy' -f ~/.ssh/scrap_ci_deploy
cat ~/.ssh/scrap_ci_deploy.pub
```

**확인:** `ssh-ed25519 AAAA... scrap-ci-deploy` 한 줄. 이 **공개키(.pub)**만 서버에 등록한다.
개인키 `~/.ssh/scrap_ci_deploy`는 GitHub `production` Environment 시크릿 `DEPLOY_SSH_KEY`에 넣는다 (12-1). 그 밖에는 PC에만 두고 저장소·채팅에 붙이지 않는다.

### 5-2. 공개키를 강제 명령과 함께 등록 — 서버에서

**무엇을:** 이 키로 접속하면 **`deploy.sh`만 실행**되고 셸·포워딩·pty가 모두 막히게 등록한다 (`restrict` = 모든 포워딩·pty·X11·`~/.ssh/rc`를 한 번에 끄는 옵션).

> ⚠️ 아래 `tee`는 `authorized_keys`를 **새로 쓴다** (있던 줄이 모두 사라진다). 서버를 새로 만들어 처음 등록할 때만 쓴다. 백업 수신 키(14-2) 줄이 생긴 뒤 CI 키를 바꿀 때는 16-3(줄 추가 → 시험 → 옛 줄만 삭제)을 쓴다.

```bash
PUBKEY='ssh-ed25519 AAAA...여기에 5-1의 .pub 한 줄 전체... scrap-ci-deploy'

sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
printf 'restrict,command="/opt/scrap-app/deploy/deploy.sh" %s\n' "$PUBKEY" \
  | sudo tee /home/deploy/.ssh/authorized_keys >/dev/null
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys

sudo ssh-keygen -lf /home/deploy/.ssh/authorized_keys
sudo cat /home/deploy/.ssh/authorized_keys
```

**확인:** `256 SHA256:... scrap-ci-deploy (ED25519)`가 나오고, 파일 줄이 `restrict,command="/opt/scrap-app/deploy/deploy.sh" ssh-ed25519 ...`로 시작한다.

CI 키를 교체할 때는 16-3을 따른다 (백업 수신 키 줄을 지우지 않도록 줄 단위로 추가·삭제한다).

### 5-3. SSH 비밀번호 로그인이 꺼져 있는지 확인

```bash
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication) '
```

**확인:** `passwordauthentication no`, `kbdinteractiveauthentication no`, `pubkeyauthentication yes`, `permitrootlogin`은 `no` 또는 `without-password`.

다르면 아래를 실행한다. **⚠️ 지금 접속한 창은 닫지 말고**, 새 터미널에서 관리 사용자로 키 로그인이 되는지 확인한 뒤 닫는다.

```bash
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' \
  | sudo tee /etc/ssh/sshd_config.d/00-scrap-hardening.conf
sudo sshd -t && sudo systemctl restart ssh
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin) '
```

(`sshd_config.d`의 파일은 이름 순으로 읽고 **먼저 나온 값이 우선**이라 `00-`으로 시작한다.)

### 5-4. 서버 호스트 키 확인

시크릿 `DEPLOY_KNOWN_HOSTS`에 쓸 값이다. 서버에서 직접 읽으므로 중간자 공격 걱정이 없다. 등록 방법은 12-1 (b).

```bash
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

`known_hosts` 한 줄 형식: `<접속 주소> ssh-ed25519 AAAA...` (`<접속 주소>`는 `DEPLOY_HOST`와 같은 값).

---

## 6. 서버 `.env` 작성

**무엇을:** 저장소의 `.env.example`을 복사해 서버에서 직접 채운다. 권한 600, 소유자 `deploy`. GitHub·저장소·채팅에는 넣지 않는다.

```bash
sudo install -m 600 -o deploy -g deploy /opt/scrap-app/src/.env.example /opt/scrap-app/.env
openssl rand -hex 32        # 출력값을 SESSION_SECRET 에 붙여넣는다
sudo -u deploy nano /opt/scrap-app/.env
```

| 이름 | 넣을 값 |
|---|---|
| `SITE_DOMAIN` | `<이름>.duckdns.org` |
| `SESSION_SECRET` | 위 `openssl rand -hex 32` 출력 |
| `IMAGE_TAG` | 예시값(`0000...`) 그대로. **바꾸지 않는다** (실제 태그는 `deploy.sh`가 넘긴다) |
| `ACME_CA` | 주석 그대로 (10절에서 시험할 때만 사용) |
| 그 밖의 항목 | `.env.example`의 각 항목 주석대로 |

nano 저장: Ctrl+O → Enter, 종료: Ctrl+X.

**원칙**

- 이미 있는 `.env`를 고칠 때는 위 `install` 줄을 다시 실행하지 않는다 (덮어쓴다). `sudo -u deploy nano /opt/scrap-app/.env`만 쓴다.
- `.env.example`에 새 항목이 생기면(PR 설명에 적힌다) 서버 `.env`에 그 줄을 직접 추가한다.
- 값은 명령줄(`echo ... >>`)로 쓰지 않고 편집기로 붙여넣는다. 따옴표·공백 없이 한 줄로.
- `.env` 변경은 다음 배포 때 컨테이너가 다시 만들어지면서 반영된다. 기다릴 수 없으면 `sudo /opt/scrap-app/deploy/rollback.sh current`(같은 버전을 다시 올림, 12-6)로 반영한다.
- 값을 화면에 출력해 확인하지 않는다. 확인은 아래처럼 형식·권한만 본다.

**확인:**

```bash
E=/opt/scrap-app/.env
chk ".env deploy 600"                           test "$(sudo stat -c '%U %a' $E)" = "deploy 600"
chk "SITE_DOMAIN 한 줄, 소문자 도메인 형식"        sh -c "sudo grep -E '^SITE_DOMAIN=' $E | grep -qxE 'SITE_DOMAIN=([a-z0-9-]+\.)+[a-z]{2,}' && [ \$(sudo grep -c '^SITE_DOMAIN=' $E) = 1 ]"
chk "SESSION_SECRET 자리표시자 아님, 32자 이상"   sh -c "sudo grep -E '^SESSION_SECRET=' $E | grep -v 'change-me' | grep -qE '^SESSION_SECRET=.{32,}$'"
```

---

## 7. (로컬 문서로 이동)

최초 구축 때 한 번 한 작업(같은 서버의 기존 서비스 정리)이라 로컬 문서 `deploy/README.local.md` 7절로 옮겼다. 다시 할 일이 없다. 그중 일반 설정인 Docker 로그 크기 제한은 2-1에 있다.

## 8. (로컬 문서로 이동)

최초 구축 때 임시 구성(`deploy/bootstrap/`)으로 HTTPS 발급을 먼저 확인한 작업이다. 로컬 문서 8절로 옮겼다.
서버를 새로 만들 때는 필요 없다 — GHCR에 이미지가 있으므로 첫 배포("서버를 새로 만들 때" 5번)에서 web 컨테이너가 인증서를 받는다. 발급이 안 되면 10절.

## 9. (로컬 문서로 이동)

최초 구축 때 한 일회성 정리 작업이다. 로컬 문서 9절로 옮겼다.

---

## 10. 문제 해결: 인증서 발급·갱신 실패, 외부 접속 불가

Caddy는 인증서를 자동으로 받고 만료 전에 자동 갱신한다. 인증서는 `/opt/scrap-app/caddy/data`에 남으므로 재배포해도 다시 받지 않는다.

인증서 상태 (PC에서):

```bash
H='<이름>.duckdns.org'
curl -sI "http://$H" | head -n 3          # 308 → https://
curl -sI "https://$H" | head -n 5         # HTTP/2 200, strict-transport-security 헤더
echo | openssl s_client -connect "$H:443" -servername "$H" 2>/dev/null \
  | openssl x509 -noout -issuer -dates     # Let's Encrypt, (STAGING) 없음, notAfter 가 미래
```

web 로그 (서버):

```bash
sudo docker compose -f /opt/scrap-app/docker-compose.yml logs --tail 100 web
```

차례대로 확인한다.

1. **DNS:** `dig +short <이름>.duckdns.org @1.1.1.1`가 서버 공인 IP인가? 아니면 4-3(스크립트)을 다시 실행하고 몇 분 기다린다. 4-4의 `duckdns.log`에 실패가 쌓였는지도 본다.
2. **포트:** `sudo ss -tlnp | grep -E ':(80|443)\b'`에 `docker-proxy` 말고 다른 프로세스(systemd caddy·nginx 등)가 있으면 그것을 멈춘다. 컨테이너 시작 때 `port is already allocated`가 나오면 다른 컨테이너가 80/443을 잡고 있다 → `sudo docker ps`로 찾아 멈춘다.
3. **OCI 보안 목록 / NSG:** TCP 80·443 수신 규칙이 있는가?
4. **서버 iptables:** `sudo iptables -L INPUT -n -v --line-numbers`에서 80/443 ACCEPT가 REJECT보다 위인가? `sudo iptables -S FORWARD | head`에서 Docker 체인(`DOCKER-USER` 등)이 REJECT보다 위인가? (Docker가 게시한 포트는 FORWARD 체인을 지난다. 아니면 `sudo systemctl restart docker`로 Docker가 자기 규칙을 다시 맨 위에 넣게 한다 — 사이트가 잠깐 끊긴다.)
5. **바깥에서 80번 (PC에서):** `curl -sI http://<이름>.duckdns.org` — 시간 초과면 3·4번 문제, 응답이 오면 방화벽은 정상.
6. **Let's Encrypt 발급 제한:** 로그에 `rateLimited` / `too many`가 보이면 제한에 걸린 것이다. 같은 이름의 인증서는 일주일에 5번, 검증 실패는 시간당 5번까지다 (같은 도메인으로 다른 서버에서 받은 것도 횟수에 포함된다). 이때는 **재배포·재시작을 반복하지 말고**, 아래 staging으로 원인을 고친 뒤 로그에 나온 대기 시간이 지나고 다시 한다.
   (`duckdns.org`는 공개 접미사 목록에 있어 다른 DuckDNS 사용자와 제한을 공유하지 않는다.)

### staging CA로 시험하기 (발급 제한 걱정 없이)

> 시험하는 동안 사이트는 브라우저가 신뢰하지 않는 staging 인증서를 쓸 수 있다 (경고가 정상). 원인을 찾을 때만 하고, 끝나면 반드시 되돌린다.

```bash
sudo -u deploy nano /opt/scrap-app/.env
#   ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory   ← 줄 앞의 # 를 지운다
sudo /opt/scrap-app/deploy/rollback.sh current      # 같은 버전을 다시 올린다 → web 이 바뀐 ACME_CA 로 다시 만들어진다
sudo docker compose -f /opt/scrap-app/docker-compose.yml logs -f web
```

- `rollback.sh`의 마지막 헬스체크는 **❌로 끝나는 것이 정상**이다 (staging 인증서는 검증을 통과하지 않는다. state는 바뀌지 않는다).
- 판정은 web 로그의 `certificate obtained successfully`와 PC의 `openssl ... -issuer`에 나오는 `(STAGING)`으로 한다. Ctrl+C로 로그 보기를 끝낸다.
- 성공하면 `.env`의 `ACME_CA` 줄을 **다시 주석 처리**하고 `sudo /opt/scrap-app/deploy/rollback.sh current`를 다시 실행한다 → 운영 인증서를 받고 헬스체크가 ✅로 끝나야 한다 (CA별로 `/opt/scrap-app/caddy/data/caddy/certificates/<CA 이름>/`에 따로 저장되어 섞이지 않는다).

그래도 안 되면 로그 100줄과 1·2·4번 결과를 (IP·도메인은 가리고) 마스터에게 붙인다.

---


## 11. 서버 파일 갱신 절차 (저장소의 서버 파일이 바뀌었을 때)

**왜 사람이 하나:** 서버 파일은 root 소유이고 `deploy` 사용자에게는 sudo가 없다. 배포(`deploy.sh`)는 **이미지 태그만** 바꾸고 이 파일들을 고치지 않는다. 그래서 CI 키가 새어도 서버 구성·배포 스크립트는 바꿀 수 없다.

| 서버 파일 | 설치 위치 | 소유·권한 |
|---|---|---|
| `docker-compose.yml` | `/opt/scrap-app/docker-compose.yml` | root 644 |
| `deploy/deploy.sh` | `/opt/scrap-app/deploy/deploy.sh` | root 755 |
| `deploy/rollback.sh` | `/opt/scrap-app/deploy/rollback.sh` | root 755 |
| `deploy/duckdns-update.sh` | `/opt/scrap-app/deploy/duckdns-update.sh` | root 755 |
| `deploy/backup.sh` | `/opt/scrap-app/deploy/backup.sh` | root 755 |
| `deploy/backup-send.sh` | `/opt/scrap-app/deploy/backup-send.sh` | root 755 |
| `deploy/logrotate.conf` | `/etc/logrotate.d/scrap-app` | root 644 |

(`deploy/scan-dist.sh`와 `deploy/mac/`은 서버에 설치하지 않는다 — 각각 CI와 사용자 Mac에서 쓴다.)

**규칙**

- 위 파일을 바꾸는 PR은 설명 맨 위에 **"🖐 서버 파일 갱신 필요"**를 표시한다 (`deploy.yml`·`deploy.sh`를 바꾸면 "⚠️ 배포 경로 변경"도 함께).
- 그런 PR을 병합하면 Actions의 Deploy 실행이 승인 대기(Waiting)에서 멈춘다. **승인 전에** 아래 11-1, 11-2를 실행한다.
- 이미지 롤백(태그 되돌리기)은 compose 파일을 되돌리지 않는다. compose를 바꿀 때는 직전 이미지와도 동작하게 만든다.

### 11-1. 갱신 (몇 번을 실행해도 같은 결과)

```bash
sudo git -C /opt/scrap-app/src pull --ff-only

sudo install -m 644 -o root -g root /opt/scrap-app/src/docker-compose.yml       /opt/scrap-app/docker-compose.yml
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/deploy.sh         /opt/scrap-app/deploy/deploy.sh
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/rollback.sh       /opt/scrap-app/deploy/rollback.sh
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/duckdns-update.sh /opt/scrap-app/deploy/duckdns-update.sh
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/backup.sh         /opt/scrap-app/deploy/backup.sh
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/backup-send.sh    /opt/scrap-app/deploy/backup-send.sh
sudo install -m 644 -o root -g root /opt/scrap-app/src/deploy/logrotate.conf    /etc/logrotate.d/scrap-app
# 배포 상태 폴더 (이미 있으면 그대로)
sudo install -d -m 750 -o deploy -g deploy /opt/scrap-app/state
```

### 11-2. 확인

```bash
S=/opt/scrap-app/src; A=/opt/scrap-app
chk "저장소 사본이 main 브랜치"           test "$(sudo git -C $S rev-parse --abbrev-ref HEAD)" = main
chk "저장소 사본이 origin/main 과 같음"    test "$(sudo git -C $S rev-parse HEAD)" = "$(sudo git -C $S rev-parse origin/main)"
chk "compose 설치본 = 저장소"             sudo cmp -s $S/docker-compose.yml $A/docker-compose.yml
chk "deploy.sh 설치본 = 저장소"           sudo cmp -s $S/deploy/deploy.sh $A/deploy/deploy.sh
chk "rollback.sh 설치본 = 저장소"         sudo cmp -s $S/deploy/rollback.sh $A/deploy/rollback.sh
chk "duckdns-update.sh 설치본 = 저장소"   sudo cmp -s $S/deploy/duckdns-update.sh $A/deploy/duckdns-update.sh
chk "backup.sh 설치본 = 저장소"           sudo cmp -s $S/deploy/backup.sh $A/deploy/backup.sh
chk "backup-send.sh 설치본 = 저장소"      sudo cmp -s $S/deploy/backup-send.sh $A/deploy/backup-send.sh
chk "logrotate 설치본 = 저장소"           sudo cmp -s $S/deploy/logrotate.conf /etc/logrotate.d/scrap-app
chk "compose root 644"                   test "$(sudo stat -c '%U %a' $A/docker-compose.yml)" = "root 644"
chk "deploy.sh root 755"                 test "$(sudo stat -c '%U %a' $A/deploy/deploy.sh)" = "root 755"
chk "rollback.sh root 755"               test "$(sudo stat -c '%U %a' $A/deploy/rollback.sh)" = "root 755"
chk "backup.sh root 755"                 test "$(sudo stat -c '%U %a' $A/deploy/backup.sh)" = "root 755"
chk "backup-send.sh root 755"            test "$(sudo stat -c '%U %a' $A/deploy/backup-send.sh)" = "root 755"
chk "state/ deploy 750"                  test "$(sudo stat -c '%U %a' $A/state)" = "deploy 750"
chk "deploy.sh 문법"                      bash -n $A/deploy/deploy.sh
chk "rollback.sh 문법"                    bash -n $A/deploy/rollback.sh
chk "backup.sh 문법"                      bash -n $A/deploy/backup.sh
chk "backup-send.sh 문법"                 bash -n $A/deploy/backup-send.sh
chk "compose 구성 유효 (deploy 권한으로)"  sudo -u deploy -H docker compose -f $A/docker-compose.yml config -q
chk "logrotate 설정 유효"                 sudo logrotate -d /etc/logrotate.d/scrap-app
```

❌가 있으면 그 줄을 마스터에게 알린다. (`compose 구성 유효`는 `.env`를 읽지만 값은 출력하지 않는다.)

compose 파일이 바뀐 PR이면 승인·배포가 끝난 뒤 12-4와 12-7로 확인한다 (컨테이너가 새 설정으로 다시 만들어진다).

---

## 12. 자동 배포: 승인 · 설정 · 확인 · 수동 롤백

흐름: `main` 병합 → Actions **Deploy** 실행: `test`(검사 재실행) → `build`(이미지 2개 GHCR push, 태그 = 커밋 SHA) → **승인 대기** → 승인하면 `deploy`가 `ssh deploy@서버 <SHA>` → 서버의 `deploy.sh`가 DB 백업 → pull → 교체 → `https://<이름>.duckdns.org/api/health` 확인 → 실패 시 직전 버전으로 자동 롤백.

배포는 한 번에 하나만 돈다. 승인 대기 중에 다른 PR이 병합되면 새 실행은 기다리고, 대기 중인 실행이 여럿이면 GitHub이 가장 최근 것만 남긴다 (최신 `main`이 배포된다).

### 평소 배포 (PR을 병합할 때마다)

1. PR을 병합한다 (사용자).
2. Actions → **Deploy** 실행에서 `test`, `build`가 ✅이고 `deploy`가 **Waiting**(승인 대기)인지 본다.
3. PR 설명 맨 위에 **"🖐 서버 파일 갱신 필요"**가 있으면 **승인 전에** 서버에서 11절(11-1 갱신, 11-2 확인)을 실행한다. `.env`에 새 항목이 필요하다고 적혀 있으면 6절대로 넣는다.
4. **Review deployments** → `production` 체크 → **Approve and deploy**.
5. `deploy` 잡 로그 끝에 `배포 성공`과 `외부 헬스체크 통과`가 나오면 끝이다. 자세히 보려면 12-4.
6. 실패하면 `deploy.sh`가 직전 버전으로 자동 롤백한다. 잡 로그의 `실패:` 줄과 12-3 (c) 아래의 로그 명령 결과를 마스터에게 알린다. 헬스체크는 통과했지만 앱이 이상하면 12-6.

아래 12-0 ~ 12-5는 **처음 구성할 때**(서버·저장소·Environment를 새로 만들 때) 쓰는 설정·확인 절차다. 평소에는 12-4(확인)와 12-6(롤백)만 쓴다.

### 12-0. 서버 요구 사항 확인 (읽기 전용)

```bash
chk "Docker Engine 25 이상 (healthcheck start_interval)" sh -c 'v=$(sudo docker version -f "{{.Server.Version}}"); [ "${v%%.*}" -ge 25 ]'
chk "Docker Compose 2.24 이상 (env_file path/required)"  sh -c 'v=$(sudo docker compose version --short); v=${v#v}; M=${v%%.*}; r=${v#*.}; m=${r%%.*}; [ "$M" -gt 2 ] || { [ "$M" -eq 2 ] && [ "$m" -ge 24 ]; }'
chk "curl·flock 있음"                  sh -c 'command -v curl && command -v flock'
chk "deploy 가 docker 그룹"            sh -c 'id -nG deploy | grep -qw docker'
chk "data/ 소유 10001, 700"            test "$(sudo stat -c '%u %a' /opt/scrap-app/data)" = "10001 700"
chk "caddy/data root 700"              test "$(sudo stat -c '%U %a' /opt/scrap-app/caddy/data)" = "root 700"
```

첫 배포 전(사이트가 아직 없는 서버)에는 하나 더: `chk "80/443 비어 있음" sh -c '! sudo ss -tln | grep -qE ":(80|443)\b"'`

### 12-1. GitHub `production` Environment와 시크릿

`deploy.yml`이 있는 커밋이 처음 `main`에 들어가기 **전에** 만든다 (Environment가 없는 채로 배포 잡이 시작되면 GitHub이 승인 규칙 없는 빈 Environment를 자동으로 만들어 버린다).

**(a) Environment 만들기** — 저장소 → Settings → Environments → **New environment** → 이름 `production` → Configure environment

- **Required reviewers**: 체크하고 본인 추가. **Prevent self-review는 체크하지 않는다** (혼자 쓰는 저장소라 체크하면 본인이 승인할 수 없다).
- **Deployment branches and tags**: `Selected branches and tags` → Add deployment branch or tag rule → `main` 만 추가.
- Save protection rules.

**(b) 시크릿 값 준비** — 4개 모두 **Environment secrets**(production 화면 아래쪽)에 넣는다. Repository secrets에는 넣지 않는다 (승인 전에는 읽히지 않게).

| 이름 | 값 |
|---|---|
| `DEPLOY_HOST` | `<이름>.duckdns.org` — IP가 아니라 **도메인**으로 (배포 후 외부 헬스체크에도 쓰고, 아래 known_hosts의 주소와 같아야 한다) |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | 5-1에서 만든 **개인키** `~/.ssh/scrap_ci_deploy` 파일 내용 전체 (`-----BEGIN ...`부터 `-----END ...-----`까지) |
| `DEPLOY_KNOWN_HOSTS` | 서버 호스트 키 한 줄: `<이름>.duckdns.org ssh-ed25519 AAAA...` (아래 명령으로 만든다) |

`DEPLOY_SSH_KEY` — PC(Mac)에서 화면에 띄우지 않고 클립보드로 복사:

```bash
pbcopy < ~/.ssh/scrap_ci_deploy     # GitHub 입력칸에 붙여넣고 저장한 뒤
pbcopy < /dev/null                  # 클립보드 비우기
```

`DEPLOY_KNOWN_HOSTS` — 서버에서 (호스트 **공개**키라 화면에 나와도 괜찮다. 저장소·채팅에는 붙이지 않는다):

```bash
D=$(sudo cat /opt/scrap-app/duckdns/domain); D="${D%.duckdns.org}.duckdns.org"
printf '%s %s\n' "$D" "$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
```

출력 한 줄을 그대로 `DEPLOY_KNOWN_HOSTS`에 넣고, PC 메모장 등에 잠시 둔다 (12-2 (c)에서 쓴다).

**(c) 확인 (PC, `gh` CLI가 로그인돼 있을 때)** — 없으면 화면에서 위 항목을 눈으로 확인한다.

```bash
R=injae-348/scrap
chk "production: 필수 승인자 있음"   sh -c "gh api repos/$R/environments/production --jq '[.protection_rules[].type] | index(\"required_reviewers\") != null' | grep -qx true"
chk "production: 배포 브랜치 제한"   sh -c "gh api repos/$R/environments/production --jq '.deployment_branch_policy.custom_branch_policies' | grep -qx true"
chk "production: 브랜치 규칙 = main" sh -c "gh api repos/$R/environments/production/deployment-branch-policies --jq '[.branch_policies[].name] == [\"main\"]' | grep -qx true"
chk "production: 시크릿 4개"         sh -c "gh api repos/$R/environments/production/secrets --jq '[.secrets[].name | select(test(\"^DEPLOY_(HOST|USER|SSH_KEY|KNOWN_HOSTS)\$\"))] | length' | grep -qx 4"
chk "Repository 시크릿에 DEPLOY_* 없음" sh -c "gh api repos/$R/actions/secrets --jq '[.secrets[].name | select(startswith(\"DEPLOY_\"))] | length' | grep -qx 0"
```

### 12-2. 시크릿·CI 키 접속 확인

시크릿 4개는 `production` Environment에만 있다 (값 준비는 12-1 (b)). 배포 잡이 "시크릿 ... 이(가) 비어 있음"으로 실패하면 12-1 (b)로 다시 넣고 12-1 (c)로 확인한다. 서버를 새로 만들었거나 CI 키·호스트 키를 바꾼 뒤에는 첫 승인 **전에** 아래로 접속을 시험한다.

**(a)** 서버에 `deploy.sh`가 설치돼 있어야 한다 (3-3 또는 11절, 11-2 확인).

**(b)** 시크릿은 12-1 (b)대로 들어가 있어야 한다.

**(c)** PC에서 GitHub에 넣은 값과 같은 값으로 CI 키 접속을 시험한다. 잘못된 요청(`ping`)을 보내므로 `deploy.sh`가 **거부만 하고 아무것도 바꾸지 않는다.**

```bash
H='<이름>.duckdns.org'
KH='<12-1 (b)에서 만든 DEPLOY_KNOWN_HOSTS 한 줄 그대로>'
T=$(mktemp -d)
printf '%s\n' "$KH" > "$T/kh"
ssh -T -n -i ~/.ssh/scrap_ci_deploy -o IdentitiesOnly=yes -o BatchMode=yes \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$T/kh" \
    "deploy@$H" ping > "$T/out" 2>&1; echo "rc=$?" >> "$T/out"
chk "known_hosts 값으로 호스트 확인 통과"   sh -c "! grep -q 'Host key verification failed' $T/out"
chk "CI 키 로그인 + 강제 명령(deploy.sh) 실행" grep -q '거부' "$T/out"
chk "deploy.sh 가 잘못된 요청을 코드 2로 거부" grep -qx 'rc=2' "$T/out"
rm -rf "$T"
```

서버에서도 한 줄 확인: `chk "deploy.log 에 거부 기록" sh -c "sudo tail -n 3 /opt/scrap-app/logs/deploy.log | grep -q 거부"`

### 12-3. GHCR 패키지 공개 확인 → 승인

서버는 `docker login` 없이 이미지를 받는다. 그래서 GHCR 패키지 2개(`scrap-api`, `scrap-web`)가 **Public**이어야 한다. `deploy.sh`가 "이미지 pull 실패"로 끝나면 여기부터 본다.

**(a) 이미지가 올라갔는지** — Actions의 Deploy 실행에서 `test`, `build`가 ✅이고 `deploy`가 Waiting이다.

**(b) ⚠️ 패키지가 Private이면 Public으로 전환 (되돌릴 수 없다)** — GitHub은 공개로 바꾼 패키지를 다시 비공개로 돌릴 수 없다. 이미지에는 앱 코드와 라이브러리만 들어 있고 `.env`·DB·`.git`은 `.dockerignore`로 막혀 있다 (결정 7). 패키지는 처음 push될 때 Private으로 생기므로, 저장소를 새로 만들었거나 패키지를 지웠을 때만 해당한다.

1. GitHub 오른쪽 위 프로필 → **Your profile** → **Packages** 탭 → `scrap-api`
2. 패키지 화면 오른쪽에 저장소 `scrap`이 연결돼 있는지 본다 (이미지 라벨 `org.opencontainers.image.source`로 자동 연결된다). **Package settings** → "Manage Actions access"에 `scrap` 저장소가 있는지 본다.
3. 같은 Package settings 아래 **Danger Zone → Change visibility → Public** → 패키지 이름을 입력해 확인
4. `scrap-web`도 1~3을 반복한다.

서버에서 로그인 없이 받을 수 있는지 확인 (`deploy` 사용자, 내려받지 않고 목록만 조회):

```bash
SHA=$(git ls-remote https://github.com/injae-348/scrap.git refs/heads/main | cut -f1)   # main 최신 = 이번 배포 커밋
echo "이번 배포 커밋: ${SHA:0:7}  ← Actions 실행 화면의 커밋과 같은지 눈으로 확인"
for r in scrap-api scrap-web; do
  chk "$r 공개 이미지 조회 (로그인 없이)" sudo -u deploy -H docker manifest inspect "ghcr.io/injae-348/$r:$SHA"
done
```

**(c) 승인** — Actions → 그 Deploy 실행 → **Review deployments** → `production` 체크 → **Approve and deploy**. `deploy` 잡 로그 끝에 `배포 성공`과 `외부 헬스체크 통과`가 나온다 (새 서버의 첫 배포는 이미지 pull 때문에 2~5분).

실패하면 잡 로그의 `실패:` 줄과 아래를 마스터에게 알린다:

```bash
sudo tail -n 40 /opt/scrap-app/logs/deploy.log
sudo docker compose -f /opt/scrap-app/docker-compose.yml ps -a
sudo docker compose -f /opt/scrap-app/docker-compose.yml logs --tail 60 api web
```

(새 서버의 첫 배포는 되돌릴 직전 버전이 없어서 실패해도 컨테이너를 그대로 둔다 — 로그를 보기 위해서다. 로그에 도메인이 보이면 가리고 붙인다.)

### 12-4. 배포 후 확인

서버:

```bash
A=/opt/scrap-app
SHA=$(sudo cat $A/state/current)
D=$(sudo sed -nE 's/^[[:space:]]*SITE_DOMAIN[[:space:]]*=[[:space:]]*["'"'"']?([^"'"'"' #]+).*/\1/p' $A/.env | tail -n 1)   # 출력하지 않는다

chk ".env 에서 SITE_DOMAIN 읽음"            test -n "$D"
chk "state/current 가 커밋 SHA 형식"         sh -c "echo '$SHA' | grep -qxE '[0-9a-f]{40}'"
echo "운영 중 커밋: ${SHA:0:7}  ← Actions 에서 승인한 실행의 커밋과 같은지 눈으로 확인"
chk "api healthy"                         sh -c "sudo docker inspect -f '{{.State.Health.Status}}' scrap-app-api-1 | grep -qx healthy"
chk "web 실행 중"                          sh -c "sudo docker inspect -f '{{.State.Running}}' scrap-app-web-1 | grep -qx true"
chk "실행 중 이미지 = state/current"        sh -c "sudo docker inspect -f '{{.Config.Image}}' scrap-app-api-1 | grep -q ':$SHA\$'"
chk "https health 200 (서버 → 로컬 Caddy)"  curl -fs -o /dev/null --resolve "$D:443:127.0.0.1" "https://$D/api/health"
chk "api 실행 UID 10001"                   sh -c "sudo docker exec scrap-app-api-1 id -u | grep -qx 10001"
chk "DB 파일 소유 10001 (DB가 있으면)"       sh -c "! sudo test -e $A/data/scrap.db || [ \$(sudo stat -c %u $A/data/scrap.db) = 10001 ]"
chk "배포 로그에 성공 기록"                  sh -c "sudo tail -n 40 $A/logs/deploy.log | grep -q '배포 성공'"
chk "배포 로그에 실제 도메인 없음"            sh -c "! sudo grep -qF -- '$D' $A/logs/deploy.log"
chk "deploy.log 권한 (다른 사용자 읽기 불가)"  sh -c "sudo stat -c %a $A/logs/deploy.log | grep -qE '^6[04]0$'"
for c in scrap-app-api-1 scrap-app-web-1; do
  chk "$c 로그 상한 적용 (json-file 10m×3)" sh -c "sudo docker inspect -f '{{.HostConfig.LogConfig.Type}} {{index .HostConfig.LogConfig.Config \"max-size\"}} {{index .HostConfig.LogConfig.Config \"max-file\"}}' $c | grep -qx 'json-file 10m 3'"
done
for c in scrap-app-api-1 scrap-app-web-1; do
  chk "$c 메모리 한도의 80% 미만"            sh -c "sudo docker stats --no-stream --format '{{.MemPerc}}' $c | awk '{exit !(\$1+0 < 80)}'"
done
chk "서버 여유 메모리(available) 150MB 이상" sh -c "free -m | awk '/^Mem:/{exit !(\$7 >= 150)}'"
chk "디스크 여유 2GB 이상"                   sh -c "df -Pm / | awk 'NR==2{exit !(\$4 >= 2048)}'"
```

PC (브라우저와 터미널):

- 시크릿 창에서 `https://<이름>.duckdns.org` → 앱 화면이 나오고 주소창에 자물쇠가 있다.

```bash
H='<이름>.duckdns.org'
chk "외부 /api/health 200"               curl -fs -o /dev/null "https://$H/api/health"
chk "SPA 경로 새로고침도 200"              curl -fs -o /dev/null "https://$H/settings"
chk "http → https 리다이렉트"             sh -c "curl -s -o /dev/null -w '%{http_code}' http://$H/ | grep -qE '^30[18]$'"
chk "보안 헤더(CSP) 있음"                  sh -c "curl -sI https://$H/ | grep -qi '^content-security-policy:'"
chk "Server 헤더 숨김"                    sh -c "! curl -sI https://$H/api/health | grep -qi '^server:'"
chk "COOP 헤더 same-origin"               sh -c "curl -sI https://$H/ | grep -qi '^cross-origin-opener-policy: same-origin'"
chk "CORP 헤더 same-origin"               sh -c "curl -sI https://$H/ | grep -qi '^cross-origin-resource-policy: same-origin'"
```

### 12-5. 필수 검사 설정 (GitHub)

CI가 한 번 돌아 `backend`(와 `images`) 검사 이름이 생긴 뒤에 한다.

저장소 → Settings → Rules → Rulesets → `rule` → **Require status checks to pass** → Add checks → `frontend`, `backend` → Save changes.
(`images`는 Dockerfile이 빌드되는지 보는 검사다. 이 저장소는 `frontend`·`backend`·`images` 3개를 모두 필수로 둔다.)

```bash
R=injae-348/scrap
id=$(gh api repos/$R/rulesets --jq '.[] | select(.name=="rule") | .id')
chk "필수 검사에 frontend·backend" sh -c "gh api repos/$R/rulesets/$id --jq '[.rules[] | select(.type==\"required_status_checks\") | .parameters.required_status_checks[].context] | (index(\"frontend\") != null and index(\"backend\") != null)' | grep -qx true"
```

### 12-6. 수동 롤백·복구 (긴급할 때 사람만)

평소 배포·롤백은 CI가 한다. 자동 롤백: 헬스체크가 실패하면 `deploy.sh`가 배포 직전 운영 버전(`state/current`)으로 되돌리고 실패로 끝난다 (상태 파일은 그대로).
아래는 **헬스체크는 통과했지만 앱이 잘못 동작할 때**, **자동 롤백까지 실패했을 때**, **`deploy.sh`가 "state 기록 실패"로 끝났을 때**만 쓴다.

**방법 A (권장, GitHub이 될 때)** — Actions → Deploy → **되돌릴 버전의 예전 성공 실행** → `deploy` 잡의 **Re-run this job** → 승인. 같은 `deploy.sh` 경로(백업·헬스체크·상태 기록)를 그대로 탄다. GitHub은 30일이 지난 실행은 다시 실행하지 못하고, GHCR에는 최근 30개 빌드와 최근 배포 버전만 남는다(21절) → 그보다 오래된 버전은 방법 B (`previous`) 또는 되돌리는 PR로 한다.

**방법 B (서버에서 직접) — `rollback.sh`**

`/opt/scrap-app/deploy/rollback.sh`(root 755, 11절로 설치)가 처음부터 끝까지 `deploy.sh`와 **같은 잠금**을 쥐고 실행한다 (CI 배포와 겹치지 않는다). 단계마다 ✅/❌ 줄을 출력하고, **❌가 나오면 그 자리에서 멈춘다** (뒤 단계로 넘어가지 않는다). 도메인·`.env` 값은 출력하지 않는다. 같은 줄이 `logs/deploy.log`에도 남는다.

(1) 상태 보기 — 아무것도 바꾸지 않는다:

```bash
sudo /opt/scrap-app/deploy/rollback.sh
```

(2) 상황에 맞는 명령 하나를 고른다:

| 상황 | 명령 | state |
|---|---|---|
| 배포는 성공했는데 앱이 이상하다 | `sudo /opt/scrap-app/deploy/rollback.sh previous` | 성공하면 current ↔ previous 교환 (실제 운영 버전에 맞춤) |
| 자동 롤백까지 실패해 사이트가 내려가 있다 | `sudo /opt/scrap-app/deploy/rollback.sh current` | 그대로 (실패한 배포는 기록되지 않았으므로 current가 마지막 정상 버전) |
| `deploy.sh`가 "state 기록 실패"로 끝났다 (새 버전은 정상 운영 중) | 로그의 `운영 중: <SHA>`를 확인하고 마스터에게 알린다. state 디렉터리 권한(11-2 `state/ deploy 750`)부터 확인 | 사람이 맞춘다 |

끝 줄이 `✅ ...`와 `완료 — 운영 중: <SHA>`면 성공이다. ❌ 줄이 나오면 그 줄만 마스터에게 알린다.

**⚠️ DB까지 되돌리기 (새 버전이 DB 구조를 바꿔 옛 버전이 못 읽을 때, 또는 DB 내용이 망가졌을 때)** — 그 백업 이후 저장한 스크랩은 사라진다. 위 명령 뒤에 `--restore-db <백업 파일 이름>`을 붙인다. 백업 이름은 (1)의 `백업:` 줄 또는 `sudo ls -l /opt/scrap-app/backups/`에서 고른다 (`predeploy-<UTC 시각>-<그때 운영 중이던 SHA 앞 12자>.db`).

```bash
sudo /opt/scrap-app/deploy/rollback.sh previous --restore-db predeploy-<시각>-<sha>.db
```

스크립트가 하는 순서: 백업 파일 이름·형식 확인 → api 정지 → **현재 DB(`scrap.db`, `-wal`, `-shm`)를 `/root/db-before-restore-<시각>/`에 복사하고 원본과 내용 비교** → 일치가 확인된 뒤에만 `-wal`/`-shm` 삭제 + 백업 설치(10001, 600) → 컨테이너 교체 → 헬스체크 → state 갱신.
보존 단계에서 실패하면 DB는 건드리지 않은 채 멈춘다 (api는 정지 상태이므로 `sudo /opt/scrap-app/deploy/rollback.sh current`로 다시 올린다).

복원 후 확인:

```bash
chk "복원 전 DB 보존본 있음" sh -c 'sudo sh -c "ls -d /root/db-before-restore-*/scrap.db" | grep -q .'
chk "data/scrap.db 소유 10001, 600" test "$(sudo stat -c '%u %a' /opt/scrap-app/data/scrap.db)" = "10001 600"
chk "api healthy" sh -c "sudo docker inspect -f '{{.State.Health.Status}}' scrap-app-api-1 | grep -qx healthy"
```

확인이 끝나면 15-4의 정리(보존본 삭제)를 한다. 일일 암호화 백업(Mac 보관본)에서 복원하는 방법과 복원 연습은 15절.

### 12-7. 배포 후 메모리 확인

**언제:** compose가 바뀐 배포, AI·의존성이 크게 바뀐 배포 뒤. 평소에도 가끔. 메모리 한도(`docker-compose.yml`의 `mem_limit`: api 384MB, web 128MB)는 이 결과를 근거로만 바꾼다 — 서버에서 compose를 직접 고치지 않고 결과를 마스터에게 알린다.

1. 앱에서 무거운 동작을 한 번씩 한다: AI로 채우기 1회(긴 글), AI 검색 1회, 목록 스크롤.
2. 바로 서버에서:

```bash
sudo docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}'   # 숫자만 나온다 (붙여도 된다)
for c in scrap-app-api-1 scrap-app-web-1; do
  chk "$c 메모리 한도의 70% 미만"   sh -c "sudo docker stats --no-stream --format '{{.MemPerc}}' $c | awk '{exit !(\$1+0 < 70)}'"
  chk "$c 메모리 부족 종료 기록 없음" sh -c "sudo docker inspect -f '{{.State.OOMKilled}}' $c | grep -qx false"
  chk "$c 재시작 0회"               sh -c "sudo docker inspect -f '{{.RestartCount}}' $c | grep -qx 0"
done
chk "커널 메모리 부족(OOM) 기록 없음 (이번 부팅)" sh -c "! sudo journalctl -k -b --no-pager | grep -qiE 'out of memory|oom-kill'"
chk "서버 여유 메모리(available) 150MB 이상"     sh -c "free -m | awk '/^Mem:/{exit !(\$7 >= 150)}'"
chk "스왑 사용 1GB 미만"                       sh -c "free -m | awk '/^Swap:/{exit !(\$3 < 1024)}'"
```

❌가 있으면 표의 숫자(`MemUsage`)와 ❌ 줄을 마스터에게 알린다. 70%는 여유 기준이다 — 넘어도 바로 문제는 아니지만, 한도에 닿으면 그 컨테이너만 종료 후 재시작된다 (api면 진행 중 요청이 끊긴다).

---

## 13. 일일 백업 (서버, age 암호화)

**구성:** 서버의 `backup.sh`가 매일 한 번 DB의 일관된 사본을 만들어 **age 공개키로 암호화**한 파일만 `backups/daily/`에 남긴다 (최근 14개). Mac이 그 파일을 매일 가져가 30일 보관한다 (14절). 배포 직전 백업(`backups/predeploy-*.db`, 평문, `deploy.sh`가 만듦)은 그대로 따로 있다.

- DB에는 로그인 정보가 들어 있다. 그래서 **서버 밖으로 나가는 백업은 반드시 암호화**하고, 복호화 개인키는 서버에도 Mac의 백업 폴더 옆에도 두지 않는다.
- 사본은 api 컨테이너 안에서 Python `sqlite3` backup API로 만든다 (배포 직전 백업과 같은 방식, WAL 모드에서도 일관된 사본). 평문 사본은 서버에 파일로 남지 않고 곧바로 gzip → age로 흘러간다. api가 멈춰 있을 때 쓰는 일회용 컨테이너도 로그 기록을 끄고 `.env` 없이 띄운다 (출력이 Docker 로그에 남지 않는다). 배포 직전 백업(`predeploy-*.db`)은 지금처럼 평문 파일이다.
- `deploy.sh`·`rollback.sh`와 같은 잠금을 쓴다 → 배포·롤백 중이면 끝날 때까지 기다렸다가 백업한다.

### 13-1. age 키 만들기와 보관 — **사용자 Mac에서** (서버 아님)

**무엇을:** 백업 암호화용 age 키 쌍을 만든다. **공개키**(`age1...`)는 서버에 두고, **개인키는 암호로 보호한 키 파일**(`scrap-backup-key.age`)로만 보관한다. 개인키가 평문 파일이나 클립보드로 나오지 않는다. 쓸 때(복원)는 `age -d -i scrap-backup-key.age ...`가 암호를 묻는다.

> ⚠️ **키 파일이나 그 암호 중 하나라도 잃으면 암호화 백업은 아무도 복원할 수 없다.**
> - 키 파일은 **두 곳**에 둔다: 이 Mac의 `~/.config/scrap-backup/scrap-backup-key.age` + 오프라인 사본(외장 USB 등. `-a`로 만든 글자 파일이라 종이에 인쇄해도 된다).
> - 암호는 **비밀번호 관리자**에 둔다 (키 파일과 같은 곳에 적어 두지 않는다).
> - 서버·저장소·백업 폴더(`~/ScrapBackups`)·채팅에는 두지 않는다.

```bash
brew install age                      # Homebrew. age, age-keygen 이 설치된다
chk() { local m=$1; shift; if "$@" >/dev/null 2>&1; then echo "✅ $m"; else echo "❌ $m"; fi; }

K=~/.config/scrap-backup/scrap-backup-key.age
mkdir -p ~/.config/scrap-backup; chmod 700 ~/.config/scrap-backup
[ -e "$K" ] && echo "이미 있음 — 덮어쓰지 않는다 (교체는 16-5)" || \
  age-keygen 2>/dev/null | age -p -a -o "$K"     # 새 암호를 두 번 묻는다 → 비밀번호 관리자에 새 항목으로 저장
chmod 600 "$K"
age -d "$K" | age-keygen -y           # 암호를 한 번 묻고 공개키 한 줄(age1...)만 출력 → 13-2에서 서버에 넣는다 (공개해도 되는 값)
```

**확인 (암호를 한 번 더 묻는다 — 비밀번호 관리자에 저장한 암호로 입력):**

```bash
K=~/.config/scrap-backup/scrap-backup-key.age
chk "키 파일이 암호로 보호됨 (평문 개인키 없음)" sh -c "head -n 1 '$K' | grep -qx -- '-----BEGIN AGE ENCRYPTED FILE-----' && ! grep -q AGE-SECRET-KEY '$K'"
chk "키 파일 600"                               test "$(stat -f %Lp "$K")" = 600
P=$(age -d "$K" | age-keygen -y)                                   # 암호 입력 (1)
if [ "$(echo scrap-age-test | age -r "$P" | age -d -i "$K")" = scrap-age-test ]; then   # 암호 입력 (2)
  echo "✅ 저장한 암호로 키 파일을 열고 복호화됨"; else echo "❌ 키 파일 또는 암호 확인"; fi
cp "$K" /Volumes/<USB 이름>/                    # 두 번째 보관 장소 (USB 등)
```

암호 입력 두 번 모두 비밀번호 관리자에 저장한 암호로 한다 (저장본이 맞는지 확인하는 단계다). ❌이거나 암호가 맞지 않으면 키 파일을 지우고 처음부터 다시 만든다 (아직 서버에 공개키를 넣기 전이면 잃는 것이 없다).

### 13-2. 서버: age 설치, 수신자(공개키) 파일

```bash
sudo apt-get install -y age
sudo install -d -m 755 -o root -g root /opt/scrap-app/age
sudo sh -c 'umask 022; cat > /opt/scrap-app/age/recipients.txt'
# ↑ 커서가 멈추면: 13-1의 공개키 한 줄(age1...)을 붙여넣고 → Enter → Ctrl+D
sudo chmod 644 /opt/scrap-app/age/recipients.txt
```

**확인:**

```bash
R=/opt/scrap-app/age/recipients.txt
chk "age 설치됨"                           command -v age
chk "수신자 파일 root 644"                  test "$(sudo stat -c '%U %a' $R)" = "root 644"
chk "공개키(age1...) 줄 있음"               grep -qE '^age1[0-9a-z]+$' $R
chk "개인키가 서버에 없음"                  sh -c "! grep -q 'AGE-SECRET-KEY-' $R"
chk "deploy 가 읽을 수 있음"                sudo -u deploy test -r $R
```

> 수신자 파일에는 공개키를 여러 줄 넣을 수 있다 (그중 아무 개인키로나 풀린다). age 키를 바꿀 때 잠시 두 줄을 둔다 (16-5).

### 13-3. 백업 폴더·스크립트 설치와 시험 실행

`backup.sh`는 11절 표의 서버 파일이다 (11-1로 설치). 폴더가 없으면 만든다:

```bash
sudo install -d -m 700 -o deploy -g deploy /opt/scrap-app/backups/daily
sudo -u deploy /opt/scrap-app/deploy/backup.sh; echo "exit=$?"
```

**확인:** 끝 줄이 `backup: 백업 완료: daily-<UTC 시각>.db.gz.age (... bytes, 보관 최대 14개)`이고 `exit=0`. 첫 배포 전(DB 없음)에는 `건너뜀: ...`과 `exit=0`이 정상이다.

```bash
D=/opt/scrap-app/backups/daily
chk "암호화 백업이 있음"                  sh -c "sudo ls $D | grep -qE '^daily-[0-9]{8}T[0-9]{6}Z\.db\.gz\.age$'"
chk "백업 파일이 age 형식"                sh -c "sudo sh -c 'head -c 21 \"\$(ls -1 $D/daily-*.age | tail -n 1)\"' | grep -qx 'age-encryption.org/v1'"
chk "백업 파일 권한 600, deploy 소유"      sh -c "sudo sh -c \"stat -c '%U %a' $D/daily-*.age\" | sort -u | grep -qx 'deploy 600'"
chk "daily/ 에 평문 SQLite 파일 없음"     sh -c "! sudo sh -c 'for f in $D/*; do head -c 15 \"\$f\"; echo; done' | grep -q 'SQLite format 3'"
chk "data/ 에 임시 사본이 남지 않음"       sh -c "! sudo test -e /opt/scrap-app/data/.daily-backup.tmp"
chk "backup.log 에 완료 기록"             sh -c "sudo tail -n 5 /opt/scrap-app/logs/backup.log | grep -q '백업 완료'"
```

실패하면 `실패:` 줄 그대로 마스터에게 알린다 (도메인·비밀값은 기록되지 않는다). 서버에서는 백업을 풀 수 없다 — 내용 확인은 Mac에서 15-5로 한다.

### 13-4. 매일 자동 실행 (cron)

**무엇을:** `deploy` 사용자로 매일 18:30 UTC(한국 03:30)에 실행한다. 스크립트가 직접 `logs/backup.log`에 기록하므로 cron 출력은 버린다.

```bash
timedatectl show -p Timezone --value     # 서버 시간대. Etc/UTC 가 아니면 아래 시각을 그 시간대로 바꾼다
sudo tee /etc/cron.d/scrap-app-backup >/dev/null <<'EOF'
# 일일 DB 백업 (age 암호화) — deploy/README.md 13절. 기록은 /opt/scrap-app/logs/backup.log
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 18 * * * deploy /opt/scrap-app/deploy/backup.sh >/dev/null 2>&1
EOF
sudo chmod 644 /etc/cron.d/scrap-app-backup
chk "cron 파일 설치됨 (root 644)" test "$(sudo stat -c '%U %a' /etc/cron.d/scrap-app-backup)" = "root 644"
chk "cron 실행 중"                systemctl is-active cron
```

- 백업은 보통 몇 초 걸린다. 그 사이에 배포를 승인하면 `deploy.sh`가 "다른 배포가 진행 중"으로 바로 끝난다 (아무것도 바꾸지 않음). 한국 시각 03:30 무렵을 피하거나, 그렇게 끝났으면 `deploy` 잡을 **Re-run**한다. 거꾸로 배포 중에 백업 시각이 되면 백업이 배포가 끝나기를 기다린다.
- `logs/backup.log`는 3-3의 logrotate 설정(`logs/*.log`)이 함께 돌린다.

### 13-5. 확인 (다음 날, 이후 수시로)

```bash
D=/opt/scrap-app/backups/daily
chk "24시간 안에 만든 백업 있음"      sh -c "sudo find $D -maxdepth 1 -name 'daily-*.db.gz.age' -mmin -1500 | grep -q ."
chk "백업 14개 이하 보관"            sh -c "[ \$(sudo find $D -maxdepth 1 -name 'daily-*.db.gz.age' | wc -l) -le 14 ]"
chk "최근 기록에 실패 없음"           sh -c "! sudo tail -n 20 /opt/scrap-app/logs/backup.log | grep -q '실패'"
chk "logrotate 가 backup.log 를 봄"  sh -c "sudo logrotate -d /etc/logrotate.d/scrap-app 2>&1 | grep -q backup.log"
sudo tail -n 3 /opt/scrap-app/logs/backup.log
```

---

## 14. Mac으로 백업 가져오기 (외부 보관)

**구성:** 사용자 Mac이 매일 서버에 접속해 아직 없는 암호화 백업만 가져온다. 접속은 **백업 수신 전용 SSH 키**로만 하고, 서버는 그 키에 강제 명령(`backup-send.sh`)을 걸어 **암호화 백업 목록과 파일만** 내보낸다 (셸·다른 파일·평문 불가). Mac은 받기·보관만 하고 복호화하지 않는다 (개인키 불필요).

파일: `deploy/mac/pull-backups.sh`(스크립트), `deploy/mac/config.example`(설정 예시), `deploy/mac/scrap-backup.plist.example`(launchd 예시). Mac에서 쓰는 명령에도 13-1의 `chk` 한 줄을 먼저 붙여넣는다.

### 14-1. Mac 준비: 수신 전용 키

```bash
# Mac 터미널. 저장소 폴더 안에 만들지 않는다. launchd 가 무인으로 쓰므로 암호(passphrase)는 비운다.
ssh-keygen -t ed25519 -a 100 -N '' -C 'scrap-backup-pull' -f ~/.ssh/scrap_backup_ed25519
cat ~/.ssh/scrap_backup_ed25519.pub
```

**확인:** `ssh-ed25519 AAAA... scrap-backup-pull` 한 줄. 이 **공개키**만 서버에 등록한다. 이 키는 CI 배포 키(`scrap_ci_deploy`)와 다른 키다 — 섞어 쓰지 않는다.

### 14-2. 서버에 수신 키 등록 (강제 명령, 별도 줄)

**무엇을:** `deploy` 사용자의 `authorized_keys`에 **줄을 하나 추가**한다 (CI 키 줄은 그대로 둔다). 이 키로 접속하면 `backup-send.sh`만 실행된다.

```bash
PUBKEY='ssh-ed25519 AAAA...여기에 14-1의 .pub 한 줄 전체... scrap-backup-pull'
AK=/home/deploy/.ssh/authorized_keys

sudo cp -p "$AK" "$AK.bak"
printf 'restrict,command="/opt/scrap-app/deploy/backup-send.sh" %s\n' "$PUBKEY" | sudo tee -a "$AK" >/dev/null
sudo ssh-keygen -lf "$AK"
```

**확인:**

```bash
AK=/home/deploy/.ssh/authorized_keys
chk "CI 키 줄(deploy.sh) 그대로 1개"      sh -c "sudo grep -c '^restrict,command=\"/opt/scrap-app/deploy/deploy.sh\" ' $AK | grep -qx 1"
chk "백업 수신 키 줄(backup-send.sh) 1개"  sh -c "sudo grep -c '^restrict,command=\"/opt/scrap-app/deploy/backup-send.sh\" ' $AK | grep -qx 1"
chk "강제 명령 없는 줄 없음"               sh -c "! sudo grep -vE '^(restrict,command=\"/opt/scrap-app/deploy/(deploy|backup-send)\.sh\" |#|\$)' $AK | grep -q ."
chk "authorized_keys deploy 600"          test "$(sudo stat -c '%U %a' $AK)" = "deploy 600"
chk "backup-send.sh 설치됨 (11절)"         test -x /opt/scrap-app/deploy/backup-send.sh
```

모두 ✅면 `sudo rm "$AK.bak"`. CI 키 줄이 사라졌으면(❌) `sudo cp -p "$AK.bak" "$AK"`로 되돌리고 다시 한다.

### 14-3. 서버 호스트 키 등록 (Mac)

Mac은 미리 등록한 서버 호스트 키로만 접속한다 (`StrictHostKeyChecking=yes`, 처음 접속 때 묻지 않는다). 값은 **서버에서 직접** 읽는다 (12-1 (b)의 `DEPLOY_KNOWN_HOSTS`와 같은 한 줄):

```bash
# 서버
D=$(sudo cat /opt/scrap-app/duckdns/domain); D="${D%.duckdns.org}.duckdns.org"
printf '%s %s\n' "$D" "$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
```

```bash
# Mac — 위 출력 한 줄을 붙여넣고 → Enter → Ctrl+D
cat > ~/.ssh/scrap_backup_known_hosts
chmod 600 ~/.ssh/scrap_backup_known_hosts
H='<이름>.duckdns.org'
chk "호스트 키 파일에 서버 주소 있음" ssh-keygen -F "$H" -f ~/.ssh/scrap_backup_known_hosts
```

서버를 새로 만들면 호스트 키가 바뀌므로 이 단계를 다시 한다 (그 전에는 Mac이 접속을 거부한다 — 정상).

### 14-4. 스크립트·설정 설치 (Mac)

launchd가 실행할 파일은 Desktop·Documents·Downloads **밖에** 둔다 (그 폴더들은 macOS 개인정보 보호 권한 때문에 백그라운드 작업이 읽지 못한다). 저장소 폴더에서:

```bash
mkdir -p ~/.local/bin ~/.config/scrap-backup
install -m 755 deploy/mac/pull-backups.sh ~/.local/bin/scrap-pull-backups.sh
[ -e ~/.config/scrap-backup/config ] || install -m 600 deploy/mac/config.example ~/.config/scrap-backup/config
nano ~/.config/scrap-backup/config     # SCRAP_BACKUP_HOST 의 <이름> 을 실제 서브도메인으로 바꾼다
```

- 설정 파일은 저장소 밖(`~/.config`)에 있다. 실제 주소를 넣은 파일을 저장소에 복사하지 않는다.
- 보관 폴더 기본값은 `~/ScrapBackups`(700). Time Machine 백업에 함께 들어가도 암호화된 파일뿐이다.
- 저장소의 스크립트가 바뀌면(PR 설명에 적힌다) 위 `install` 줄만 다시 실행한다.

### 14-5. 첫 실행 확인 (Mac)

```bash
~/.local/bin/scrap-pull-backups.sh; echo "exit=$?"
```

**확인:** 끝 줄이 `pull: 완료: 서버 N개, 새로 받음 N개, ...`이고 `exit=0`.

```bash
chk "보관 폴더 700"                    test "$(stat -f %Lp ~/ScrapBackups)" = 700
chk "암호화 백업을 받음"                 sh -c "ls ~/ScrapBackups | grep -qE '^daily-[0-9]{8}T[0-9]{6}Z\.db\.gz\.age$'"
chk "받은 파일이 age 형식"              sh -c "head -c 21 \"\$(ls -1 ~/ScrapBackups/daily-*.age | tail -n 1)\" | grep -qx 'age-encryption.org/v1'"
chk "조각(.part) 파일 없음"             sh -c "! ls -a ~/ScrapBackups | grep -q '\.part$'"
H='<이름>.duckdns.org'
chk "수신 키로는 다른 요청이 거부됨"     sh -c "ssh -F /dev/null -T -n -i ~/.ssh/scrap_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/scrap_backup_known_hosts deploy@$H 'get ../../.env'; [ \$? -eq 2 ]"
```

`exit=2`면 설정 오류다 — 메시지에 적힌 절을 본다. `Host key verification failed`면 14-3, `Permission denied`면 14-2를 다시 확인한다.

### 14-6. 매일 자동 실행 (launchd)

```bash
P=~/Library/LaunchAgents/local.scrap-backup.pull.plist
mkdir -p ~/Library/LaunchAgents
sed "s#/Users/USERNAME#$HOME#g" deploy/mac/scrap-backup.plist.example > "$P"   # 저장소 폴더에서
chk "plist 형식 정상"             plutil -lint "$P"
chk "경로에 자리표시자가 남지 않음"  sh -c "! grep -q '/Users/USERNAME' '$P'"   # 설명 주석의 USERNAME 글자는 그대로 남는다
launchctl bootstrap "gui/$(id -u)" "$P"
launchctl kickstart -k "gui/$(id -u)/local.scrap-backup.pull"    # 지금 한 번 실행
```

- 매일 10:00(Mac 시각)에 실행한다. 그 시각에 잠자기 중이었으면 **깨어난 뒤 한 번** 실행된다. 전원이 꺼져 있던 날은 건너뛰고, 다음 실행이 밀린 백업까지 받는다 (서버는 14일 치를 갖고 있다).
- 처음 등록하면 macOS가 "백그라운드 항목 추가" 알림을 띄울 수 있다 (시스템 설정 → 일반 → 로그인 항목에서 켜져 있어야 한다).
- 끄기: `launchctl bootout "gui/$(id -u)/local.scrap-backup.pull"`. 시각을 바꾸려면 plist를 고친 뒤 끄고 다시 `bootstrap`한다.

### 14-7. 확인 (수시로, Mac)

```bash
chk "launchd 작업 등록됨"        launchctl print "gui/$(id -u)/local.scrap-backup.pull"
chk "마지막 실행 종료 코드 0"    sh -c "launchctl print gui/$(id -u)/local.scrap-backup.pull | grep -qE 'last exit code = 0\$'"
chk "2일 안에 받은 백업 있음"     sh -c "find ~/ScrapBackups -name 'daily-*.db.gz.age' -mtime -2 | grep -q ."
tail -n 3 ~/Library/Logs/scrap-backup.log
```

- 실패하면 macOS 알림("스크랩 백업")이 뜬다. 최근 3일 동안 새 백업이 없어도 실패로 알린다 (서버 13-5 확인).
- Mac은 30일 지난 백업을 지우되, 날짜와 상관없이 최근 7개는 남기고, **매월 첫 백업은 12개월 보관**한다 (설정 `SCRAP_BACKUP_KEEP_DAYS`, `SCRAP_BACKUP_KEEP_MIN`, `SCRAP_BACKUP_KEEP_MONTHLY`).
- 백업 하나가 500MB(`SCRAP_BACKUP_MAX_MB`)를 넘거나, 이름의 날짜가 Mac의 오늘보다 1일 넘게 미래면 받지 않고 실패로 알린다. 미래 날짜면 서버 시각을 확인한다: `timedatectl show -p NTPSynchronized --value`(서버, `yes`여야 한다).

---

## 15. 백업 복원

| 상황 | 쓰는 백업 | 절 |
|---|---|---|
| 배포 직후 DB 문제 (새 버전이 DB를 바꿈) | 서버 `backups/predeploy-*.db` (평문) | 15-1 |
| 며칠 전 상태로 되돌리기, 서버 디스크 문제 | Mac `~/ScrapBackups/daily-*.db.gz.age` (암호화) | 15-2 |
| 서버를 새로 만들어 데이터 옮기기 | Mac 암호화 백업 | 15-3 |

**원칙 (WAL):** DB는 WAL 모드라 `scrap.db` 옆에 `scrap.db-wal`·`scrap.db-shm`이 있다. 복원할 때는 **api를 멈춘 뒤** 이 두 파일을 지우고 `scrap.db`를 바꿔 넣어야 한다 (옛 `-wal`이 새 DB에 덮어씌워지면 DB가 망가진다). `rollback.sh --restore-db`가 이 순서(정지 → 현재 DB 3개 파일 보존·비교 → `-wal`/`-shm` 삭제 → 교체(10001, 600) → 기동 → 헬스체크)를 그대로 하므로 **직접 파일을 옮기지 않고 이 스크립트를 쓴다.**

> ⚠️ 복원하면 그 백업 이후 저장한 스크랩·설정은 사라진다. 지금 DB는 `/root/db-before-restore-<시각>/`에 보존되므로, 잘못 복원했으면 같은 방법으로 그 파일을 다시 넣을 수 있다.

### 15-1. 배포 직전 백업에서 (서버 안에서 끝남)

12-6 방법 B의 "DB까지 되돌리기"와 같다. 버전은 그대로 두고 DB만 되돌리려면 `current`를 쓴다:

```bash
sudo /opt/scrap-app/deploy/rollback.sh                                     # 백업 목록 보기
sudo /opt/scrap-app/deploy/rollback.sh current --restore-db predeploy-<시각>-<sha>.db
```

끝나면 15-4로 확인한다.

### 15-2. Mac의 암호화 백업에서

**(a) Mac: 복호화·검사** — 13-1의 암호 보호 키 파일을 쓴다 (암호를 묻는다. Mac 사본이 없으면 USB 사본 경로를 `K`에 넣는다).

```bash
F=~/ScrapBackups/daily-<UTC 시각>.db.gz.age       # 되돌릴 시점의 백업
K=~/.config/scrap-backup/scrap-backup-key.age
T=$(mktemp -d); chmod 700 "$T"
age -d -i "$K" -o "$T/scrap.db.gz" "$F"
gunzip "$T/scrap.db.gz"; chmod 600 "$T/scrap.db"
chk "복호화·압축 해제됨"      test -s "$T/scrap.db"
chk "SQLite 파일"            sh -c "head -c 15 '$T/scrap.db' | grep -qx 'SQLite format 3'"
chk "integrity_check ok"     sh -c "/usr/bin/sqlite3 '$T/scrap.db' 'PRAGMA integrity_check' | grep -qx ok"
```

**(b) Mac → 서버로 보내기** (관리 사용자, OCI 기본 `ubuntu`. 서버의 관리 사용자 홈에 600으로 올린다):

```bash
scp "$T/scrap.db" ubuntu@<이름>.duckdns.org:scrap-restore.db
rm -rf "$T"                          # Mac 의 평문 사본 삭제
```

**(c) 서버: 복원** — `backups/`에 이름을 붙여 넣고 `rollback.sh`로 바꿔 넣는다.

```bash
N="restore-$(date -u +%Y%m%dT%H%M%SZ).db"
sudo install -m 600 -o deploy -g deploy ~/scrap-restore.db "/opt/scrap-app/backups/$N" && rm -f ~/scrap-restore.db
chk "복원할 파일 준비됨" sudo test -s "/opt/scrap-app/backups/$N"
sudo /opt/scrap-app/deploy/rollback.sh current --restore-db "$N"
```

끝 줄이 `완료 — 운영 중: <SHA>`면 15-4로 확인한다.

### 15-3. 새 서버로 옮길 때 (첫 배포 전)

15-2 (a)·(b)를 한 뒤, 새 서버에서 **첫 배포 전에** (`data/`에 아무 파일도 없을 때):

```bash
chk "data/ 비어 있음 (첫 배포 전)" sh -c "[ -z \"\$(sudo ls -A /opt/scrap-app/data)\" ]"
sudo install -m 600 -o 10001 -g 10001 ~/scrap-restore.db /opt/scrap-app/data/scrap.db && rm -f ~/scrap-restore.db
chk "scrap.db 소유 10001, 600" test "$(sudo stat -c '%u %a' /opt/scrap-app/data/scrap.db)" = "10001 600"
```

그다음 "서버를 새로 만들 때" 5번(첫 배포)부터 이어 간다. 첫 배포는 이 DB를 그대로 쓴다.

### 15-4. 복원 후 확인과 정리

```bash
chk "api healthy"                    sh -c "sudo docker inspect -f '{{.State.Health.Status}}' scrap-app-api-1 | grep -qx healthy"
chk "data/scrap.db 소유 10001, 600"   test "$(sudo stat -c '%u %a' /opt/scrap-app/data/scrap.db)" = "10001 600"
sudo docker compose -f /opt/scrap-app/docker-compose.yml exec -T api python -m app.admin fts-check   # ✅/❌ 한 줄 (19-3)
```

- 브라우저에서 로그인해 목록·검색이 되는지 본다. 복원한 백업 시점의 비밀번호·2차 인증으로 로그인한다. (로그인 세션도 그 시점으로 돌아가므로 다른 기기는 다시 로그인해야 할 수 있다.)
- `fts-check`가 ❌면 19-3의 `fts-rebuild`를 실행한다. 옛 이미지라 `app.admin`이 없으면 이 줄은 건너뛴다.

**⚠️ 정리 (확인이 끝난 뒤에만):** 평문 DB 사본을 서버에 오래 두지 않는다.

```bash
sudo sh -c 'ls -d /root/db-before-restore-* /opt/scrap-app/backups/restore-*.db 2>/dev/null'
sudo rm -rf /root/db-before-restore-<시각>          # 위 목록에서 이번 복원의 보존본
sudo sh -c 'rm -f /opt/scrap-app/backups/restore-*.db'
chk "복원용 평문 사본 정리됨" sh -c "! sudo ls /opt/scrap-app/backups | grep -q '^restore-'"
```

### 15-5. 정기 복원 연습 (월 1회, Mac에서만)

**무엇을:** 최근 암호화 백업이 실제로 풀리고 온전한지 Mac 안에서만 확인한다. **서버에 올리지 않는다.** 개인키 보관본이 쓸 수 있는 상태인지도 함께 확인된다.

```bash
F=$(ls -1 ~/ScrapBackups/daily-*.db.gz.age | tail -n 1); echo "${F##*/}"
K=~/.config/scrap-backup/scrap-backup-key.age
T=$(mktemp -d); chmod 700 "$T"
age -d -i "$K" "$F" | gunzip > "$T/scrap.db"       # 키 파일 암호를 묻는다 (비밀번호 관리자의 암호)
S=/usr/bin/sqlite3
chk "복호화·압축 해제됨"            test -s "$T/scrap.db"
chk "integrity_check ok"           sh -c "$S '$T/scrap.db' 'PRAGMA integrity_check' | grep -qx ok"
chk "검색 색인(FTS) 무결성"         $S "$T/scrap.db" "INSERT INTO scraps_fts(scraps_fts) VALUES('integrity-check');"
chk "사용자 1명"                    sh -c "$S '$T/scrap.db' 'SELECT count(*) FROM users' | grep -qx 1"
$S "$T/scrap.db" "SELECT count(*) || '개 스크랩, 마지막 저장 ' || ifnull(max(created_at), '-') FROM scraps"
rm -rf "$T"
chk "평문 사본 삭제됨" test ! -e "$T"
```

- 스크랩 수·마지막 저장 시각이 기억과 대략 맞으면 된다. 이 출력에는 비밀값이 없다.
- 복호화가 ❌면 키 파일·암호 보관본을 확인한다 (USB 사본으로도 해 본다). 둘 다 안 되면 즉시 16-5로 새 키를 만든다 — 그 전 백업은 원래 키로만 풀린다.
- 몇 달에 한 번은 오프라인 사본(USB)으로도 해 본다 (`K=/Volumes/<USB 이름>/scrap-backup-key.age`).

---

## 16. 비밀값 교체

**공통:**
- 값은 화면에 출력하지 않는다. 확인은 형식만 보는 ✅/❌ 줄로 한다 (17절).
- `.env`를 바꾼 뒤에는 `sudo /opt/scrap-app/deploy/rollback.sh current`로 같은 버전을 다시 올려 반영한다 (컨테이너가 새 `.env`로 다시 만들어진다. 끝 줄 `완료 — 운영 중: <SHA>`).
- 유출이 의심되면 다른 조사보다 **교체가 먼저**다.

### 16-1. `SESSION_SECRET`

> ⚠️ 바꾸면 **모든 기기가 로그아웃**된다 (아이폰 홈 화면 앱 포함). 다시 로그인할 때 2차 인증 코드가 필요하다.

값을 화면에 띄우지 않고 파일 안에서 바로 바꾼다:

```bash
sudo bash <<'EOF'
set -euo pipefail; umask 077
f=/opt/scrap-app/.env; t=$(mktemp)
NEW="$(openssl rand -hex 32)" awk '
  BEGIN { n = ENVIRON["NEW"] }
  /^[[:space:]]*SESSION_SECRET[[:space:]]*=/ { if (!d) print "SESSION_SECRET=" n; d = 1; next }
  { print }
  END { if (!d) print "SESSION_SECRET=" n }' "$f" > "$t"
install -m 600 -o deploy -g deploy "$t" "$f"; rm -f "$t"
EOF
E=/opt/scrap-app/.env
chk "SESSION_SECRET 한 줄"          sh -c "sudo grep -c '^SESSION_SECRET=' $E | grep -qx 1"
chk "SESSION_SECRET 64자 16진수"     sudo grep -qE '^SESSION_SECRET=[0-9a-f]{64}$' $E
chk ".env deploy 600"              test "$(sudo stat -c '%U %a' $E)" = "deploy 600"
sudo /opt/scrap-app/deploy/rollback.sh current
```

### 16-2. `ANTHROPIC_API_KEY`

1. Anthropic Console → API Keys → **Create Key** (이름 예: `scrap-app-<연월>`, 이 앱 전용). 키를 복사한다.
2. 서버에서 `sudo -u deploy nano /opt/scrap-app/.env` → `ANTHROPIC_API_KEY=` 뒤의 값을 새 키로 바꾼다 (따옴표·공백 없이 한 줄). 저장.
3. 확인 후 반영:
   ```bash
   E=/opt/scrap-app/.env
   chk "ANTHROPIC_API_KEY 한 줄"         sh -c "sudo grep -c '^ANTHROPIC_API_KEY=' $E | grep -qx 1"
   chk "sk-ant- 로 시작, 자리표시자 아님"  sh -c "sudo grep -E '^ANTHROPIC_API_KEY=sk-ant-[A-Za-z0-9_-]{20,}$' $E | grep -qv 'sk-ant-xxxx'"
   sudo /opt/scrap-app/deploy/rollback.sh current
   ```
4. 앱에서 "AI로 채우기"를 한 번 해 본다 (성공해야 다음 단계로).
5. Console에서 **옛 키를 삭제(Delete)**한다. 사용량 화면에서 새 키로 호출이 잡히는지 본다.
6. Console의 **월 지출 한도**(Limits / spend limit)가 걸려 있는지 확인한다. 한도에 닿으면 앱은 "이번 달 한도 도달"로 응답한다 (AI만 멈추고 나머지 기능은 정상).

### 16-3. CI 배포 키 (정기 교체)

**권장 주기:** 6개월마다, 그리고 키가 있던 PC를 잃었거나 GitHub 계정·시크릿 노출이 의심될 때 즉시. 새 키를 **먼저 추가**하고 확인한 뒤 옛 줄을 지우므로 배포가 끊기지 않는다.

(a) PC: 새 키 만들기

```bash
C="scrap-ci-deploy-$(date +%Y%m)"
ssh-keygen -t ed25519 -a 100 -N '' -C "$C" -f ~/.ssh/scrap_ci_deploy_new
cat ~/.ssh/scrap_ci_deploy_new.pub
```

(b) 서버: 줄 추가 (옛 줄·백업 수신 키 줄은 그대로)

```bash
PUBKEY='ssh-ed25519 AAAA...(a)의 .pub 한 줄 전체... scrap-ci-deploy-<연월>'
AK=/home/deploy/.ssh/authorized_keys
sudo cp -p "$AK" "$AK.bak"
printf 'restrict,command="/opt/scrap-app/deploy/deploy.sh" %s\n' "$PUBKEY" | sudo tee -a "$AK" >/dev/null
chk "deploy.sh 강제 명령 줄 2개 (옛 키 + 새 키)" sh -c "sudo grep -c '^restrict,command=\"/opt/scrap-app/deploy/deploy.sh\" ' $AK | grep -qx 2"
```

(c) PC: 12-2 (c)를 `~/.ssh/scrap_ci_deploy` 대신 `~/.ssh/scrap_ci_deploy_new`로 실행한다 (✅ 3개).

(d) GitHub: Settings → Environments → `production` → `DEPLOY_SSH_KEY` → 새 개인키로 바꾼다 (`pbcopy < ~/.ssh/scrap_ci_deploy_new` → 붙여넣기 → `pbcopy < /dev/null`).

(e) 시험 배포: Actions → Deploy → 가장 최근 성공 실행 → `deploy` 잡 **Re-run this job** → 승인 → `배포 성공`.

(f) 서버: 옛 줄 삭제 (**CI 키 전용** — 백업 수신 키는 16-4의 블록을 쓴다) — **줄 끝의 키 주석**으로 고른다 (처음 등록한 키의 주석은 `scrap-ci-deploy`).

```bash
OLD='scrap-ci-deploy'          # 지울 키의 주석 (아래 ssh-keygen -lf 출력에서 각 줄의 주석 확인)
AK=/home/deploy/.ssh/authorized_keys
sudo ssh-keygen -lf "$AK"
NB=$(sudo grep -c 'backup-send.sh' "$AK" || true)     # 백업 수신 키 줄 수 (그대로여야 한다)
sudo cp -p "$AK" "$AK.bak"
sudo awk -v c="$OLD" '$NF != c' "$AK.bak" | sudo tee "$AK" >/dev/null
chk "deploy.sh 강제 명령 줄 1개"     sh -c "sudo grep -c '^restrict,command=\"/opt/scrap-app/deploy/deploy.sh\" ' $AK | grep -qx 1"
chk "옛 키 주석 없음"                sh -c "! sudo awk -v c='$OLD' '\$NF == c' $AK | grep -q ."
chk "백업 수신 키 줄 수 그대로"       sh -c "sudo grep -c 'backup-send.sh' $AK | grep -qx '$NB'"
```

모두 ✅면 `sudo rm "$AK.bak"`. ❌면 `sudo cp -p "$AK.bak" "$AK"`로 되돌린다.

(g) PC: 옛 키가 거부되는지 확인하고 파일을 정리한다.

```bash
H='<이름>.duckdns.org'
KH="$HOME/.ssh/scrap_backup_known_hosts"     # 14-3의 호스트 키 파일 (12-2 (c)처럼 DEPLOY_KNOWN_HOSTS 한 줄 파일이어도 된다)
chk "옛 CI 키는 거부됨 (Permission denied)" sh -c "ssh -T -n -i ~/.ssh/scrap_ci_deploy -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KH deploy@$H ping 2>&1 | grep -q 'Permission denied'"
# ✅ 뒤에만:
rm -f ~/.ssh/scrap_ci_deploy ~/.ssh/scrap_ci_deploy.pub
mv ~/.ssh/scrap_ci_deploy_new ~/.ssh/scrap_ci_deploy; mv ~/.ssh/scrap_ci_deploy_new.pub ~/.ssh/scrap_ci_deploy.pub
```

### 16-4. 백업 수신 키

새 키를 **먼저 추가**하고 Mac에서 받기를 확인한 뒤 옛 줄을 지운다. CI 키 줄은 건드리지 않는다.

(a) Mac: 새 키 만들기

```bash
C="scrap-backup-pull-$(date +%Y%m)"
ssh-keygen -t ed25519 -a 100 -N '' -C "$C" -f ~/.ssh/scrap_backup_ed25519_new
cat ~/.ssh/scrap_backup_ed25519_new.pub
```

(b) 서버: 줄 추가 (14-2와 같은 형식)

```bash
PUBKEY='ssh-ed25519 AAAA...(a)의 .pub 한 줄 전체... scrap-backup-pull-<연월>'
AK=/home/deploy/.ssh/authorized_keys
printf 'restrict,command="/opt/scrap-app/deploy/backup-send.sh" %s\n' "$PUBKEY" | sudo tee -a "$AK" >/dev/null
chk "backup-send.sh 강제 명령 줄 2개 (옛 키 + 새 키)" sh -c "sudo grep -c '^restrict,command=\"/opt/scrap-app/deploy/backup-send.sh\" ' $AK | grep -qx 2"
```

(c) Mac: 새 키로 받기 확인

```bash
SCRAP_BACKUP_KEY=~/.ssh/scrap_backup_ed25519_new ~/.local/bin/scrap-pull-backups.sh; echo "exit=$?"     # exit=0
```

(d) 서버: 옛 수신 키 줄 삭제 (**백업 수신 키 전용**)

```bash
OLD='scrap-backup-pull'        # 지울 키의 주석 (아래 ssh-keygen -lf 출력에서 확인)
AK=/home/deploy/.ssh/authorized_keys
sudo ssh-keygen -lf "$AK"
NC=$(sudo grep -c 'deploy/deploy.sh' "$AK" || true)   # CI 키 줄 수 (그대로여야 한다)
sudo cp -p "$AK" "$AK.bak"
sudo awk -v c="$OLD" '$NF != c' "$AK.bak" | sudo tee "$AK" >/dev/null
chk "backup-send.sh 강제 명령 줄 1개 (새 키)" sh -c "sudo grep -c '^restrict,command=\"/opt/scrap-app/deploy/backup-send.sh\" ' $AK | grep -qx 1"
chk "옛 수신 키 줄 0개"                     sh -c "! sudo awk -v c='$OLD' '\$NF == c' $AK | grep -q ."
chk "CI 키 줄 수 그대로"                     sh -c "sudo grep -c 'deploy/deploy.sh' $AK | grep -qx '$NC'"
```

모두 ✅면 `sudo rm "$AK.bak"`. ❌면 `sudo cp -p "$AK.bak" "$AK"`로 되돌리고 `OLD` 값부터 다시 확인한다.

(e) Mac: 옛 키가 거부되는지 확인하고 파일을 정리한다.

```bash
H='<이름>.duckdns.org'
chk "옛 수신 키는 거부됨 (Permission denied)" sh -c "ssh -F /dev/null -T -n -i ~/.ssh/scrap_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=\$HOME/.ssh/scrap_backup_known_hosts deploy@$H list 2>&1 | grep -q 'Permission denied'"
# ✅ 뒤에만: 새 키를 원래 이름으로 (설정 파일·launchd 는 원래 이름을 쓴다)
rm -f ~/.ssh/scrap_backup_ed25519 ~/.ssh/scrap_backup_ed25519.pub
mv ~/.ssh/scrap_backup_ed25519_new ~/.ssh/scrap_backup_ed25519; mv ~/.ssh/scrap_backup_ed25519_new.pub ~/.ssh/scrap_backup_ed25519.pub
~/.local/bin/scrap-pull-backups.sh; echo "exit=$?"     # exit=0
```

### 16-5. age 키

1. 13-1로 새 키 파일을 만든다. 옛 키 파일과 섞이지 않게 `K`를 `~/.config/scrap-backup/scrap-backup-key-<연월>.age`로 바꿔 실행하고, 새 암호를 비밀번호 관리자에 새 항목으로 저장한다. 두 번째 보관 장소(USB)에도 복사한다.
2. 서버 수신자 파일을 새 공개키 **한 줄로** 바꾼다 (13-2의 `cat >` 명령으로 덮어쓰고 13-2 확인).
3. `sudo -u deploy /opt/scrap-app/deploy/backup.sh`로 새 백업을 하나 만들고, Mac에서 받은 뒤 15-5로 **새 키 파일로** 풀리는지 확인한다 (`K`를 새 파일로).
4. 그 전에 만든 백업(서버 14일·Mac 30일, 월간 장기 보관본 12개월)은 **옛 키 파일로만** 풀린다. 옛 키 파일과 암호는 그 백업들이 모두 지워질 때까지 보관하고, 그 뒤에 지운다. 새 키 파일을 기본 이름(`scrap-backup-key.age`)으로 바꿀 때는 옛 파일을 `scrap-backup-key-old.age` 같은 이름으로 남긴다.
   - 옛 개인키가 노출됐을 수 있어 바꾸는 경우: 옛 키로 암호화된 백업을 계속 둘지(복원 가능성) 지울지(노출 범위) 정한다. 지우려면 서버 `backups/daily/`와 Mac `~/ScrapBackups/`에서 새 키 이전 날짜 파일을 지운다.

### 16-6. DuckDNS 토큰

DuckDNS 계정 화면에서 토큰을 새로 받은 뒤(화면 구성은 바뀔 수 있다), 4-2의 `cat >` 명령으로 서버 파일을 덮어쓰고 4-3으로 확인한다. 토큰은 서버 파일 한 곳에만 있다 (저장소·CI·로그에 없음 — 4-4 확인의 `grep -c` 줄이 `0`).

### 16-7. `.env`에 넣지 않는 변수

`.env`의 모든 줄은 api 컨테이너의 환경변수가 된다. 앱이 쓰는 Anthropic SDK는 키 말고도 접속 주소·인증·프록시를 환경변수에서 읽으므로 아래 이름은 **넣지 않는다** (`.env.example`에 있는 이름만 쓴다):

- `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`(소문자 포함)
- 로컬 개발 전용: `ALLOWED_ORIGINS`, `COOKIE_SECURE`, `ENABLE_API_DOCS`

```bash
E=/opt/scrap-app/.env
chk ".env 에 SDK 접속·프록시 변수 없음" sh -c "! sudo grep -qiE '^[[:space:]]*(export[[:space:]]+)?(ANTHROPIC_BASE_URL|ANTHROPIC_AUTH_TOKEN|HTTPS?_PROXY|ALL_PROXY|NO_PROXY)[[:space:]]*=' $E"
chk ".env 에 개발 전용 변수 없음"       sh -c "! sudo grep -qE '^[[:space:]]*(export[[:space:]]+)?(ALLOWED_ORIGINS|COOKIE_SECURE|ENABLE_API_DOCS)[[:space:]]*=' $E"
```

---

### 16-8. 서버 침해가 의심될 때 (교체 순서)

서버나 계정에 다른 사람이 들어왔다고 의심되면, 조사보다 먼저 아래 순서로 바꾼다. 각 단계가 끝날 때마다 다음으로 넘어간다.

1. 앱 비밀번호 재설정 — 19-2 (모든 기기 로그아웃)
2. 2차 인증 재설정 — 19-1 (새 인증 앱 등록, 새 복구 코드)
3. `SESSION_SECRET` 교체 — 16-1 (남은 로그인 세션 모두 무효)
4. `ANTHROPIC_API_KEY` 교체 — 16-2 (Console에서 옛 키 삭제, 사용량 확인)
5. CI 배포 키 교체 — 16-3 (GitHub `production` 시크릿 포함)
6. 백업 수신 키 교체 — 16-4
7. DuckDNS 토큰 교체 — 16-6
8. 서버 `authorized_keys`에 강제 명령 없는 줄이 없는지 14-2의 확인 블록으로 본다.
9. age 키(16-5)는 개인키가 서버에 없으므로 서버 침해만으로는 바꿀 필요가 없다. Mac이나 키 파일 보관 장소가 의심되면 바꾼다.

그다음 마스터에게 알려 서버를 새로 만들지("서버를 새로 만들 때") 함께 정한다. 그 경우 DB는 침해 이전 날짜의 암호화 백업(Mac, 월간 장기 보관본 포함)에서 15-3으로 옮긴다.

## 17. 비밀값을 화면에 펼치지 않기

### 17-1. 진단할 때 쓰지 않는 명령과 대신 쓰는 방법

아래 명령은 `.env`의 값(세션 비밀값·API 키 등)이나 토큰을 화면에 그대로 출력한다. 터미널 기록·화면 공유·채팅에 남을 수 있으므로 **쓰지 않는다.** 실수로 출력했고 그 화면을 다른 곳에 붙였다면 16절로 그 값을 교체한다.

| 쓰지 않는 명령 | 펼쳐지는 것 | 대신 |
|---|---|---|
| `docker inspect <컨테이너>` (형식 지정 없이), `docker container inspect` | `Config.Env`에 `.env` 전체 | 필요한 칸만: `docker inspect -f '{{.State.Health.Status}}' scrap-app-api-1`, `-f '{{.Config.Image}}'`, `-f '{{.State.OOMKilled}}'` |
| `docker compose config` (옵션 없이) | `.env` 값이 치환된 전체 구성 | `docker compose config -q`(유효성만), `--services`, `--images` |
| `docker compose exec api env`, `printenv`, `docker exec … env`, `cat /proc/<pid>/environ`, `ps e`·`ps eww` | 컨테이너·프로세스 환경변수 전체 | 이름이 있는지만: `sudo docker compose -f /opt/scrap-app/docker-compose.yml exec -T api python -c "import os; print('ANTHROPIC_API_KEY' in os.environ)"` |
| `cat`·`less`·`head`·`nano`로 보기만 · `grep`(줄 출력) — `.env`, `duckdns/token` | 값 | 형식 판정 `chk` 줄 (16절), `grep -c`(개수), `stat`(권한) |
| `docker compose run api env`, `bash -x`로 스크립트 실행 | 환경변수·도메인 | 스크립트의 ✅/❌·`실패:` 줄과 `logs/*.log` |

- `.env`를 고칠 때만 편집기(`sudo -u deploy nano /opt/scrap-app/.env`)를 연다. 화면 공유·녹화 중에는 열지 않는다.
- 로그(`docker compose logs`, `logs/*.log`)에는 앱과 스크립트가 비밀값을 쓰지 않는다. 도메인이 보이면 가리고 붙인다.
- 판정 줄(✅/❌)은 값을 출력하지 않게 만들어져 있다. 새 확인 명령을 만들 때도 같은 원칙을 따른다.

### 17-2. 이미지 빌드 규칙 (공개 이미지)

GHCR 이미지는 공개다. 누구나 `docker history --no-trunc`, `docker inspect`로 빌드 단계와 환경변수를 볼 수 있다.

- 비밀값을 `--build-arg`(워크플로의 `build-args`), Dockerfile `ARG`·`ENV`로 넣지 않는다. 앱 비밀값은 실행할 때 서버 `.env`로만 전달한다.
- 빌드 인자는 공개값만 쓴다. 지금은 web 이미지의 `VITE_APP_BUILD_ID`(= 커밋 SHA) 하나뿐이다.
- `VITE_`로 시작하는 값은 브라우저 번들에 그대로 들어간다. CI가 허용 목록(`ci.yml`의 `ALLOWED_VITE_VARS`) 밖의 이름을 막는다.
- 이미지에 들어가는 파일은 `.dockerignore`(허용 목록)로 고른다. CI가 web 이미지 안의 `/srv`를 push 전에 꺼내 비밀값 형태를 검사한다 (`deploy/scan-dist.sh`).

---

## 18. AI 운영 (모델·한도·사용량)

설정은 서버 `.env`에 있고, 바꾸면 `rollback.sh current`로 반영한다. 값의 형식이 틀리면 앱은 기본값을 쓴다.

| 이름 | 기본 | 뜻 |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | 쓸 Claude 모델. 비용이 부담되면 더 가벼운 모델 이름으로 바꾼다 |
| `AI_PER_MINUTE` | 10 | 분당 AI 요청 수 (채우기·검색 합산) |
| `AI_PER_DAY` | 200 | 하루(한국 날짜) AI 요청 수 |
| `AI_TOKENS_PER_DAY` | 1000000 | 하루 토큰 예산 (응답의 사용량 합계). 넘으면 그날은 AI가 "오늘 사용량을 모두 썼어요"로 응답 (앱 새 버전부터) |
| `ANTHROPIC_FALLBACKS` | 켜짐 | 0이면 Claude가 안전상 답을 거부했을 때 다른 모델로 다시 처리하지 않는다 |

**바꾸기:**

```bash
sudo -u deploy nano /opt/scrap-app/.env           # 예: 주석(#)을 지우고 AI_PER_DAY=100
E=/opt/scrap-app/.env
chk "AI 한도 값이 정수 (있는 줄만)" sh -c "! sudo grep -E '^(AI_PER_MINUTE|AI_PER_DAY|AI_TOKENS_PER_DAY)=' $E | grep -vqE '=[1-9][0-9]*$'"
chk "모델 줄 형식 (있는 줄만)"      sh -c "! sudo grep -E '^ANTHROPIC_MODEL=' $E | grep -vqE '^ANTHROPIC_MODEL=[a-z0-9.-]+$'"
sudo /opt/scrap-app/deploy/rollback.sh current
```

- 하루 한도에 닿으면 AI 요청은 429(`ai_daily_limit`)로 끝나고 다음 날(한국 자정) 풀린다. 다른 기능은 그대로 된다.
- Anthropic Console의 월 지출 한도는 이 설정과 별개로 둔다 (16-2 6번). 앱 한도는 하루 단위, Console 한도는 달 단위 비용 상한이다.

**사용량 보기:**

```bash
sudo docker compose -f /opt/scrap-app/docker-compose.yml exec -T api python -m app.admin ai-usage --days 14
```

날짜별 요청 수·토큰과 하루 상한이 표로 나온다 (비밀값 없음). `app.admin`이 없는 옛 이미지에서는 요청 수만 이렇게 본다:

```bash
sudo docker compose -f /opt/scrap-app/docker-compose.yml exec -T api python -c "
import sqlite3
c = sqlite3.connect('file:/data/scrap.db?mode=ro', uri=True)
for row in c.execute('SELECT day, count FROM ai_usage_days ORDER BY day DESC LIMIT 14'): print(*row)"
```

비용(금액)은 Anthropic Console의 사용량·비용 화면에서 본다.

---

## 19. 관리 명령: 계정 복구 · 비밀번호 재설정 · 검색 색인

서버에서 api 컨테이너 안의 관리 명령(`python -m app.admin`)을 쓴다. **앱 Phase 8 이후 이미지에만 있다** (옛 버전으로 롤백한 상태에서는 `No module named app.admin`).

```bash
sudo docker compose -f /opt/scrap-app/docker-compose.yml exec api python -m app.admin <명령>
```

- 화면에서 묻는 명령(`reset-2fa`, `set-password`)에는 **`-T`를 붙이지 않는다** (터미널이 아니면 거부하고 종료 코드 2). `docker compose exec`는 기본으로 터미널을 붙이므로 `-it`도 필요 없다.
- 결과만 보는 명령(`fts-check`, `fts-rebuild`, `ai-usage`)은 `-T`를 붙여 스크립트에서도 쓴다.
- **api 컨테이너가 멈춰 있을 때**(`exec`가 "not running"으로 실패): 운영 버전 이미지로 일회용 컨테이너를 띄워 같은 명령을 쓴다. 태그는 `state/current`에서 읽는다.
  ```bash
  A=/opt/scrap-app; SHA=$(sudo cat $A/state/current)
  sudo IMAGE_TAG="$SHA" docker compose -f $A/docker-compose.yml run --rm --no-deps -T api python -m app.admin fts-check
  sudo IMAGE_TAG="$SHA" docker compose -f $A/docker-compose.yml run --rm --no-deps api python -m app.admin reset-2fa   # 대화형: -T 없이 (run 은 기본으로 터미널을 붙인다)
  ```
  그 뒤 api를 다시 올리는 것은 12-6(`rollback.sh current`)으로 한다.
- 종료 코드: 0 정상, 1 실패·이상·취소(아무것도 바꾸지 않음), 2 터미널 아님·설정·DB·사용법 오류, 130 Ctrl+C.
- ⚠️ 바꾸는 명령(`reset-2fa`, `set-password`, `fts-rebuild`) 전에는 백업을 하나 만든다: `sudo -u deploy /opt/scrap-app/deploy/backup.sh` (13-3).
- ⚠️ 화면에 나온 QR·수동 입력 키·복구 코드·새 비밀번호를 채팅·메모 앱·스크린샷에 남기지 않는다. 복구 코드는 비밀번호 관리자에만 옮긴다.

### 19-1. 계정 복구 (인증 앱과 복구 코드를 모두 잃었을 때)

```bash
sudo docker compose -f /opt/scrap-app/docker-compose.yml exec api python -m app.admin reset-2fa
# 밝은 배경 터미널이라 QR이 잘 안 읽히면: ... reset-2fa --light-background
```

1. `yes`로 확인한다.
2. 터미널에 나온 QR을 인증 앱(Google Authenticator 등)으로 찍는다 (안 되면 함께 나온 수동 입력 키를 앱에 입력).
3. 앱의 6자리 코드를 입력한다 (최대 3번).
4. `✅` 줄과 **새 복구 코드 10개**가 한 번만 나온다 → 비밀번호 관리자에 옮긴다. 옛 복구 코드는 더 쓸 수 없다.
5. 모든 기기가 로그아웃된다 → 새 인증 앱 코드로 다시 로그인한다.

### 19-2. 비밀번호 재설정

```bash
sudo docker compose -f /opt/scrap-app/docker-compose.yml exec api python -m app.admin set-password
```

새 비밀번호를 두 번 입력한다 (10자 이상, 화면에 보이지 않는다). 끝나면 모든 기기가 로그아웃된다. 2차 인증은 그대로다.

### 19-3. 검색 색인(FTS) 확인·재구성

검색 결과가 이상하거나(있는 스크랩이 안 나옴), 복원 뒤(15-4)에 확인한다.

```bash
sudo docker compose -f /opt/scrap-app/docker-compose.yml exec -T api python -m app.admin fts-check
```

`✅ 검색 색인 정상: …` 또는 `❌ 검색 색인 이상: … → fts-rebuild 로 다시 만드세요` 한 줄이 나온다 (종료 코드 0/1). ❌면 백업 후 재구성:

```bash
sudo -u deploy /opt/scrap-app/deploy/backup.sh
sudo docker compose -f /opt/scrap-app/docker-compose.yml exec -T api python -m app.admin fts-rebuild
```

재구성 뒤 `fts-check`와 같은 ✅/❌ 줄이 나온다. 재구성은 스크랩 내용으로 색인을 다시 만들 뿐 스크랩은 바꾸지 않는다. 다시 ❌면 그 줄을 마스터에게 알린다.

---

## 20. PWA가 새 버전으로 안 바뀔 때 (서비스워커 해제·강제 갱신)

**평소:** 배포하면 앱이 "새 버전" 안내를 띄운다 → **새로고침**을 누르면 바뀐다. 앱은 열려 있는 동안 주기적으로, 그리고 새로 열 때 새 버전을 확인한다. 아이폰 홈 화면 앱은 앱 전환기에서 위로 밀어 완전히 닫았다가 다시 열면 확인이 빨라진다.

**지금 운영 중인 빌드 확인:**

```bash
H='<이름>.duckdns.org'
chk "사이트에 빌드 식별자 있음" sh -c "curl -s https://$H/ | grep -c 'name=\"app-build\"' | grep -qx 1"
```

앱의 설정 화면 맨 아래 **"앱 빌드"**가 배포한 커밋 SHA 앞 7자(Actions 실행·`state/current`의 앞 7자)와 같으면 새 버전이다.

**안내가 계속 안 뜨거나, 화면이 깨졌을 때 — 그 기기에서만 해제:**

- **아이폰 홈 화면 앱:** 홈 화면 앱은 Safari와 저장소가 따로라, **앱 아이콘을 삭제하면 그 앱의 서비스워커·캐시·로그인 쿠키가 함께 지워진다.**
  1. 홈 화면에서 앱 아이콘 길게 누르기 → 앱 제거 → 홈 화면에서 제거(삭제).
  2. Safari 쪽 데이터도 지운다: 설정 → 앱 → Safari → 고급 → 웹사이트 데이터 → `<이름>.duckdns.org` 검색 → 삭제 (iOS 18 이상 경로).
  3. Safari로 사이트를 열어 로그인 → 공유 → **홈 화면에 추가**. 홈 화면 앱에서 다시 로그인한다 (2차 인증 코드 필요).
- **PC Chrome:** 사이트를 연 채 개발자 도구(F12 / ⌥⌘I) → **Application** → Service workers → **Unregister** → Storage → **Clear site data** → 새로고침. 로그인 쿠키도 지워지므로 다시 로그인한다.
- **PC Safari:** 설정 → 개인정보 보호 → 웹사이트 데이터 관리 → 도메인 검색 → 제거 → 새로고침 후 다시 로그인.

**모든 기기에서 한꺼번에 해제해야 할 때(긴급):** 서버에서 할 일은 없다. 프론트를 서비스워커 자기 해제(`selfDestroying`) 설정으로 한 번 배포하는 PR을 마스터에게 요청한다. `/sw.js` 파일을 지우는 방식은 쓰지 않는다.

---

## 21. GHCR 옛 이미지 보존 정책, 정기 의존성 검사

### 21-1. GHCR 옛 이미지 정리 (월 1회 자동)

워크플로 `.github/workflows/ghcr-cleanup.yml`이 매월 3일에 `scrap-api`·`scrap-web` 패키지의 옛 버전을 지운다.

| 남기는 것 | 이유 |
|---|---|
| 커밋 SHA 태그 버전 중 최근 30개 (패키지마다) | 최근 빌드로의 롤백(12-6 방법 A) |
| production에 최근 배포된 SHA (최근 성공 배포 5개와 그 사이의 모든 배포 기록) | 서버의 현재·직전 버전(`state/current`·`previous`)은 반드시 이 안에 있다 → 지워지지 않는다 |
| 태그 없는 버전, SHA가 아닌 태그가 붙은 버전 | 손대지 않는다 |

- 이미지는 단일 매니페스트(`provenance: false`)라 빌드 1번 = 패키지 버전 1개다. 워크플로가 실행마다 이를 확인하고, 아니면 아무것도 지우지 않는다. production 성공 배포 기록을 2개 이상 찾지 못해도 지우지 않는다. 실제 삭제는 예약 실행이나 `dry_run`을 끈 수동 실행에서만 한다.
- 지운 버전으로는 되돌릴 수 없다 → 그보다 오래된 상태가 필요하면 코드를 되돌리는 PR로 새로 빌드한다.
- 공개 패키지라 누구나 받을 수 있는 옛 버전이 무한히 쌓이지 않게 하려는 정책이다.

**처음 한 번 (GitHub 화면):**
1. 프로필 → Packages → `scrap-api` → Package settings → **Manage Actions access**에서 저장소 `scrap`의 역할이 **Admin**인지 본다 (삭제에 필요). 아니면 Admin으로 바꾼다. `scrap-web`도 같게.
   - 이 역할은 저장소 단위로 적용된다. Admin으로 바꾸면 이 저장소에서 `packages: write` 권한을 받는 모든 잡(이 정리 워크플로와 `deploy.yml`의 `build` 잡)이 패키지 버전 삭제까지 할 수 있게 된다.
2. Actions → **GHCR cleanup** → Run workflow (`dry_run` 체크된 채) → 로그의 `삭제 대상:` 줄과 `남김 N개, 삭제 예정 M개`를 본다. 보호 SHA 줄에 지금 운영 중인 SHA 앞 7자(`sudo cat /opt/scrap-app/state/current | cut -c1-7`)가 있는지 확인한다.

**확인 (PC, `gh` 로그인돼 있을 때):** 버전 수는 패키지 화면(Packages → `scrap-api` → 오른쪽 "versions")에서 본다 (30개 + 보호분).

```bash
R=injae-348/scrap
chk "최근 GHCR cleanup 실행 성공" sh -c "gh run list -R $R -w 'GHCR cleanup' -L 1 --json conclusion --jq '.[0].conclusion' | grep -qx success"
```

실패하면 실행 로그의 `::error::` 줄을 마스터에게 알린다 (삭제 권한이면 위 1번).

### 21-2. 정기 의존성 검사 (주 1회 자동)

워크플로 `.github/workflows/audit.yml`(Dependency audit)이 매주 월요일 백엔드 `pip-audit`과 프론트 `npm audit`(런타임 + 빌드 도구 포함 전체, high 이상)을 돌린다. 시크릿·배포와 무관하다.

- 실패하면 GitHub이 알림을 보낸다. 실패한 단계 이름과 로그의 패키지 이름·권고 ID를 마스터에게 알린다 → 의존성을 올리는 PR로 고친다. PR CI도 같은 검사(npm은 런타임만)로 막힌다.
- 수동 실행: Actions → Dependency audit → Run workflow.
- 저장소에 60일 동안 활동이 없으면 GitHub이 예약 워크플로를 끈다 → Actions 화면에서 다시 켠다 (GHCR cleanup도 같다).
- 저장소 Settings → Code security → **Dependabot alerts / security updates**를 켜 두면 같은 정보를 PR로도 받는다.

```bash
R=injae-348/scrap
chk "최근 Dependency audit 성공" sh -c "gh run list -R $R -w 'Dependency audit' -L 1 --json conclusion --jq '.[0].conclusion' | grep -qx success"
```
