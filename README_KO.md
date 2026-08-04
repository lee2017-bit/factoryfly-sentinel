# FactoryFly Sentinel - 한국어 재현 가이드

**Human-Guided Physical AI for Active Factory Inspection**

이 문서는 제출 저장소의 영어 `README.md`와 동일한 최종 검증 절차를 한국어로 설명합니다. GitHub 기본 README는 영어판을 사용합니다.

> **범위:** FactoryFly는 관찰된 시각적 변화와 증거 품질을 보고합니다. 변화가 결함인지, 안전 문제인지, 정상 운영인지 판단하지 않으며 최종 운영 판단은 사람이 수행합니다.

## 1. 시스템 개요

FactoryFly는 다음 13단계를 연결합니다.

1. 기준 영상으로 COLMAP 3D Baseline 구축
2. 희소 구조와 카메라 궤적을 상대좌표 공간기억으로 저장
3. 점검 영상과 입력 파일 등록
4. 점검 프레임을 고정 Baseline 좌표계에 위치 등록
5. 위치등록 결과 검토
6. 가까운 기준 카메라 후보를 검색하고 기하 정합
7. Excellent/Good/Usable/Poor 분류
8. AMD Radeon Cloud에서 ROCm DINOv2 분석
9. Heatmap과 p95 결과 검토
10. Stable/Confirmed/Uncertain 증거 분기
11. 불확실 증거의 재점검 미션 생성
12. 재점검 영상에서 목표 재획득 및 재분석
13. 독립 실행형 HTML 증거 보고서 생성

드론 비행과 재점검 실행은 사람이 수행합니다. 3D 지도는 대략적인 공간 맥락이며 충돌회피 경로가 아닙니다.

## 2. 실행 구조

### Windows 로컬

- Streamlit UI
- FFmpeg 프레임 추출
- COLMAP Baseline과 점검 위치등록
- SIFT/RANSAC/Homography 정합
- Change Triage
- Reinspection Mission
- JSON/Markdown/HTML 보고서

### AMD Radeon Cloud

- Python 3.12
- PyTorch 2.9.1 + ROCm 7.2.1
- DINOv2 ViT-S/14
- 상대적 semantic-change heatmap과 p95 점수
- GPU 성능 측정

## 3. 최종 클린 검증 결과

```text
ROCM_OK
GPU_OK
DINOV2_OK

Python : 3.12.3
PyTorch: 2.9.1+rocm7.2.1
HIP    : 7.2.53211
VRAM   : 47.98 GiB
```

최종 보고서 요약:

```text
Analyzed pairs             : 13
Stable cleared             : 7
Confirmed findings         : 4
Reinspections              : 1
Cleared after reinspection : 0
Unresolved                 : 0
```

재점검 결과:

```text
Geometry         : good
Initial p95      : 0.865
Reinspection p95 : 0.859
Conclusion       : Persistent visual change confirmed
```

## 4. 입력 데이터와 Telemetry 주의사항

```text
sample_data/raw/
├─ baseline.mp4
├─ inspection.mp4
├─ inspection_telemetry.txt
└─ reinspection.mp4
```

DJI 비행기록은 확장자가 `.txt`여도 바이너리 파일일 수 있습니다. 현재 v7.3.13은 Telemetry 내용을 해석하지 않습니다. 등록 단계에서 파일명, 크기, 수정시간, SHA256만 기록하며 위치등록은 COLMAP 영상처리로 수행합니다.

따라서:

- DJI API Key가 필요하지 않습니다.
- 바이너리 파일을 메모장으로 열어도 읽을 수 없는 것이 정상일 수 있습니다.
- GPS나 기기 식별자가 포함될 수 있으므로 원본 비행기록을 공개 저장소에 올리지 않습니다.
- 현재 코드 검증만을 위해서는 개인정보가 없는 placeholder 파일을 사용할 수 있지만, 이것은 비행기록을 재현하는 것이 아니라 미사용 입력 경로만 충족하는 것입니다.

## 5. Windows 설치

저장소 루트에서 PowerShell을 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File ".\scripts\setup_local.ps1" `
  -ProjectRoot "$PWD" `
  -ColmapBat "C:\Tools\COLMAP\COLMAP.bat"
```

실행:

```powershell
.\.venv-vision\Scripts\python.exe `
  -m streamlit run .\app.py `
  --server.port 8501 `
  --server.headless true `
  --browser.gatherUsageStats false
```

접속 주소:

```text
http://localhost:8501
```

## 6. 새 Radeon Cloud 환경 생성

기존 환경을 재사용하지 말고 새 Template과 새 Instance를 사용합니다.

```text
Title           : FactoryFly Sentinel
Category        : Computer Vision
Container image : AMD OneClick Base (ROCm 7.2.1 / Python 3.12)
GitHub Repo URL : https://github.com/lee2017-bit/factoryfly-sentinel
Branch          : main
Notebook Path   : 비움
SSH Access      : ON
Workspace       : Local SSD only
```

Instance가 Ready가 되면 먼저 Open Notebook에서 Terminal을 엽니다. Template 번호는 매번 달라지므로 경로를 하드코딩하지 않습니다.

```bash
REPO="$(find /workspace/template-repos \
  -type f \
  -path '*/repo/scripts/setup_radeon_cloud.sh' \
  -print -quit 2>/dev/null | sed 's#/scripts/setup_radeon_cloud.sh##')"

test -n "$REPO"
cd "$REPO"
```

설치와 SSH 서버 시작:

```bash
bash scripts/setup_radeon_cloud.sh /workspace/factoryfly-radeon \
  2>&1 | tee /workspace/factoryfly_setup.log
```

검증:

```bash
bash /workspace/factoryfly-radeon/scripts/verify_radeon_cloud.sh \
  /workspace/factoryfly-radeon \
  2>&1 | tee /workspace/factoryfly_verify.log
```

필수 출력:

```text
ROCM_OK
GPU_OK
DINOV2_OK
```

Windows에서 외부 포트 확인:

```powershell
Test-NetConnection <HOST> -Port <PORT>
```

`TcpTestSucceeded : True`가 나온 뒤 접속합니다.

```powershell
ssh `
  -i "$HOME\.ssh\factoryfly_amd" `
  -p <PORT> `
  -o IdentitiesOnly=yes `
  root@<HOST>
```

Private Key는 Windows에만 두고 Radeon Cloud에는 Public Key만 등록합니다.

## 7. 최종 재현 설정

```text
Baseline sampling FPS          : 4
Inspection sampling FPS        : 1
Top-K baseline candidates      : 5
Automatic AMD-ready pairs      : 12
Reviewer-selected poor pair    : 1개 이상
AMD batch pairs                : 2
Confirmed p95 threshold        : 0.62
Uncertain p95 threshold        : 0.70
```

특정 Frame 번호는 데이터와 실행에 따라 달라지므로 README에 고정하지 않습니다. 재점검 분기를 검증하려면 Step 8의 **Visual Borderline Evidence Review**에서 semantic-change가 높고 geometry가 `poor`인 항목을 최소 1개 직접 선택합니다.

## 8. 단계별 검증값

### Baseline

```text
Sampled frames     : 158
Registered cameras : 91
Registration rate  : 57.59%
Sparse 3D points   : 5,438
```

Sparse point 수는 COLMAP 버전과 하드웨어에 따라 조금 달라질 수 있습니다.

### Inspection Localization

```text
Input frames           : 47
Registered frames      : 18
Registration rate      : 38.3%
Failed frames          : 29
Longest registered run : 16
```

### Pair Refinement

```text
Candidate pairs      : 90
Excellent            : 3
Good                 : 5
Usable               : 4
Poor                 : 6
AMD-ready            : 12
High confidence      : 8
Median reprojection  : 0.962 px
```

### AMD Analysis

```text
Automatic pairs : 12
Reviewer pairs  : 1
Analyzed pairs  : 13
Batch pairs     : 2
Mean ms/pair    : 4.75
Pairs/second    : 210.46
Peak GPU memory : 133.7 MB
```

`xFormers is not available`은 최적화 라이브러리 경고이며 분석 실패가 아닙니다.

### Change Triage

```text
Confirmed change clusters : 3
Needs reinspection        : 1
Automatically cleared     : 7
```

13개 pair가 공간적으로 가까운 증거 cluster로 합쳐지기 때문에 위 분류 수의 합이 13일 필요는 없습니다.

### Reinspection

```text
Geometry         : good
Initial p95      : 0.865
Reinspection p95 : 0.859
Persistent visual change confirmed
```

### Final Report

```text
Analyzed pairs             : 13
Stable cleared             : 7
Confirmed findings         : 4
Reinspections              : 1
Cleared after reinspection : 0
Unresolved                 : 0
```

## 9. 이번 최종 소스에서 반영된 수정

- `shared/scripts/run_amd_analysis.ps1`에 `WorkspaceName` 파라미터 추가
- `current`와 `preview` AMD 작업공간 모두 지원
- 새 Radeon Cloud에서 `sshd` 설치/기동
- GitHub 인증서 문제 발생 시 secure-first, Radeon mirror-second, 명령 단위 fallback 처리
- Baseline 4 FPS / Inspection 1 FPS로 문서 수정
- 자동 12개 + reviewer-selected poor pair 1개 절차 반영
- 특정 Frame/Mission 번호 제거
- Telemetry가 현재 위치등록에 사용되지 않는다는 사실 명시
- 최종 결과를 13/7/4/1/0/0과 0.865/0.859로 갱신

## 10. 문제 해결

### SSH Timeout

Radeon Terminal에서 설치 스크립트를 실행하고 다음을 확인합니다.

```bash
pgrep -a sshd
ss -lntp | grep ':22'
```

### GitHub 인증서 오류

최종 설치 스크립트가 공식 GitHub, Radeon Cloud mirror, 제한된 command-scoped fallback 순으로 처리합니다. 전역 Git SSL 검증을 끄지 않습니다.

### `WorkspaceName` 오류

최종 `shared/scripts/run_amd_analysis.ps1`을 사용해야 합니다. 이전 v3 공개 패키지에는 이 파라미터가 누락되어 있었습니다.

### 재점검 Mission이 0개

Threshold를 임의로 올리는 것이 아니라 Step 8에서 semantic-change가 높고 geometry가 `poor`인 pair를 reviewer-selected로 추가하고 AMD 분석을 overwrite하여 다시 실행합니다.

## 11. 보안 및 개인정보

공개 저장소에 다음을 올리지 않습니다.

```text
SSH Private Key
실제 Radeon Host/Port
Cloud Token
개인 절대경로
원본 DJI 비행기록
동의받지 않은 영상
가상환경/Cache
DINOv2 Checkpoint
COLMAP/AMD 생성 데이터
```

데모에는 회사 데이터, 회사 코드, 기밀 공장정보, 회사 소유 자산이 포함되지 않습니다. 영상은 참가자가 개인 실내공간에서 직접 촬영했습니다.

## 12. 한계

- 좌표는 상대 단위이며 metric 보정값이 아닙니다.
- 3D 지도는 충돌회피 경로가 아닙니다.
- Homography는 평면 근사입니다.
- p95와 threshold는 확률이 아닙니다.
- 데이터는 PoC 규모이며 산업 통계 benchmark가 아닙니다.
- 드론 비행은 사람이 수행합니다.
- 시각 변화는 보고하지만 결함 종류와 위험도를 판정하지 않습니다.
- v7.3.13은 Telemetry를 파싱하거나 위치등록에 사용하지 않습니다.
