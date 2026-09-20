#!/usr/bin/env python3
"""
숏폼(Shorts) 제작 후보 자동 채점 스크립트
==========================================

content/cards/*.md 의 프론트매터를 읽어, 각 영상을 숏폼 후보로서
3개 축으로 채점하고 순위표(CSV)를 생성한다.

채점 철학 (전략적 근거)
------------------------
숏폼은 "차가운 신규 시청자 발견(top-of-funnel)"용 도구다. 따라서
멤버십 심화편이 아니라, 일반 대중이 실제로 검색·염려하는 공개영상이
후보로서 가치가 높다. 세 축으로 점수화한다.

  1. reach  (대중 검색성)   : 일반인이 검색·걱정하는 주제인가
  2. hook   (훅 강도)        : 통념을 깨거나 궁금증 격차를 만드는가
  3. fit    (숏폼 적합성)    : 30~60초 하나의 완결 인사이트 + 시각화 가능성

total = reach + hook + fit  (최대 15점)

주의: 이 점수는 "제목·주제 메타데이터" 기반의 추정 우선순위다.
최종 판단은 유튜브 애널리틱스(이미 노출·시청지속률이 좋은 영상)와
반드시 교차 검증할 것.

사용법
------
  python3 tools/shorts-ranking/rank_shorts.py                 # 공개영상만, CSV 생성
  python3 tools/shorts-ranking/rank_shorts.py --all           # 전체 멤버십 포함
  python3 tools/shorts-ranking/rank_shorts.py --top 20        # 상위 20개 콘솔 출력
  python3 tools/shorts-ranking/rank_shorts.py --out foo.csv   # 출력 경로 지정
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML이 필요합니다:  pip install pyyaml")


# ---------------------------------------------------------------------------
# 채점 규칙 (설명 가능하도록 데이터로 분리)
# ---------------------------------------------------------------------------

# reach: 주제 키워드 → 대중 검색성 점수. 카드의 태그/제목에서 매칭.
# 상위 티어일수록 일반 대중의 검색·불안이 큰 주제.
REACH_TIERS: list[tuple[int, list[str]]] = [
    # 5점: 국민병 수준의 관심 주제
    (5, ["당뇨", "dm", "고혈압", "htn", "혈압", "콜레스테롤", "고지혈",
          "간수치", "lft", "갑상선", "thyroid", "빈혈", "anemia",
          "대장암", "위암", "간암", "hcc", "암", "콩팥", "신장", "ckd",
          "흉통", "가슴", "심장", "치매", "골다공"]),
    # 4점: 흔한 증상·질환
    (4, ["복통", "기침", "구토", "구역", "설사", "변비", "통증", "두통",
          "어지럼", "탈수", "간염", "hbv", "간경변", "cirrhosis", "담석",
          "위염", "위궤양", "역류", "속쓰림", "체중", "부종", "혈뇨",
          "단백뇨", "감염", "당뇨병", "gi", "liver", "kidney"]),
    # 3점: 관심은 있으나 다소 전문적
    (3, ["심전도", "ecg", "acs", "부정맥", "심방세동", "af", "판막",
          "약", "부작용", "기전", "대사", "췌장", "담도", "pancreas",
          "호르몬", "인슐린", "전해질", "칼륨", "나트륨"]),
    # 2점: 생리학·기초의학 심화 (대중 관심 낮음)
    (2, ["생리", "physiology", "buffer", "완충", "삼투", "여과",
          "순환생리", "신장생리", "산염기", "acid", "base"]),
]
REACH_DEFAULT = 3

# hook: 제목 패턴 → 가점. 통념 파괴/궁금증/공포는 조회·공유·댓글을 유발.
HOOK_QUESTION = ["무엇", "왜", "어떻게", "어떤", "가?", "까?", "는가", "은가", "?"]
HOOK_CONTRARIAN = ["정말", "항상", "수록", "아닌가", "오해", "착각",
                    "사실이 아", "괜찮", "해도 되", "안 되", "뿐인가",
                    "만 하면", "정말로", "진짜", "의외"]
HOOK_STAKES = ["위험", "응급", "죽", "생명", "놓치", "반드시", "무서",
                "놀라", "치명", "심각", "급성", "함정"]

# fit: 시각화가 쉬운(그림/부위/단계 등) 소재는 숏폼 완성도가 높다.
FIT_VISUAL = ["위치", "부위", "어디", "그림", "모양", "단계", "지도",
               "종류", "구분", "차이", "vs", "기준", "순서"]


def score_reach(title: str, tags: list[str]) -> tuple[int, str]:
    """가장 높은 티어에 매칭되는 주제 점수를 반환."""
    haystack = (title + " " + " ".join(tags)).lower()
    for score, kws in REACH_TIERS:
        for kw in kws:
            if kw.lower() in haystack:
                return score, kw
    return REACH_DEFAULT, "-"


def score_hook(title: str) -> tuple[int, list[str]]:
    """기본 2점 + 질문/반전/공포 가점, 최대 5점."""
    reasons: list[str] = []
    score = 2
    if any(p in title for p in HOOK_QUESTION):
        score += 1
        reasons.append("질문형")
    if any(p in title for p in HOOK_CONTRARIAN):
        score += 1
        reasons.append("통념파괴")
    if any(p in title for p in HOOK_STAKES):
        score += 1
        reasons.append("위험/공포")
    return min(score, 5), reasons


def score_fit(title: str, level: int) -> tuple[int, list[str]]:
    """기본 3점 + 난이도(L1↑ / L3↓) + 시각화 소재 가점, 1~5점."""
    reasons: list[str] = []
    score = 3
    if level == 1:
        score += 1
        reasons.append("기초개념(L1)")
    elif level == 3:
        score -= 1
        reasons.append("심화(L3)")
    if any(p in title for p in FIT_VISUAL):
        score += 1
        reasons.append("시각화용이")
    return max(1, min(score, 5)), reasons


def parse_card(path: Path) -> dict | None:
    """마크다운 파일에서 YAML 프론트매터를 파싱."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    return fm


def main() -> int:
    ap = argparse.ArgumentParser(description="숏폼 후보 자동 채점")
    ap.add_argument("--cards", default="content/cards",
                    help="카드 디렉터리 (기본: content/cards)")
    ap.add_argument("--all", action="store_true",
                    help="전체 멤버십 포함 (기본: public 공개영상만)")
    ap.add_argument("--top", type=int, default=15,
                    help="콘솔에 출력할 상위 N개 (기본: 15)")
    ap.add_argument("--out", default="tools/shorts-ranking/shorts_ranking.csv",
                    help="출력 CSV 경로")
    args = ap.parse_args()

    cards_dir = Path(args.cards)
    if not cards_dir.is_dir():
        sys.exit(f"카드 디렉터리를 찾을 수 없습니다: {cards_dir}")

    rows: list[dict] = []
    skipped_no_yid = 0
    for path in sorted(cards_dir.glob("*.md")):
        fm = parse_card(path)
        if fm is None:
            continue
        membership = str(fm.get("membership", "")).strip()
        if not args.all and membership != "public":
            continue
        yid = str(fm.get("youtube_id", "")).strip()
        if not yid:
            skipped_no_yid += 1
            continue
        title = str(fm.get("title", "")).strip()
        tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        try:
            level = int(fm.get("level", 2))
        except (TypeError, ValueError):
            level = 2

        reach, reach_kw = score_reach(title, [str(t) for t in tags])
        hook, hook_r = score_hook(title)
        fit, fit_r = score_fit(title, level)
        total = reach + hook + fit
        # 동점 구간을 의미있게 벌리기 위한 신호 풍부도(tiebreaker).
        # 통념파괴 훅은 공유·댓글 유발이 커서 가중치를 조금 더 준다.
        richness = len(hook_r) + len(fit_r) + (1 if "통념파괴" in hook_r else 0)

        rows.append({
            "total": total,
            "richness": richness,
            "reach": reach,
            "hook": hook,
            "fit": fit,
            "title": title,
            "youtube_id": yid,
            "url": f"https://youtu.be/{yid}",
            "membership": membership,
            "level": level,
            "topic": reach_kw,
            "hook_reasons": "+".join(hook_r) or "-",
            "fit_reasons": "+".join(fit_r) or "-",
            "file": path.name,
        })

    # 정렬: 총점 → 신호풍부도 → reach → hook 내림차순, 제목 오름차순(재현성)
    rows.sort(key=lambda r: (-r["total"], -r["richness"], -r["reach"],
                             -r["hook"], r["title"]))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["rank", "total", "richness", "reach", "hook", "fit", "title",
                  "url", "youtube_id", "membership", "level", "topic",
                  "hook_reasons", "fit_reasons", "file"]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, r in enumerate(rows, 1):
            writer.writerow({"rank": i, **{k: r[k] for k in fieldnames if k != "rank"}})

    # 콘솔 요약
    scope = "전체 멤버십" if args.all else "공개영상(public)"
    print(f"[대상] {scope}  |  채점 완료: {len(rows)}개"
          + (f"  |  youtube_id 없어 제외: {skipped_no_yid}개" if skipped_no_yid else ""))
    print(f"[출력] {out_path}")
    print(f"\n=== 숏폼 제작 우선순위 TOP {args.top} ===")
    print(f"{'순위':>3} {'점수':>4} {'(대/훅/적)':>9}  제목")
    print("-" * 78)
    for i, r in enumerate(rows[:args.top], 1):
        print(f"{i:>3} {r['total']:>4}  ({r['reach']}/{r['hook']}/{r['fit']})   "
              f"{r['title'][:48]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
