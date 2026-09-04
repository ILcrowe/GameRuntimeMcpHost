# Unity C# 런타임 어댑터 샘플

[English guide](README.md)

이 샘플은 GameRuntimeMcpHost 연결 중 게임이 소유하는 절반입니다. 토큰 인증 숫자형 루프백 endpoint를 열고, 리스너 스레드에서 받은 요청을 큐에 넣은 뒤 Unity 메인 스레드에서 처리합니다.

## 요구사항

- Unity 2022.3 LTS 이상
- `HttpListener`를 지원하는 데스크톱 타깃. WebGL 제외
- GameRuntimeMcpHost 실행용 Python 3.10 이상

Unity와 .NET API만 사용합니다. 별도 JSON 패키지나 Unity CLI는 필요하지 않습니다.

## 설정

1. [`Runtime`](Runtime)을 Unity 프로젝트의 `Assets/GameRuntimeMcpHostSample/Runtime`으로 복사합니다.
2. 부트 씬 또는 부트 프리팹의 명시적인 `RuntimeServices` 오브젝트에 `UnityRuntimeMcpSampleBridge`를 추가합니다.
3. 범용 런타임 진단이 필요하면 같은 오브젝트에 `UnityRuntimeDiagnosticsProvider`를 추가합니다.
4. Play Mode에 진입하거나 빌드한 Player를 실행합니다.
5. 생성된 세션 기술자와 샘플 매니페스트로 호스트를 실행합니다.

```powershell
game-runtime-mcp-host `
  --session-file "C:\path\to\LocalLow\Company\Product\unity-runtime-mcp-sample.json" `
  --tools-file "C:\path\to\GameRuntimeMcpHost\examples\unity\unity-runtime-sample.tools.json"
```

브리지가 시작되면 Unity 로그에 정확한 세션 경로가 표시됩니다. 컴포넌트가 정지하면 해당 기술자를 삭제합니다.

`LocalLow` 자동 탐색은 세션 파일명과 Unity 제품명을 사용합니다.

```powershell
game-runtime-mcp-host `
  --session-name unity-runtime-mcp-sample.json `
  --session-product YourUnityProductName `
  --tools-file "C:\path\to\GameRuntimeMcpHost\examples\unity\unity-runtime-sample.tools.json"
```

## 샘플이 노출하는 도구

| MCP 도구 | 용도 | Provider 필요 |
|---|---|---|
| `runtime_status` | 런타임/프로세스 생존 확인 | 아니요 |
| `runtime_build_info` | 빌드 및 프로세스 식별 | `UnityRuntimeDiagnosticsProvider` |
| `runtime_logs_read` | 제한된 증분 Unity 로그 | `UnityRuntimeDiagnosticsProvider` |
| `runtime_metrics_snapshot` | 단일 프레임·메모리 스냅샷 | `UnityRuntimeDiagnosticsProvider` |
| `runtime_capture_screenshot` | `persistentDataPath` 아래에 스크린샷 예약 | `UnityRuntimeDiagnosticsProvider` |
| `echo_message` | 메인 스레드 전송 왕복 확인 | 아니요 |

범용 진단 계약과 로그 cursor 규칙은 [`RUNTIME_DIAGNOSTICS.md`](RUNTIME_DIAGNOSTICS.md)에 있습니다.

## 씬 배치와 수명

- 배치: `Boot Scene / RuntimeServices` 또는 동등한 부트 프리팹
- 관측: 컴포넌트, 포트 범위, 요청 제한, 타임아웃, 세션 파일명, 로그 용량, 출력 폴더가 Inspector에 보입니다.
- 수명: `OnEnable`에서 시작/구독하고 `OnDisable`에서 중지/해제합니다. 숨은 `RuntimeInitializeOnLoadMethod` 부트스트랩은 없습니다.
- 씬 전환 생존이 필요하면 기존 부트·영속화 시스템이 명시적으로 책임집니다.

## 게임 로직 도구 확장

1. 게임 소유 매니페스트에 도구와 JSON Schema를 추가합니다.
2. 런타임 어댑터에 타입이 있는 payload DTO를 추가합니다.
3. RPC dispatch route를 추가합니다.
4. 권위 상태를 바꾸기 전에 합법 행동과 revision을 검증합니다.
5. 재시도 민감 mutation에는 안정적인 action/result 식별자를 반환합니다.
6. PlayMode 왕복 테스트를 추가합니다.

범용 진단은 게임별 명령을 대체하지 않습니다. 게임 플레이 권한, 합법 행동 판정, 멱등성, 타임아웃 복구는 게임 어댑터가 소유합니다.

## 보안 경계

- 숫자형 루프백 `127.0.0.1`에만 bind합니다.
- 브리지 시작마다 로그에 남기지 않는 새 토큰을 생성합니다.
- 요청 body, 메인 스레드 대기 시간, 프레임당 처리량을 제한합니다.
- Unity API는 메인 스레드 dispatch에서만 호출합니다.
- 로그 메시지, stack trace, 결과 컬렉션 크기를 제한합니다.
- 스크린샷은 `Application.persistentDataPath` 아래의 어댑터 소유 폴더에만 기록합니다.
- 임의 C# 실행, 파일 탐색, 원격 bind, Provider SDK 접근을 제공하지 않습니다.
- 활성 토큰이 든 세션 기술자를 커밋·업로드·로그 출력하지 않습니다.

런타임 AI 제어가 제품 기능이 아니라면 출시 빌드에서 이 컴포넌트를 비활성화하거나 제외합니다.

## 자동 샘플 테스트

Unity Test Framework가 설치된 프로젝트에 `Runtime`과 `Tests`를 복사한 뒤 PlayMode 테스트 `UnityRuntimeMcpSampleBridgeTests`를 실행합니다.

검증 범위:

- 세션 기술자 생성·정리
- 잘못된 토큰 거부
- 인증된 런타임 상태
- 빌드 식별
- 필터된 증분 로그 조회
- 메트릭 스냅샷
- 메인 스레드 echo

스크린샷은 후속 프레임에 기록되고 테스트 러너의 그래픽 환경에 영향을 받으므로 파일 생성 완료를 테스트에서 강제하지 않습니다.

## 설계 메모

MCP 프로토콜은 Python sidecar에 남겨 게임 빌드가 MCP revision을 추적하지 않게 했습니다. Unity 어댑터는 작은 localhost RPC 계약과 게임 권한만 소유합니다. 선택형 진단 Provider는 기존 listener/session/token을 재사용하며 두 번째 호스트나 전송 계층을 만들지 않습니다.
