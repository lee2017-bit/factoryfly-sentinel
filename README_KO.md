# FactoryFly 재현 README 한글 해설

이 문서는 제출용 영어 `README.md`를 사용자가 검토하기 쉽게 요약한 자료입니다. 제출 저장소의 기본 README는 영어판을 사용합니다.

## README가 충족하는 필수 항목

규정상 요구된 다음 내용을 모두 포함했습니다.

- 환경 설정 방법
- 실행 방법
- 사용 방법
- 의존성 사양
- Step-by-step 재현 절차
- 예상 결과
- 트러블슈팅
- 개인정보와 SSH 보안 주의사항

## 재현 구조

FactoryFly는 한 컴퓨터에서 전부 실행되는 구조가 아닙니다.

### Windows 로컬 컴퓨터

- Streamlit 화면
- FFmpeg 영상 프레임 추출
- COLMAP 3D 기준 모델
- 점검 영상 위치 등록
- SIFT/RANSAC/Homography 정합
- Change Triage
- Reinspection Mission
- 최종 HTML 보고서

### AMD Radeon Cloud

- ROCm PyTorch
- DINOv2 ViT-S/14
- Semantic-change heatmap
- p95 변화 점수

## 제출 전 실제로 남은 작업

README 본문은 완성됐지만 최종 저장소를 만들 때 아래 두 가지를 연결해야 합니다.

1. `sample_data/raw/`에 공개 가능한 축소 영상 4개를 넣거나 다운로드 링크를 제공
2. 정리된 v7.3.13 소스 코드와 이 README 패키지를 하나의 GitHub 저장소로 합치기

## 재현에 쓰는 고정 설정

```text
Baseline FPS: 4
Inspection FPS: 4
Top-K: 5
Manual Frames: empty
AMD Batch Pairs: 2
Confirmed Threshold: 0.62
Uncertain Threshold: 0.70
```

## 최종 기대 결과

```text
Analyzed pairs: 18
Stable cleared: 10
Confirmed findings: 4
Reinspections: 1
Cleared after reinspection: 0
Unresolved: 0

Geometry: good
Initial p95: 0.866
Reinspection p95: 0.860
```

## 주의

현재 실제 FactoryFly `app.py`에는 프로젝트 루트가 절대경로로 들어가 있습니다. 패키지에 포함한 `scripts/configure_local_paths.ps1`이 저장소 위치에 맞게 이 값을 자동 변경하도록 만들었습니다.

README에는 실제 Radeon Cloud IP, Port, SSH private key가 없습니다. 공개 저장소에서도 반드시 예시값만 사용해야 합니다.
