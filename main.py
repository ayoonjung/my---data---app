"""
KOBIS(영화진흥위원회) 일별 박스오피스 조회 앱
--------------------------------------------
- Streamlit Cloud 배포를 전제로 작성했습니다.
- 인증키는 절대 코드에 적지 않고, secrets.toml (또는 Streamlit Cloud의 Secrets 설정)의
  KOBIS_KEY 값을 불러와서 사용합니다.

  [secrets.toml 예시]
  KOBIS_KEY = "여기에_발급받은_인증키"
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ------------------------------------------------------------
# 기본 설정
# ------------------------------------------------------------
st.set_page_config(page_title="박스오피스 조회", page_icon="🎬", layout="wide")

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

# 숫자로 바꿔야 하는 컬럼들 (API에서는 전부 문자열로 옴)
# rankInten: 전날 대비 순위 증감 (양수=순위 상승, 음수=순위 하락, 0=변동 없음)
NUMERIC_COLS = ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]

# 누적관객이 이 숫자를 넘으면 영화명 옆에 트로피를 붙입니다.
MILLION = 1_000_000


def get_today_kst() -> datetime:
    """한국 시간(KST) 기준 '오늘' datetime을 돌려줍니다."""
    return datetime.now(ZoneInfo("Asia/Seoul"))


def to_yyyymmdd(d) -> str:
    """date 객체를 KOBIS API가 요구하는 yyyymmdd 문자열로 바꿉니다."""
    return d.strftime("%Y%m%d")


@st.cache_data(ttl=3600)  # 같은 날짜는 1시간 동안 다시 API를 호출하지 않고 기억(캐시)합니다.
def fetch_box_office(target_dt: str, api_key: str):
    """
    KOBIS API에서 일별 박스오피스 목록을 가져옵니다.
    성공하면 (True, 영화 목록 리스트)를,
    아직 집계 전(빈 목록)이면 (False, "EMPTY")를,
    그 외 실패면 (False, 안내 메시지)를 돌려줍니다.
    """
    params = {"key": api_key, "targetDt": target_dt}

    try:
        response = requests.get(KOBIS_URL, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return False, "인터넷 연결 상태나 KOBIS 서버 상태를 확인해 주세요. (네트워크 요청 자체가 실패했습니다)"

    # 상태 코드가 200이어도 인증키가 틀리면 faultInfo가 들어올 수 있습니다.
    if response.status_code != 200:
        return False, f"KOBIS 서버가 오류를 반환했습니다. (상태 코드: {response.status_code}) 잠시 후 다시 시도해 주세요."

    try:
        data = response.json()
    except ValueError:
        return False, "KOBIS 서버 응답을 해석할 수 없습니다. (JSON 형식이 아닙니다) 잠시 후 다시 시도해 주세요."

    # 인증키 오류 등은 faultInfo 상자로 옵니다.
    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, f"KOBIS API 오류: {message}  → secrets에 등록한 KOBIS_KEY 값이 올바른지 확인해 주세요."

    box_office_result = data.get("boxOfficeResult")
    if not box_office_result:
        return False, "응답 구조가 예상과 다릅니다. KOBIS API 문서가 변경되었는지 확인해 주세요."

    movie_list = box_office_result.get("dailyBoxOfficeList")
    if not movie_list:
        # 목록이 비어 있는 경우 = 아직 그 날짜 집계가 나오지 않은 경우
        return False, "EMPTY"

    return True, movie_list


def to_dataframe(movie_list):
    """API에서 받은 리스트(딕셔너리들의 리스트)를 pandas DataFrame으로 바꾸고,
    문자열로 온 숫자 컬럼들을 실제 숫자(int)로 변환합니다."""
    df = pd.DataFrame(movie_list)

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 혹시 모를 결측치는 0으로 채워서 정렬/그래프에서 에러가 나지 않게 합니다.
    df[NUMERIC_COLS] = df[NUMERIC_COLS].fillna(0)

    # rank(순위) 기준으로 정렬
    df = df.sort_values("rank").reset_index(drop=True)
    return df


def rank_change_badge(rank_inten: int) -> str:
    """rankInten(전날 대비 순위 증감) 값을 색깔 있는 화살표 HTML로 바꿔 줍니다.
    양수(순위 상승) -> 빨간 위 화살표, 음수(순위 하락) -> 파란 아래 화살표,
    0(변동 없음) -> 표시 없음."""
    if rank_inten > 0:
        return f"<span style='color:red;font-weight:bold;'>▲ {rank_inten}</span>"
    elif rank_inten < 0:
        return f"<span style='color:blue;font-weight:bold;'>▼ {abs(rank_inten)}</span>"
    else:
        return "-"


def movie_name_with_trophy(row) -> str:
    """누적관객이 100만 명을 넘으면 영화명 옆에 트로피 이모지를 붙입니다."""
    name = row["movieNm"]
    if row["audiAcc"] >= MILLION:
        return f"{name} 🏆"
    return name


# ------------------------------------------------------------
# 화면 구성
# ------------------------------------------------------------
st.title("🎬 박스오피스 조회")

today_kst = get_today_kst()
# 오늘 건 아직 집계 전이므로, 고를 수 있는 가장 늦은 날짜는 '어제'까지입니다.
max_date = (today_kst - timedelta(days=1)).date()

selected_date = st.date_input(
    "조회할 날짜를 선택하세요 (한국 시간 기준)",
    value=max_date,      # 기본값은 어제
    max_value=max_date,  # 오늘/미래는 선택 불가
)

target_dt = to_yyyymmdd(selected_date)
pretty_date = selected_date.strftime("%Y년 %m월 %d일")
st.caption(f"선택한 날짜: {pretty_date}")

# secrets에서 인증키 불러오기
if "KOBIS_KEY" not in st.secrets:
    st.error(
        "KOBIS_KEY가 설정되어 있지 않습니다. "
        "Streamlit Cloud의 앱 설정 → Secrets 메뉴에서 KOBIS_KEY를 등록해 주세요."
    )
    st.stop()

api_key = st.secrets["KOBIS_KEY"]

success, result = fetch_box_office(target_dt, api_key)

if not success:
    if result == "EMPTY":
        st.info(f"{pretty_date}은(는) 아직 집계 전입니다.")
    else:
        # result에는 사용자에게 보여줄 안내 메시지가 들어있습니다.
        st.warning(result)
    st.stop()

df = to_dataframe(result)

# ------------------------------------------------------------
# 1위 영화 - 지표 카드 3장
# ------------------------------------------------------------
top1 = df.iloc[0]
top1_title = movie_name_with_trophy(top1)
st.subheader(f"🥇 1위: {top1_title}")

col1, col2, col3 = st.columns(3)
col1.metric("그날 관객수", f"{int(top1['audiCnt']):,} 명")
col2.metric("누적 관객수", f"{int(top1['audiAcc']):,} 명")
col3.metric("스크린수", f"{int(top1['scrnCnt']):,} 개")

st.divider()

# ------------------------------------------------------------
# 관객수 상위 5편 - 막대그래프
# ------------------------------------------------------------
st.subheader("📊 관객수 상위 5편")
top5 = df.nlargest(5, "audiCnt").set_index("movieNm")["audiCnt"]
st.bar_chart(top5)

st.divider()

# ------------------------------------------------------------
# 전체 표
# ------------------------------------------------------------
st.subheader("📋 전체 순위표")

table_df = pd.DataFrame({
    "순위": df["rank"].astype(int),
    "전일대비": df["rankInten"].astype(int).apply(rank_change_badge),
    "영화명": df.apply(movie_name_with_trophy, axis=1),
    "개봉일": df["openDt"],
    "관객수": df["audiCnt"].astype(int).map("{:,}".format),
    "누적관객": df["audiAcc"].astype(int).map("{:,}".format),
    "스크린수": df["scrnCnt"].astype(int).map("{:,}".format),
})

# 화살표에 색을 입혀야 하므로 st.dataframe 대신 HTML 표로 렌더링합니다.
st.markdown(
    table_df.to_html(escape=False, index=False),
    unsafe_allow_html=True,
)
