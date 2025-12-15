import os
import re
import json
import time
import streamlit as st
from typing import List, Optional
from datetime import datetime
from io import BytesIO
import pandas as pd
from dotenv import load_dotenv
from fpdf import FPDF
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

load_dotenv()

def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """Ambil secret dari st.secrets (hosting) atau dari environment variable."""

    try:
        if hasattr(st, 'secrets') and key in st.secrets:
            return st.secrets[key]
    except Exception:

        pass
    return os.getenv(key, default)

st.set_page_config(layout="wide")

ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "admin123")
USER_PASSWORD = get_secret("USER_PASSWORD", "user123")
DATA_FILENAME = get_secret("DATA_FILENAME", "mahasiswa_data.json")

EMAIL_PENGIRIM = get_secret("EMAIL_PENGIRIM")
EMAIL_APP_PASSWORD = get_secret("EMAIL_APP_PASSWORD")

USERS = {
    "admin": {"password": ADMIN_PASSWORD, "role": "admin"},
    "user": {"password": USER_PASSWORD, "role": "user"}
}

HEADERS = ["Nama", "NIM", "Jurusan", "Hobi", "Cita-cita", "Tanggal Dibuat"]


if 'role' not in st.session_state:
    st.session_state['role'] = "guest"
if 'page' not in st.session_state:
    st.session_state['page'] = "Dashboard"

def apply_transparent_background(bg_image_url: str = None):
    bg_css = ""

    if bg_image_url:
        bg_css = f"""
        .stApp {{
            background-image: url("{bg_image_url}");
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        """

    st.markdown(
        f"""
        <style>
        {bg_css}

        /* Konten utama (KANAN) dibuat transparan */
        section[data-testid="stMain"] {{
            background-color: transparent;
        }}

        /* Container dalam main (aman & ringan) */
        div[data-testid="stVerticalBlock"] {{
            background-color: rgba(255, 255, 255, 0.85);
            padding: 1rem;
            border-radius: 10px;
        }}

        /* Sidebar BIARKAN DEFAULT (TIDAK DISENTUH) */
        /* Tidak ada CSS untuk stSidebar */

        /* Text default (tidak dipaksa putih) */
        </style>
        """,
        unsafe_allow_html=True
    )

class MahasiswaException(Exception): pass
class ValidationException(MahasiswaException): pass
class FileOperationException(MahasiswaException): pass
class DataNotFoundException(MahasiswaException): pass

class Validator:
    NAMA_PATTERN = r'^[A-Za-z\s]{3,50}$'
    NIM_PATTERN = r'^\d{12}$'
    JURUSAN_PATTERN = r'^[A-Za-z\s]{3,50}$'
    HOBI_PATTERN = r'^[A-Za-z0-9\s]{3,30}$'
    CITA_CITA_PATTERN = r'^[A-Za-z\s]{3,50}$'

    @staticmethod
    def validate_nim(nim: str) -> bool:
        return bool(re.match(Validator.NIM_PATTERN, nim.strip()))

    @staticmethod
    def validate_all(nama: str, nim: str, jurusan: str, hobi: str, cita: str) -> tuple:
        errors = []
        if not re.match(Validator.NAMA_PATTERN, (nama or "").strip()):
            errors.append("Nama harus 3-50 huruf/spasi.")
        if not Validator.validate_nim(nim or ""):
            errors.append("NIM harus tepat 12 digit angka.")
        if not re.match(Validator.JURUSAN_PATTERN, (jurusan or "").strip()):
            errors.append("Jurusan harus 3-50 huruf/spasi.")
        if not re.match(Validator.HOBI_PATTERN, (hobi or "").strip()):
            errors.append("Hobi harus 3-30 huruf/angka/spasi.")
        if not re.match(Validator.CITA_CITA_PATTERN, (cita or "").strip()):
            errors.append("Cita-cita harus 3-50 huruf/spasi.")
        if errors:
            return False, "\n".join(errors)
        return True, ""

class Mahasiswa:
    def __init__(self, nama: str, nim: str, jurusan: str, hobi: str, cita_cita: str, created_at: Optional[str] = None):
        self._nama = (nama or "").strip()
        self._nim = (nim or "").strip()
        self._jurusan = (jurusan or "").strip()
        self._hobi = (hobi or "").strip()
        self._cita_cita = (cita_cita or "").strip()
        self._created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @property
    def nim(self) -> str: return self._nim
    @property
    def nama(self) -> str: return self._nama
    @property
    def jurusan(self) -> str: return self._jurusan
    @property
    def hobi(self) -> str: return self._hobi
    @property
    def cita_cita(self) -> str: return self._cita_cita
    @property
    def tanggal(self) -> str: return self._created_at

    def to_dict(self) -> dict:
        return {
            'nama': self._nama,
            'nim': self._nim,
            'jurusan': self._jurusan,
            'hobi': self._hobi,
            'cita_cita': self._cita_cita,
            'created_at': self._created_at
        }

    @staticmethod
    def from_dict(data: dict) -> 'Mahasiswa':
        return Mahasiswa(data.get('nama',''), data.get('nim',''), data.get('jurusan',''), data.get('hobi',''), data.get('cita_cita',''), data.get('created_at'))

class MahasiswaDataManager:
    def __init__(self, filename: str = DATA_FILENAME):
        self._filename = filename
        self._mahasiswa_list: List[Mahasiswa] = []
        self.load_from_file()

    def load_from_file(self) -> None:
        try:
            if os.path.exists(self._filename):
                with open(self._filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._mahasiswa_list = [Mahasiswa.from_dict(item) for item in data]
            else:
                self._mahasiswa_list = []
        except Exception as e:
            raise FileOperationException(f"Error membaca file: {e}")

    def save_to_file(self) -> None:
        try:
            data = [mhs.to_dict() for mhs in self._mahasiswa_list]
            with open(self._filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            raise FileOperationException(f"Error menulis file: {e}")

    def get_all_mahasiswa(self) -> List[Mahasiswa]:
        return self._mahasiswa_list.copy()

    def get_count(self) -> int:
        return len(self._mahasiswa_list)

    def tambah_mahasiswa(self, nama: str, nim: str, jurusan: str, hobi: str, cita_cita: str) -> None:
        is_valid, err = Validator.validate_all(nama, nim, jurusan, hobi, cita_cita)
        if not is_valid:
            raise ValidationException(err)
        if self.cari_by_nim(nim):
            raise ValidationException(f"NIM {nim} sudah terdaftar")
        mahasiswa = Mahasiswa(nama, nim, jurusan, hobi, cita_cita)
        self._mahasiswa_list.append(mahasiswa)
        self.save_to_file()

    # Ganti fungsi cari_by_nim yang lama dengan ini:
    def cari_by_nim(self, nim: str) -> Optional[Mahasiswa]:
        """
        Mencari Mahasiswa berdasarkan NIM menggunakan Binary Search.
        List diurutkan sementara sebelum pencarian.
        """
        if not Validator.validate_nim(nim):
            return None

        # Binary Search membutuhkan list yang terurut.
        sorted_list = sorted(self._mahasiswa_list, key=lambda x: x.nim)
        
        low = 0
        high = len(sorted_list) - 1

        while low <= high:
            mid = (low + high) // 2
            mhs = sorted_list[mid]
            
            if mhs.nim == nim:
                return mhs
            elif mhs.nim < nim:
                low = mid + 1
            else:
                high = mid - 1
        
        return None

    def edit_mahasiswa(self, nim_lama: str, nama: str, nim_baru: str, jurusan: str, hobi: str, cita: str) -> None:
        target = self.cari_by_nim(nim_lama)
        if not target:
            raise DataNotFoundException("Data tidak ditemukan untuk di-edit")
        is_valid, err = Validator.validate_all(nama, nim_baru, jurusan, hobi, cita)
        if not is_valid:
            raise ValidationException(err)
  
        if nim_baru != nim_lama and self.cari_by_nim(nim_baru):
            raise ValidationException("NIM baru sudah terpakai oleh mahasiswa lain")
  
        target._nama = nama.strip()
        target._nim = nim_baru.strip()
        target._jurusan = jurusan.strip()
        target._hobi = hobi.strip()
        target._cita_cita = cita.strip()
        self.save_to_file()

    def hapus_mahasiswa(self, nim: str) -> None:
        target = self.cari_by_nim(nim)
        if not target:
            raise DataNotFoundException("Data tidak ditemukan untuk dihapus")
        self._mahasiswa_list = [m for m in self._mahasiswa_list if m.nim != nim]
        self.save_to_file()

    def merge_sort_by_jurusan(self) -> float:
        start = time.time()
        self._mahasiswa_list.sort(key=lambda x: x.jurusan.lower())
        self.save_to_file()
        return round((time.time() - start) * 1000, 2)
    
    # Tambahkan ini di dalam class MahasiswaDataManager:

    def cari_by_nim_binary(self, nim: str) -> Optional[Mahasiswa]:
        """
        Mencari Mahasiswa berdasarkan NIM menggunakan Binary Search.
        Membutuhkan list yang SANGAT terurut berdasarkan NIM.
        """
        if not Validator.validate_nim(nim):
            return None

        # Untuk memastikan Binary Search berjalan sempurna,
        # kita harus mengurutkan data terlebih dahulu berdasarkan NIM.
        # Catatan: NIM sudah unik, jadi urutan ini konsisten.
        sorted_list = sorted(self._mahasiswa_list, key=lambda x: x.nim)
        
        low = 0
        high = len(sorted_list) - 1

        while low <= high:
            mid = (low + high) // 2
            mhs = sorted_list[mid]
            
            if mhs.nim == nim:
                return mhs
            elif mhs.nim < nim:
                low = mid + 1
            else:
                high = mid - 1
        
        return None
        
    def cari_by_nama_linear(self, query: str) -> List[Mahasiswa]:
        """
        Mencari Mahasiswa berdasarkan nama menggunakan Linear Search.
        """
        if not query:
            return []
        query = query.strip().lower()
        
        hasil = []
        for mhs in self._mahasiswa_list:
            # Cari nama yang mengandung query
            if query in mhs.nama.lower():
                hasil.append(mhs)
        return hasil

    def cari_by_hobi_sequential(self, query: str) -> List[Mahasiswa]:
        """
        Mencari Mahasiswa berdasarkan hobi menggunakan Sequential Search.
        (Secara fungsional sama dengan Linear Search, tapi diterapkan pada kolom Hobi).
        """
        if not query:
            return []
        query = query.strip().lower()
        
        hasil = []
        for mhs in self._mahasiswa_list:
            # Cari hobi yang mengandung query
            if query in mhs.hobi.lower():
                hasil.append(mhs)
        return hasil
    
    # Tambahkan ini di dalam class MahasiswaDataManager:

    def bubble_sort_by_nama(self) -> float:
        """Mengurutkan data berdasarkan Nama menggunakan Bubble Sort."""
        start = time.time()
        n = len(self._mahasiswa_list)
        
        for i in range(n - 1):
            swapped = False
            for j in range(0, n - i - 1):
                # Membandingkan dan menukar nama (case-insensitive)
                if self._mahasiswa_list[j].nama.lower() > self._mahasiswa_list[j + 1].nama.lower():
                    self._mahasiswa_list[j], self._mahasiswa_list[j + 1] = self._mahasiswa_list[j + 1], self._mahasiswa_list[j]
                    swapped = True
            if not swapped:
                break
                
        self.save_to_file()
        return round((time.time() - start) * 1000, 2)

    def selection_sort_by_nim(self) -> float:
        """Mengurutkan data berdasarkan NIM menggunakan Selection Sort."""
        start = time.time()
        n = len(self._mahasiswa_list)
        
        for i in range(n):
            min_idx = i
            # Mencari elemen terkecil di sisa list
            for j in range(i + 1, n):
                # Membandingkan NIM (string angka)
                if self._mahasiswa_list[j].nim < self._mahasiswa_list[min_idx].nim:
                    min_idx = j
                    
            # Menukar elemen terkecil yang ditemukan dengan elemen pada posisi i
            self._mahasiswa_list[i], self._mahasiswa_list[min_idx] = self._mahasiswa_list[min_idx], self._mahasiswa_list[i]
            
        self.save_to_file()
        return round((time.time() - start) * 1000, 2)
    
    def user_input_page():
        st.title("📝 Input Data Mahasiswa (User)")
        with st.form("form_user_input"):
            nama = st.text_input("Nama Lengkap")
            nim = st.text_input("NIM (12 digit)")
            jurusan = st.text_input("Jurusan")
            hobi = st.text_input("Hobi")
            cita = st.text_input("Cita-cita")

            if st.form_submit_button("Kirim Data"):
                try:
                    data_manager.tambah_mahasiswa(
                        nama, nim, jurusan, hobi, cita
                    )
                    st.success("✅ Data berhasil dikirim.")
                except Exception as e:
                    st.error(f"❌ Gagal: {e}")


data_manager = MahasiswaDataManager()

def data_to_df(mahasiswas: List[Mahasiswa]) -> pd.DataFrame:
    data = [[m.nama, m.nim, m.jurusan, m.hobi, m.cita_cita, m.tanggal] for m in mahasiswas]
    return pd.DataFrame(data, columns=HEADERS)

class SimplePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Laporan Data Mahasiswa', ln=1, align='C')

def _create_pdf_bytes(df: pd.DataFrame) -> BytesIO:
    pdf = SimplePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Arial', size=10)


    col_names = ['Nama', 'NIM', 'Jurusan', 'Hobi', 'Cita-cita', 'Dibuat']
    widths = [40, 30, 35, 30, 35, 30]
    for i, h in enumerate(col_names):
        pdf.cell(widths[i], 8, h, border=1)
    pdf.ln()

    for _, row in df.iterrows():
        pdf.cell(widths[0], 6, str(row['Nama'])[:30], border=1)
        pdf.cell(widths[1], 6, str(row['NIM']), border=1)
        pdf.cell(widths[2], 6, str(row['Jurusan'])[:20], border=1)
        pdf.cell(widths[3], 6, str(row['Hobi'])[:15], border=1)
        pdf.cell(widths[4], 6, str(row['Cita-cita'])[:20], border=1)
        pdf.cell(widths[5], 6, str(row['Tanggal Dibuat']).split(' ')[0], border=1)
        pdf.ln()

    buf = BytesIO()
    buf.write(pdf.output(dest='S').encode('latin-1'))
    buf.seek(0)
    return buf


def gr_kirim_email_attachment(email_tujuan: str, role: str, format_file: str, sender_email: str, sender_app_password: str) -> str:
    
    if not email_tujuan or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email_tujuan):
        return "❌ Format email tujuan tidak valid."
    
    if not sender_email or not sender_app_password:
        return "❌ Email Pengirim atau App Password belum diisi."
        
    df = data_to_df(data_manager.get_all_mahasiswa())
    if df.empty:
        return "ℹ Tidak ada data mahasiswa untuk dikirim."

    msg = MIMEMultipart('mixed')
    msg['Subject'] = f"Data Mahasiswa ({format_file}) - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = sender_email # Menggunakan email yang diinput/tersimpan
    msg['To'] = email_tujuan

    body = "Terlampir adalah data mahasiswa dalam format " + format_file + "."
    msg.attach(MIMEText(body, 'plain'))

    filename = f"Data_Mahasiswa_{datetime.now().strftime('%Y%m%d')}"

    try:
        if format_file == "CSV":
            payload = df.to_csv(index=False).encode('utf-8')
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(payload)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}.csv"')
            msg.attach(part)

        elif format_file == "Excel (.xlsx)":
            buf = BytesIO()
            df.to_excel(buf, index=False, engine='openpyxl')
            buf.seek(0)
            part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            part.set_payload(buf.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}.xlsx"')
            msg.attach(part)

        elif format_file == "PDF":
            buf = _create_pdf_bytes(df)
            part = MIMEBase('application', 'pdf')
            part.set_payload(buf.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}.pdf"')
            msg.attach(part)

  
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        # Login menggunakan kredensial yang diinput/tersimpan
        server.login(sender_email, sender_app_password)
        server.send_message(msg)
        server.quit()
        return f"✅ Data ({format_file}) berhasil dikirim dari {sender_email} ke {email_tujuan}."
    except Exception as e:
        if "Authentication failed" in str(e):
             return "❌ Gagal mengirim email: Autentikasi gagal. Pastikan App Password Anda benar dan email Anda mengizinkan akses aplikasi pihak ketiga."
        return f"❌ Gagal mengirim email: {e}"

def login_page():
    apply_transparent_background(
        "https://s3.bukalapak.com/bukalapak-kontenz-production/content_attachments/89753/original/biaya_kuliah_unpam_2.jpg"
    )
    st.title("🔐 Login Portal Mahasiswa")
    st.markdown("---")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.header("Masuk")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            username = (username or "").strip()
            password = (password or "").strip()
            if username in USERS and USERS[username]["password"] == password:
                st.session_state['role'] = USERS[username]["role"]
                st.session_state['page'] = "Dashboard"
            else:
                st.error("Username atau password salah. Coba admin/admin123 atau user/user123")
    with col2:
        st.info(f"**Role Aktif: {st.session_state['role'].upper()}**\n\nAkses Admin diperlukan untuk fitur CRUD, Sort, dan Email.")

def dashboard_page():
    apply_transparent_background(
        "https://an-nur.ac.id/wp-content/uploads/2025/09/kampus2.B0WqicWG-1.jpg"
    )
    st.header(f"👋 Selamat Datang, {st.session_state['role'].title()}!")
    st.markdown("## 📚 Data Mahasiswa")
    col_filter, col_total = st.columns([3,1])
    with col_total:
        count = data_manager.get_count()
        st.metric("Total Data", value=count)
    df_main = data_to_df(data_manager.get_all_mahasiswa())
    st.dataframe(df_main, use_container_width=True, height=500)

def crud_page():
    apply_transparent_background(
        "https://an-nur.ac.id/wp-content/uploads/2025/09/kampus2.B0WqicWG-1.jpg"
    )
    st.title("📥 Manajemen Data Mahasiswa (Admin)")
    col_add, col_edit_del = st.columns(2)
    with col_add:
        st.subheader("➕ Tambah Data Baru")
        with st.form("form_tambah"):
            f_nama = st.text_input("Nama")
            f_nim = st.text_input("NIM (12 digit)")
            f_jurusan = st.text_input("Jurusan")
            f_hobi = st.text_input("Hobi")
            f_cita = st.text_input("Cita-cita")
            if st.form_submit_button("Tambah Mahasiswa"):
                try:
                    data_manager.tambah_mahasiswa(f_nama, f_nim, f_jurusan, f_hobi, f_cita)
                    st.success(f"✅ Mahasiswa {f_nama} berhasil ditambahkan.")
                except Exception as e:
                    st.error(f"❌ Gagal: {e}")
    with col_edit_del:
        st.subheader("✏️ Edit / 🗑️ Hapus Data")
        nim_lama = st.text_input("NIM Lama (untuk Edit/Hapus)", key="nim_lama_crud")
        st.markdown("---")
        st.info("Masukkan Data Baru untuk Edit:")
        e_nama = st.text_input("Nama Baru")
        e_nim = st.text_input("NIM Baru (12 digit)")
        e_jurusan = st.text_input("Jurusan Baru")
        e_hobi = st.text_input("Hobi Baru")
        e_cita = st.text_input("Cita-cita Baru")
        col_btn_edit, col_btn_del = st.columns(2)
        with col_btn_edit:
            if st.button("Edit Data"):
                try:
                    data_manager.edit_mahasiswa(nim_lama, e_nama, e_nim, e_jurusan, e_hobi, e_cita)
                    st.success("✅ Data berhasil diperbarui.")
                except Exception as e:
                    st.error(f"❌ Gagal Edit: {e}")
        with col_btn_del:
            if st.button("Hapus Data"):
                try:
                    data_manager.hapus_mahasiswa(nim_lama)
                    st.warning("🗑️ Data berhasil dihapus.")
                except Exception as e:
                    st.error(f"❌ Gagal Hapus: {e}")
    st.markdown("### Tabel Data")
    st.dataframe(data_to_df(data_manager.get_all_mahasiswa()), use_container_width=True)


def search_sort_page():
    apply_transparent_background(
        "https://an-nur.ac.id/wp-content/uploads/2025/09/kampus2.B0WqicWG-1.jpg"
    )
    st.title("🔎 Pencarian & 📊 Pengurutan")
    col_search, col_sort = st.columns(2)
    
    # Inisialisasi hasil pencarian kosong
    hasil_pencarian: List[Mahasiswa] = []
    waktu_eksekusi = 0.0
    
    with col_search:
        st.subheader("Pencarian Data")
        metode_cari = st.radio("Metode Pencarian", options=["Linear (Nama)", "Binary (NIM)", "Sequential (Hobi)"], horizontal=True)
        q_cari = st.text_input("Kata kunci / NIM")
        btn_cari = st.button("Cari Data")
        
        if btn_cari and q_cari:
            start_time = time.time()
            try:
                if metode_cari == "Binary (NIM)":
                    if not Validator.validate_nim(q_cari):
                         st.error("❌ NIM harus tepat 12 digit angka untuk Binary Search.")
                    else:
                        hasil = data_manager.cari_by_nim_binary(q_cari)
                        if hasil:
                            hasil_pencarian = [hasil]
                        waktu_eksekusi = (time.time() - start_time) * 1000
                
                elif metode_cari == "Linear (Nama)":
                    hasil_pencarian = data_manager.cari_by_nama_linear(q_cari)
                    waktu_eksekusi = (time.time() - start_time) * 1000
                    
                elif metode_cari == "Sequential (Hobi)":
                    hasil_pencarian = data_manager.cari_by_hobi_sequential(q_cari)
                    waktu_eksekusi = (time.time() - start_time) * 1000
                
                # Menampilkan status pencarian
                if 'hasil_pencarian' in locals() and hasil_pencarian:
                    st.success(f"Ditemukan **{len(hasil_pencarian)}** data ({metode_cari}) dalam {round(waktu_eksekusi, 2)} ms.")
                elif 'hasil' in locals() and hasil is None: # Kasus Binary Search tidak ketemu
                     st.info(f"Tidak ditemukan data untuk NIM tersebut ({metode_cari}) dalam {round(waktu_eksekusi, 2)} ms.")
                elif 'hasil_pencarian' in locals() and not hasil_pencarian:
                    st.info(f"Tidak ditemukan data yang cocok ({metode_cari}) dalam {round(waktu_eksekusi, 2)} ms.")
            
            except Exception as e:
                st.error(f"❌ Terjadi kesalahan saat pencarian: {e}")
        elif btn_cari and not q_cari:
             st.warning("Masukkan kata kunci atau NIM untuk memulai pencarian.")

    with col_sort:
        st.subheader("Pengurutan Data")
        metode_sort = st.radio("Metode Pengurutan (Admin)", options=["Bubble Sort (Nama)", "Selection Sort (NIM)", "Merge Sort (Jurusan)"], horizontal=True)
        
        if st.button("Urutkan Data"):
            elapsed = 0.0 # Waktu eksekusi dalam ms
            
            try:
                if metode_sort == "Merge Sort (Jurusan)":
                    elapsed = data_manager.merge_sort_by_jurusan()
                elif metode_sort == "Bubble Sort (Nama)":
                    elapsed = data_manager.bubble_sort_by_nama() # Panggilan fungsi baru
                elif metode_sort == "Selection Sort (NIM)":
                    elapsed = data_manager.selection_sort_by_nim() # Panggilan fungsi baru
                    
                st.success(f"✅ **{metode_sort}** selesai dalam **{elapsed} ms**.")
                
            except Exception as e:
                st.error(f"❌ Gagal melakukan pengurutan: {e}")
            
    # ... (setelah bagian Pengurutan Data selesai) ...
    
    st.markdown("### Data Hasil")
    
    # 💡 Cek apakah ada hasil pencarian yang ditemukan
    if btn_cari and q_cari and hasil_pencarian:
        st.info("Menampilkan hasil pencarian:")
        st.dataframe(data_to_df(hasil_pencarian), use_container_width=True)
    elif btn_cari and q_cari:
        # Tampilkan keseluruhan jika tidak ada hasil, atau tampilkan info "tidak ditemukan"
        st.info("Tidak ditemukan data yang cocok.")
    else:
        # Default: Tampilkan semua data (yang mungkin sudah diurutkan)
        st.info("Menampilkan seluruh data mahasiswa:")
        st.dataframe(data_to_df(data_manager.get_all_mahasiswa()), use_container_width=True)


def stat_email_page():
    apply_transparent_background(
        "https://an-nur.ac.id/wp-content/uploads/2025/09/kampus2.B0WqicWG-1.jpg"
    )
    st.title("📈 Statistik & 📧 Kirim Laporan") # Judul umum
    col_stat, col_email = st.columns(2)
    
    with col_stat:
        st.subheader("Statistik Jurusan & Cita-cita")
        df_all = data_to_df(data_manager.get_all_mahasiswa())
        total = len(df_all)
        if total > 0:
            st.markdown("#### Distribusi Jurusan")
            jurusan_counts = df_all['Jurusan'].value_counts().reset_index()
            jurusan_counts.columns = ['Jurusan', 'Jumlah']
            jurusan_counts['Persentase'] = (jurusan_counts['Jumlah'] / total * 100).round(1).astype(str) + '%'
            st.dataframe(jurusan_counts, use_container_width=True)
            st.markdown("#### Cita-cita Terpopuler")
            cita_counts = df_all['Cita-cita'].value_counts().head(5)
            st.bar_chart(cita_counts)
        else:
            st.info("Data kosong. Tidak dapat menampilkan statistik.")
            
    with col_email:
        st.subheader("Kirim Laporan via Email")

        # --- LOGIK INPUT KREDENSIAL BERDASARKAN ROLE ---
        if st.session_state['role'] == 'admin':
            st.info("Anda menggunakan kredensial Admin yang tersimpan.")
            user_email_pengirim = EMAIL_PENGIRIM
            user_app_password = EMAIL_APP_PASSWORD
        else:
            st.warning("Sebagai user, Anda harus memasukkan Email dan App Password Anda (pastikan App Password sudah dibuat untuk aplikasi).")
            user_email_pengirim = None
            user_app_password = None
        # -----------------------------------------------

        with st.form("form_email"):
            email_tujuan = st.text_input("Email Tujuan (Penerima Laporan)")
            format_file = st.radio("Pilih Format Laporan", options=["CSV", "Excel (.xlsx)", "PDF"], horizontal=True)

            # Input Kredensial Pengirim hanya untuk role 'user'
            if st.session_state['role'] != 'admin':
                user_email_pengirim_input = st.text_input("Email Pengirim Anda")
                user_app_password_input = st.text_input("App Password Anda", type="password")
            else:
                user_email_pengirim_input = user_email_pengirim
                user_app_password_input = user_app_password
                
            if st.form_submit_button("Kirim Laporan"):
                if email_tujuan:
                    status_email = gr_kirim_email_attachment(
                        email_tujuan, 
                        st.session_state['role'], 
                        format_file, 
                        user_email_pengirim_input, # Kredensial pengirim yang digunakan
                        user_app_password_input    # App Password pengirim yang digunakan
                    )
                    if "✅" in status_email:
                        st.success(status_email)
                    else:
                        st.error(status_email)
                else:
                    st.error("Masukkan email tujuan.")

if st.session_state['role'] == "guest":
    login_page()
else:
    with st.sidebar:
        st.image("https://www.bing.com/th/id/OIP.NRQxqAviwTtWhhNuNtHF6wHaHa?w=227&h=211&c=8&rs=1&qlt=90&o=6&cb=ucfimg1&dpr=1.5&pid=3.1&rm=2&ucfimg=1")
        st.markdown("### 👤 Informasi Pengguna")
        st.markdown(f"**Role Aktif:** {st.session_state['role'].upper()}")
        st.markdown(f"**Nama User:** {st.session_state.get('login_user', 'N/A')}")
        st.markdown("---")
        menu = {
            "Dashboard": "🏠 Dashboard & Data",
            "CRUD": "🛠️ Data Mahasiswa",
            "Search_Sort": "🔍 Cari & Urutkan",
            "Stat_Email": "📈 Statistik & Email",
            "Logout": "🚪 Logout"
        }
        if st.session_state['role'] == 'admin':
            menu["CRUD"] = "🛠️ Data Mahasiswa (Admin)"
            menu["Stat_Email"] = "📈 Statistik & Email (Admin)"
        if st.session_state['role'] == 'user':
            menu["CRUD"] = "🛠️ Data Mahasiswa"
            menu["Stat_Email"] = "📈 Statistik & Email"
        selected_page = st.radio("Pilih Menu", list(menu.keys()), format_func=lambda x: menu[x])
        st.session_state['page'] = selected_page
        st.markdown("---")
        if st.session_state['page'] == "Logout":
            st.session_state['role'] = "guest"
            st.session_state['page'] = "Dashboard"
            
    if st.session_state['page'] == "Dashboard":
        dashboard_page()
    elif st.session_state['page'] == "CRUD":
        crud_page()
    elif st.session_state['page'] == "Search_Sort":
        search_sort_page()
    elif st.session_state['page'] == "Stat_Email":
        stat_email_page()
    else:
        st.session_state['role'] = "guest"
  
