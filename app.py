import os
import sys
import subprocess
import urllib.request
import io
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd

# [Step 0] 스마트 런처 (필수 라이브러리 자동 점검 및 설치)
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

    # 한글 폰트 다운로드 (PDF용)
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

# API Keys Load (Secrets에서 로드)
api_key = st.secrets.get("GOOGLE_API_KEY")
data_go_key = st.secrets.get("DATA_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] Kakao Geocoding (주소 -> 행정코드 & 좌표 변환)
# --------------------------------------------------------------------------------
def get_codes_from_kakao(address):
    if not kakao_key:
        return None, None, None, None, None, "카카오 API 키 미설정 (Secrets 확인 필요)"
    
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    params = {"query": address}
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                # 1. 좌표 (지도 표시용 - float 변환 필수)
                lat = float(docs[0]['y'])
                lon = float(docs[0]['x'])
                
                # 2. 행정코드 파싱
                b_code = docs[0]['address']['b_code']
                sigungu_cd = b_code[:5]
                bjdong_cd = b_code[5:]
                
                # 3. 지번 파싱 (4자리 패딩: 1 -> 0001)
                main_no = docs[0]['address']['main_address_no']
                sub_no = docs[0]['address']['sub_address_no']
                bun = main_no.zfill(4)
                ji = sub_no.zfill(4) if sub_no else "0000"
                
                return sigungu_cd, bjdong_cd, bun, ji, (lat, lon), "Success"
            else:
                return None, None, None, None, None, "주소를 찾을 수 없습니다. (도로명 혹은 지번 주소를 정확히 입력하세요)"
        else:
            return None, None, None, None, None, f"카카오 API 오류 ({resp.status_code})"
    except Exception as e:
        return None, None, None, None, None, f"통신 실패: {str(e)}"

# --------------------------------------------------------------------------------
# [Engine 2] Real Data Connector (공공데이터포털 - 건축물대장)
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
                    else: return {"status": "nodata", "msg": "해당 지번에 건축물대장이 없습니다. (나대지 가능성)"}
                except: return {"status": "error", "msg": "XML 파싱 오류 (데이터 형식이 올바르지 않음)"}
            else: return {"status": "error", "msg": f"정부 서버 오류 {response.status_code}"}
        except Exception as e: return {"status": "error", "msg": str(e)}

# --------------------------------------------------------------------------------
# [Engine 3] PDF Generator (오류 수정 완료)
# --------------------------------------------------------------------------------
def generate_final_pdf(address, context):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # 폰트 로드 (없으면 기본 폰트)
    font_name = 'Helvetica'
    font_path = "NanumGothic.ttf"
    if os.path.exists(font_path): 
        pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
        font_name = 'NanumGothic'
    
    # Header
    c.setFont(font_name, 24)
    c.drawCentredString(width/2, height-40*mm, "Jisang AI 부동산 정밀 분석 보고서")
    
    c.setStrokeColorRGB(0.2, 0.2, 0.8)
    c.line(20*mm, height-45*mm, width-20*mm, height-45*mm)

    # Body Info
    c.setFont(font_name, 12)
    y = height - 70*mm
    c.drawString(25*mm,
