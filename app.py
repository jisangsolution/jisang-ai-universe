import os
import sys
import subprocess
import urllib.request
import io
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd

# [Step 0] 스마트 런처 (환경 설정)
def setup_environment():
    required = {
        "streamlit": "streamlit", 
        "plotly": "plotly", 
        "google-generativeai": "google.generativeai", 
        "python-dotenv": "dotenv", 
        "reportlab": "reportlab",
        "requests": "requests"
    }
    needs_install = []
    for pkg, mod in required.items():
        try: __import__(mod)
        except ImportError: needs_install.append(pkg)
    if needs_install:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U"] + needs_install)
        os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", __file__])

    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path) or os.path.getsize(font_path) < 100:
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try: urllib.request.urlretrieve(url, font_path)
        except: pass

if "streamlit" not in sys.modules:
    setup_environment()
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", __file__]
    sys.exit(stcli.main())

import streamlit as st
import google.generativeai as genai
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

# API Keys Load
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] Kakao Geocoding & Admin Info
# --------------------------------------------------------------------------------
def get_codes_from_kakao(address):
    if not kakao_key: return None, None, None, None, None, None, "API Key Missing"
    
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    params = {"query": address}
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                lat, lon = float(docs[0]['y']), float(docs[0]['x'])
                b_code = docs[0]['address']['b_code']
                
                # 행정구역 상세 분해
                region_1 = docs[0]['address']['region_1depth_name'] # 도
                region_2 = docs[0]['address']['region_2depth_name'] # 시군구
                region_3 = docs[0]['address']['region_3depth_name'] # 읍면동
                
                sigungu, bjdong = b_code[:5], b_code[5:]
                main_no = docs[0]['address']['main_address_no']
                sub_no = docs[0]['address']['sub_address_no']
                bun = main_no.zfill(4)
                ji = sub_no.zfill(4) if sub_no else "0000"
                
                loc_info = {
                    "si": region_1, "gu": region_2, "dong": region_3,
                    "full_addr": f"{region_1} {region_2} {region_3} {main_no}-{sub_no if sub_no else ''}"
                }
                return sigungu, bjdong, bun, ji, (lat, lon), loc_info, "Success"
            return None, None, None, None, None, None, "주소 미확인"
        return None, None, None, None, None, None, f"Error {resp.status_code}"
    except Exception as e: return None, None, None, None, None, None, str(e)

# --------------------------------------------------------------------------------
# [Engine 2] Gov Data Connector (Building Ledger)
# --------------------------------------------------------------------------------
class RealDataConnector:
    def __init__(self, service_key):
        self.service_key = service_key
        self.base_url = "http://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"

    def get_building_info(self, sigungu_cd, bjdong_cd, bun, ji):
        if not self.service_key: return {"status": "error", "msg": "API Key Missing"}
        
        key_to_use = requests.utils.unquote(self.service_key)
        params = {
            "serviceKey": key_to_use, "sigunguCd": sigungu_cd, "bjdongCd": bjdong_cd,
            "bun": bun, "ji": ji, "numOfRows": 1, "pageNo": 1
        }
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                try:
                    root = ET.fromstring(response.content)
                    item = root.find('.//item')
                    if item is not None:
                        return {
                            "status": "success",
                            "주용도": item.findtext("mainPurpsCdNm") or "미지정",
                            "연면적": item.findtext("totArea") or "0",
                            "사용승인일": item.findtext("useAprDay") or "-",
                            "구조": item.findtext("strctCdNm") or "-",
                            "위반여부": "위반" if item.findtext("otherConst") else "정상"
                        }
                    return {"status": "nodata", "msg": "나대지 (건물 없음)"}
                except: return {"status": "error", "msg": "XML Parsing Error"}
            elif response.status_code == 500: return {"status": "nodata", "msg": "데이터 미존재 (나대지)"}
            else: return {"status": "error", "msg": f"Server Error {response.status_code}"}
        except Exception as e: return {"status": "error", "msg": str(e)}

# --------------------------------------------------------------------------------
# [Engine 3] The Unicorn Brain (0.1% Expert AI)
# --------------------------------------------------------------------------------
def get_unicorn_analysis(loc_info, building_data):
    if not api_key: return "Google API 키가 없습니다."
    
    # 모델 교체: gemini-pro (구형) -> gemini-1.5-flash (신형/고속)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 상황별 프롬프트 분기
    is_land_only = (building_data['status'] == 'nodata')
    
    context_str = ""
    if is_land_only:
        context_str = "현재 상태: 건축물대장 없음 (나대지 또는 철거 후 신축 부지)."
    else:
        context_str = f"현재 상태: 기존 건물 있음 (용도: {building_data.get('주용도')}, 연면적: {building_data.get('연면적')}m2, 위반여부: {building_data.get('위반여부')})."

    prompt = f"""
    당신은 대한민국 상위 0.1%의 '부동산 개발 종합 어드바이저'입니다.
    (건축사 + 감정평가사 + 도시계획기술사 + 부동산 전문 변호사의 지식을 통합)
    
    분석 대상: {loc_info['full_addr']} ({loc_info['si']} {loc_info['gu']} {loc_info['dong']})
    {context_str}
    
    이 고객은 부동산 전문가(중개사, 시행사)이거나 투자자입니다.
    단순한 정보 나열이 아니라, '돈이 되는 의사결정 정보'를 제공해야 합니다.
    
    다음 4가지 관점에서 정밀 분석하여 마크다운 표와 리스트로 출력하세요:

    ### 1. 🏗️ 건축 규제 및 가설계 (Architectural Feasibility)
    * **예상 용도지역**: 주소를 기반으로 해당 지번의 가장 유력한 용도지역 추정 (예: 계획관리지역, 제2종일반주거지역 등).
    * **건폐율/용적률**: 해당 지자체({loc_info['gu']}) 조례 기준 상한선 제시.
    * **주차장 이슈**: 해당 용도지역에서 신축 시 예상되는 주차장 확보 기준 (개략적).
    * **추천 용도**: 법적으로 허용되며 수익성이 높은 용도 (상가주택, 창고, 근생 등).

    ### 2. ⚖️ 권리 및 공법 리스크 (Legal & Zoning Risk)
    * **행위 제한**: 군사시설보호구역, 비행안전구역 등 해당 지역에서 흔히 발생하는 규제 가능성 체크.
    * **토지이음 연계**: 토지이용계획확인원 확인이 필요한 핵심 키워드 제시 (예: '접도구역 확인 필요').

    ### 3. 💰 사업성 및 가치 평가 (Valuation & Strategy)
    * **최유효 이용(Highest and Best Use)**: 이 땅의 잠재력을 100% 끌어올리는 개발 컨셉.
    * **예상 타겟**: 누구에게 임대/매매를 맞춰야 하는지 (예: 인근 공단 근로자, 도심 출퇴근족 등).

    ### 4. 🚨 전문가의 한 마디 (Professional Opinion)
    * 냉철한 투자 조언 (매입 추천/보류/추가확인).
    * "지갑을 열게 만드는" 핵심 포인트 1줄 요약.
    
    *주의: 수치는 추정치임을 명시하고, 정확한 데이터는 등기부등본 및 토지이용계획확인원 대조가 필요함을 고지할 것.*
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 중 오류 발생: {str(e)}"

# --------------------------------------------------------------------------------
# [UI] Dashboard
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Universe", page_icon="🦄", layout="wide")

st.markdown("""
<style>
    .big-font {font-size:20px !important; font-weight: bold;}
    .success-box {padding:15px; background-color:#e6fffa; border-radius:10px; border:1px solid #4fd1c5;}
    .warning-box {padding:15px; background-color:#fffaf0; border-radius:10px; border:1px solid #fbd38d;}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2040/2040504.png", width=50)
    st.title("🦄 지상 AI")
    st.caption("Premium Real Estate Solution")
    st.markdown("---")
    addr_input = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.button("🚀 유니콘 분석 실행", type="primary", use_container_width=True):
        st.session_state['run'] = True
        st.session_state['addr'] = addr_input
    st.markdown("---")
    st.info("💡 **Premium Tip:** 건축사, 감정평가사, 세무사의 관점을 통합하여 분석합니다.")

st.title("지상 AI 부동산 종합 솔루션 (Unicorn Ver.)")

if st.session_state.get('run'):
    target = st.session_state['addr']
    
    with st.status("🔍 상위 0.1% 전문가 그룹이 분석 중입니다...", expanded=True) as status:
        st.write("1. 🛰️ 위성 및 행정 데이터 정밀 타격 (Kakao)...")
        sigungu, bjdong, bun, ji, coords, loc_info, msg = get_codes_from_kakao(target)
        
        if sigungu:
            # 지도 표시 (Map First)
            if coords:
                st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=16, use_container_width=True)
            
            st.write("2. 🏢 건축물대장 및 권리 관계 스캔 (Gov24)...")
            connector = RealDataConnector(data_go_key)
            real_data = connector.get_building_info(sigungu, bjdong, bun, ji)
            
            st.write("3. 🧠 유니콘 AI(법률/건축/금융) 종합 진단 중...")
            ai_report = get_unicorn_analysis(loc_info, real_data)
            
            status.update(label="분석 완료! (Ready to Report)", state="complete", expanded=False)
            
            # --- 결과 화면 ---
            st.divider()
            st.header(f"📍 {target} 분석 리포트")
            
            # 탭 구성: 현황 -> 심층분석 -> 투자의견
            tab1, tab2 = st.tabs(["📊 기본 현황 (Fact)", "🦄 유니콘 심층 분석 (Insight)"])
            
            with tab1:
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("토지/건물 데이터")
                    if real_data['status'] == 'success':
                        st.metric("주용도", real_data['주용도'])
                        st.metric("연면적", f"{real_data['연면적']}㎡")
                        st.metric("사용승인일", real_data['사용승인일'])
                        if real_data['위반여부'] == "위반":
                             st.error("🚨 [리스크] 위반건축물 등재")
                        else:
                             st.success("✅ 건축물대장상 위반사항 없음")
                    else:
                        st.warning("📌 **건축물 정보 없음 (나대지/토지)**")
                        st.write("현재 해당 지번에는 건축물대장이 존재하지 않습니다.")
                        st.write("👉 **토지 가치 중심**으로 분석을 진행합니다.")

                with col2:
                    st.subheader("위치 특성")
                    st.write(f"• 행정구역: {loc_info['si']} {loc_info['gu']}")
                    st.write(f"• 법정동: {loc_info['dong']}")
                    st.caption("※ 정확한 지목/면적/공시지가는 '토지대장' API 연동 시 제공됩니다.")

            with tab2:
                st.markdown(ai_report)
                
                st.divider()
                st.info("📢 **전문가 코멘트:** 이 보고서는 법적 효력이 없으며, 실제 투자 시에는 반드시 관할 관청의 서류를 확인하시기 바랍니다.")

        else:
            status.update(label="주소 오류", state="error")
            st.error(f"주소를 찾을 수 없습니다: {msg}")
