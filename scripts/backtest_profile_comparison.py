#!/usr/bin/env python3
"""
Before/After 백테스트: 원사이즈 PER 필터 vs 프로필별 필터

US 종목 (AAPL, MSFT, NVDA, QQQ) 6개월 백테스트로
프로필 시스템 효과를 검증합니다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import yfinance as yf

sys.path.insert(0, ".")

from src.analysis.market_profile import (
    SectorType,
    calculate_peg_ratio,
    classify_by_profile,
    get_stock_profile,
)


SYMBOLS = ["AAPL", "MSFT", "NVDA", "QQQ"]
PERIOD = "6mo"

# 원사이즈 PER threshold (국장 기준)
ONESIZE_PER_THRESHOLD = 15.0


def run_backtest():
    print("=" * 70)
    print("Before/After 백테스트: 원사이즈 PER vs 프로필별 필터")
    print("=" * 70)

    results = []

    for symbol in SYMBOLS:
        print(f"\n{'─' * 50}")
        print(f"종목: {symbol}")
        print(f"{'─' * 50}")

        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        hist = ticker.history(period=PERIOD)

        if hist.empty:
            print(f"  ⚠ 데이터 없음, 스킵")
            continue

        per = info.get("trailingPE", 0) or 0
        earnings_growth = info.get("earningsGrowth")
        revenue_growth = info.get("revenueGrowth")
        sector_avg_per = 25.0  # US 평균 근사

        # 6개월 수익률
        start_price = hist["Close"].iloc[0]
        end_price = hist["Close"].iloc[-1]
        returns_6m = (end_price - start_price) / start_price * 100

        profile = get_stock_profile(symbol)
        peg = calculate_peg_ratio(per, earnings_growth, revenue_growth)

        # ─── Before: 원사이즈 PER 필터 ───
        if per > ONESIZE_PER_THRESHOLD:
            before_decision = "HOLD (PER 초과)"
        elif per > 0:
            before_decision = "BUY 후보"
        else:
            before_decision = "HOLD (PER 없음)"

        # ─── After: 프로필별 필터 ───
        quality, score_adj, reason = classify_by_profile(
            profile, per, sector_avg_per,
            earnings_growth=earnings_growth,
            revenue_growth=revenue_growth,
        )

        if quality == "skip":
            after_decision = "BUY 후보 (ETF, PER 스킵)"
        elif quality == "undervalued":
            after_decision = f"BUY 후보 (저평가, +{score_adj:.0f}점)"
        elif quality == "fair":
            after_decision = "BUY 후보 (적정가)"
        else:
            after_decision = "HOLD (고평가)"

        before_missed = "HOLD" in before_decision and returns_6m > 0
        after_caught = "BUY" in after_decision and returns_6m > 0

        print(f"  PER: {per:.1f} | PEG: {peg:.2f}" if peg else f"  PER: {per:.1f} | PEG: N/A")
        print(f"  Earnings Growth: {earnings_growth}" if earnings_growth else "  Earnings Growth: N/A")
        print(f"  Revenue Growth: {revenue_growth}" if revenue_growth else "  Revenue Growth: N/A")
        print(f"  프로필: {profile.market.value} {profile.sector.value}")
        print(f"  6개월 수익률: {returns_6m:+.1f}%")
        print()
        print(f"  [Before] 원사이즈 PER<15: {before_decision}")
        print(f"  [After]  프로필별 필터:   {after_decision}")
        print(f"  → 프로필 판단 사유: {reason}")

        if before_missed and after_caught:
            print(f"  ✅ 프로필 시스템이 기회를 포착! (+{returns_6m:.1f}% 수익 기회)")
        elif before_missed:
            print(f"  ⚠ Before 놓침, After도 놓침")
        elif after_caught:
            print(f"  ✅ 둘 다 포착")

        results.append({
            "symbol": symbol,
            "per": per,
            "peg": peg,
            "returns_6m": returns_6m,
            "before": before_decision,
            "after": after_decision,
            "before_missed": before_missed,
            "after_caught": after_caught,
            "profile": f"{profile.market.value}/{profile.sector.value}",
            "reason": reason,
        })

    # ─── Summary ───
    print(f"\n{'=' * 70}")
    print("요약")
    print(f"{'=' * 70}")

    before_buy = sum(1 for r in results if "BUY" in r["before"])
    after_buy = sum(1 for r in results if "BUY" in r["after"])
    missed_opportunities = sum(1 for r in results if r["before_missed"] and r["after_caught"])

    print(f"  종목 수: {len(results)}")
    print(f"  [Before] BUY 후보: {before_buy}/{len(results)}")
    print(f"  [After]  BUY 후보: {after_buy}/{len(results)}")
    print(f"  프로필이 추가로 포착한 기회: {missed_opportunities}개")

    if missed_opportunities > 0:
        avg_missed_return = sum(
            r["returns_6m"] for r in results if r["before_missed"] and r["after_caught"]
        ) / missed_opportunities
        print(f"  추가 포착 종목 평균 수익률: {avg_missed_return:+.1f}%")

    return results


if __name__ == "__main__":
    run_backtest()
