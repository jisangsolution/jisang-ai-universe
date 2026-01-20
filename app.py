import os
import sys
import subprocess
import urllib.request
import io
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd
import streamlit as st

# [Step 0] 환경 설정 및 폰트 로드
def setup_environment():
    required = ["streamlit", "google-generativeai", "requests", "reportlab"]
    for pkg in required:
        try: __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", __file__])

    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try: urllib.request.urlretrieve(url, font_path)
        except: pass

if "streamlit" not in sys.modules:
    setup_environment()

import google.generativeai as genai

# API Keys Load
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")   # 건축물대장용
land_go_key = st.secrets.get("LAND_GO_KR_KEY")   # 토지대장용 (신규 확보한 키)
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 주소 -> PNU 변환 및 좌표 추출
# --------------------------------------------------------------------------------
def get_pnu_and_coords(address):
    if not kakao_key: return None, None, "Kakao API Key Missing"
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    try:
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                lat, lon = float(docs[0]['y']), float(docs[0]['x'])
                b_code = addr['b_code']
                mount_cd = "2" if addr.get('mountain_yn') == 'Y' else "1"
                bun = addr['main_address_no'].zfill(4)
                ji = addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else "0000"
                pnu = f"{b_code}{mount_cd}{bun}{ji}" # 19자리 PNU
                
                loc_info = {
                    "full_addr": addr['address_name'],
                    "sigungu": b_code[:5], "bjdong": b_code[5:],
                    "bun": bun, "ji": ji, "gu_name": addr['region_2depth_name']
                }
                return pnu, (lat, lon), loc_info
    except: pass
    return None, None, "주소 해석 실패"

# --------------------------------------------------------------------------------
# [Engine 2] 국토교통부 데이터 수집 (토지 + 건물)
# --------------------------------------------------------------------------------
class GovDataEngine:
    @staticmethod
    def get_land_info(pnu):
        # 토지대장 정보 (면적, 지목, 공시지가)
        key = land_go_key or data_go_key
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        params = {"serviceKey": requests.utils.unquote(key), "pnu": pnu, "numOfRows": 1}
        try:
            res = requests.get(url, params=params, timeout=10)
            root = ET.fromstring(res.content)
            item = root.find('.//item')
            if item is not None:
                return {
                    "지목": item.findtext("lndcgrCodeNm"),
                    "면적": item.findtext("lndpclAr"),
                    "공시지가": item.findtext("pblntfPclnd"),
                    "소유": item.findtext("ownshpSeCodeNm")
                }
        except: pass
        return None

    @staticmethod
    def get_bld_info(loc):
        # 건축물대장 정보 (용도, 위반여부 등)
        url = "http://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"
        params = {
            "serviceKey": requests.utils.unquote(data_go_key),
            "sigunguCd": loc['sigungu'], "bjdongCd": loc['bjdong'],
            "bun": loc['bun'], "ji": loc['ji']
        }
        try:
            res = requests.get(url, params=params, timeout=10)
            root = ET.fromstring(res.content)
            item = root.find('.//item')
            if item is not None:
                return {
                    "용도": item.findtext("mainPurpsCdNm"),
                    "연면적": item.findtext("totArea"),
                    "위반": "위반" if item.findtext("otherConst") else "정상"
                }
        except: pass
        return None

# --------------------------------------------------------------------------------
# [Engine 3] 유니콘 AI 종합 분석 (Gemini 1.5 Flash)
# --------------------------------------------------------------------------------
def get_ai_analysis(loc, land, bld):
    if not api_key: return "AI 엔진 연결 필요"
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    land_str = f"지목: {land['지목']}, 면적: {land['면적']}m2, 공시지가: {land['공시지가']}원/m2" if land else "토지 정보 없음"
    bld_str = f"건물용도: {bld['용도']}, 상태: {bld['위반']}" if bld else "나대지(건물 없음)"

    prompt = f"""
    당신은 대한민국 상위 0.1% 부동산 시행/개발 컨설턴트입니다.
    대상: {loc['full_addr']}
    데이터: {land_str} / {bld_str}

    이 정보를 바탕으로 부동산 관련 종사자가 '돈'을 지불할 가치가 있는 인사이트를 작성하세요.
    1. 개발 잠재력: 면적과 지목을 고려한 최적의 건축 규모(건폐율/용적률 추정)
    2. 수익성 분석: 공시지가 기반 예상 실거래가 및 개발 시 기대 가치
    3. 규제 및 리스크: 해당 지역({loc['gu_name']}) 조례상 주의점
    4. 투자 결정: 매수/보유/매도 의견과 그 이유 (3줄 요약 필수)
    """
    try:
        return model.generate_content(prompt).text
    except: return "AI 분석 일시적 오류"

# --------------------------------------------------------------------------------
# [UI] 유니콘 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="지상 AI 유니콘", layout="wide")

st.title("🦄 지상 AI 부동산 종합 분석 시스템")
st.caption("토지대장/건축물대장 실시간 연동 및 AI 전문가 분석 모드")

with st.sidebar:
    st.header("🔍 주소 검색")
    target_addr = st.text_input("분석할 주소", "경기도 김포시 통진읍 도사리 163-1")
    run_btn = st.button("종합 분석 실행", type="primary", use_container_width=True)

if run_btn:
    pnu, coords, loc_info = get_pnu_and_coords(target_addr)
    
    if pnu:
        # 데이터 수집
        with st.spinner("정부 공인 데이터를 수집 중입니다..."):
            land_data = GovDataEngine.get_land_info(pnu)
            bld_data = GovDataEngine.get_bld_info(loc_info)
            ai_report = get_ai_analysis(loc_info, land_data, bld_data)

        # 1. 상단 지도
        st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)

        # 2. 결과 리포트
        st.divider()
        col1, col2 = st.columns([1, 2])

        with col1:
            st.subheader("📊 핵심 팩트 시트")
            with st.container(border=True):
                st.markdown("**[토지 정보]**")
                if land_data:
                    st.write(f"• 지목: {land_data['지목']}")
                    st.write(f"• 면적: {float(land_data['면적']):,.1f} ㎡ (약 {float(land_data['면적'])/3.3058:.1f}평)")
                    st.write(f"• 공시지가: {int(land_data['공시지가']):,} 원/㎡")
                    st.write(f"• 소유: {land_data['소유']}")
                else: st.warning("토지 정보를 불러올 수 없습니다.")
                
                st.markdown("---")
                st.markdown("**[건물 정보]**")
                if bld_data:
                    st.write(f"• 용도: {bld_data['용도']}")
                    st.write(f"• 상태: {bld_data['위반']}")
                else: st.info("나대지 상태 (건물 없음)")

        with col2:
            st.subheader("💡 유니콘 AI 전문가 진단")
            st.markdown(ai_report)
            
    else:
        st.error("주소를 정확히 찾을 수 없습니다. 지번까지 상세히 입력해 주세요.")
