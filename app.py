import os
import sys
import subprocess
import urllib.request
import io
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd

# [Step 0] 스마트 런처
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

# API Keys
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] Kakao Geocoding
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
                lat = float(docs[0]['y'])
                lon = float(docs[0]['x'])
                b_code = docs[0]['address']['b_code']
                sigungu_cd = b_code[:5]
                bjdong_cd = b_code[5:]
                main_no = docs[0]['address']['main_address_no']
                sub_no = docs[0]['address']['sub_address_no']
                bun = main_no.zfill(4)
                ji = sub_no.zfill(4) if sub_no else "0000"
                return sigungu_cd, bjdong_cd, bun, ji, (lat, lon), "Success"
            else:
                return None, None, None, None, None, "주소 미확인"
        else:
            return None, None, None, None, None, f"Kakao Error {resp.status_code}"
    except Exception as e:
        return None, None, None, None, None, str(e)

# --------------------------------------------------------------------------------
# [Engine 2] Gov Data Connector (Enhanced Error Handling)
# --------------------------------------------------------------------------------
class RealDataConnector:
    def __init__(self, service_key):
        self.service_key = service_key
        self.base_url = "http://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"

    def get_building_info(self, sigungu_cd, bjdong_cd, bun, ji):
        if not self.service_key: return {"status": "error", "msg": "API Key Missing"}
        
        # requests 라이브러리는 serviceKey를 자동으로 인코딩하므로, 
        # 사용자가 이미 인코딩된 키(%)를 넣었다면 디코딩 처리 필요
        key_to_use = requests.utils.unquote(self.service_key)

        params = {
            "serviceKey": key_to_use, 
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
                            "주용도": item.findtext("mainPurpsCdNm") or "미지정",
                            "연면적": item.findtext("totArea") or "0",
                            "사용승인일": item.findtext("useAprDay") or "-",
                            "구조": item.findtext("strctCdNm") or "-",
                            "위반여부": "위반" if item.findtext("otherConst") else "정상"
                        }
                    else: 
                        # 정상 응답이지만 데이터가 없는 경우 (나대지 등)
                        return {"status": "nodata", "msg": "건물 정보 없음 (토지 상태)"}
                except: return {"status": "error", "msg": "데이터 파싱 오류"}
            
            # 500 에러 발생 시 처리 (키 문제 or 데이터 없음)
            elif response.status_code == 500:
                return {"status": "nodata", "msg": "데이터 미존재 (나대지 가능성)"}
            else: 
                return {"status": "error", "msg": f"서버 오류 {response.status_code}"}
        except Exception as e: return {"status": "error", "msg": str(e)}

# --------------------------------------------------------------------------------
# [Engine 3] PDF Generator
# --------------------------------------------------------------------------------
def generate_final_pdf(address, context):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    font_name = 'Helvetica'
    if os.path.exists("NanumGothic.ttf"): 
        pdfmetrics.registerFont(TTFont('NanumGothic', "NanumGothic.ttf"))
        font_name = 'NanumGothic'
    
    c.setFont(font_name, 24)
    c.drawCentredString(width/2, height-40*mm, "Jisang AI 부동산 분석 보고서")
    c.line(20*mm, height-45*mm, width-20*mm, height-45*mm)

    c.setFont(font_name, 12)
    y_pos = height - 70*mm
    c.drawString(25*mm, y_pos, f"주소: {address}")
    c.drawString(25*mm, y_pos-10*mm, f"일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    y_pos -= 30*mm
    c.setFont(font_name, 16)
    
    # 토지 상태일 경우 리포트 내용 변경
    if context.get('status') == 'nodata':
        c.drawString(25*mm, y_pos, "[토지 분석 결과]")
        c.setFont(font_name, 12)
        c.drawString(30*mm, y_pos-15*mm, "• 현재 해당 지번에는 건축물대장이 존재하지 않습니다.")
        c.drawString(30*mm, y_pos-25*mm, "• 나대지(빈 땅)이거나, 미등기 건물일 가능성이 있습니다.")
    else:
        c.drawString(25*mm, y_pos, "[건축물 데이터 요약]")
        c.setFont(font_name, 12)
        y_pos -= 15*mm
        lines = [
            f"• 용도: {context.get('주용도', '-')}",
            f"• 위반: {context.get('위반여부', '-')}",
            f"• 면적: {context.get('연면적', '-')} m2",
            f"• 구조: {context.get('구조', '-')}"
        ]
        for line in lines:
            c.drawString(30*mm, y_pos, line)
            y_pos -= 10*mm

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# --------------------------------------------------------------------------------
# [UI] Dashboard
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Universe", page_icon="🏗️", layout="wide")

with st.sidebar:
    st.title("🏗️ Jisang AI")
    st.markdown("---")
    addr_input = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.button("🚀 분석 실행", type="primary", use_container_width=True):
        st.session_state['run'] = True
        st.session_state['addr'] = addr_input

st.title("지상 AI 부동산 분석 시스템")

if st.session_state.get('run'):
    target = st.session_state['addr']
    st.subheader(f"📍 분석 대상: {target}")
    
    # [수정] 지도 우선 표시 로직
    with st.status("데이터 분석 중...", expanded=True) as status:
        st.write("1. 카카오 위성 좌표 수신 중...")
        sigungu, bjdong, bun, ji, coords, msg = get_codes_from_kakao(target)
        
        if sigungu:
            # ✅ 지도부터 그리기 (Map First)
            if coords:
                st.write("✅ 위치 확인 완료")
                st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17, use_container_width=True)
            
            st.write("2. 건축물대장 데이터 조회 중...")
            connector = RealDataConnector(data_go_key)
            real_data = connector.get_building_info(sigungu, bjdong, bun, ji)
            
            # 결과 처리
            if real_data['status'] == 'success':
                status.update(label="건축물 분석 완료", state="complete", expanded=False)
                
                st.divider()
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("주용도", real_data['주용도'])
                c2.metric("위반여부", real_data['위반여부'], "주의" if real_data['위반여부']=="위반" else "정상", delta_color="inverse")
                c3.metric("연면적", f"{real_data['연면적']}㎡")
                c4.metric("사용승인", real_data['사용승인일'])
                
                if real_data['위반여부'] == "위반":
                    st.error("🚨 위반건축물입니다. 이행강제금 리스크를 확인하세요.")
                else:
                    st.success("✅ 건축물대장상 깨끗한 건물입니다.")

            # [수정] 데이터가 없거나(토지), 에러가 나도 유연하게 처리
            elif real_data['status'] == 'nodata':
                status.update(label="토지 분석 모드", state="complete", expanded=False)
                st.info("ℹ️ **건축물대장이 없습니다.** (현재 나대지이거나 미등기 상태)")
                st.caption("💡 팁: 건물 정보가 없다면 토지이용계획(LURIS) 확인이 필요합니다.")
                
            else:
                status.update(label="정부 서버 응답 지연", state="error")
                st.warning(f"건물 데이터 조회 불가: {real_data['msg']}")
                st.caption("💡 공공데이터포털 키 설정을 확인하거나, 잠시 후 다시 시도하세요.")

            # 보고서 다운로드 (데이터 없어도 가능하게)
            st.divider()
            st.download_button(
                label="📄 현황 보고서 다운로드 (PDF)",
                data=generate_final_pdf(target, real_data if real_data else {'status': 'error'}),
                file_name="Report.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

        else:
            status.update(label="주소 오류", state="error")
            st.error(f"주소를 찾을 수 없습니다: {msg}")
