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
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

# 숫자로 바꿔야 하는 컬럼들 (API에서는 전부 문자열로 옴)
NUMERIC_COLS = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]

# 화면에 보여줄 이름표
DISPLAY_NAMES = {
    "rank": "순위",
    "movieNm": "영화명",
    "openDt": "개봉일",
    "audiCnt": "관객수",
    "audiAcc": "누적관객",
    "scrnCnt": "스크린수",
}


def get_yesterday_kst() -> str:
    """
    한국 시간(KST) 기준으로 '어제' 날짜를 yyyymmdd 형태의 문자열로 계산합니다.
    배포 서버의 시계는 한국 시간이 아닐 수 있으므로, 항상 한국 시간대(Asia/Seoul)를
    기준으로 직접 계산합니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


@st.cache_data(ttl=3600)  # 같은 날짜는 1시간 동안 다시 API를 호출하지 않고 기억(캐시)합니다.
def fetch_box_office(target_dt: str, api_key: str):
    """
    KOBIS API에서 일별 박스오피스 목록을 가져옵니다.
    성공하면 (True, 영화 목록 리스트)를, 실패하면 (False, 오류 메시지)를 돌려줍니다.
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
        return False, "해당 날짜의 박스오피스 목록이 비어 있습니다. 조회 날짜가 아직 집계 전이거나 공휴일 등의 이유일 수 있습니다."

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


# ------------------------------------------------------------
# 화면 구성
# ------------------------------------------------------------
st.title("🎬 어제의 박스오피스")

target_dt = get_yesterday_kst()
pretty_date = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
st.caption(f"기준 날짜(한국 시간 기준 어제): {pretty_date}")

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
    # result에는 사용자에게 보여줄 안내 메시지가 들어있습니다.
    st.warning(result)
    st.stop()

df = to_dataframe(result)

# ------------------------------------------------------------
# 1위 영화 - 지표 카드 3장
# ------------------------------------------------------------
top1 = df.iloc[0]
st.subheader(f"🥇 1위: {top1['movieNm']}")

col1, col2, col3 = st.columns(3)
col1.metric("어제 관객수", f"{int(top1['audiCnt']):,} 명")
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
table_df = df[list(DISPLAY_NAMES.keys())].rename(columns=DISPLAY_NAMES)
st.dataframe(table_df, use_container_width=True, hide_index=True)
