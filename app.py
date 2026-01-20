import os
import sys
import subprocess
import urllib.request
import io
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd

# [Step 0] 스마트 런처 (라이브러리 자동 점검)
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

# API Keys Load (Secrets)
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] Kakao Geocoding (주소 -> 행정코드 & 좌표 변환)
# --------------------------------------------------------------------------------
def get_codes_from_kakao(address):
    if not kakao_key:
        return None, None, None, None, None, "카카오 API 키 미설정"
    
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    params = {"query": address}
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                # 좌표 (지도 표시용)
                lat = float(docs[0]['y'])
                lon = float(docs[0]['x'])
                
                # 행정코드 파싱
                b_code = docs[0]['address']['b_code']
                sigungu_cd = b_code[:5]
                bjdong_cd = b_code[5:]
                
                # 지번 파싱 (4자리 패딩 필수)
                main_no = docs[0]['address']['main_address_no']
                sub_no = docs[0]['address']['sub_address_no']
                bun = main_no.zfill(4)
                ji = sub_no.zfill(4) if sub_no else "0000"
                
                return sigungu_cd, bjdong_cd, bun, ji, (lat, lon), "Success"
            else:
                return None, None, None, None, None, "주소를 찾을 수 없습니다. (도로명/지번 확인)"
        else:
            return None, None, None, None, None, f"카카오 API 오류 ({resp.status_code})"
    except Exception as e:
        return None, None, None, None, None, f"통신 실패: {str(e)}"

# --------------------------------------------------------------------------------
# [Engine 2] Real Data Connector (공공데이터포털)
# --------------------------------------------------------------------------------
class RealDataConnector:
    def __init__(self, service_key):
        self.service_key = service_key
        self.base_url = "http://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"

    def get_building_info(self, sigungu_cd, bjdong_cd, bun, ji):
        if not self.service_key: return {"status": "error", "msg": "공공데이터 키 미설정"}
        
        params = {
            "serviceKey": self.service_key,
            "sigunguCd": sigungu_cd,
            "bjdongCd": bjdong_cd,
            "bun": bun,
            "ji": ji,
            "numOfRows": 1,
            "pageNo": 1
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
                            "주용도": item.findtext("mainPurpsCdNm") or "-",
                            "연면적": item.findtext("totArea") or "0",
                            "사용승인일": item.findtext("useAprDay") or "-",
                            "구조": item.findtext("strctCdNm") or "-",
                            "높이": item.findtext("heit") or "0",
                            "위반여부": "위반" if item.findtext("otherConst") else "정상"
                        }
                    else: return {"status": "nodata", "msg": "건축물대장이 존재하지 않습니다. (나대지 등)"}
                except: return {"status": "error", "msg": "XML 파싱 오류"}
            else: return {"status": "error", "msg": f"정부 서버 오류 {response.status_code}"}
        except Exception as e: return {"status": "error", "msg": str(e)}

# --------------------------------------------------------------------------------
# [Engine 3] PDF Generator
# --------------------------------------------------------------------------------
def generate_final_pdf(address, context):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    font_path = "NanumGothic.ttf"
    font_name = 'NanumGothic' if os.path.exists(font_path) else 'Helvetica'
    if os.path.exists(font_path): pdfmetrics.registerFont(TTFont(font_name, font_path))
    
    # Header
    c.setFont(font_name, 24)
    c.drawCentredString(width/2, height-40*mm, "Jisang AI 부동산 정밀 분석 보고서")
    
    c.setStrokeColorRGB(0.2, 0.2, 0.8)
    c.line(20*mm, height-45*mm, width-20*mm, height-45*mm)

    # Body
    c.setFont(font_name, 12)
    y = height - 70*mm
    c.drawString(25*mm, y, f"• 분석 주소: {address}")
    c.drawString(25*mm, y-10*mm, f"• 분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    y -= 30*mm
    c.setFont(font_name, 16)
    c.drawString(25*mm, y, "[핵심 데이터]")
    c.setFont(font_name, 12)
    
    # [수정된 부분] 괄호 오류 완벽 수정
    data_lines = [
        f"1. 건물 용도: {context.get('주용도', '-')}",
        f"2. 위반 여부: {context.get('위반여부', '-')}",
        f"3. 연 면 적: {context.get('연면적', '-')} ㎡",
        f"4. 구    조: {context.get('구조', '-')}"
    ]
    
    y -= 15*mm
    for line in data_lines:
        c.drawString(30*mm, y, line)
        y -= 10*mm

    # Disclaimer
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(20*mm, 30*mm, width-20*mm, 30*mm)
    c.setFont(font_name, 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(width/2, 25*mm, "본 보고서는 AI 분석 시뮬레이션 결과이며 법적 효력이 없습니다.")
    
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# --------------------------------------------------------------------------------
# [UI] Main Dashboard
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Universe", page_icon="🏢", layout="wide")

with st.sidebar:
    st.title("🏢 Jisang AI")
    st.markdown("---")
    addr_input = st.text_input("주소를 입력하세요 (도로명/지번)", "경기도 김포시 통진읍 도사리 163-1")
    
    if st.button("🚀 AI 정밀 분석 실행", type="primary", use_container_width=True):
        st.session_state['run_analysis'] = True
        st.session_state['target_addr'] = addr_input
    
    st.markdown("---")
    st.caption("Powered by Google x Gov24 x Kakao")

# Main Logic
st.title("지상 AI 부동산 분석 시스템")

if 'run_analysis' in st.session_state and st.session_state['run_analysis']:
    target = st.session_state['target_addr']
    st.subheader(f"📍 분석 대상: {target}")
    
    # 1. Kakao Geocoding
    with st.status("📡 위성 및 행정 데이터 수집 중...", expanded=True) as status:
        st.write("1단계: 카카오 위성 좌표 및 행정코드 추출 중...")
        sigungu, bjdong, bun, ji, coords, msg = get_codes_from_kakao(target)
        
        if sigungu:
            st.write("✅ 주소 확인 완료! (좌표 획득)")
            
            # Map Display
            if coords:
                df_map = pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]})
                st.map(df_map, zoom=15, use_container_width=True)

            st.write("2단계: 정부24 건축물대장 서버 접속 중...")
            connector = RealDataConnector(data_go_key)
            real_data = connector.get_building_info(sigungu, bjdong, bun, ji)
            
            if real_data['status'] == 'success':
                st.write("✅ 건축물대장 데이터 확보 성공!")
                status.update(label="분석 완료!", state="complete", expanded=False)
            else:
                st.write(f"⚠️ 대장 정보 없음: {real_data['msg']}")
                status.update(label="데이터 확인 필요", state="error")
        else:
            st.error(f"❌ 주
