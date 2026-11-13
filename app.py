import streamlit as st
import pandas as pd
import io
import re
import requests
from PIL import Image
from pypdf import PdfReader
from google import genai
from google.genai import types

# ==========================================
# KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(
    page_title="AI Casemix & Klaim BPJS Assistant",
    page_icon="🏥",
    layout="wide"
)

# ==========================================
# SYSTEM PROMPT (KAIDAH PMK & PNPK)
# ==========================================
SYSTEM_INSTRUCTION = """
Anda adalah Dokter Verifikator Internal & Senior Koder Casemix RS di Indonesia yang sangat ahli dalam:
1. Kaidah Koding ICD-10 (Revisi Tahun 2010) & ICD-9-CM (Revisi Tahun 2010).
2. Peraturan Menteri Kesehatan (PMK) No. 26 Tahun 2021 tentang Pedoman INA-CBG dalam Pelaksanaan JKN, serta Berita Acara Kesepakatan Bersama Penyelesaian Dispute Klaim Kemenkes-BPJS Kesehatan.
3. Pedoman Nasional Pelayanan Kedokteran (PNPK) Kemenkes RI terbaru (termasuk pembaruan PNPK 2024-2026) dan Panduan Praktik Klinis (PPK).

Aturan Jawaban:
- Selalu pisahkan secara jelas antara Diagnosis Utama (Primary Diagnosis), Diagnosis Sekunder (Komorbid/Komplikasi), dan Tindakan/Prosedur (ICD-9-CM).
- Berikan kode yang spesifik hingga digit ke-4 atau ke-5 jika diperlukan sesuai aturan morbiditas ICD-10.
- Untuk jawaban pending klaim BPJS, susun argumentasi medis yang tajam, objektif, berbasis bukti klinis pada rekam medis (hasil lab, radiologi, tanda vital, terapi), dan cantumkan dasar regulasi (PMK 26/2021, BA Kesepakatan Dispute, atau PNPK terkait) agar diterima oleh Verifikator BPJS.
- Gunakan bahasa Indonesia medis yang formal, terstruktur, dan siap salin (copy-paste) ke lembar jawaban konfirmasi klaim.
"""

# ==========================================
# FUNGSI HELPER
# ==========================================
def get_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)

def extract_gdrive_file_id(url: str):
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
        r"/spreadsheets/d/([a-zA-Z0-9_-]+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_from_gdrive(url: str, is_excel: bool = False):
    file_id = extract_gdrive_file_id(url)
    if not file_id:
        raise ValueError("Link Google Drive tidak valid. Pastikan format link benar.")
    
    if "spreadsheets" in url or is_excel:
        # Export Google Sheets atau download file Excel dari Drive
        download_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
        resp = requests.get(download_url)
        if resp.status_code != 200:
            # Fallback jika file berupa binary .xlsx yang diupload ke Drive
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            resp = requests.get(download_url)
    else:
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        resp = requests.get(download_url)
        
    if resp.status_code != 200:
        raise ConnectionError("Gagal mengunduh file. Pastikan akses Google Drive diubah ke 'Anyone with the link' (Siapa saja yang memiliki link).")
    return resp.content

def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for i, page in enumerate(reader.pages):
        extracted = page.extract_text()
        if extracted:
            text += f"\n--- Halaman {i+1} ---\n{extracted}"
    return text.strip()

# ==========================================
# SIDEBAR: KONFIGURASI API KEY
# ==========================================
with st.sidebar:
    st.title("⚙️ Pengaturan AI")
    st.markdown(
        "Aplikasi ini menggunakan **Google Gemini API (Gratis)**. "
        "Dapatkan API Key gratis di [Google AI Studio](https://aistudio.google.com/app/apikey)."
    )
    
    # Cek apakah API key sudah disimpan di Streamlit Secrets
    default_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
    api_key = st.text_input("Masukkan Gemini API Key:", value=default_key, type="password")
    
    model_choice = st.selectbox(
        "Pilih Model AI:",
        ["gemini-2.5-flash", "gemini-2.5-pro"],
        index=0,
        help="gemini-2.5-flash sangat cepat, akurat, dan memiliki kuota gratis harian yang besar."
    )
    
    st.divider()
    st.info(
        "**Standar Acuan Aktif:**\n"
        "- ICD-10 & ICD-9-CM (Versi 2010)\n"
        "- PMK No. 26 Tahun 2021\n"
        "- BA Kesepakatan Dispute Klaim\n"
        "- PNPK Kemenkes Terbaru"
    )

# ==========================================
# HEADER UTAMA
# ==========================================
st.title("🏥 AI Casemix: Koding ICD-10/9 & Jawaban Pending BPJS")
st.caption("Asisten Koder & Verifikator Internal RS berbasis AI sesuai PMK 26/2021 & PNPK Kemenkes")

if not api_key:
    st.warning("👈 Silakan masukkan **Gemini API Key** Anda di menu sebelah kiri untuk mulai menggunakan aplikasi.")
    st.stop()

client = get_gemini_client(api_key)

# ==========================================
# TABS FITUR UTAMA
# ==========================================
tab1, tab2, tab3 = st.tabs([
    "📄 Auto-Koding Rekam Medis (Upload / G-Drive)",
    "🔍 Pencarian Cepat ICD-10 & ICD-9-CM",
    "⚖️ Jawab Pendingan Klaim BPJS (Single & Batch Excel)"
])

# ------------------------------------------
# TAB 1: AUTO KODING REKAM MEDIS
# ------------------------------------------
with tab1:
    st.subheader("Ekstraksi Otomatis ICD-10 & ICD-9-CM dari Dokumen Rekam Medis")
    
    input_method = st.radio(
        "Pilih Sumber Rekam Medis:",
        ["Upload File (PDF / Gambar / TXT)", "Link Google Drive (Publik)", "Input Teks Manual"],
        horizontal=True
    )
    
    rm_content = None
    image_data = None
    
    if input_method == "Upload File (PDF / Gambar / TXT)":
        uploaded_file = st.file_uploader(
            "Unggah Resume Medis, Laporan Operasi, atau Hasil Penunjang",
            type=["pdf", "png", "jpg", "jpeg", "txt"]
        )
        if uploaded_file:
            file_bytes = uploaded_file.read()
            if uploaded_file.type == "application/pdf":
                with st.spinner("Membaca teks PDF..."):
                    rm_content = extract_text_from_pdf(file_bytes)
                    if not rm_content:
                        st.warning("PDF terdeteksi sebagai hasil scan gambar. Konversikan halaman ke JPG/PNG jika teks tidak terbaca.")
            elif uploaded_file.type.startswith("image/"):
                image_data = Image.open(io.BytesIO(file_bytes))
                st.image(image_data, caption="Pratinjau Dokumen Rekam Medis", width=400)
            else:
                rm_content = file_bytes.decode("utf-8", errors="ignore")
                
    elif input_method == "Link Google Drive (Publik)":
        gdrive_url = st.text_input(
            "Tempel Link Google Drive File Rekam Medis (PDF/Gambar):",
            placeholder="https://drive.google.com/file/d/1A2B3C4D5E.../view?usp=sharing"
        )
        if gdrive_url:
            if st.button("Ambil File dari Google Drive"):
                try:
                    with st.spinner("Mengunduh file dari Google Drive..."):
                        file_bytes = download_from_gdrive(gdrive_url)
                        # Cek apakah PDF atau Gambar
                        if file_bytes[:4] == b"%PDF":
                            rm_content = extract_text_from_pdf(file_bytes)
                            st.success("File PDF dari Google Drive berhasil dibaca!")
                        else:
                            image_data = Image.open(io.BytesIO(file_bytes))
                            st.image(image_data, caption="Dokumen dari Google Drive", width=400)
                except Exception as e:
                    st.error(f"Terjadi kesalahan: {e}")

    else:
        rm_content = st.text_area(
            "Tempel teks Resume Medis / SOAP / Laporan Operasi di sini:",
            height=200,
            placeholder="Contoh: Pasien laki-laki 58 tahun masuk dengan sesak napas memberat sejak 2 hari SMRS. Riwayat DM tipe 2 dan Hipertensi. TD 160/95, GDS 310 mg/dL, Ro Thorax: Efusi pleura kanan masif. Dilakukan pungsi pleura..."
        )

    if rm_content:
        with st.expander("Lihat Teks Rekam Medis yang Terbaca"):
            st.text(rm_content[:3000] + ("..." if len(rm_content) > 3000 else ""))

    if st.button("🚀 Analisis & Generate Kode ICD-10 / ICD-9-CM", type="primary"):
        if not rm_content and not image_data:
            st.error("Harap unggah file, masukkan link Google Drive, atau isi teks rekam medis terlebih dahulu.")
        else:
            with st.spinner("AI sedang menganalisis dokumen berdasarkan kaidah PMK 26/2021..."):
                prompt = """
                Analisis dokumen rekam medis berikut dan berikan hasil koding lengkap:
                1. **Ringkasan Klinis Singkat** (Keluhan, Pemeriksaan Fisik, Penunjang penting, Terapi).
                2. **Diagnosis Utama (ICD-10)** beserta kode, deskripsi resmi, dan alasan pemilihan sesuai kaidah morbiditas PMK 26/2021.
                3. **Diagnosis Sekunder / Komorbid / Komplikasi (ICD-10)** (jika ada, sertakan syarat klinis/sumber daya yang mendukung agar tidak di-pending BPJS).
                4. **Tindakan / Prosedur (ICD-9-CM)** beserta kode dan deskripsi resmi.
                5. **Potensi Risiko Pending BPJS & Saran Kelengkapan Berkas** (peringatan dini jika ada bukti klinis yang kurang sesuai PNPK terbaru).
                """
                contents = [prompt]
                if rm_content:
                    contents.append(f"Isi Rekam Medis:\n{rm_content}")
                if image_data:
                    contents.append(image_data)
                
                response = client.models.generate_content(
                    model=model_choice,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.1
                    )
                )
                st.markdown("### 📋 Hasil Koding & Audit Klinis")
                st.markdown(response.text)

# ------------------------------------------
# TAB 2: PENCARIAN CEPAT ICD-10 & ICD-9-CM
# ------------------------------------------
with tab2:
    st.subheader("🔍 Pencarian Otomatis Kode ICD-10 & ICD-9-CM")
    st.markdown("Ketik nama penyakit, gejala, istilah medis bahasa Indonesia/Inggris, atau nama tindakan medis.")
    
    search_query = st.text_input(
        "Ketik Penyakit atau Tindakan (contoh: 'Demam berdarah', 'Usus buntu laparoskopi', 'Sepsis syok', 'Hemodialisa'):",
        key="icd_search_box"
    )
    
    if search_query:
        with st.spinner(f"Mencari kode untuk '{search_query}'..."):
            search_prompt = f"""
            Pengguna mencari istilah medis: "{search_query}".
            Berikan daftar kode **ICD-10 (Diagnosis)** dan/atau **ICD-9-CM (Tindakan)** yang paling relevan dalam bentuk **Tabel Markdown** dengan kolom:
            | Jenis | Kode | Deskripsi Resmi (Inggris & Indonesia) | Catatan Kaidah Koding BPJS (PMK 26/2021 & PNPK) |
            
            Sertakan hingga 5-8 variasi kode paling spesifik (termasuk kode asterisk/dagger atau kode kombinasi jika berlaku dalam aturan INA-CBG).
            """
            res = client.models.generate_content(
                model=model_choice,
                contents=search_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.1
                )
            )
            st.markdown(res.text)

# ------------------------------------------
# TAB 3: JAWAB PENDINGAN KLAIM BPJS
# ------------------------------------------
with tab3:
    st.subheader("⚖️ Penyelesaian Pendingan Klaim BPJS (PMK 26/2021 & PNPK)")
    
    pending_mode = st.radio(
        "Pilih Mode Penyelesaian Pending:",
        ["Satuan (Input Manual Kasus)", "Massal via Excel / Link Google Sheets"],
        horizontal=True
    )
    
    if pending_mode == "Satuan (Input Manual Kasus)":
        col1, col2 = st.columns(2)
        with col1:
            diag_klaim = st.text_input("Diagnosis & Kode ICD-10 / ICD-9 yang Diajukan:", placeholder="Contoh: J18.9 Pneumonia + E87.6 Hipokalemia")
            alasan_pending = st.text_area("Catatan / Alasan Pending dari Verifikator BPJS:", height=120, placeholder="Contoh: Mohon konfirmasi penegakan diagnosis Pneumonia sesuai PNPK (bukti infiltrat radiologi & leukositosis) serta koreksi kalium.")
        with col2:
            bukti_rm = st.text_area("Data Klinis / Bukti di Rekam Medis RS:", height=195, placeholder="Contoh: Ro Thorax tgl 12/10/2026: Infiltrat parakardial kanan. Leukosit 16.400/uL, Suhu 38.6 C, RR 26x/m. Kalium awal 2.9 mmol/L, diberikan KCl 25 mEq dalam NaCl 0.9% 500cc.")
            
        if st.button("✍️ Susun Jawaban Konfirmasi Pending", type="primary"):
            if not alasan_pending or not bukti_rm:
                st.error("Harap isi Alasan Pending BPJS dan Bukti Rekam Medis RS.")
            else:
                with st.spinner("Menyusun argumentasi medis berdasarkan PMK 26/2021 & PNPK..."):
                    prompt_single = f"""
                    Susun surat/catatan jawaban konfirmasi klaim pending BPJS Kesehatan untuk kasus berikut:
                    - **Kode/Diagnosis Diajukan:** {diag_klaim}
                    - **Alasan Pending Verifikator BPJS:** {alasan_pending}
                    - **Bukti Klinis di Rekam Medis RS:** {bukti_rm}
                    
                    Format output:
                    1. **Analisis Kaidah Koding & Regulasi** (rujuk PMK 26/2021, BA Kesepakatan Dispute Klaim, atau kriteria diagnostik PNPK Kemenkes terbaru yang relevan).
                    2. **Draf Jawaban Resmi untuk Verifikator BPJS** (bahasa medis yang sopan, tegas, terstruktur poin per poin, dan siap copy-paste ke aplikasi VClaim/Vedika).
                    3. **Checklist Lampiran Berkas** yang wajib dilampirkan agar klaim langsung layak bayar.
                    """
                    res_single = client.models.generate_content(
                        model=model_choice,
                        contents=prompt_single,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.15
                        )
                    )
                    st.markdown(res_single.text)

    else:
        st.markdown(
            "Unggah file Excel (`.xlsx`) daftar pendingan klaim atau masukkan **Link Google Sheets** publik. "
            "Pastikan file memiliki kolom seperti: `No SEP`, `Diagnosis/Kode`, `Alasan Pending`, dan `Data Klinis/Resume`."
        )
        
        excel_source = st.radio("Sumber File Excel:", ["Upload File Excel (.xlsx)", "Link Google Drive / Google Sheets"], horizontal=True)
        df_pending = None
        
        if excel_source == "Upload File Excel (.xlsx)":
            up_excel = st.file_uploader("Upload Excel Daftar Pending BPJS", type=["xlsx", "xls"])
            if up_excel:
                df_pending = pd.read_excel(up_excel)
        else:
            gsheet_url = st.text_input("Tempel Link Google Sheets / Excel di Google Drive:", placeholder="https://docs.google.com/spreadsheets/d/...")
            if gsheet_url and st.button("Muat Data dari Google Sheets"):
                try:
                    excel_bytes = download_from_gdrive(gsheet_url, is_excel=True)
                    df_pending = pd.read_excel(io.BytesIO(excel_bytes))
                    st.success("Berhasil memuat data dari Google Sheets!")
                except Exception as e:
                    st.error(f"Gagal memuat file: {e}")
                    
        if df_pending is not None:
            st.write("**Pratinjau Data Pendingan:**")
            st.dataframe(df_pending.head(10), use_container_width=True)
            
            # Pilih kolom agar fleksibel dengan format Excel RS manapun
            cols = df_pending.columns.tolist()
            c1, c2, c3 = st.columns(3)
            with c1:
                col_diag = st.selectbox("Pilih Kolom Diagnosis/Kode:", cols, index=0)
            with c2:
                col_pending = st.selectbox("Pilih Kolom Alasan Pending:", cols, index=min(1, len(cols)-1))
            with c3:
                col_klinis = st.selectbox("Pilih Kolom Data Klinis/RM:", cols, index=min(2, len(cols)-1))
                
            max_rows = st.slider("Jumlah baris yang diproses sekaligus:", 1, min(30, len(df_pending)), min(5, len(df_pending)))
            
            if st.button("⚡ Proses Semua Jawaban Pending Otomatis", type="primary"):
                jawaban_list = []
                dasar_hukum_list = []
                progress_bar = st.progress(0)
                
                for idx in range(max_rows):
                    row = df_pending.iloc[idx]
                    prompt_row = f"""
                    Berikan jawaban konfirmasi pending BPJS yang ringkas, padat, medis, dan sesuai PMK 26/2021 serta PNPK Kemenkes terbaru untuk baris data berikut:
                    - Diagnosis/Kode: {row[col_diag]}
                    - Alasan Pending BPJS: {row[col_pending]}
                    - Data Klinis RM: {row[col_klinis]}
                    
                    Pisahkan output dengan tanda '|||' menjadi 2 bagian saja tanpa teks pembuka:
                    Bagian 1: Jawaban konfirmasi siap salin ke BPJS.
                    Bagian 2: Dasar Regulasi (PMK 26/2021 / PNPK / BA Dispute terkait).
                    """
                    resp = client.models.generate_content(
                        model=model_choice,
                        contents=prompt_row,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.1
                        )
                    )
                    parts = resp.text.split("|||")
                    jawaban_list.append(parts[0].strip())
                    dasar_hukum_list.append(parts[1].strip() if len(parts) > 1 else "PMK No. 26 Tahun 2021 & PNPK Kemenkes")
                    progress_bar.progress((idx + 1) / max_rows)
                
                df_result = df_pending.iloc[:max_rows].copy()
                df_result["Jawaban_Konfirmasi_BPJS"] = jawaban_list
                df_result["Dasar_Regulasi_PMK_PNPK"] = dasar_hukum_list
                
                st.success("Selesai memproses jawaban pending!")
                st.dataframe(df_result, use_container_width=True)
                
                # Download hasil ke Excel baru
                output_buffer = io.BytesIO()
                with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
                    df_result.to_excel(writer, index=False, sheet_name="Jawaban_Pending_BPJS")
                
                st.download_button(
                    label="📥 Download Hasil Jawaban Pending (.xlsx)",
                    data=output_buffer.getvalue(),
                    file_name="Hasil_Jawaban_Pending_BPJS.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
