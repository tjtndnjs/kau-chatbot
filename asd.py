import requests
from bs4 import BeautifulSoup
import os
import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse
import base64
import google.generativeai as genai
from dotenv import load_dotenv
from PIL import Image, ImageFile
import io

ImageFile.LOAD_TRUNCATED_IMAGES = True

# ----------------------------
# 1. API 키 및 모델 로드
# ----------------------------
load_dotenv()
API_KEY = os.environ.get("GOOGLE_API_KEY")
if not API_KEY:
    print("오류: .env 파일에 GOOGLE_API_KEY가 없습니다.")
    exit()

genai.configure(api_key=API_KEY)

OCR_MODEL = genai.GenerativeModel('gemini-2.5-pro')
OCR_PROMPT = """
이 이미지는 공지사항 문서입니다.
이미지 상단부터 하단까지, 눈에 보이는 모든 텍스트를 순서대로 빠짐없이 추출해주세요.
배경색이 다르더라도 모든 영역의 텍스트를 포함해야 합니다.
설명이나 요약 없이, 추출된 텍스트 원본만 제공해주세요.
"""


# ----------------------------
# 2. 텍스트 클린 함수
# ----------------------------
def clean_text(text):
    text = re.sub(r'\n\s*\n', '\n', text)
    lines = [line.strip() for line in text.split('\n')]
    cleaned_lines = [line for line in lines if len(line) > 5]
    return "\n".join(cleaned_lines)


# ----------------------------
# 3. Gemini OCR 함수
# ----------------------------
def ocr_with_gemini(image_url, headers):
    try:
        image_content = None

        if image_url.startswith('data:image'):
            print(f"    -> 🖼️ 데이터 URL 처리 시도...")
            header, encoded = image_url.split(',', 1)
            image_content = base64.b64decode(encoded)
        else:
            print(f"    -> 🖼️ 웹 이미지 처리 시도: {image_url[:70]}...")
            response = requests.get(image_url, headers=headers, stream=True, timeout=15)
            response.raise_for_status()
            image_content = response.content

        if not image_content:
            return None

        img = Image.open(io.BytesIO(image_content))

        # 이미지 모드 처리
        if img.mode in ('RGBA', 'LA'):
            print("    -> 💡 투명도(PNG) 감지. 흰색 배경으로 병합합니다.")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, (0, 0), img)
            img = background
        elif img.mode != 'RGB':
            print(f"    -> 💡 이미지 모드({img.mode})를 RGB로 변환합니다.")
            img = img.convert('RGB')

        print(f"    -> 🤖 Gemini OCR 시도...")
        response = OCR_MODEL.generate_content([OCR_PROMPT, img])
        time.sleep(1)

        extracted_text = response.text.strip()
        if extracted_text and len(extracted_text) > 5:
            print("    -> ✅ Gemini OCR 성공")
            return extracted_text
        else:
            print("    -> ℹ️ Gemini OCR 결과 텍스트 없음")
            return None

    except Exception as e:
        print(f"    -> ❌ Gemini OCR 처리 실패! 오류 타입: {e.__class__.__name__}, 메시지: {e}")
        return None


# ----------------------------
# 4. 본문 + 이미지 + 첨부파일 추출 함수
# ----------------------------
def extract_content_from_soup(soup, url):
    try:
        title = soup.select_one('div.view_header h4').get_text(strip=True)

        content_area = soup.select_one('div.view_conts')
        main_text, image_urls = "", []

        if content_area:

            # 이미지 수집
            for img_tag in content_area.select('img[src]'):
                image_urls.append(urljoin(url, img_tag['src']))

            # script/style 제거
            for tag in content_area.find_all(['script', 'style']):
                tag.decompose()

            # ----------------------------
            # ⚡ 새 로직: 본문 + 테이블을 원래 순서대로 조합
            # ----------------------------
            result_lines = []

            for elem in content_area.children:
                # 텍스트 요소일 경우
                if elem.name is None:
                    text = elem.strip()
                    if text:
                        result_lines.append(text)

                # 테이블일 경우 → 테이블 파싱해서 삽입
                elif elem.name == "table":
                    table_rows = []
                    for tr in elem.find_all("tr"):
                        cols = []
                        for td in tr.find_all(["td", "th"]):
                            cell = td.get_text(separator=" ", strip=True)
                            cell = re.sub(r'\s+', ' ', cell)
                            cols.append(cell)
                        if cols:
                            table_rows.append(" | ".join(cols))
                    if table_rows:
                        result_lines.append("\n".join(table_rows))

                # p, div 등 다른 태그의 텍스트 처리
                else:
                    text = elem.get_text(separator="\n", strip=True)
                    if text:
                        result_lines.append(text)

            # 최종 main_text 구성
            main_text = "\n".join(result_lines)

        # 첨부파일
        attachments = []

        attachment_li = soup.select_one('li.attatch a[href]')
        if attachment_li:
            attachments.append({
                'filename': attachment_li.get_text(strip=True),
                'url': urljoin(url, attachment_li['href'])
            })

        file_list_area = soup.select_one('div.view_file')
        if file_list_area:
            for link_tag in file_list_area.select('a[href]'):
                attachments.append({
                    'filename': link_tag.get_text(strip=True),
                    'url': urljoin(url, link_tag['href'])
                })

        return title, main_text or '본문 없음', image_urls, attachments

    except Exception as e:
        print(f"       -> ❌ 웹 페이지 파싱 오류: {e}")
        return "제목 없음", "본문 없음", [], []

   

# ----------------------------
# 5. 크롤링 함수
# ----------------------------
def start_crawling(start_url, headers, output_folder="cleaned_texts", max_pages=100):
    os.makedirs(output_folder, exist_ok=True)
    queue = deque([start_url])
    visited_urls = {start_url}
    page_count = 0

    base_netloc = urlparse(start_url).netloc
    allowed_patterns = ['acdnoti.php', 'notice.php']

    while queue and page_count < max_pages:
        current_url = queue.popleft()

        print(f"\n➡️  페이지 방문/수집: {current_url}")
        try:
            response = requests.get(current_url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            print(f"    -> ❌ 페이지 방문 오류: {e}")
            continue

        # ----------------------------
        # 게시글 읽기 모드일 때 처리
        # ----------------------------
        if 'mode=read' in current_url:
            title, main_text, image_urls, attachments = extract_content_from_soup(soup, current_url)
            print(f"    -> ✅ [{page_count + 1}/{max_pages}] 게시물 처리: {title[:30]}...")

            ocr_texts = []
            for img_url in image_urls:
                if img_url and urlparse(img_url).scheme in ['http', 'https', 'data']:
                    ocr_result = ocr_with_gemini(img_url, headers)
                    if ocr_result:
                        ocr_texts.append(ocr_result)

            # OCR 텍스트 포함
            full_content = main_text
            if ocr_texts:
                full_content += "\n\n--- 이미지 추출 텍스트 (Gemini OCR) ---\n"
                full_content += "\n".join(ocr_texts)

            final_text_to_save = f"출처 URL: {current_url}\n"
            final_text_to_save += f"제목: {title}\n"

            # ---------- ★ 여기 수정됨 (문법 오류 제거) ----------
            if attachments:
                attachment_text = ";".join(
                    [f"{att['filename']}|{att['url']}" for att in attachments]
                )
                final_text_to_save += f"첨부파일: {attachment_text}\n"
            # -----------------------------------------------------

            final_text_to_save += f"{'=' * 40}\n\n{clean_text(full_content)}"

            post_id_match = re.search(r'seq=(\d+)', current_url)
            if post_id_match:
                post_id = post_id_match.group(1)
                filename = f"kau_article_{post_id}.txt"
                try:
                    with open(os.path.join(output_folder, filename), 'w', encoding='utf-8') as f:
                        f.write(final_text_to_save)
                    page_count += 1
                except Exception as write_e:
                    print(f"    -> ❌ 파일 쓰기 오류: {write_e}")
            else:
                print(f"    -> ⚠️ 게시글 ID(seq) 없음, 파일 저장 스킵.")


        # ----------------------------
        # 링크 수집
        # ----------------------------
        try:
            for link in soup.find_all('a', href=True):
                absolute_url = urljoin(current_url, link['href']).split('#')[0]

                if (
                    urlparse(absolute_url).netloc == base_netloc and
                    absolute_url not in visited_urls and
                    any(p in absolute_url for p in allowed_patterns)
                ):
                    visited_urls.add(absolute_url)
                    queue.append(absolute_url)

        except Exception as e:
            print(f"    -> ❌ 링크 수집 오류: {e}")


# ----------------------------
# 6. 실행
# ----------------------------
if __name__ == "__main__":
    start_url = 'https://kau.ac.kr/kaulife/acdnoti.php?searchkey=&searchvalue=&code=s1201&page=&mode=read&seq=9897'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/129.0.0.0 Safari/537.36'
    }

    start_crawling(start_url, headers, max_pages=100)
    print("\n\n크롤링 완료.")
