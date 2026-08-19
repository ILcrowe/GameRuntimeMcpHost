# Unity C# 런타임 어댑터 샘플

[English guide](README.md)

이 샘플은 GameRuntimeMcpHost 연결 중 게임이 소유하는 절반입니다. 세션 토큰으로 인증하는 숫자형 루프백 종단점(endpoint)을 열고, 수신 스레드의 요청을 큐에 넣은 뒤 Unity 메인 스레드에서 처리합니다.

## 요구사항

- Unity 2022.3 LTS 이상
- `HttpListener`를 지원하는 데스크톱 대상. WebGL은 제외
- GameRuntimeMcpHost 실행용 Python 3.10 이상

Unity와 .NET API만 사용하므로 별도 JSON 패키지는 필요하지 않습니다.

## 3단계 설정

1. [`Runtime`](Runtime)을 Unity 프로젝트의 `Assets/GameRuntimeMcpHostSample/Runtime`에 복사합니다.
2. 부트 씬 또는 부트 프리팹의 눈에 보이는 `RuntimeServices` GameObject에 `UnityRuntimeMcpSampleBridge`를 추가하고 플레이 모드(Play Mode)에 진입합니다.
3. 생성된 세션 기술자와 샘플 매니페스트로 호스트를 실행합니다.

```powershell
game-runtime-mcp-host `
  --session-file "C:\path\to\LocalLow\Company\Product\unity-runtime-mcp-sample.json" `
  --tools-file "C:\path\to\GameRuntimeMcpHost\examples\unity\unity-runtime-sample.tools.json"
```

리스너가 시작되면 Unity Console에 정확한 세션 경로가 출력됩니다. 컴포넌트가 중지되면 기술자는 제거됩니다.

`LocalLow` 자동 탐색을 사용하려면 파일명과 Unity 제품명을 전달합니다.

```powershell
game-runtime-mcp-host `
  --session-name unity-runtime-mcp-sample.json `
  --session-product YourUnityProductName `
  --tools-file "C:\path\to\GameRuntimeMcpHost\examples\unity\unity-runtime-sample.tools.json"
```

MCP 클라이언트에는 `runtime_status`, `echo_message`가 나타납니다.

## 씬 배치와 수명

- 배치: `Boot Scene / RuntimeServices` 또는 같은 역할의 부트 프리팹
- 관찰: 컴포넌트, 포트 범위, 요청 제한, 타임아웃, 기술자 파일명이 인스펙터(Inspector)에 그대로 보임
- 수명: Play Mode의 `OnEnable`에서 시작하고 `OnDisable`에서 중지. 숨은 `RuntimeInitializeOnLoadMethod` 부트스트랩 없음
- 영속: 씬 전환 뒤에도 유지해야 한다면 기존 부트·영속 시스템이 명시적으로 소유

## 샘플 확장

1. `unity-runtime-sample.tools.json`에 도구와 JSON Schema를 추가합니다.
2. `UnityRuntimeMcpSampleBridge.cs`에 타입이 정해진 페이로드(payload) 필드나 데이터 전송 객체(DTO)를 추가합니다.
3. `Dispatch`의 `switch`에 명령을 추가하고, 권위 상태를 바꾸기 전에 게임 규칙을 검증합니다.

샘플의 `runtime.status`, `sample.echo`는 의도적으로 무해합니다. 실제 변경 명령에는 관측 정보인 `clientName`과 별도의 권한 검증, 재시도 가능한 변경의 멱등성, 합법 행동 판정, 결정적인 타임아웃 대체 경로가 필요합니다.

## 보안 경계

- 네트워크 바인딩(binding)은 숫자형 루프백 `127.0.0.1`로 고정합니다.
- 브리지를 시작할 때마다 로그에 남기지 않는 새 토큰을 만듭니다.
- 요청 본문 크기, 메인 스레드 대기 시간, 프레임당 처리량에 상한이 있습니다.
- Unity API는 메인 스레드의 `Dispatch`에서만 호출합니다.
- 임의 C# 실행, 파일 탐색, 원격 bind, 공급자 SDK 접근을 제공하지 않습니다.
- 활성 토큰이 들어 있으므로 생성된 세션 기술자를 커밋·업로드·로그 기록하지 마세요.

출시 게임에서는 런타임 AI 제어가 의도한 제품 기능일 때만 컴포넌트를 포함하거나 활성화해야 합니다.

## 자동 샘플 테스트

Unity 테스트 프레임워크(Test Framework)가 설치된 프로젝트에 `Runtime`, `Tests`를 함께 복사하고 PlayMode의 `UnityRuntimeMcpSampleBridgeTests`를 실행합니다. 기술자 생성, 인증된 `runtime.status`, 메인 스레드 `sample.echo`, 기술자 정리를 검증합니다.

## 설계 노트

MCP 프로토콜은 파이썬 사이드카(Python sidecar)에 남겨 게임 빌드가 MCP 개정판을 직접 따라가지 않게 했습니다. Unity 어댑터는 작은 로컬호스트(localhost) RPC 계약과 게임 권위만 소유합니다. 자동 부트스트랩 대신 명시적 씬 컴포넌트를 택해 출시 포함 여부, 설정, 수명을 눈에 보이게 유지합니다.
