# rag_core.py (AI 두뇌 전용 파일)
import os
import re
import pickle
import google.generativeai as genai

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever

# 1. 경로 설정 (상대 경로 적용!)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FAISS_PATH = os.path.join(BASE_DIR, "faiss_index")
DB_BM25_PATH = os.path.join(BASE_DIR, "bm25_retriever.pkl")
EMBEDDING_MODEL = "BAAI/bge-m3"

# 2. API 키 설정
if "GOOGLE_API_KEY" in os.environ:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
else:
    pass

# 3. DB 로더
def load_resources():
    print("Loading Vector DB & BM25...")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    
    vector_db = None
    bm25_retriever = None

    if os.path.exists(DB_FAISS_PATH):
        vector_db = FAISS.load_local(DB_FAISS_PATH, embeddings, allow_dangerous_deserialization=True)
    
    if os.path.exists(DB_BM25_PATH):
        with open(DB_BM25_PATH, "rb") as f:
            bm25_retriever = pickle.load(f)
            bm25_retriever.k = 10
            
    return vector_db, bm25_retriever

vector_db, bm25_retriever = load_resources()

if vector_db:
    faiss_retriever = vector_db.as_retriever(search_kwargs={"k": 10})
else:
    faiss_retriever = None


# 4. 앙상블 검색기
class EnsembleRetriever:
    def __init__(self, retrievers, weights=None, k=3):
        self.retrievers = retrievers
        self.weights = weights or [1.0] * len(retrievers)
        self.k = k

    def invoke(self, query):
        scored = {}
        seen_docs = {}

        for retriever, weight in zip(self.retrievers, self.weights):
            if retriever is None:
                continue
            try:
                if hasattr(retriever, "invoke"):
                    docs = retriever.invoke(query)
                else:
                    docs = retriever.get_relevant_documents(query)
            except:
                docs = []

            docs = docs[:10]
            for rank, doc in enumerate(docs):
                key = (doc.page_content, tuple(sorted(doc.metadata.items())))
                score = weight * (10 - rank)
                if key not in scored:
                    scored[key] = score
                    seen_docs[key] = doc
                else:
                    scored[key] += score
        
        sorted_keys = sorted(scored.keys(), key=lambda k: -scored[k])
        return [seen_docs[key] for key in sorted_keys[: self.k]]

# 초기화
ensemble = None
if vector_db and bm25_retriever:
    ensemble = EnsembleRetriever(
        retrievers=[bm25_retriever, faiss_retriever],
        weights=[0.3, 0.7],
        k=5,
    )


# 5. 핵심 질문 처리 함수
def get_ai_response(user_input):
    if not ensemble:
        return "죄송합니다. 데이터베이스가 로드되지 않았습니다."

    # (1) 검색
    docs = ensemble.invoke(user_input)

    final_seen = set()
    unique_docs = []
    for d in docs:
        key = f"{d.metadata.get('source','')}_{d.metadata.get('title','')}"
        if key not in final_seen:
            final_seen.add(key)
            unique_docs.append(d)

    # (2) 프롬프트 구성
    context = ""
    for i, d in enumerate(unique_docs):
        context += f"--- 문서 {i+1} ---\n"
        context += f"제목: {d.metadata.get('title')}\n"
        context += f"출처: {d.metadata.get('source')}\n"
        context += d.metadata.get("raw_content", d.page_content) + "\n\n"

    system_message = """
    항공대와 관련된 공식 문서, 공지사항, 학사 일정, 규정 등의 내용을 기반으로 정확하게 답변하세요.

    [답변 원칙]
    1. 답변은 반드시 제공된 문서와 데이터에 근거해야 합니다.
    2. 문서에 없거나 불확실한 내용은 임의로 지어내지 말고, "해당 내용은 문서에서 확인되지 않습니다."라고 말하세요.
    3. 학생들이 이해하기 쉽도록 짧고 명확하게 설명하세요.
    5. 답변 마지막에 참고한 문서 번호를 [근거: 1, 3] 형태로 붙이세요.
    6. 문서 간 내용 충돌이 있을 경우, 최신 문서(번호가 가장 큰 것)를 우선합니다.

    [추가 규칙]
    - 학사일정, 수업, 시험, 장학금, 등록금 등 학생 관련 질문에 친절하고 정확하게 답합니다.
    - 개인 정보, 민감한 조언(법률, 의학 등), 사실이 아닌 내용은 제공하지 않습니다.
    - 질문이 모호하면 명확한 답변을 위해 추가 질문을 요청하세요.
    - 답변에는 어떤 형태의 URL, 링크, 출처 링크도 포함하지 마세요.

    """

    final_prompt = f"{system_message}\n\n[Context]\n{context}\n\n[질문]\n{user_input}\n\n[답변]"

    # (3) Gemini 호출
    try:
        model = genai.GenerativeModel("gemini-2.5-pro")
        response = model.generate_content(final_prompt)
        full_text = response.text
    except Exception as e:
        return f"AI 응답 생성 중 오류가 발생했습니다: {e}"

    # (4) 출처 태그 제거
    source_matches = re.findall(r"\[근거:\s*([\d,\s]+)\]", full_text)
    final_content = re.sub(r"\[근거:[^\]]*\]", "", full_text).strip()

    footer_items = []
    used_indexes = set()

    if source_matches:
        for match in source_matches:
            indexes = match.replace(" ", "").split(",")
            for idx in indexes:
                if idx.isdigit():
                    num = int(idx)
                    if num not in used_indexes:
                        used_indexes.add(num)
                        doc_index = num - 1
                        if 0 <= doc_index < len(unique_docs):
                            doc = unique_docs[doc_index]

                            title = doc.metadata.get("title", "제목 없음")
                            url = doc.metadata.get("source", "")
                            if url:
                                footer_items.append(f"- [{title}]({url})")

                            # ★ 첨부파일 추가
                            attach_raw = doc.metadata.get("attachments")
                            if attach_raw:
                                for item in attach_raw.split(";"):
                                    parts = item.split("|")
                                    if len(parts) == 2:
                                        fname, furl = parts
                                        footer_items.append(f"- 📁 [{fname}]({furl})")

    if footer_items:
        final_content += "\n\n---\n**참고한 출처:**\n" + "\n".join(footer_items)

    return final_content
