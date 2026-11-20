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
| 배포 후 상태 점검 | 12-4 |
| HTTPS 인증서 문제, 외부에서 접속이 안 됨 | 10 |
| DuckDNS IP 갱신 확인 | 4-4 |
| 서버를 처음부터 다시 만들 때 | 1 → 2 → 3 → 4 → 5 → 6 → 12-0 → 12-1 → 12-2 → 12-3 → 12-4 (아래 "서버를 새로 만들 때") |

### 서버를 새로 만들 때

1. 1·2절로 서버 기본 상태를 확인·설정한다.
2. 3절(배포 사용자·폴더·저장소 파일) → 4절(DuckDNS) → 5절(CI 키 등록) → 6절(`.env`) 순서로 한다.
3. 12-0으로 서버 요구 사항을 확인한다.
4. 새 서버는 호스트 키가 다르므로 12-1 (b)의 `DEPLOY_KNOWN_HOSTS`를 다시 만들어 넣는다 (CI 키를 새로 만들었으면 `DEPLOY_SSH_KEY`도). 12-2 (c)로 접속을 시험한다.
5. 첫 배포: Actions → Deploy → **가장 최근 성공 실행** → `deploy` 잡 **Re-run this job** → 승인 (새 커밋이 없어도 배포할 수 있다. GitHub은 30일이 지난 실행은 다시 실행하지 못하므로, 그때는 작은 PR을 병합해 새 배포를 만든다). `state/current`가 없으므로 DB 백업 없이 첫 배포로 진행되고, web 컨테이너가 인증서를 새로 받는다.
6. 12-4로 확인한다. 이전 서버의 DB를 옮길 때는 첫 배포 전에 `data/scrap.db`(소유 10001, 600)로 넣는다.

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
│   └── rollback.sh                      755   수동 롤백·DB 복원 (사람이 sudo로, 12-6)
├── data/                       APP_UID  700   SQLite → api 컨테이너 /data
├── caddy/                      root     755
│   ├── data/                   root     700   인증서·ACME 계정 → web 컨테이너 /data  (절대 지우지 않음)
│   └── config/                 root     700   Caddy 자동 설정 → web 컨테이너 /config
├── backups/                    deploy   750   predeploy-*.db (600, 배포 직전 자동 백업, 최근 14개) · Phase 8 정기 백업
├── logs/                       deploy   750   duckdns.log, deploy.log
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

CI 키를 교체할 때: 5-1로 새 키 → 5-2로 덮어쓰기(`tee`는 파일을 새로 쓰므로 옛 키는 사라진다) → 12-1 (b)의 `DEPLOY_SSH_KEY` 갱신 → 12-2 (c)로 확인.

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
sudo ls -l /opt/scrap-app/.env                       # -rw------- 1 deploy deploy
sudo grep -E '^SITE_DOMAIN=' /opt/scrap-app/.env     # SITE_DOMAIN=<이름>.duckdns.org
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
| `deploy/logrotate.conf` | `/etc/logrotate.d/scrap-app` | root 644 |

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
chk "logrotate 설치본 = 저장소"           sudo cmp -s $S/deploy/logrotate.conf /etc/logrotate.d/scrap-app
chk "compose root 644"                   test "$(sudo stat -c '%U %a' $A/docker-compose.yml)" = "root 644"
chk "deploy.sh root 755"                 test "$(sudo stat -c '%U %a' $A/deploy/deploy.sh)" = "root 755"
chk "rollback.sh root 755"               test "$(sudo stat -c '%U %a' $A/deploy/rollback.sh)" = "root 755"
chk "state/ deploy 750"                  test "$(sudo stat -c '%U %a' $A/state)" = "deploy 750"
chk "deploy.sh 문법"                      bash -n $A/deploy/deploy.sh
chk "rollback.sh 문법"                    bash -n $A/deploy/rollback.sh
chk "compose 구성 유효 (deploy 권한으로)"  sudo -u deploy -H docker compose -f $A/docker-compose.yml config -q
chk "logrotate 설정 유효"                 sudo logrotate -d /etc/logrotate.d/scrap-app
```

❌가 있으면 그 줄을 마스터에게 알린다. (`compose 구성 유효`는 `.env`를 읽지만 값은 출력하지 않는다.)

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

**방법 A (권장, GitHub이 될 때)** — Actions → Deploy → **되돌릴 버전의 예전 성공 실행** → `deploy` 잡의 **Re-run this job** → 승인. 같은 `deploy.sh` 경로(백업·헬스체크·상태 기록)를 그대로 탄다. GHCR의 옛 이미지는 지우지 않지만, GitHub은 30일이 지난 실행은 다시 실행하지 못한다 → 그보다 오래된 버전은 방법 B (`previous`) 또는 되돌리는 PR로 한다.

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

**⚠️ DB까지 되돌리기 (새 버전이 DB 구조를 바꿔 옛 버전이 못 읽을 때만)** — 그 백업 이후 저장한 스크랩은 사라진다. 위 명령 뒤에 `--restore-db <백업 파일 이름>`을 붙인다. 백업 이름은 (1)의 `백업:` 줄 또는 `sudo ls -l /opt/scrap-app/backups/`에서 고른다 (`predeploy-<UTC 시각>-<그때 운영 중이던 SHA 앞 12자>.db`).

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

정기 백업·외부 복사·복원 절차 전체는 Phase 8에서 이 문서에 추가한다.
