# 서버 작업 문서 (Phase 2: 서버 준비)

사람이 서버에서 직접 실행하는 절차서다. **위에서부터 순서대로** 복사해 실행한다.
AI(마스터·서브에이전트)는 서버에 접속하지 않는다. "결과를 마스터에게" 라고 적힌 단계는 출력을 마스터에게 전달한다.

## 읽기 전에

- 대상: Oracle Cloud `VM.Standard.E2.1.Micro` (x86_64), Canonical Ubuntu 24.04, 1 OCPU / RAM 1GB.
- 결정: 앞으로 80/443은 **이 앱의 web 컨테이너(Caddy)**가 맡는다. 기존 앱(`conversation`)과 그 안의 Caddy는 끄고, 기존 앱 데이터는 필요 없으므로 새 HTTPS 확인 뒤 지운다. 인증서는 새로 받는다.
- 데이터(SQLite, Caddy 인증서)는 Docker 볼륨이 아니라 **서버 폴더** `/opt/scrap-app/...`에 저장한다 (3-2).
- 기본 사용자 `ubuntu`로 SSH 접속해 `sudo`로 실행한다고 가정한다.
- `<이름>` = 기존 DuckDNS 서브도메인 (`<이름>.duckdns.org`). `<...>`는 직접 바꿔 넣는다.
- ⚠️ 표시 단계는 **되돌리기 어렵다.** 바로 앞의 백업·확인을 끝낸 뒤 진행한다.
- 이 문서는 공개 저장소에 있다. **공인 IP, 실제 도메인, 토큰, 이메일**을 이 문서나 저장소 파일에 적지 않는다.
- 비밀값(토큰·키)은 `echo 토큰 > 파일`처럼 명령줄에 쓰지 않는다 (셸 기록에 남는다). 이 문서의 방법(붙여넣기 후 Ctrl+D, 편집기)을 쓴다.

## 단계 요약

| 단계 | 내용 | 서비스 중단 | 되돌리기 |
|---|---|---|---|
| 1 | 현황 (확인 완료, 요약) | 없음 | 해당 없음 |
| 2 | 이미 된 것 확인 (스왑·Docker·방화벽 등 체크리스트) | 없음 | 해당 없음 |
| 3 | `deploy` 사용자, `/opt/scrap-app` 구조, 저장소 파일 설치 | 없음 | 쉬움 |
| 4 | DuckDNS IP 자동 갱신 (토큰 파일 + 스크립트 + cron) | 없음 | 쉬움 |
| 5 | CI 전용 SSH 키 등록, SSH 설정 점검 | 없음 | 쉬움 |
| 6 | 서버 `.env` 작성 | 없음 | 쉬움 |
| 7 | ⚠️ 기존 `conversation`: 배포 키 제거 → 기록 → **중지(`down`)** → (선택) 백업 | **시작** | 쉬움 (`up -d`) |
| 8 | 임시 페이지로 새 web Caddy HTTPS 발급 확인 (실패 시 복구) | 계속 | 쉬움 |
| 9 | ⚠️ 정리: 옛 이미지 5개, 볼륨 5개(`conversation_*`, `caddy-test_*`), `/home/ubuntu/conversation` 삭제 | — | **어려움** |
| 10 | 문제 해결 (인증서 발급 실패) | — | — |

> 순서 메모: 사이트가 꺼지는 시간을 줄이려고, 준비(3~6)를 모두 끝낸 뒤 7(기존 앱 중지)과 8(새 Caddy 발급)을 **이어서** 한다.
> 8단계 끝에서 임시 구성을 내리므로, 사이트는 Phase 3 첫 배포 전까지 꺼져 있다. 이 점이 괜찮을 때 7단계를 시작한다.

---

## 1. 현황 (확인 완료)

사용자가 확인해 준 결과다. 다시 확인하려면 맨 아래 명령을 실행한다.

| 항목 | 상태 |
|---|---|
| 아키텍처 | `x86_64` → 이미지 플랫폼 `linux/amd64` |
| 스왑 / 디스크 | 스왑 2G 있음 / 여유 약 37G |
| Docker | Docker + compose 플러그인 설치됨 |
| 80/443 | `docker-proxy`만 사용 (= 기존 앱의 web 컨테이너). **systemd Caddy 없음** (`inactive`, `/etc/caddy` 없음) |
| 기존 앱 | compose 프로젝트 `conversation` (`/home/ubuntu/conversation/docker-compose.yml`) — `conversation-web-1`(Caddy 내장, 80/443), `conversation-api-1`, 둘 다 `restart=unless-stopped` |
| 볼륨 | `conversation_app-data`(기존 앱 데이터), `conversation_caddy-data`, `conversation_caddy-config`, 테스트 잔재 `caddy-test_caddy_data`, `caddy-test_caddy_config` |
| 이미지 | `ghcr.io/injae-348/conversation-api:latest`, `conversation-web:latest`, `nginx:alpine`, `caddy:2-alpine`, `hello-world` |
| 기존 앱 데이터 | **필요 없음** (사용자 결정) → 9단계에서 삭제 |
| `conversation` 배포 워크플로 | 사용자가 GitHub에서 **이미 Disable** 함 |
| cron | 사용자(ubuntu) 크론탭 1줄(DuckDNS 아님), root 크론탭 없음 → **DuckDNS 자동 갱신 없음** |
| 방화벽 | OCI 보안 목록·iptables 80/443 개방됨 |

다시 확인할 때 (읽기 전용):

```bash
uname -m
sudo ss -tlnp | grep -E ':(80|443)\b'
sudo docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
sudo docker volume ls
sudo docker images
crontab -l; sudo crontab -l
```

이 앱의 compose 프로젝트 이름(`scrap-app`, 임시 구성 `scrap-bootstrap`)은 기존 `conversation`, `caddy-test`와 겹치지 않고, 이 앱은 이름 있는 Docker 볼륨을 쓰지 않는다 (데이터는 `/opt/scrap-app` 아래 폴더).

---

## 2. 이미 된 것 확인 (체크리스트)

한 줄씩 실행해 기대값과 같은지 본다. 다르면 그 줄의 결과를 마스터에게 알린다.

| 확인 | 명령 | 기대값 |
|---|---|---|
| 스왑 | `swapon --show` | 약 2G 스왑 한 줄 |
| Docker 실행·부팅 시 시작 | `systemctl is-active docker; systemctl is-enabled docker` | `active`, `enabled` |
| compose 플러그인 | `docker compose version` | `Docker Compose version v2.x` 이상 |
| iptables 80/443 | `sudo iptables -S INPUT \| grep -E 'dport (80\|443)'` | 80, 443 ACCEPT 두 줄 (REJECT 규칙이 없는 이미지면 빈 출력도 정상) |
| 규칙 영구 저장 | `sudo grep -cE -- '--dport (80\|443) ' /etc/iptables/rules.v4` | `2` |
| OCI 보안 목록 | PC에서 `curl -sI http://<이름>.duckdns.org \| head -n 1` | 응답이 옴 (지금은 기존 Caddy가 응답) |
| 자동 보안 업데이트 | `cat /etc/apt/apt.conf.d/20auto-upgrades` | 두 줄 모두 `"1"` |
| 필요한 도구 | `sudo apt-get install -y git curl dnsutils sqlite3 cron` | 오류 없음 (`dig`·DB 백업에 사용) |

- 자동 보안 업데이트가 꺼져 있으면:
  ```bash
  printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' | sudo tee /etc/apt/apt.conf.d/20auto-upgrades
  ```
- Docker 로그 크기 제한(`/etc/docker/daemon.json`)은 Docker 재시작이 필요해서 **7단계에서 기존 컨테이너를 멈춘 뒤** 넣는다.
- ufw는 쓰지 않는다 (OCI 이미지는 `/etc/iptables/rules.v4`로 관리하고, Docker가 게시한 포트는 ufw를 우회한다).

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

> docker 그룹은 사실상 root 권한이다. 그래서 이 사용자의 SSH 키는 5단계에서 **배포 스크립트만 실행하도록 강제**한다.

### 3-2. 디렉터리 구조 (데이터는 서버 폴더에 저장)

**무엇을:** 앱 폴더를 만든다. 데이터는 이름 있는 Docker 볼륨이 아니라 **서버 폴더(bind mount)**에 둔다 — 부트 디스크를 그대로 쓰고, Docker 정리 명령에 지워지지 않으며, 백업이 파일 복사로 끝난다.
compose 파일은 이 폴더들을 **절대경로**로 붙이고, 폴더가 없으면 Docker가 대신 만들지 않고 오류로 멈추게 해 두었다 (`create_host_path: false`). 그래서 여기서 소유권까지 맞춰 만들어야 한다.

```bash
APP_UID=10001     # api 컨테이너 실행 UID. Phase 3 Dockerfile에서 확정되면 그 값으로 (다르면 아래 chown만 다시)

# 스크립트·설정: root 소유 (deploy가 고칠 수 없음)
sudo install -d -m 755 -o root   -g root   /opt/scrap-app /opt/scrap-app/deploy /opt/scrap-app/caddy
# SQLite: api 컨테이너(non-root, APP_UID)만 읽고 쓴다
sudo install -d -m 700 -o "$APP_UID" -g "$APP_UID" /opt/scrap-app/data
# Caddy 인증서·설정: caddy 공식 이미지는 root로 실행 → root 소유, 인증서 개인키가 있으므로 700
sudo install -d -m 700 -o root   -g root   /opt/scrap-app/caddy/data /opt/scrap-app/caddy/config
# 백업·로그·DuckDNS 토큰: deploy 사용자(배포 스크립트·cron)가 쓴다
sudo install -d -m 750 -o deploy -g deploy /opt/scrap-app/backups /opt/scrap-app/logs
sudo install -d -m 700 -o deploy -g deploy /opt/scrap-app/duckdns

sudo ls -la /opt/scrap-app /opt/scrap-app/caddy
```

**확인:** 아래 표와 소유자·권한이 같다 (`data`의 소유자는 이름 대신 숫자 `10001`로 보이는 것이 정상).

최종 구조 (Phase 3 이후 포함):

```
/opt/scrap-app/                 root     755
├── docker-compose.yml          root     644   운영 구성 (저장소의 docker-compose.yml)
├── .env                        deploy   600   서버에서 직접 작성 (6단계)
├── deploy/                     root     755   스크립트 (deploy가 고칠 수 없음)
│   ├── duckdns-update.sh                755
│   ├── deploy.sh                        755   (Phase 3)
│   └── bootstrap/                             8단계 임시 구성
├── data/                       APP_UID  700   SQLite → api 컨테이너 /data
├── caddy/                      root     755
│   ├── data/                   root     700   인증서·ACME 계정 → web 컨테이너 /data  (절대 지우지 않음)
│   └── config/                 root     700   Caddy 자동 설정 → web 컨테이너 /config
├── backups/                    deploy   750   DB 백업 (Phase 3·8)
├── logs/                       deploy   750   duckdns.log, deploy.log
├── duckdns/                    deploy   700   token(600), domain
└── src/                        root           저장소 사본 (파일 설치용)
```

> `data/`를 APP_UID 전용(700)으로 두므로, 배포 직전 DB 백업을 호스트의 `deploy` 사용자가 어떻게 읽을지(컨테이너 안에서 백업 등)는 Phase 3 `deploy.sh`에서 정한다.

### 3-3. 저장소 파일 설치

**무엇을:** 공개 저장소를 받아 필요한 파일만 정해진 위치에 복사한다 (서버에서 빌드하지 않는다).

```bash
REPO_URL="https://github.com/injae-348/scrap.git"
BRANCH="main"      # Phase 2 PR이 아직 병합 전이면 "feat/phase2-server"

sudo git clone --depth 1 --branch "$BRANCH" "$REPO_URL" /opt/scrap-app/src

sudo install -m 644 -o root -g root /opt/scrap-app/src/docker-compose.yml       /opt/scrap-app/docker-compose.yml
sudo install -m 755 -o root -g root /opt/scrap-app/src/deploy/duckdns-update.sh /opt/scrap-app/deploy/duckdns-update.sh
sudo install -d -m 755 -o root -g root /opt/scrap-app/deploy/bootstrap
sudo install -m 644 -o root -g root /opt/scrap-app/src/deploy/bootstrap/docker-compose.yml /opt/scrap-app/deploy/bootstrap/docker-compose.yml
sudo install -m 644 -o root -g root /opt/scrap-app/src/deploy/bootstrap/Caddyfile          /opt/scrap-app/deploy/bootstrap/Caddyfile
sudo install -m 644 -o root -g root /opt/scrap-app/src/deploy/logrotate.conf    /etc/logrotate.d/scrap-app

sudo ls -la /opt/scrap-app /opt/scrap-app/deploy /opt/scrap-app/deploy/bootstrap
sudo logrotate -d /etc/logrotate.d/scrap-app 2>&1 | tail -n 5
```

**확인:** 파일이 위 구조대로 있고, `logrotate -d`(시험 실행) 출력에 `error`가 없다.

> 저장소에서 이 파일들이 바뀌면 `sudo git -C /opt/scrap-app/src pull --ff-only` 후 위 `install` 줄을 다시 실행한다. (Phase 3에서 갱신 방식을 정리한다.)

---

## 4. DuckDNS IP 자동 갱신

도메인은 이미 있으므로 새로 발급하지 않는다. 토큰 파일 + 갱신 스크립트 + cron만 설정한다.

### 4-1. 토큰 확인 (브라우저)

1. https://www.duckdns.org 에 기존 계정으로 로그인
2. 도메인 목록에서 `<이름>`의 `current ip`가 서버 공인 IP(OCI 콘솔 → 인스턴스 상세 → 공용 IP 주소)인지 본다
3. 페이지 상단의 **token**을 복사한다. **비밀값이다.** 저장소·채팅·스크린샷에 남기지 않는다.

### 4-2. 서브도메인 이름과 토큰을 서버에 저장

```bash
echo '<이름>' | sudo -u deploy tee /opt/scrap-app/duckdns/domain >/dev/null

sudo -u deploy sh -c 'umask 077; cat > /opt/scrap-app/duckdns/token'
# ↑ 실행 후 커서가 멈추면: 토큰을 붙여넣고 → Enter → Ctrl+D

sudo ls -l /opt/scrap-app/duckdns
```

**확인:** `token`이 `-rw------- 1 deploy deploy`, `sudo cat /opt/scrap-app/duckdns/domain`이 `<이름>`. **token 파일은 `cat`으로 출력하지 않는다.**

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

**확인 (5분 이상 지난 뒤):**

```bash
sudo tail -n 3 /opt/scrap-app/logs/duckdns.log                               # OK 줄이 쌓인다
sudo grep -cFf /opt/scrap-app/duckdns/token /opt/scrap-app/logs/duckdns.log  # 0 (로그에 토큰 없음)
dig +short <이름>.duckdns.org @1.1.1.1                                         # 서버 공인 IP
curl -4s https://checkip.amazonaws.com                                        # 위와 같은 IP
```


## 5. CI 전용 SSH 키 등록, SSH 설정 점검

> 배포 스크립트(`deploy.sh`)는 Phase 3에서 만든다. **지금은 공개키를 강제 명령과 함께 등록만** 하고, 실제 접속 동작은 Phase 3에서 확인한다 (지금 이 키로 접속하면 스크립트가 없어 실패하는 것이 정상).

### 5-1. 키 생성 — **사용자 PC에서** (서버 아님)

**무엇을:** GitHub Actions 전용 키를 새로 만든다. 개인 키를 재사용하지 않는다. CI가 쓰므로 암호(passphrase)는 비운다.

```bash
# PC 터미널. 저장소 폴더 안에 만들지 않는다.
ssh-keygen -t ed25519 -a 100 -N '' -C 'scrap-ci-deploy' -f ~/.ssh/scrap_ci_deploy
cat ~/.ssh/scrap_ci_deploy.pub
```

**확인:** `ssh-ed25519 AAAA... scrap-ci-deploy` 한 줄. 이 **공개키(.pub)**만 서버에 등록한다.
개인키 `~/.ssh/scrap_ci_deploy`는 Phase 3에서 GitHub `production` Environment 시크릿 `DEPLOY_SSH_KEY`에 넣는다. 그 전까지 PC에만 두고 저장소·채팅에 붙이지 않는다.

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

### 5-3. SSH 비밀번호 로그인이 꺼져 있는지 확인

```bash
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication) '
```

**확인:** `passwordauthentication no`, `kbdinteractiveauthentication no`, `pubkeyauthentication yes`, `permitrootlogin`은 `no` 또는 `without-password`.

다르면 아래를 실행한다. **⚠️ 지금 접속한 창은 닫지 말고**, 새 터미널에서 `ubuntu`로 키 로그인이 되는지 확인한 뒤 닫는다.

```bash
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' \
  | sudo tee /etc/ssh/sshd_config.d/00-scrap-hardening.conf
sudo sshd -t && sudo systemctl restart ssh
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin) '
```

(`sshd_config.d`의 파일은 이름 순으로 읽고 **먼저 나온 값이 우선**이라 `00-`으로 시작한다.)

### 5-4. (Phase 3 준비) 서버 호스트 키 확인

Phase 3 시크릿 `DEPLOY_KNOWN_HOSTS`에 쓸 값이다. 서버에서 직접 읽으므로 중간자 공격 걱정이 없다. 지금은 확인만 한다.

```bash
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

`known_hosts` 한 줄 형식: `<접속 주소> ssh-ed25519 AAAA...` (`<접속 주소>`는 `DEPLOY_HOST`와 같은 값).

---

## 6. 서버 `.env` 작성

**무엇을:** 저장소의 `.env.example`을 복사해 서버에서 직접 채운다. 권한 600, 소유자 `deploy`. GitHub·저장소에는 넣지 않는다.

```bash
sudo install -m 600 -o deploy -g deploy /opt/scrap-app/src/.env.example /opt/scrap-app/.env
openssl rand -hex 32        # 출력값을 SESSION_SECRET 에 붙여넣는다
sudo -u deploy nano /opt/scrap-app/.env
```

| 이름 | Phase 2에서 넣을 값 |
|---|---|
| `SITE_DOMAIN` | `<이름>.duckdns.org` |
| `SESSION_SECRET` | 위 `openssl rand -hex 32` 출력 |
| `ACME_CA` | 주석 그대로 (10단계에서 시험할 때만 사용) |
| `IMAGE_TAG`, `ANTHROPIC_API_KEY` 등 | 지금은 예시값 그대로 (Phase 3·7에서 채움) |

nano 저장: Ctrl+O → Enter, 종료: Ctrl+X.

**확인:**

```bash
sudo ls -l /opt/scrap-app/.env                       # -rw------- 1 deploy deploy
sudo grep -E '^SITE_DOMAIN=' /opt/scrap-app/.env     # SITE_DOMAIN=<이름>.duckdns.org
```

---

## 7. ⚠️ 기존 `conversation`: 배포 키 제거 → 기록 → 중지 → (선택) 백업

> **⚠️ 주의 — 여기서부터 기존 사이트가 꺼진다.**
> - 이 단계에서는 **데이터를 지우지 않는다.** `docker compose down`은 컨테이너·네트워크만 지우고 **볼륨과 이미지는 남긴다** (`-v`를 붙이지 않는 한). 그래서 같은 파일로 `up -d` 하면 그대로 되살아난다.
> - **`down -v` 는 절대 쓰지 않는다** (기존 앱 데이터 볼륨이 지워진다).
> - 기존 앱 데이터는 필요 없다(사용자 결정). 백업(7-6)은 혹시 몰라 하는 **선택** 단계이고, 실제 삭제는 8단계 성공 뒤 9단계에서 한다.
> - 7단계를 끝냈으면 바로 8단계로 넘어간다 (중단 시간 최소화).

### 7-1. 변수와 백업 디렉터리

```bash
C=/home/ubuntu/conversation/docker-compose.yml
B=/root/backup-$(date +%Y%m%d)
sudo install -d -m 700 -o root -g root "$B"
sudo ls -ld "$B"
```

**확인:** `drwx------ ... root root ... /root/backup-YYYYMMDD`.
접속이 끊겨 다시 들어왔으면 `C=...`와 `B=/root/backup-YYYYMMDD`(같은 날짜)를 다시 실행하고 이어서 한다.

### 7-2. ⚠️ `conversation` 배포 키 제거 (중지 전에)

**왜:** `conversation` 저장소의 GitHub Actions 배포가 이 서버로 다시 배포하면 컨테이너가 되살아나 80/443을 빼앗는다. 워크플로는 이미 꺼졌으므로, 그 배포가 쓰던 SSH 키도 서버에서 빼서 실수로 다시 켜지더라도 접속하지 못하게 한다.

**(a) 배포 워크플로 꺼짐 확인 — 완료됨**

- [x] `conversation` 저장소 → Actions → 배포 워크플로 **Disable** (사용자가 이미 완료)
- [ ] 확인만: 같은 화면에 진행 중(노란 점)인 실행이 없다. 있으면 들어가서 **Cancel workflow**.

그 워크플로 파일(`.github/workflows/*.yml`)에서 **어느 사용자로 접속하는지**(`username:`·`DEPLOY_USER` 같은 값)를 봐 두면 (b)에서 어느 `authorized_keys`를 볼지 정하기 쉽다.

**(b) 그 배포용 SSH 키 찾기 — 서버 (읽기 전용)**

```bash
# 1) 서버의 authorized_keys 파일들과 각 줄의 지문(fingerprint)·주석
for f in /home/*/.ssh/authorized_keys /root/.ssh/authorized_keys; do
  sudo test -f "$f" || continue
  echo "== $f"
  n=0
  while IFS= read -r line; do
    n=$((n+1))
    case "$line" in ''|'#'*) continue ;; esac
    printf '줄 %s: %s...  →  ' "$n" "$(printf '%s' "$line" | cut -c1-40)"
    printf '%s\n' "$line" | ssh-keygen -lf -
  done < <(sudo cat "$f")
done

# 2) 최근 SSH 키 로그인 기록: (사용자, 접속 IP, 키 지문)별 횟수
sudo zgrep -h 'Accepted publickey' /var/log/auth.log* 2>/dev/null \
  | grep -oE 'for [^ ]+ from [^ ]+ .*SHA256:[^ ]+' \
  | awk '{print $2, $4, $NF}' | sort | uniq -c
# (출력이 비어 있으면 저널에서: sudo journalctl _COMM=sshd --since "-90d" --no-pager | grep 'Accepted publickey')

# 3) 지금 내가 접속한 IP (내 키를 구별하는 데 사용)
echo "$SSH_CONNECTION" | awk '{print "내 접속 IP:", $1}'
```

**어떤 키인지 판단하는 법:**

- **내 키(지우면 안 됨):** 2)에서 *내 접속 IP*로 로그인한 줄의 지문. PC에서 `ssh-keygen -lf ~/.ssh/<내 키 파일>.pub`로 나오는 지문과도 같다.
- **conversation 배포 키(지울 대상):** 2)에서 *내 IP가 아닌 여러 IP*(GitHub Actions 실행기)로 반복 로그인한 지문. 주석(`... (ED25519)` 앞 부분)에 `github`, `actions`, `deploy`, `conversation` 같은 단어가 있는 경우가 많다.
- ⚠️ **배포 키와 내 키의 지문이 같다면**(내 개인 키를 conversation 배포에 재사용한 경우) **지우지 않는다** — 지우면 나도 못 들어온다. 이 경우 지금은 그대로 두고 마스터에게 알린다 (내 키를 새로 만들어 교체하는 절차를 따로 정한다). 워크플로가 꺼져 있으므로 당장 배포가 되살아나지는 않는다.
- 판단이 서지 않으면 1)·2) 결과를 (IP는 가리고) 마스터에게 붙이고 기다린다.

**(c) 그 키 줄 지우기**

> ⚠️ 지금 접속한 창은 닫지 않는다. 지운 뒤 **새 터미널에서 내 키로 접속되는지 확인**하고 나서 닫는다.

```bash
F=/home/ubuntu/.ssh/authorized_keys     # (b)에서 그 키가 있던 파일
N=<지울 줄 번호>                         # (b)의 "줄 N"

sudo cp -a "$F" "$B/authorized_keys-$(sudo stat -c %U "$F").bak"   # 백업 (복구용)
sudo sed -n "${N}p" "$F" | ssh-keygen -lf -                          # 지울 키가 맞는지 마지막 확인
sudo sed -i "${N}d" "$F"
sudo ls -l "$F"                                                      # 소유자·권한(600) 그대로인지
sudo ssh-keygen -lf "$F"                                             # 남은 키 목록 — 내 키가 남아 있어야 함
```

**확인:** 새 터미널에서 `ssh ubuntu@<서버 주소>`가 된다. 남은 목록에 배포 키 지문이 없다.
(선택) `conversation` 저장소 Settings → Secrets and variables → Actions에서 그 배포용 시크릿(SSH 키·호스트)도 지운다.

### 7-3. 현재 상태 기록 (복구·정리 판단용)

```bash
sudo docker compose -f "$C" ps -a | sudo tee "$B/conversation-ps.txt"
for c in conversation-web-1 conversation-api-1; do
  sudo docker inspect "$c" | sudo tee "$B/inspect-$c.json" >/dev/null
done
sudo docker images    | sudo tee "$B/images.txt"  >/dev/null
sudo docker volume ls | sudo tee "$B/volumes.txt" >/dev/null
crontab -l 2>&1       | sudo tee "$B/crontab-ubuntu.txt" >/dev/null
crontab -l
```

**확인:** 마지막 줄에 사용자 크론탭 1줄이 보인다. 그 줄이 `conversation`과 관련된 작업(예: 그 앱 백업·재시작)이면 9-3에서 함께 정리한다. 관련 없으면 그대로 둔다.

### 7-4. 중지: `docker compose down` (볼륨 유지)

```bash
sudo docker compose -f "$C" down          # ⚠️ -v 붙이지 않음
sudo docker ps -a --format 'table {{.Names}}\t{{.Status}}'
```

**확인:** `conversation-web-1`, `conversation-api-1`이 목록에 없다. `sudo docker volume ls`에 `conversation_*` 볼륨 3개는 **그대로 있다.**

### 7-5. 포트 80/443이 비었는지 확인

```bash
sudo ss -tlnp | grep -E ':(80|443)\b' || echo "80/443 비어 있음"
```

**확인:** `80/443 비어 있음`. 무언가 남아 있으면 그 프로세스 이름을 마스터에게 알리고, 필요하면 8-5로 복구한다.

### 7-6. (선택) 데이터 백업 (멈춘 상태에서)

**선택 단계다.** 기존 앱 데이터는 필요 없지만, 9단계에서 지우기 전에 혹시 몰라 남겨 두는 용도다. 건너뛰어도 8단계로 갈 수 있다.

**무엇을:** 볼륨 3개는 읽기 전용으로 붙인 임시 `alpine` 컨테이너로 tar하고, `/home/ubuntu/conversation/`(compose 파일·Caddyfile·`.env`가 있을 수 있음)를 tar한다. 모든 백업 파일은 **root 소유, 권한 600**.

```bash
for v in conversation_app-data conversation_caddy-data conversation_caddy-config; do
  # 없는 이름으로 docker run -v 하면 빈 볼륨이 새로 생기므로 먼저 존재 확인
  sudo docker volume inspect "$v" >/dev/null || { echo "볼륨 없음: $v — 중단"; break; }
  sudo docker run --rm -v "$v":/v:ro -v "$B":/b alpine:3.24 tar czf "/b/vol-$v.tar.gz" -C /v .
done

sudo du -sh /home/ubuntu/conversation
sudo tar -czpf "$B/conversation-dir.tar.gz" -C /home/ubuntu conversation

sudo chown root:root "$B"/*
sudo chmod 600 "$B"/*
sudo ls -l "$B"
```

**확인:**

```bash
for f in "$B"/vol-*.tar.gz "$B"/conversation-dir.tar.gz; do
  echo "== $f  ($(sudo du -h "$f" | cut -f1))"; sudo tar -tzf "$f" | head -n 10
done
```

- 모든 파일이 `-rw------- root root`이고 크기가 0이 아니다.
- `vol-conversation_app-data.tar.gz` 목록에 기존 앱 데이터 파일이 보인다.
- `vol-conversation_caddy-data.tar.gz` 목록에 `./caddy/certificates/...`가 보인다.
- `conversation-dir.tar.gz` 목록에 `conversation/docker-compose.yml`이 보인다.

### 7-7. Docker 로그 크기 제한 (아직 없을 때만)

**무엇을:** 실행 중인 컨테이너가 없는 지금 넣는다 (Docker 재시작 필요). 컨테이너 로그를 파일당 10MB × 3개로 제한한다.

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

## 8. 첫 확인: 새 web Caddy로 HTTPS 발급

**무엇을:** 아직 GHCR 이미지가 없으므로 공식 `caddy` 이미지 + 임시 응답(`deploy/bootstrap/`, 프로젝트 이름 `scrap-bootstrap`)으로 `https://<이름>.duckdns.org` 인증서를 서버 폴더 `/opt/scrap-app/caddy/data`에 받는다. Phase 3 운영 구성이 같은 폴더를 붙이므로 이 인증서를 그대로 이어 쓴다.

### 8-1. 실행

```bash
cd /opt/scrap-app
sudo -u deploy -H docker compose -f deploy/bootstrap/docker-compose.yml --env-file .env up -d
sudo -u deploy -H docker compose -f deploy/bootstrap/docker-compose.yml --env-file .env logs -f web
```

**확인 (로그):** 1~2분 안에 `certificate obtained successfully`. 확인되면 Ctrl+C (컨테이너는 계속 실행). `error`가 반복되면 10단계로 — 바로 고치기 어려우면 8-5로 기존 사이트를 복구한다.

### 8-2. PC에서 접속 확인

- 브라우저(시크릿 창)로 `https://<이름>.duckdns.org` → "HTTPS 확인용 임시 페이지입니다." + 자물쇠
- PC 터미널:

```bash
curl -sI http://<이름>.duckdns.org | head -n 3       # 308 → https://
curl -sI https://<이름>.duckdns.org | head -n 5      # HTTP/2 200, strict-transport-security 헤더
echo | openssl s_client -connect <이름>.duckdns.org:443 -servername <이름>.duckdns.org 2>/dev/null \
  | openssl x509 -noout -issuer -dates                # Let's Encrypt, (STAGING) 없음
```

### 8-3. 임시 구성 내리기

```bash
cd /opt/scrap-app
sudo -u deploy -H docker compose -f deploy/bootstrap/docker-compose.yml --env-file .env down
sudo find /opt/scrap-app/caddy/data/caddy/certificates -name '*.crt'
```

**확인:** `.../acme-v02.api.letsencrypt.org-directory/<이름>.duckdns.org/<이름>.duckdns.org.crt`가 나온다 (인증서가 서버 폴더에 남음).
이후 사이트는 Phase 3 첫 배포 전까지 꺼져 있는 것이 정상이다.

### 8-4. 성공했으면

9단계(정리)로 간다.

### 8-5. 실패해서 기존 사이트로 되돌릴 때 (복구)

```bash
cd /opt/scrap-app
sudo -u deploy -H docker compose -f deploy/bootstrap/docker-compose.yml --env-file .env down
sudo docker compose -f /home/ubuntu/conversation/docker-compose.yml up -d
sudo docker compose -f /home/ubuntu/conversation/docker-compose.yml ps
sudo ss -tlnp | grep -E ':(80|443)\b'
```

**확인:** 두 컨테이너가 `Up`이고 80/443을 `docker-proxy`가 잡는다. PC 브라우저에서 기존 사이트가 열린다. 재시작 정책(`unless-stopped`)은 compose 파일에 있는 값으로 다시 만들어진다.
(7-2에서 끈 `conversation` 자동 배포·지운 키는 되돌리지 않아도 기존 사이트는 동작한다. 정말 필요하면 워크플로를 Enable하고 `$B/authorized_keys-*.bak`의 그 줄을 다시 넣는다.)
그 뒤 10단계 결과와 함께 마스터에게 알린다.

---

## 9. ⚠️ 정리 (8단계 성공 후)

> **⚠️ 주의 — 되돌리기 어렵다.**
> - 8단계 HTTPS 확인이 성공한 뒤에만 한다. 이 단계 후에는 8-5 복구(기존 사이트 되살리기)를 할 수 없다.
> - 기존 앱 데이터는 필요 없다는 사용자 결정에 따라 `conversation_*` 볼륨과 폴더까지 지운다.
> - **`/opt/scrap-app` 아래 폴더(특히 `caddy/data` 인증서, `data` DB)는 절대 지우지 않는다.** 이 앱은 Docker 볼륨을 쓰지 않으므로 아래 볼륨 삭제와 무관하다.

### 9-1. (선택) 백업을 PC로 복사

7-6 백업을 했고 서버 밖에도 두고 싶을 때만. 서버에서:

```bash
B=/root/backup-YYYYMMDD     # 7-1의 실제 날짜로
sudo tar -czf /tmp/server-backup.tar.gz -C /root "$(basename "$B")"
sudo chown ubuntu:ubuntu /tmp/server-backup.tar.gz
chmod 600 /tmp/server-backup.tar.gz
```

PC에서 (저장소 폴더 **밖**에 — 옛 인증서 개인키, 옛 앱 `.env`가 들어 있을 수 있다):

```bash
mkdir -p ~/scrap-server-backup && chmod 700 ~/scrap-server-backup
scp ubuntu@<서버 주소>:/tmp/server-backup.tar.gz ~/scrap-server-backup/
tar -tzf ~/scrap-server-backup/server-backup.tar.gz
```

그 뒤 서버 임시 파일 삭제: `rm /tmp/server-backup.tar.gz`

### 9-2. 남은 컨테이너 확인

```bash
sudo docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

**확인:** `conversation-*` 컨테이너가 없다 (7-4에서 `down`으로 지워짐). 옛 테스트 컨테이너(예: `hello-world`, `nginx`, `caddy-test` 계열)가 멈춘 채 남아 있으면 이름을 확인하고 지운다:

```bash
sudo docker rm <남은 옛 컨테이너 이름들>
```

### 9-3. 옛 이미지 5개 삭제

```bash
sudo docker images                                   # conversation-web 의 정확한 REPOSITORY 확인
sudo docker image rm \
  ghcr.io/injae-348/conversation-api:latest \
  <conversation-web 이미지 REPOSITORY>:latest \
  nginx:alpine caddy:2-alpine hello-world
```

`image is being used by stopped container <ID>` 오류가 나면 `sudo docker ps -a --filter id=<ID>`로 무엇인지 보고, 옛 컨테이너가 맞으면 `sudo docker rm <ID>` 후 다시 실행한다.

### 9-4. 옛 볼륨 5개 삭제

```bash
sudo docker volume ls
for v in conversation_app-data conversation_caddy-data conversation_caddy-config caddy-test_caddy_data caddy-test_caddy_config; do
  echo "== $v 를 쓰는 컨테이너:"; sudo docker ps -a --filter volume="$v" --format '{{.Names}}'
done
```

**확인:** 각 볼륨 아래에 컨테이너 이름이 하나도 나오지 않는다 (나오면 그 컨테이너를 먼저 9-2처럼 지운다). 그 다음:

```bash
sudo docker volume rm conversation_app-data conversation_caddy-data conversation_caddy-config \
                      caddy-test_caddy_data caddy-test_caddy_config
sudo docker volume ls
```

### 9-5. 옛 앱 폴더와 cron 삭제

```bash
ls -la /home/ubuntu/conversation                     # 지울 폴더가 맞는지 확인
sudo rm -rf /home/ubuntu/conversation
crontab -l                                           # 7-3에서 본 줄이 conversation용이면:
# crontab -e 로 그 줄을 지운다 (관련 없는 작업이면 그대로 둔다)
```

### 9-6. (선택) 백업 파일 삭제

7-6에서 만든 서버 백업이 더는 필요 없으면 지운다 (9-1로 PC에 옮겼다면 PC 사본은 그대로 둔다).

```bash
sudo ls -la /root/ | grep backup-
sudo rm -rf /root/backup-YYYYMMDD                    # ⚠️ 실제 날짜로. 7-2의 authorized_keys 백업도 함께 지워진다
```

(선택) 확인용으로 받은 `alpine:3.24` 이미지도 지워도 된다: `sudo docker image rm alpine:3.24`. `caddy:2.11.4-alpine`은 Phase 3까지 둔다 (10단계 시험용).

### 9-7. 일괄 삭제 명령에 대해 (선택, 권장하지 않음)

위처럼 이름을 확인하며 지우는 것을 권장한다. 일괄 명령을 쓰고 싶다면 위험을 알고 쓴다.

| 명령 | 지우는 것 | 위험 |
|---|---|---|
| `sudo docker image prune -a` | 어떤 컨테이너도 쓰지 않는 **모든** 이미지 | 낮음. 지금은 실행 중인 컨테이너가 없어 **모든 이미지**가 지워진다 (필요하면 다시 받으면 됨) |
| `sudo docker system prune -a` | 멈춘 컨테이너 전부, 안 쓰는 네트워크·이미지·빌드 캐시 | 중간. **멈춰 둔 컨테이너가 확인 없이 사라진다** (앞으로 롤백용으로 남겨 둔 것 포함) |
| `sudo docker volume prune -a`, `sudo docker system prune -a --volumes` | 컨테이너에 연결되지 않은 **모든** 볼륨 | 높음. 지금은 지울 볼륨만 남아 있어 결과는 같지만, 습관이 되면 나중에 필요한 볼륨을 확인 없이 지운다. 이 앱 데이터는 폴더라 영향 없음 |

### 9-8. 확인

```bash
sudo docker ps -a
sudo docker images
sudo docker volume ls
sudo ls -la /opt/scrap-app/caddy/data                # 인증서 폴더가 그대로 있다
sudo ss -tlnp | grep -E ':(80|443)\b' || echo "80/443 비어 있음 (Phase 3 배포 전 정상)"
df -h /
```

---

## 10. 문제 해결: 인증서 발급 실패

로그: `sudo -u deploy -H docker compose -f /opt/scrap-app/deploy/bootstrap/docker-compose.yml --env-file /opt/scrap-app/.env logs --tail 100 web`

차례대로 확인한다.

1. **DNS:** `dig +short <이름>.duckdns.org @1.1.1.1`가 서버 공인 IP인가? 아니면 4-3(스크립트)을 다시 실행하고 몇 분 기다린다.
2. **포트:** 컨테이너 시작 시 `port is already allocated`가 나오면 기존 컨테이너가 아직 실행 중이다 → `sudo docker ps`, `sudo docker compose -f /home/ubuntu/conversation/docker-compose.yml ps`. 7-2의 자동 배포가 다시 띄웠을 수도 있다 (워크플로가 꺼졌는지 다시 확인).
3. **OCI 보안 목록 / NSG:** TCP 80·443 수신 규칙이 있는가? (기존 Caddy가 동작했으므로 보통 문제없다)
4. **서버 iptables:** `sudo iptables -L INPUT -n -v --line-numbers`에서 80/443 ACCEPT가 REJECT보다 위인가? `sudo iptables -S FORWARD | head`에서 Docker 체인(`DOCKER-USER` 등)이 REJECT보다 위인가? (Docker가 게시한 포트는 FORWARD 체인을 지난다. 아니면 `sudo systemctl restart docker`로 Docker가 자기 규칙을 다시 맨 위에 넣게 한다.)
5. **바깥에서 80번 (PC에서):** `curl -sI http://<이름>.duckdns.org` — 시간 초과면 3·4번 문제, 응답이 오면 방화벽은 정상.
6. **Let's Encrypt 발급 제한:** 로그에 `rateLimited` / `too many`가 보이면 제한에 걸린 것이다. 같은 이름의 인증서는 일주일에 5번, 검증 실패는 시간당 5번까지다 (기존 Caddy가 받은 인증서도 같은 이름이라 횟수에 포함된다). 이때는 **반복 재시작을 멈추고**, 8-5로 기존 사이트를 복구한 뒤 아래 staging으로 원인을 고치고 로그에 나온 대기 시간이 지난 뒤 다시 한다.
   (`duckdns.org`는 공개 접미사 목록에 있어 다른 DuckDNS 사용자와 제한을 공유하지 않는다.)

### staging CA로 시험하기 (발급 제한 걱정 없이)

```bash
sudo -u deploy nano /opt/scrap-app/.env
#   ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory   ← 줄 앞의 # 를 지운다
cd /opt/scrap-app
sudo -u deploy -H docker compose -f deploy/bootstrap/docker-compose.yml --env-file .env up -d --force-recreate
sudo -u deploy -H docker compose -f deploy/bootstrap/docker-compose.yml --env-file .env logs -f web
```

staging 인증서는 브라우저가 신뢰하지 않으므로(경고가 정상) `certificate obtained successfully` 로그와 `openssl ... -issuer`의 `(STAGING)`으로 확인한다.
성공하면 `.env`의 `ACME_CA` 줄을 **다시 주석 처리**하고 `up -d --force-recreate`로 운영 인증서를 받는다 (CA별로 `/opt/scrap-app/caddy/data/caddy/certificates/<CA 이름>/`에 따로 저장되어 섞이지 않는다).

그래도 안 되면 로그 100줄과 1·2·4번 결과를 (IP·도메인은 가리고) 마스터에게 붙인다.

---

## 다음 (Phase 3에서 할 서버 작업 예고)

- GHCR 이미지 pull용 읽기 전용 토큰(`read:packages`)으로 `deploy` 사용자에서 `docker login ghcr.io` 한 번
- `deploy/deploy.sh` 설치 후 5단계 키로 배포 접속 확인
- api 컨테이너 실행 UID가 `10001`이 아니면 `sudo chown <UID>:<UID> /opt/scrap-app/data`
- 배포 직전 DB 백업 방식 확정 (`data/`가 APP_UID 전용이므로)
