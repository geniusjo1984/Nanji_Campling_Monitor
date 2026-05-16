# 난지캠핑장 바비큐존 예약 알림 봇

서울시 공공서비스예약 사이트에서 `공간시설 > 캠핑장 > 바비큐존` 중 `2차:17시~22시` 예약 가능 여부를 확인하고, 예약 가능한 항목이 생기면 텔레그램으로 알려주는 GitHub Actions용 모니터링 봇입니다.

이 봇은 예약 가능 여부만 확인하고 알림을 보냅니다. 로그인, 예약 신청, 결제는 하지 않습니다.

## 확인 대상

- 난지캠핑장 바비큐존
- 2차 시간대: `17시~22시`
- 4인용, 8인용, 12인용 항목
- 현재 등록된 5월, 6월 서비스 ID
- 검색 결과에서 새로 발견되는 `바비큐존` + `2차:17시~22시` 항목

## 파일 구성

- `monitor.py`: 서울시 예약 페이지를 확인하고 텔레그램 알림을 보내는 메인 스크립트
- `monitor_config.json`: 검색 조건과 기본 확인 대상 서비스 ID 설정
- `state.json`: 마지막 확인 상태 저장 파일, 중복 알림 방지용
- `.github/workflows/camping-monitor.yml`: 10분마다 실행되는 GitHub Actions 워크플로
- `tests/test_monitor.py`: 파서와 알림 로직 테스트

## 텔레그램 봇 준비

1. 텔레그램에서 `@BotFather`를 엽니다.
2. `/newbot` 명령으로 새 봇을 만듭니다.
3. 발급된 봇 토큰을 복사합니다.
4. 새로 만든 봇에게 아무 메시지나 한 번 보냅니다.
5. 아래 주소를 브라우저에서 열되, `<TOKEN>` 부분을 실제 봇 토큰으로 바꿉니다.

   ```text
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

6. 응답 JSON에서 `message.chat.id` 값을 찾습니다. 이 값이 `TELEGRAM_CHAT_ID`입니다.

단체방으로 알림을 받고 싶다면 봇을 단체방에 초대한 뒤, 단체방에 메시지를 하나 보내고 `getUpdates` 결과에서 단체방의 `chat.id`를 사용하면 됩니다.

## GitHub 설정

1. 이 폴더를 GitHub 저장소로 올립니다.
2. GitHub 저장소에서 `Settings > Secrets and variables > Actions`로 이동합니다.
3. `New repository secret`을 눌러 아래 값을 각각 등록합니다.

   ```text
   TELEGRAM_BOT_TOKEN
   TELEGRAM_CHAT_ID
   ```

4. `Actions > Camping availability monitor > Run workflow`에서 수동 실행으로 먼저 테스트합니다.
5. 이후에는 GitHub Actions가 아래 일정으로 자동 실행합니다.

   ```yaml
   cron: "3/10 * * * *"
   ```

이 설정은 매시 `03, 13, 23, 33, 43, 53분`에 실행한다는 뜻입니다. GitHub Actions의 예약 실행은 서버 상황에 따라 몇 분 늦어질 수 있습니다.

## 로컬에서 테스트하기

테스트 실행:

```bash
python -m unittest discover -s tests
```

텔레그램 메시지를 실제로 보내지 않고 알림 내용을 미리 확인:

```bash
python monitor.py --dry-run --state tmp_state.json
```

실제로 텔레그램 알림까지 테스트하려면 환경변수를 설정한 뒤 실행합니다.

PowerShell 예시:

```powershell
$env:TELEGRAM_BOT_TOKEN="봇_토큰"
$env:TELEGRAM_CHAT_ID="채팅_ID"
python monitor.py
```

## 알림 방식

처음 실행했을 때 이미 예약 가능한 항목이 있으면 한 번 알림을 보냅니다. 이후에는 `state.json`에 마지막 상태를 저장해 같은 상태에 대해 반복 알림을 보내지 않습니다.

예약 가능 상태, 버튼 문구, 제목 등이 바뀌면 상태 변경으로 판단하고 다시 알림을 보낼 수 있습니다.

## 주의사항

서울시 공공서비스예약 사이트에는 자동 접근 보호가 적용되어 있습니다. GitHub Actions 로그에 `blocked by the reservation site` 같은 경고가 보이면 사이트가 자동 실행 환경의 접근을 제한한 것입니다.

그 경우에는 실행 주기를 더 길게 조정하거나, GitHub Actions 대신 개인 PC 또는 서버에서 실행하는 방식을 고려해야 합니다.
