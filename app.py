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

# [Step 0] 환경 설정 및 필수 부품 로드
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

# API Keys - 보안 로드
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")   # 건축물대장
land_go_key = st.secrets.get("LAND_GO_KR_KEY")   # 토지대장
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 주소 마스터 (PNU 생성 및 GIS 좌표)
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
                pnu = f"{b_code}{mount_cd}{bun}{ji}" 
                
                loc_info = {
                    "full_addr": addr['address_name'],
                    "sigungu": b_code[:5], "bjdong": b_code[5:],
                    "bun": bun, "ji": ji, "gu_name": addr['region_2depth_name'],
                    "dong_name": addr['region_3depth_name']
                }
                return pnu, (lat, lon), loc_info
    except: pass
    return None, None, "주소 해석 실패"

# --------------------------------------------------------------------------------
# [Engine 2] 토지/건물 융합 팩트 엔진 (이름 오타 수정 완료)
# --------------------------------------------------------------------------------
class RealEstateFactEngine:
    @staticmethod
    def get_land_details(pnu):
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
    def get_building_details(loc):
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
# [Engine 3] 유니콘 AI 종합 전략 (수익성 + 규제 분석)
# --------------------------------------------------------------------------------
def get_unicorn_insight(loc, land, bld):
    if not api_key: return "AI 라이선스 미등록"
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 데이터 구조화
    land_text = f"지목:{land['지목']}, 면적:{land['면적']}m2, 공시지가:{land['공시지가']}원/m2" if land else "토지정보 미수신"
    bld_text = f"용도:{bld['용도']}, 위반:{bld['위반']}" if bld else "나대지(건물 없음)"

    prompt = f"""
    당신은 대한민국 0.1% 부동산 개발 전문가(건축사+감정평가사)입니다.
    주소: {loc['full_addr']}
    토지현황: {land_text} / 건물현황: {bld_text}

    다음 4가지 섹션으로 '돈이 되는 보고서'를 작성하십시오:

    1. 📐 토지이용계획 및 건축 규모: 
       - 지목과 주변 환경을 고려한 예상 용도지역 추정 및 건폐율/용적률 가이드.
       - 추천 건축 용도 (예: 창고, 근생, 다가구 등).
    2. 💸 사업성 분석: 
       - 공시지가를 기반으로 한 자산 가치 평가 및 수익 창출 전략.
    3. 📜 규제 리스크 (토지이음 관점): 
       - 해당 필지에서 주의 깊게 봐야 할 공법적 규제 (군사시설, 배수구역 등).
    4. 💡 유니콘의 전략: 
       - 이 매물에 대한 투자의견(S-D 등급)과 핵심 한 줄 평.
    """
    try:
        return model.generate_content(prompt).text
    except: return "AI 서버 응답 지연 (재시도 필요)"

# --------------------------------------------------------------------------------
# [UI] 프리미엄 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn", layout="wide")

st.title("🦄 지상 AI 부동산 종합 솔루션")
st.caption("건축사, 감정평가사, 시행사 전문가 그룹의 통합 분석 플랫폼")

with st.sidebar:
    st.header("📍 주소 검색")
    target_addr = st.text_input("분석 주소", "경기도 김포시 통진읍 도사리 163-1")
    search_btn = st.button("🚀 종합 정밀 분석 실행", type="primary", use_container_width=True)

if search_btn:
    pnu, coords, loc_info = get_pnu_and_coords(target_addr)
    
    if pnu:
        with st.status("🔍 유니콘 브레인 가동 중...", expanded=True) as status:
            st.write("1. 토지대장 원천 데이터 추출...")
            # [수정 완료] 클래스 이름 RealEstateFactEngine으로 일치시킴
            land_data = RealEstateFactEngine.get_land_details(pnu)
            
            st.write("2. 건축물 현황 및 권리 스캔...")
            bld_data = RealEstateFactEngine.get_building_details(loc_info)
            
            st.write("3. 유니콘 AI 통합 인사이트 생성...")
            ai_insight = get_unicorn_insight(loc_info, land_data, bld_data)
            
            status.update(label="분석 완료!", state="complete", expanded=False)

        # 지도 시각화
        st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)

        # 보고서 영역
        st.divider()
        st.header(f"🏢 {target_addr} 분석 보고서")
        
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.subheader("📊 팩트 체크")
            with st.container(border=True):
                st.markdown("**[토지 원천 데이터]**")
                if land_data:
                    st.write(f"• 지목: {land_data['지목']}")
                    st.write(f"• 면적: {float(land_data['면적']):,.1f} ㎡ (약 {float(land_data['면적'])/3.3058:.1f}평)")
                    st.write(f"• 공시지가: {int(land_data['공시지가']):,} 원/㎡")
                else:
                    st.warning("데이터 동기화 중 (잠시 후 시도)")
                
                st.markdown("---")
                st.markdown("**[건물 현황]**")
                if bld_data:
                    st.write(f"• 용도: {bld_data['용도']}")
                    st.write(f"• 상태: {bld_data['위반']}")
                else:
                    st.info("나대지 상태 (건물 없음)")

        with c2:
            st.subheader("💡 유니콘 수석 전략가 진단")
            st.markdown(ai_insight)
    else:
        st.error("정확한 주소 형식이 아닙니다.")
