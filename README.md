# krwfolio

`krwfolio`는 한국 투자자 관점에서 다통화 포트폴리오의 원화 기준 성과를
분해하는 작은 Python 도구입니다.

증권앱은 보유 종목, 평가금액, 수익률을 보여줍니다. `krwfolio`는 그 다음 질문을
다룹니다.

- 원화 기준 수익률 중 자산 가격에서 온 부분은 얼마인가
- USD/KRW 같은 환율 변화가 얼마나 기여했나
- 자산 수익률과 환율 수익률이 같이 움직이면서 생긴 효과는 얼마인가
- 리밸런싱은 buy-and-hold보다 나았나
- 거래비용은 전체 성과를 얼마나 깎았나

실시간 매매, 종목 추천, 포트폴리오 최적화, 세금 계산은 목표가 아닙니다.

## 설치

```bash
git clone https://github.com/Woosang-Cho/krwfolio.git
cd krwfolio
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,yfinance]"
```

`yfinance`를 쓰지 않고 CSV 입력만 사용할 계획이면 아래처럼 설치해도 됩니다.

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

## 웹 UI

로컬에서 웹 화면을 띄웁니다.

```bash
./scripts/krwfolio-web
```

브라우저에서 엽니다.

```text
http://127.0.0.1:8765
```

웹 UI에서는 보통 아래 순서로 씁니다.

1. 초기 금액과 분석 기간을 입력합니다.
2. 티커, 통화, 목표 비중을 입력합니다.
3. 데이터 소스를 고릅니다.
4. `원화 기준 성과 분석 실행`을 누릅니다.

분석 기간은 연도를 드롭다운으로 먼저 고르고, 월/일은 브라우저 날짜 선택기로
고릅니다. 긴 기간을 볼 때 연도 이동이 번거로운 문제를 줄이기 위한 방식입니다.

기본 데이터 소스는 `yfinance에서 가져오기`입니다. 티커와 기간만 넣고 빠르게
확인할 때 씁니다.

중요한 분석에는 yfinance 결과만 그대로 쓰지 않는 편이 좋습니다. yfinance 데이터는
나중에 수정될 수 있으므로, 재현이 필요한 경우 받은 가격과 환율을 CSV로 저장한 뒤
CSV 입력으로 다시 실행하세요.

`CSV 직접 입력`은 가격과 환율 데이터를 직접 붙여 넣는 방식입니다. 같은 CSV를
넣으면 같은 결과가 나오므로, 기록으로 남길 분석이나 테스트에는 이쪽이 더
재현성이 좋습니다.

## CLI

YAML과 CSV 파일을 기준으로 실행합니다.

```bash
PYTHONPATH=src .venv/bin/python -m krwfolio run examples/01_krw_usd_6040.yaml --out results/6040 --format csv,json
```

yfinance에서 데이터를 받아 실행할 수도 있습니다.

```bash
PYTHONPATH=src .venv/bin/python -m krwfolio run examples/01_krw_usd_6040.yaml --provider yfinance --out results/6040-yf --format csv,json
```

테스트:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

## 입력

`krwfolio`는 포트폴리오 설정과 시장 데이터를 분리해서 받습니다.

### YAML

YAML은 포트폴리오 규칙입니다.

```yaml
base_currency: KRW
initial_value: 10000000
start: 2020-01-02
end: 2024-12-31

rebalance:
  frequency: quarterly
  timing: after_close
  transaction_cost_bps: 5

calendar:
  policy: union_ffill
  max_staleness_days: 7

data:
  prices: prices.csv
  fx: fx.csv

assets:
  - symbol: 069500.KS
    name: KODEX 200
    currency: KRW
    weight: 0.4
  - symbol: SPY
    name: SPDR S&P 500 ETF
    currency: USD
    weight: 0.4
  - symbol: TLT
    name: iShares 20+ Year Treasury Bond ETF
    currency: USD
    weight: 0.2
```

주요 항목:

- `base_currency`: 현재는 `KRW`만 지원합니다.
- `initial_value`: 시작 원금입니다.
- `start`, `end`: 분석 기간입니다.
- `rebalance.frequency`: `none`, `monthly`, `quarterly`, `yearly` 중 하나입니다.
- `transaction_cost_bps`: 거래비용입니다. `5`는 0.05%입니다.
- `calendar.max_staleness_days`: 가격이나 환율이 며칠 이상 새로 관측되지 않으면 실행을 중단할지 정합니다.
- `assets`: 자산 목록과 목표 비중입니다. 비중 합계는 1.0이어야 합니다.

yfinance 모드에서는 `data.prices`, `data.fx`를 쓰지 않습니다.

### 가격 CSV

가격 CSV는 각 자산의 현지통화 가격입니다.

```csv
date,069500.KS,SPY,TLT
2020-01-02,29800,324.87,137.01
2020-04-01,22100,246.15,162.93
2020-07-01,28950,310.52,163.71
```

`069500.KS`는 원화 가격이고 `SPY`, `TLT`는 달러 가격입니다. 가능하면 배당과
분할이 반영된 adjusted close를 일관되게 쓰는 것이 좋습니다.

### 환율 CSV

환율 CSV는 외화 1단위를 KRW로 환산하기 위한 값입니다.

```csv
date,USD,KRW
2020-01-02,1158.1,1.0
2020-04-01,1230.5,1.0
2020-07-01,1200.0,1.0
```

`USD` 컬럼은 USD/KRW입니다. 예를 들어 `1300`은 1달러가 1300원이라는 뜻입니다.
`KRW` 컬럼은 항상 `1.0`입니다.

## 출력

웹 UI는 요약 지표, 성과 분해, 데이터 상태, 원화 기준 NAV 차트를 보여줍니다.

CLI는 결과 폴더에 아래 파일을 저장합니다.

```text
equity_curve.csv
holdings.csv
weights.csv
trades.csv
attribution_daily.csv
attribution_cumulative.csv
attribution_rebalance.csv
result.json
```

파일별 의미:

- `equity_curve.csv`: 날짜별 NAV, 일별 수익률, 리스크 지표용 수익률, drawdown, 거래비용
- `holdings.csv`: 날짜별 자산 평가금액. 모두 KRW 기준
- `weights.csv`: 날짜별 자산 비중
- `trades.csv`: 초기 매수와 리밸런싱 거래 내역
- `attribution_daily.csv`: 날짜별 local, FX, cross, cost 기여도
- `attribution_cumulative.csv`: 초기자본 대비 전체 기간 PnL 기여도. 최종 total return과 합산 검산됩니다.
- `attribution_rebalance.csv`: 리밸런싱 포트폴리오와 buy-and-hold 비교
- `result.json`: 지표, 진단 정보, 성과 분해를 모은 JSON

yfinance 모드로 CLI를 실행하면 받은 시장 데이터도 함께 저장합니다.

- `market_prices_yfinance.csv`
- `market_fx_yfinance.csv`

## 성과 분해 방식

외화 자산의 원화 기준 수익률은 현지통화 수익률과 환율 수익률을 함께 반영합니다.

```text
1 + R_base = (1 + R_local) * (1 + R_fx)
R_base = R_local + R_fx + R_local * R_fx
```

여기서 `R_local`은 자산 가격 효과, `R_fx`는 환율 효과, `R_local * R_fx`는
교차항입니다.

예를 들어 SPY가 10% 오르고 USD/KRW도 10% 오르면 원화 기준 수익률은 20%가
아니라 21%입니다. 마지막 1%p가 교차항입니다.

## 데이터와 캘린더

한국 주식, 미국 ETF, 환율은 휴장일이 서로 다릅니다. `krwfolio`는 평가에는 union
calendar와 forward-fill을 사용하지만, 오래된 데이터가 계속 이어지는 것은 막습니다.

- `max_staleness_days`를 넘으면 실행을 중단합니다.
- 리밸런싱 스케줄은 평가 캘린더에서 잡고, 실제 매매는 대상 자산 가격과 필요한 환율이 모두 관측된 다음 실행 가능일에 합니다.
- 마지막 평가일에는 기본적으로 리밸런싱하지 않습니다.

## 문서

- [계산 모델](docs/model.md)
- [성과 기여도 모델](docs/attribution.md)
- [데이터 정책](docs/data_policy.md)
