import os
import re
import pickle

import streamlit as st
import google.generativeai as genai

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

# -------------------------
# 1. 초기 설정
# -------------------------
st.set_page_config(page_title="한국항공대학교 RAG 챗봇", page_icon="✈️")
st.title("✈️ 한국항공대학교 RAG 챗봇")
st.caption("궁금한 것을 물어보시면 교내 정보를 찾아 답변해 드립니다.")

DB_FAISS_PATH = r"C:\Users\sswon\source\repos\PythonApplication1\PythonApplication1\faiss_index"
DB_BM25_PATH = r"C:\Users\sswon\source\repos\PythonApplication1\PythonApplication1\bm25_retriever.pkl"

EMBEDDING_MODEL = "BAAI/bge-m3"


# -------------------------
# 2. Vector DB + BM25 로딩
# -------------------------
@st.cache_resource
def load_vector_db():
    if not os.path.exists(DB_FAISS_PATH):
        return None
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        db = FAISS.load_local(
            DB_FAISS_PATH,
            embeddings,
            allow_dangerous_deserialization=True,
        )
        return db
    except Exception as e:
        st.error(f"Vector DB 로딩 오류: {e}")
        return None


@st.cache_resource
def load_bm25_retriever():
    if not os.path.exists(DB_BM25_PATH):
        return None
    try:
        with open(DB_BM25_PATH, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        st.error(f"BM25 로딩 오류: {e}")
        return None


vector_db = load_vector_db()
bm25_retriever: BM25Retriever = load_bm25_retriever()

if vector_db is None or bm25_retriever is None:
    st.error("FAISS 또는 BM25 데이터베이스가 로드되지 않아 실행을 중단합니다.")
    st.stop()

faiss_retriever = vector_db.as_retriever(search_kwargs={"k": 15})   # 확장
bm25_retriever.k = 15                                              # 확장


# -------------------------
# 4. Ensemble Retriever (최적화 버전)
# -------------------------
class EnsembleRetriever:
    def __init__(self, retrievers, weights=None, k=3):
        self.retrievers = retrievers
        self.weights = weights or [1.0] * len(retrievers)
        self.k = k

    def _fetch_docs(self, retriever, query):
        if hasattr(retriever, "invoke"):
            try:
                return retriever.invoke(query) or []
            except Exception:
                pass

        if hasattr(retriever, "get_relevant_documents"):
            try:
                return retriever.get_relevant_documents(query) or []
            except Exception:
                pass

        return []

    def invoke(self, query):
        scored = {}
        seen_docs = {}

        for retriever, weight in zip(self.retrievers, self.weights):
            docs = self._fetch_docs(retriever, query)

            # 🔥 retriever별 최대 10개만 사용
            docs = docs[:10]

            for rank, doc in enumerate(docs):
                key = (doc.page_content, tuple(sorted(doc.metadata.items())))
                score = weight * (10 - rank)


                if key not in scored:
                    scored[key] = score
                    seen_docs[key] = doc
                else:
                    scored[key] += score

        # 🔥 점수순 정렬
        sorted_keys = sorted(scored.keys(), key=lambda k: -scored[k])

        result_docs = []
        for key in sorted_keys[: self.k]:
            result_docs.append(seen_docs[key])

        return result_docs


ensemble_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, faiss_retriever],
    weights=[0.3, 0.7],   # 수정된 가중치
    k=3,
)


# -------------------------
# 5. get_relevant_documents (간결 최적화)
# -------------------------
def get_relevant_documents(query: str):
    return ensemble_retriever.invoke(query)


# -------------------------
# 6. Gemini LLM
# -------------------------
if "GOOGLE_API_KEY" not in st.secrets:
    st.error("GOOGLE_API_KEY가 없습니다. Streamlit Secrets에 등록해주세요.")
    st.stop()

genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

system_message = """
당신은 한국항공대학교 안내 챗봇입니다.
문서의 내용에 기반하여 신뢰도 높은 답변을 제공해야 합니다.

[매우 중요] 출처 표기 규칙:
1. 답변 생성 후, 반드시 자신이 주요 근거로 사용한 '문서 N'의 번호를 [근거: N] 형태로 붙이세요.
"""


def get_gemini_response_stream(prompt: str):
    try:
        model = genai.GenerativeModel("gemini-2.5-pro")
        stream = model.generate_content(prompt, stream=True)
        for chunk in stream:
            try:
                yield chunk.text
            except Exception:
                continue
    except Exception as e:
        st.error(f"Gemini 오류: {e}")
        yield ""


# -------------------------
# 7. 이전 질문 기억 삭제됨
# -------------------------


# -------------------------
# 8. Streamlit UI
# -------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("질문을 입력하세요."):

    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        full = ""

        with st.spinner("답변을 생각하고 있어요... 🤔"):

            combined_query = user_input.strip()

            print("=" * 50)
            print(f"Query: {combined_query}")

            # ------------------------------
            # BM25 검색 (중복 제거 포함 15개)
            # ------------------------------
            bm25_only = bm25_retriever.invoke(combined_query)
            bm25_seen = set()
            bm25_unique = []

            for d in bm25_only:
                key = f"{d.metadata.get('source','')}_{d.metadata.get('title','')}"
                if key not in bm25_seen:
                    bm25_seen.add(key)
                    bm25_unique.append(d)
                if len(bm25_unique) >= 15:
                    break

            print("\n--- 🟡 BM25 검색 결과 ---")
            for i, d in enumerate(bm25_unique, 1):
                print(f"[BM25 {i}] [{d.metadata.get('title')}] ({d.metadata.get('source')})")

            # ------------------------------
            # FAISS 검색 (중복 제거 포함 15개)
            # ------------------------------
            faiss_only = faiss_retriever.invoke(combined_query)
            faiss_seen = set()
            faiss_unique = []

            for d in faiss_only:
                key = f"{d.metadata.get('source','')}_{d.metadata.get('title','')}"
                if key not in faiss_seen:
                    faiss_seen.add(key)
                    faiss_unique.append(d)
                if len(faiss_unique) >= 15:
                    break

            print("\n--- 🔵 FAISS 검색 결과 ---")
            for i, d in enumerate(faiss_unique, 1):
                print(f"[FAISS {i}] [{d.metadata.get('title')}] ({d.metadata.get('source')})")

            # ------------------------------
            # 앙상블 최종
            # ------------------------------
            docs = get_relevant_documents(combined_query)

            print("\n--- 🔴 앙상블 최종 검색 결과 ---")
            for i, d in enumerate(docs, 1):
                print(f"[FINAL {i}] [{d.metadata.get('title')}] ({d.metadata.get('source')})")

            print("====================================================")

            # ------------------------------
            # LLM 문맥 구성
            # ------------------------------
            context = ""
            for i, d in enumerate(docs):
                context += f"--- 문서 {i+1} ---\n"
                context += f"제목: {d.metadata.get('title')}\n"
                context += f"출처: {d.metadata.get('source')}\n"
                context += d.metadata.get("raw_content", d.page_content) + "\n\n"

            final_prompt = (
                system_message
                + "\n\n[Context]\n"
                + context
                + f"\n\n[사용자 질문]\n{user_input}"
                + "\n\n[답변] (출처 표기 규칙을 반드시 지켜주세요.)"
            )

            placeholder = st.empty()

            for t in get_gemini_response_stream(final_prompt):
                full += t
                placeholder.markdown(full + "▌")

        # -------------------------
        # 근거 태그 파싱
        # -------------------------
        source_matches = re.findall(r"\[근거:\s*([\d,\s]+)\]", full)
        final_content = re.sub(r"\[근거:[^\]]*\]", "", full).strip()

        footer_items = []
        used_indexes = set()

        if source_matches:
            try:
                for match in source_matches:
                    indexes = match.replace(" ", "").split(",")

                    for idx in indexes:
                        if not idx.isdigit():
                            continue

                        num = int(idx)
                        if num in used_indexes:
                            continue
                        used_indexes.add(num)

                        doc_index = num - 1

                        if 0 <= doc_index < len(docs):
                            doc_to_cite = docs[doc_index]
                            source_url = doc_to_cite.metadata.get("source")
                            source_title = doc_to_cite.metadata.get("title", "제목 없음")
                            attachment_str = doc_to_cite.metadata.get("attachments")

                            if source_url:
                                footer_items.append(f"- [{source_title}]({source_url})")

                            if attachment_str:
                                first_item = attachment_str.split(";")[0]
                                parts = first_item.split("|")
                                if len(parts) == 2:
                                    filename, file_url = parts
                                    footer_items.append(
                                        f"- 📁 [{filename} (첨부파일)]({file_url})"
                                    )

            except Exception as e:
                print(f"근거 태그 처리 중 오류: {e}")

        footer_items = list(dict.fromkeys(footer_items))

        if footer_items:
            final_content += "\n\n---\n**참고한 출처:**\n" + "\n".join(footer_items)

        placeholder.markdown(final_content)
        st.session_state.messages.append({"role": "assistant", "content": final_content})
