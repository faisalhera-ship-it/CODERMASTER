import streamlit as st
import pandas as pd
import io
import re
import requests
from pypdf import PdfReader
from docx import Document
from google import genai
from google.genai import types

# ==========================================
# KONFIGURASI HALAMAN & API KEY
# ==========================================
st.set_page_config(
    page_title="BPJS Auto-Coder & Pending Resolver",
    page_icon="🏥",
    layout="wide"
)

# API Key Anda yang sudah tertanam langsung di kode
GEMINI_API_KEY = "AQ.Ab8RN6L0_4PPOA-4MZlKlQMiglQqxUDCzRx2nA8hMGHlS_-ZJg"

# ==========================================
# FUNGSI EKSTRAKSI & GOOGLE DRIVE HELPER
# ==========================================
def extract_gdrive_id(url):
    """Mengambil File ID dari berbagai format link Google Drive / Sheets."""
    patterns = [
        r'/d/([a-zA-Z0-9-_]+)',
        r'id=([a-zA-Z0-9-_]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_from_gdrive(url, is_excel=False):
    """Mengunduh file dari Google Drive yang berstatus 'Anyone with the link'."""
    file_id = extract_gdrive_id(url)
    if not file_id:
        raise ValueError("Link Google Drive tidak valid. Pastikan link berisi ID file.")
    
    if is_excel or "spreadsheets" in url:
        download_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
    else:
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
    response = requests.get(download_url)
    if response.status_code != 200:
        raise ConnectionError("Gagal mengunduh dari Google Drive. Pastikan akses file sudah diatur ke 'Siapa saja yang memiliki link (Anyone with the link)'.")
    
    return io.BytesIO(response.content), response.headers.get('Content-Type', '')

def read_document_text(file_bytes, filename="", content_type=""):
    """Membaca teks dari PDF, DOCX, TXT, atau Excel."""
    text = ""
    fname = filename.lower()
    
    try:
        if fname.endswith('.pdf') or 'pdf' in content_type:
            reader = PdfReader(file_bytes)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif fname.endswith('.docx') or 'wordprocessingml' in content_type:
            doc = Document(file_bytes)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif fname.endswith(('.xlsx', '.xls')) or 'spreadsheet' in content_type:
            df = pd.read_excel(file_bytes)
            text = df.to_string(index=False)
        else:
            try:
                reader = PdfReader(file_bytes)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            except:
                file_bytes.seek(0)
                text = file_bytes.read().decode('utf-8', errors='ignore')
    except Exception as e:
        raise RuntimeError(f"Gagal mengekstrak teks dokumen: {e}")
        
    return text.strip()

# ==========================================
# FUNGSI AI CODING & ANALISIS PENDING (GEMINI)
# ==========================================
def analyze_coding_ai(medical_text):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
    Anda adalah seorang Senior Clinical Coder & Verifikator Medis Rumah Sakit di Indonesia yang sangat ahli dalam kaidah Koding INA-CBG / iDRG, ICD-10, ICD-9-CM, Permenkes (PMK No. 26 Tahun 2021 tentang Pedoman INA-CBG dan aturan BPJS Kesehatan terbaru), serta PNPK Kemenkes.

    Berdasarkan teks Resume Medis / Rekam Medis berikut, lakukan analisis koding secara mendalam dan akurat:

    TEKS REKAM MEDIS:
    \"\"\"{medical_text}\"\"\"

    Berikan output terstruktur dengan format Markdown berikut:
    1. **Ringkasan Klinis Singkat** (Keluhan utama, pemeriksaan fisik/penunjang penting, terapi utama).
    2. **Diagnosis Utama (ICD-10)**
       - Kode ICD-10 & Deskripsi Resmi
       - Alasan pemilihan sebagai Diagnosis Utama sesuai aturan MB1–MB5 & PMK 26/2021.
    3. **Diagnosis Sekunder / Komorbid / Komplikasi (ICD-10)**
       - Daftar kode ICD-10 beserta bukti klinis/penunjang yang mendukung (misal: hasil lab/radiologi/terapi yang diberikan).
    4. **Tindakan / Prosedur Medis (ICD-9-CM)**
       - Daftar kode ICD-9-CM untuk seluruh tindakan operasi maupun non-operasi (USG, CT-Scan, transfusi, pemasangan alat, dll).
    5. **Audit Potensi Pending BPJS (Early Warning)**
       - Peringatan dini jika ada diagnosis/tindakan yang rawan terkena *pending* verifikator BPJS (misal: aturan *combination code*, koding *asterisks-dagger*, atau syarat bukti penunjang sesuai PNPK).
    """
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2)
    )
    return response.text

def resolve_pending_ai(pending_df, rm_context=""):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    excel_data_str = pending_df.to_markdown(index=False)
    
    prompt = f"""
    Anda adalah Dokter Verifikator Internal RS & Spesialis Casemix JKN. Tugas Anda adalah menjawab daftar **Pending Klaim BPJS Kesehatan** berdasarkan regulasi **PMK No. 26 Tahun 2021**, Berita Acara Kesepakatan Bersama Panduan Penatalaksanaan Solusi Permasalahan Klaim INA-CBG (Kemenkes & BPJS), serta **PNPK (Pedoman Nasional Pelayanan Kedokteran)** terbaru.

    DATA TABEL PENDING DARI EXCEL:
    {excel_data_str}

    KONTEKS REKAM MEDIS TAMBAHAN (Jika tersedia):
    \"\"\"{rm_context if rm_context else 'Tidak ada file RM tambahan dilampirkan, jawab berdasarkan data pada tabel Excel.'}\"\"\"

    INSTRUKSI:
    Untuk SETIAP baris kasus pending pada tabel di atas, buatkan jawaban sanggahan/klarifikasi medis yang profesional, tegas, berbasis bukti klinis, dan mencantumkan dasar regulasi (PMK / PNPK / Kaidah ICD-10 & ICD-9-CM) yang relevan agar klaim layak bayar.

    Sajikan output dalam bentuk **Tabel Markdown** yang rapi dengan kolom:
    - No / No. SEP (sesuai data)
    - Masalah Pending
    - Analisis & Dasar Regulasi (PMK / PNPK / Kaidah Koding)
    - Draft Jawaban Resmi ke Verifikator BPJS (Siap Copy-Paste ke aplikasi E-Klaim/Vidi)
    - Dokumen Pendukung yang Wajib Dilampirkan
    """
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2)
    )
    return response.text

# ==========================================
# ANTARMUKA PENGGUNA (UI STREAMLIT)
# ==========================================
st.title("🏥 Sistem Auto-Coding ICD-10/9 & Jawaban Pending BPJS")
st.markdown("Otomatisasi koding rekam medis dan penyelesaian *dispute/pending* klaim JKN berbasis **PMK & PNPK Terbaru**.")

# Sidebar informasi
with st.sidebar:
    st.header("⚙️ Informasi Sistem")
    st.success("✅ Gemini API Terhubung Otomatis")
    st.info("💡 **Tips Google Drive:** Pastikan link file/spreadsheet sudah diatur ke **'Anyone with the link' (Siapa saja yang memiliki link)** agar bisa ditarik otomatis.")
    st.markdown("---")
    st.caption("Referensi Regulasi: PMK No. 26/2021, PNPK Kemenkes, Kaidah ICD-10 & ICD-9-CM.")

# Tab Navigasi Utama
tab1, tab2 = st.tabs([
    "🩺 Auto-Coding ICD-10 & ICD-9 (Rekam Medis)", 
    "⚖️ Jawab Pending BPJS (Excel & G-Drive)"
])

# ------------------------------------------
# TAB 1: AUTO CODING REKAM MEDIS
# ------------------------------------------
with tab1:
    st.subheader("Ekstraksi Otomatis ICD-10 & ICD-9-CM dari Rekam Medis")
    
    input_method_rm = st.radio(
        "Pilih Sumber Rekam Medis:",
        ["Upload File (PDF / Word / TXT)", "Link Google Drive", "Paste Teks Resume Medis"],
        horizontal=True
    )
    
    rm_text_extracted = ""
    
    if input_method_rm == "Upload File (PDF / Word / TXT)":
        uploaded_rm = st.file_uploader("Upload dokumen Resume Medis / CPPT / Laporan Operasi", type=["pdf", "docx", "txt"])
        if uploaded_rm:
            with st.spinner("Membaca isi dokumen..."):
                rm_text_extracted = read_document_text(uploaded_rm, uploaded_rm.name)
                
    elif input_method_rm == "Link Google Drive":
        gdrive_rm_url = st.text_input("Tempel Link Google Drive Rekam Medis (PDF/Docx):")
        if gdrive_rm_url:
            if st.button("Tarik Dokumen dari G-Drive"):
                try:
                    with st.spinner("Mengunduh dan membaca file dari Google Drive..."):
                        file_bytes, c_type = download_from_gdrive(gdrive_rm_url, is_excel=False)
                        rm_text_extracted = read_document_text(file_bytes, content_type=c_type)
                        st.session_state['rm_gdrive_text'] = rm_text_extracted
                        st.success("Dokumen berhasil dibaca!")
                except Exception as e:
                    st.error(str(e))
        if 'rm_gdrive_text' in st.session_state:
            rm_text_extracted = st.session_state['rm_gdrive_text']
            
    else:
        rm_text_extracted = st.text_area("Tempel teks resume medis di sini:", height=200, placeholder="Contoh: Pasien datang dengan keluhan nyeri dada menjalar ke lengan kiri...")

    if rm_text_extracted:
        with st.expander("📄 Lihat Teks Rekam Medis yang Terbaca"):
            st.text(rm_text_extracted[:3000] + ("..." if len(rm_text_extracted) > 3000 else ""))
            
        if st.button("🚀 Generate Kode ICD-10 & ICD-9 Sekarang", type="primary"):
            with st.spinner("Menganalisis klinis & mencocokkan kaidah ICD-10 / ICD-9-CM..."):
                try:
                    hasil_coding = analyze_coding_ai(rm_text_extracted)
                    st.markdown("---")
                    st.markdown(hasil_coding)
                    
                    st.download_button(
                        label="📥 Download Hasil Koding (.md)",
                        data=hasil_coding,
                        file_name="Hasil_Auto_Coding_ICD.md",
                        mime="text/markdown"
                    )
                except Exception as e:
                    st.error(f"Terjadi kesalahan AI: {e}")

# ------------------------------------------
# TAB 2: PENYELESAIAN PENDING BPJS
# ------------------------------------------
with tab2:
    st.subheader("Otomatisasi Jawaban Pending Klaim BPJS Sesuai PMK & PNPK")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**1. Sumber Data Pending (Excel / Google Sheets)**")
        pending_source = st.radio(
            "Pilih sumber file pending:",
            ["Upload File Excel (.xlsx)", "Link Google Sheets / G-Drive Excel"],
            key="pending_src"
        )
        
        df_pending = None
        if pending_source == "Upload File Excel (.xlsx)":
            uploaded_excel = st.file_uploader("Upload Excel Daftar Pending BPJS", type=["xlsx", "xls"])
            if uploaded_excel:
                df_pending = pd.read_excel(uploaded_excel)
        else:
            gdrive_excel_url = st.text_input("Tempel Link Google Sheets / Drive Excel Pending:")
            if gdrive_excel_url and st.button("Tarik Excel Pending dari G-Drive"):
                try:
                    with st.spinner("Mengambil data spreadsheet..."):
                        excel_bytes, _ = download_from_gdrive(gdrive_excel_url, is_excel=True)
                        df_pending = pd.read_excel(excel_bytes)
                        st.session_state['df_pending_gdrive'] = df_pending
                        st.success("Data Excel berhasil dimuat!")
                except Exception as e:
                    st.error(str(e))
            if 'df_pending_gdrive' in st.session_state:
                df_pending = st.session_state['df_pending_gdrive']

    with col2:
        st.markdown("**2. Bukti Rekam Medis Pendukung (Opsional)**")
        rm_support_url = st.text_input("Link Google Drive Rekam Medis Pasien:")
        rm_support_file = st.file_uploader("Atau Upload File RM Pendukung (PDF/Docx)", type=["pdf", "docx"], key="rm_supp")
        
        rm_support_text = ""
        if rm_support_file:
            rm_support_text = read_document_text(rm_support_file, rm_support_file.name)
        elif rm_support_url:
            try:
                f_bytes, c_type = download_from_gdrive(rm_support_url, is_excel=False)
                rm_support_text = read_document_text(f_bytes, content_type=c_type)
            except Exception as e:
                st.warning(f"Catatan G-Drive RM: {e}")

    if df_pending is not None:
        st.markdown("### 📊 Preview Data Pending yang Terbaca")
        st.dataframe(df_pending, use_container_width=True)
        
        if st.button("⚖️ Jawab Semua Pending Sesuai PMK & PNPK", type="primary"):
            with st.spinner("Menyusun argumen medis dan dasar hukum PMK/PNPK untuk seluruh kasus..."):
                try:
                    hasil_pending = resolve_pending_ai(df_pending, rm_support_text)
                    st.markdown("---")
                    st.markdown("### ✅ Hasil Jawaban & Sanggahan Pending BPJS")
                    st.markdown(hasil_pending)
                    
                    st.download_button(
                        label="📥 Download Laporan Jawaban Pending (.md)",
                        data=hasil_pending,
                        file_name="Jawaban_Pending_BPJS_PMK_PNPK.md",
                        mime="text/markdown"
                    )
                except Exception as e:
                    st.error(f"Terjadi kesalahan saat memproses jawaban: {e}")
