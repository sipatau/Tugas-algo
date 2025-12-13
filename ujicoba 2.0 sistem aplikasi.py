import os
import re
import json
import time
import pandas as pd
import gradio as gr
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime
from io import BytesIO
from dotenv import load_dotenv
from fpdf import FPDF
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Catatan: Pastikan Anda telah menginstal: 
# pip install pandas gradio fpdf python-dotenv openpyxl

load_dotenv()

# =========================================================================
# === KONSTANTA & KREDENSIAL ===
# =========================================================================

def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """Mengambil secret dari environment variable."""
    return os.getenv(key, default)

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

# Catatan: Anda harus memiliki file logo_kiri.png dan logo_kanan.png
# di direktori yang sama atau menggantinya dengan URL publik.
LOGO_LEFT = "https://alumni.unpam.ac.id/assets/yayasan-d647a8db.png" 
LOGO_RIGHT = "https://1.bp.blogspot.com/-vVS34SwFWFI/WjCSXpKb0BI/AAAAAAAAF6Y/HjlGqQNtBq0HPFQUFzd2CE0DD6a0i30xwCLcBGAs/s1600/Unpam.png" 

# =========================================================================
# === MANAJEMEN DATA & LOGIKA BISNIS ===
# =========================================================================

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
            data = [m.to_dict() for m in self._mahasiswa_list]
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

    def cari_by_nim(self, nim: str) -> Optional[Mahasiswa]:
        for mhs in self._mahasiswa_list:
            if mhs.nim == (nim or ""):
                return mhs
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
        
    def linear_search_by_nama(self, keyword: str) -> List[Mahasiswa]:
        keyword = keyword.lower().strip()
        return [mhs for mhs in self._mahasiswa_list if keyword in mhs.nama.lower()]

    def sequential_search_by_hobi(self, keyword: str) -> List[Mahasiswa]:
        keyword = keyword.lower().strip()
        return [mhs for mhs in self._mahasiswa_list if keyword in mhs.hobi.lower()]

    def binary_search_by_nim(self, nim_target: str) -> List[Mahasiswa]:
        nim_target = nim_target.strip()
        sorted_list = sorted(self._mahasiswa_list, key=lambda x: x.nim)
        
        low, high = 0, len(sorted_list) - 1
        found_mhs = []
        
        while low <= high:
            mid = (low + high) // 2
            mid_nim = sorted_list[mid].nim
            
            if mid_nim == nim_target:
                i = mid
                while i >= 0 and sorted_list[i].nim == nim_target:
                    found_mhs.append(sorted_list[i])
                    i -= 1
                i = mid + 1
                while i < len(sorted_list) and sorted_list[i].nim == nim_target:
                    found_mhs.append(sorted_list[i])
                    i += 1
                return found_mhs
            elif mid_nim < nim_target:
                low = mid + 1
            else:
                high = mid - 1
        return []

# Instance Manager
data_manager = MahasiswaDataManager()

def data_to_df(mahasiswas: List[Mahasiswa]) -> pd.DataFrame:
    data = [[m.nama, m.nim, m.jurusan, m.hobi, m.cita_cita, m.tanggal] for m in mahasiswas]
    return pd.DataFrame(data, columns=HEADERS)

def get_stat_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = data_to_df(data_manager.get_all_mahasiswa())
    
    if df.empty:
        return pd.DataFrame({'Jurusan': [], 'Jumlah': [], 'Persentase': []}), pd.DataFrame({'labels': [], 'values': []})

    jurusan_counts = df['Jurusan'].value_counts().reset_index()
    jurusan_counts.columns = ['Jurusan', 'Jumlah']
    total = jurusan_counts['Jumlah'].sum()
    jurusan_counts['Persentase'] = ((jurusan_counts['Jumlah'] / total) * 100).round(2)
    
    cita_counts = df['Cita-cita'].value_counts().reset_index()
    cita_counts.columns = ['labels', 'values']
    
    return jurusan_counts, cita_counts

# PDF Helper
class SimplePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Laporan Data Mahasiswa', ln=1, align='C')

def _create_pdf_bytes(df: pd.DataFrame) -> BytesIO:
    pdf = SimplePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Arial', size=10)

    def safe_encode(text):
        return text.encode('latin-1', 'ignore').decode('latin-1')

    col_names = ['Nama', 'NIM', 'Jurusan', 'Hobi', 'Cita-cita', 'Dibuat']
    widths = [40, 30, 35, 30, 35, 30]
    for i, h in enumerate(col_names):
        pdf.cell(widths[i], 8, safe_encode(h), border=1)
    pdf.ln()

    for _, row in df.iterrows():
        pdf.cell(widths[0], 6, safe_encode(str(row['Nama'])[:30]), border=1)
        pdf.cell(widths[1], 6, safe_encode(str(row['NIM'])), border=1)
        pdf.cell(widths[2], 6, safe_encode(str(row['Jurusan'])[:20]), border=1)
        pdf.cell(widths[3], 6, safe_encode(str(row['Hobi'])[:15]), border=1)
        pdf.cell(widths[4], 6, safe_encode(str(row['Cita-cita'])[:20]), border=1)
        pdf.cell(widths[5], 6, safe_encode(str(row['Tanggal Dibuat']).split(' ')[0]), border=1)
        pdf.ln()

    buf = BytesIO()
    pdf_output = pdf.output(dest='S').encode('latin-1') 
    buf.write(pdf_output)
    buf.seek(0)
    return buf

# Fungsi Email (Menggunakan kredensial Admin/User)
def gr_kirim_email_attachment(email_tujuan: str, current_state: dict, format_file: str, user_email_pengirim: Optional[str], user_app_password: Optional[str]) -> str:
    
    role = current_state.get('role', 'guest')
    
    if not email_tujuan or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email_tujuan):
        return "❌ Format email tujuan tidak valid."
    
    if role == 'admin' and EMAIL_PENGIRIM and EMAIL_APP_PASSWORD:
        sender_email = EMAIL_PENGIRIM
        sender_app_password = EMAIL_APP_PASSWORD
    elif role == 'user' and user_email_pengirim and user_app_password:
        sender_email = user_email_pengirim
        sender_app_password = user_app_password
    else:
        return "❌ Kredensial pengirim tidak lengkap. Pastikan Anda mengisi semua kolom (jika user) atau .env (jika admin)."
        
    df = data_to_df(data_manager.get_all_mahasiswa())
    if df.empty:
        return "ℹ Tidak ada data mahasiswa untuk dikirim."

    msg = MIMEMultipart('mixed')
    msg['Subject'] = f"Data Mahasiswa ({format_file}) - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = sender_email 
    msg['To'] = email_tujuan

    body = f"Terlampir adalah data mahasiswa dalam format {format_file}. Dikirim oleh {role.title()} ({sender_email})."
    msg.attach(MIMEText(body, 'plain'))

    filename = f"Data_Mahasiswa_{datetime.now().strftime('%Y%m%d')}"

    try:
        # --- LAMPIRAN FILE ---
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
        # --- END LAMPIRAN FILE ---

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_app_password)
        server.send_message(msg)
        server.quit()
        return f"✅ Data ({format_file}) berhasil dikirim dari {sender_email} ke {email_tujuan}."
    except Exception as e:
        if "Authentication failed" in str(e):
             return "❌ Gagal mengirim email: Autentikasi gagal. Pastikan App Password Anda benar."
        return f"❌ Gagal mengirim email: {e}"


# =========================================================================
# === STATE & HANDLER GRADIO ===
# =========================================================================

def get_current_df() -> pd.DataFrame:
    data_manager.load_from_file() 
    return data_to_df(data_manager.get_all_mahasiswa())

def update_user_info(current_state: dict) -> Tuple[str, str]:
    role = current_state.get('role', 'guest')
    user = current_state.get('user', 'N/A')
    if role == 'guest':
        return "", ""
    return f"Role Aktif: {role.upper()}", f"User: {user}"

def login_handler(username: str, password: str, current_state: dict) -> Tuple[dict, gr.Column, gr.Column, str, str]:
    username = (username or "").strip()
    password = (password or "").strip()
    
    if username in USERS and USERS[username]["password"] == password:
        new_state = {
            "is_logged_in": True,
            "role": USERS[username]["role"],
            "user": username
        }
        return new_state, gr.Column(visible=False), gr.Column(visible=True), "", ""
    else:
        return current_state, gr.Column(visible=True), gr.Column(visible=False), "Username atau password salah.", ""

def logout_handler(current_state: dict) -> Tuple[dict, gr.Column, gr.Column]:
    new_state = {"is_logged_in": False, "role": "guest", "user": "N/A"}
    return new_state, gr.Column(visible=True), gr.Column(visible=False)

def update_tab_visibility(current_state: dict) -> Dict[gr.TabItem, Any]:
    role = current_state.get('role', 'guest')
    is_admin = (role == 'admin')
    
    return {
        crud_tab: gr.TabItem(visible=is_admin),
    }

def refresh_dashboard(current_state: dict) -> Tuple[pd.DataFrame, str]:
    df = get_current_df()
    total = len(df)
    return df, f"Total Data: {total}"

def tambah_mahasiswa_handler(nama: str, nim: str, jurusan: str, hobi: str, cita: str, current_state: dict) -> Tuple[pd.DataFrame, str, str, str, str, str, str]:
    current_role = current_state.get('role', 'guest')
    if current_role != 'admin':
        return get_current_df(), "Akses Ditolak. Hanya Admin yang bisa menambah data.", nama, nim, jurusan, hobi, cita

    try:
        data_manager.tambah_mahasiswa(nama, nim, jurusan, hobi, cita)
        return get_current_df(), f"✅ Mahasiswa {nama} berhasil ditambahkan.", "", "", "", "", ""
    except Exception as e:
        return get_current_df(), f"❌ Gagal: {e}", nama, nim, jurusan, hobi, cita

def edit_mahasiswa_handler(nim_lama: str, e_nama: str, e_nim: str, e_jurusan: str, e_hobi: str, e_cita: str, current_state: dict) -> Tuple[pd.DataFrame, str]:
    current_role = current_state.get('role', 'guest')
    if current_role != 'admin':
        return get_current_df(), "Akses Ditolak. Hanya Admin yang bisa mengedit data."
    
    if not nim_lama:
        return get_current_df(), "❌ Error: NIM Lama harus diisi untuk mengedit data."
        
    try:
        data_manager.edit_mahasiswa(nim_lama, e_nama, e_nim, e_jurusan, e_hobi, e_cita)
        return get_current_df(), "✅ Data berhasil diperbarui."
    except Exception as e:
        return get_current_df(), f"❌ Gagal Edit: {e}"

def hapus_mahasiswa_handler(nim_lama: str, current_state: dict) -> Tuple[pd.DataFrame, str]:
    current_role = current_state.get('role', 'guest')
    if current_role != 'admin':
        return get_current_df(), "Akses Ditolak. Hanya Admin yang bisa menghapus data."
        
    if not nim_lama:
        return get_current_df(), "❌ Error: NIM Lama harus diisi untuk menghapus data."

    try:
        data_manager.hapus_mahasiswa(nim_lama)
        return get_current_df(), "🗑️ Data berhasil dihapus."
    except Exception as e:
        return get_current_df(), f"❌ Gagal Hapus: {e}"

def search_handler(metode_cari: str, q_cari: str) -> Tuple[pd.DataFrame, str]:
    if not q_cari:
        return pd.DataFrame(columns=HEADERS), "Masukkan kata kunci pencarian."
        
    found_mhs = []
    
    start_time = time.time()
    if metode_cari == "Linear (Nama)":
        found_mhs = data_manager.linear_search_by_nama(q_cari)
    elif metode_cari == "Sequential (Hobi)":
        found_mhs = data_manager.sequential_search_by_hobi(q_cari)
    elif metode_cari == "Binary (NIM)":
        if not Validator.validate_nim(q_cari):
            return pd.DataFrame(columns=HEADERS), "❌ Error: NIM harus 12 digit angka untuk Binary Search."
        found_mhs = data_manager.binary_search_by_nim(q_cari)

    elapsed = round((time.time() - start_time) * 1000, 2)
    df_result = data_to_df(found_mhs)
    return df_result, f"✅ Ditemukan {len(found_mhs)} data dalam {elapsed} ms."

def sort_handler(metode_sort: str, current_state: dict) -> Tuple[pd.DataFrame, str]:
    current_role = current_state.get('role', 'guest')
    if current_role != 'admin':
        return get_current_df(), "Akses Ditolak. Hanya Admin yang dapat melakukan pengurutan."

    start_time = time.time()
    list_mhs = data_manager.get_all_mahasiswa()
    
    if metode_sort == "Merge Sort (Jurusan)":
        elapsed = data_manager.merge_sort_by_jurusan()
    elif metode_sort == "Bubble Sort (Nama)":
        n = len(list_mhs)
        for i in range(n - 1):
            for j in range(0, n - i - 1):
                if list_mhs[j].nama > list_mhs[j + 1].nama:
                    list_mhs[j], list_mhs[j + 1] = list_mhs[j + 1], list_mhs[j]
        data_manager._mahasiswa_list = list_mhs
        data_manager.save_to_file()
        elapsed = round((time.time() - start_time) * 1000, 2)
    elif metode_sort == "Selection Sort (NIM)":
        n = len(list_mhs)
        for i in range(n):
            min_idx = i
            for j in range(i + 1, n):
                if list_mhs[j].nim < list_mhs[min_idx].nim:
                    min_idx = j
            list_mhs[i], list_mhs[min_idx] = list_mhs[min_idx], list_mhs[i]
        data_manager._mahasiswa_list = list_mhs
        data_manager.save_to_file()
        elapsed = round((time.time() - start_time) * 1000, 2)
    else:
        elapsed = 0.0

    return get_current_df(), f"✅ {metode_sort} selesai dalam {elapsed} ms."

def update_email_inputs(current_state: dict) -> Tuple[gr.Textbox, gr.Textbox, gr.Markdown]:
    current_role = current_state.get('role', 'user')
    if current_role == 'admin':
        info = f"Anda menggunakan kredensial Admin ({EMAIL_PENGIRIM}) yang tersimpan. Input di bawah diabaikan."
        return gr.Textbox(visible=False, value=""), gr.Textbox(visible=False, value=""), gr.Markdown(info, visible=True)
    else:
        info = "Sebagai user, Anda harus memasukkan Email dan App Password Anda (pastikan App Password sudah dibuat)."
        return gr.Textbox(visible=True, value="", placeholder="Email Pengirim Anda"), gr.Textbox(visible=True, value="", placeholder="App Password Anda"), gr.Markdown(info, visible=True)
        

# =========================================================================
# === INTERFACE UTAMA GRADIO ===
# =========================================================================

CUSTOM_CSS = f"""
.gradio-container {{
    min-height: 100vh;
    background-image: linear-gradient(rgba(0, 60, 180, 0.65), rgba(0, 60, 180, 0.65)), url('https://s3.bukalapak.com/bukalapak-kontenz-production/content_attachments/89753/original/biaya_kuliah_unpam_2.jpg');
    background-size: cover;
    background-position: center;
}}
#login_block {{
    max-width: 450px;
    margin: 100px auto;
    padding: 30px;
    background-color: white;
    border-radius: 20px;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.28);
}}
.login-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 25px;
    padding-bottom: 5px;
    border-bottom: 1px solid #eee;
}}
.login-header img {{
    height: 50px;
    width: auto;
    object-fit: contain;
}}
.login-header span {{
    font-size: 28px;
    font-weight: 800;
    color: #333;
}}
.lupa-pass {{
    text-align: center;
    margin-top: 15px;
}}
.lupa-pass a {{
    color: #1e90ff;
    text-decoration: none;
    font-weight: 500;
}}
"""

with gr.Blocks(theme=gr.themes.Soft(), title="Aplikasi Data Mahasiswa (Gradio)", css=CUSTOM_CSS) as app:
    
    app_state = gr.State(value={"is_logged_in": False, "role": "guest", "user": "N/A"})
    
    # --- 1. LOGIN BLOCK ---
    with gr.Column(visible=True, elem_id="login_block") as login_block:
        
        with gr.Row(elem_classes="login-header"):
            gr.Image(LOGO_LEFT, width=50, height="auto")
            gr.HTML('<span class="title-login-fix">LOGIN</span>', elem_classes="login-header-title")
            gr.Image(LOGO_RIGHT, width=50, height="auto")

        with gr.Column(variant="panel") as login_form_group:
            username_input = gr.Textbox(label="Username *", placeholder="Username *")
            password_input = gr.Textbox(label="Password *", placeholder="Password *", type="password")
            login_btn = gr.Button("LOGIN", variant="primary")
            
        gr.Button("Login dengan SSO", variant="secondary")
        gr.HTML("""<div class="lupa-pass"><a href="#">Lupa Password?</a></div>""")
        login_output = gr.Markdown("", visible=True)

    # --- 2. MAIN APP BLOCK (TABS) ---
    with gr.Column(visible=False) as main_app_block:
        
        with gr.Row(variant="panel", elem_classes="header-panel"):
            with gr.Column(scale=1):
                # Ganti dengan URL logo publik jika file lokal bermasalah
                gr.Image(LOGO_RIGHT, width=150, height="auto")
            with gr.Column(scale=3):
                gr.Markdown("## Aplikasi Manajemen Data Mahasiswa (Gradio)")
                info_role = gr.Markdown(f"Role Aktif: {app_state.value['role'].upper()}", elem_id="info_role")
                info_user = gr.Markdown(f"User: {app_state.value['user']}", elem_id="info_user")
            with gr.Column(scale=1, min_width=100):
                logout_btn = gr.Button("🚪 Logout", variant="stop")

        with gr.Tabs() as tabs:
            dashboard_tab = gr.TabItem("🏠 Dashboard & Data", id=0)
            crud_tab = gr.TabItem("🛠️ Data Mahasiswa (Admin)", id=1, visible=False) 
            search_sort_tab = gr.TabItem("🔍 Cari & Urutkan", id=2)
            stat_email_tab = gr.TabItem("📈 Statistik & Email", id=3)

            # --- TAB: DASHBOARD ---
            with dashboard_tab:
                with gr.Row():
                    dashboard_data = gr.Dataframe(value=get_current_df, headers=HEADERS, wrap=True, show_row_numbers=True, interactive=False)
                with gr.Row():
                    total_data_output = gr.Markdown(f"Total Data: {data_manager.get_count()}")
                    gr.Button("Refresh Data", variant="secondary").click(
                        fn=refresh_dashboard,
                        inputs=[app_state], 
                        outputs=[dashboard_data, total_data_output]
                    )

            # --- TAB: CRUD ---
            with crud_tab:
                gr.Markdown("## Manajemen Data Mahasiswa")
                crud_status_output = gr.Markdown("")
                
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### ➕ Tambah Data Baru")
                        with gr.Group():
                            f_nama = gr.Textbox(label="Nama")
                            f_nim = gr.Textbox(label="NIM (12 digit)")
                            f_jurusan = gr.Textbox(label="Jurusan")
                            f_hobi = gr.Textbox(label="Hobi")
                            f_cita = gr.Textbox(label="Cita-cita")
                            tambah_btn = gr.Button("Tambah Mahasiswa", variant="primary")
                    
                    with gr.Column(scale=1):
                        gr.Markdown("### ✏️ Edit / 🗑️ Hapus Data")
                        nim_lama_crud = gr.Textbox(label="NIM Lama (untuk Edit/Hapus)", placeholder="Masukkan NIM yang akan di-edit/hapus")
                        gr.Markdown("---")
                        gr.Markdown("Masukkan Data Baru untuk Edit:")
                        e_nama = gr.Textbox(label="Nama Baru")
                        e_nim = gr.Textbox(label="NIM Baru (12 digit)")
                        e_jurusan = gr.Textbox(label="Jurusan Baru")
                        e_hobi = gr.Textbox(label="Hobi Baru")
                        e_cita = gr.Textbox(label="Cita-cita Baru")
                        
                        with gr.Row():
                            edit_btn = gr.Button("Edit Data", variant="secondary")
                            hapus_btn = gr.Button("Hapus Data", variant="stop")
                            
                gr.Markdown("### Tabel Data CRUD")
                crud_data = gr.Dataframe(value=get_current_df, headers=HEADERS, wrap=True, show_row_numbers=True, interactive=False)
            
            # --- TAB: SEARCH & SORT ---
            with search_sort_tab:
                search_status_output = gr.Markdown("")
                sort_status_output = gr.Markdown("")
                
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### Pencarian Data")
                        with gr.Group():
                            metode_cari = gr.Radio(label="Metode Pencarian", choices=["Linear (Nama)", "Binary (NIM)", "Sequential (Hobi)"], value="Linear (Nama)")
                            q_cari = gr.Textbox(label="Kata kunci / NIM")
                            search_btn = gr.Button("Cari Data", variant="primary")
                    with gr.Column(scale=1):
                        gr.Markdown("### Pengurutan Data")
                        with gr.Group():
                            metode_sort = gr.Radio(label="Metode Pengurutan (Admin)", choices=["Bubble Sort (Nama)", "Selection Sort (NIM)", "Merge Sort (Jurusan)"], value="Merge Sort (Jurusan)")
                            sort_btn = gr.Button("Urutkan Data", variant="secondary")
                
                gr.Markdown("### Data Hasil Pencarian")
                search_data = gr.Dataframe(headers=HEADERS, wrap=True, show_row_numbers=True, interactive=False)
                
                gr.Markdown("### Data Hasil (Utama)")
                sort_data_output = gr.Dataframe(value=get_current_df, headers=HEADERS, wrap=True, show_row_numbers=True, interactive=False)

            # --- STATISTIK & EMAIL ---
            with stat_email_tab:
                gr.Markdown("## Statistik & Kirim Laporan")
                email_status_output = gr.Markdown("")
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### Statistik Jurusan & Cita-cita")
                        # FIX: Menghapus row_headers=False
                        stat_jurusan_table = gr.Dataframe(value=lambda: get_stat_data()[0], headers=['Jurusan', 'Jumlah', 'Persentase'], interactive=False) 
                        stat_cita_chart = gr.BarPlot(value=lambda: get_stat_data()[1], x="labels", y="values", title="Cita-cita Terpopuler", height=300)
                    with gr.Column(scale=1):
                        gr.Markdown("### Kirim Laporan via Email")
                        with gr.Group():
                            email_tujuan = gr.Textbox(label="Email Tujuan (Penerima Laporan)")
                            format_file = gr.Radio(label="Pilih Format Laporan", choices=["CSV", "Excel (.xlsx)", "PDF"], value="CSV")
                            
                            email_input_info = gr.Markdown("Info kredensial")
                            user_email_pengirim_input = gr.Textbox(label="Email Pengirim Anda", visible=False)
                            user_app_password_input = gr.Textbox(label="App Password Anda", type="password", visible=False)
                            
                            kirim_email_btn = gr.Button("Kirim Laporan", variant="primary")
                        
    # =========================================================================
    # === GRADIO EVENT HANDLERS / INTERACTIONS ===
    # =========================================================================

    # --- LOGIN / LOGOUT FLOW ---
    login_btn.click(
        fn=login_handler,
        inputs=[username_input, password_input, app_state],
        outputs=[app_state, login_block, main_app_block, login_output, username_input],
        queue=False 
    ).then(
        fn=update_tab_visibility,
        inputs=[app_state],
        outputs=[crud_tab] 
    ).then(
        fn=update_user_info,
        inputs=[app_state],
        outputs=[info_role, info_user]
    )

    logout_btn.click(
        fn=logout_handler,
        inputs=[app_state],
        outputs=[app_state, login_block, main_app_block],
        queue=False
    ).then(
        fn=update_user_info,
        inputs=[app_state],
        outputs=[info_role, info_user]
    )
    
    # --- CRUD HANDLERS ---
    tambah_btn.click(
        fn=tambah_mahasiswa_handler,
        inputs=[f_nama, f_nim, f_jurusan, f_hobi, f_cita, app_state],
        outputs=[crud_data, crud_status_output, f_nama, f_nim, f_jurusan, f_hobi, f_cita]
    ).then(
        fn=refresh_dashboard,
        inputs=[app_state],
        outputs=[dashboard_data, total_data_output]
    )

    edit_btn.click(
        fn=edit_mahasiswa_handler,
        inputs=[nim_lama_crud, e_nama, e_nim, e_jurusan, e_hobi, e_cita, app_state],
        outputs=[crud_data, crud_status_output]
    ).then(
        fn=refresh_dashboard,
        inputs=[app_state],
        outputs=[dashboard_data, total_data_output]
    )

    hapus_btn.click(
        fn=hapus_mahasiswa_handler,
        inputs=[nim_lama_crud, app_state],
        outputs=[crud_data, crud_status_output]
    ).then(
        fn=refresh_dashboard,
        inputs=[app_state],
        outputs=[dashboard_data, total_data_output]
    )

    # --- SEARCH / SORT HANDLERS ---
    search_btn.click(
        fn=search_handler,
        inputs=[metode_cari, q_cari],
        outputs=[search_data, search_status_output]
    )

    sort_btn.click(
        fn=sort_handler,
        inputs=[metode_sort, app_state],
        outputs=[sort_data_output, sort_status_output]
    )

    # --- STATS / EMAIL HANDLERS ---
    stat_email_tab.select(
        fn=update_email_inputs,
        inputs=[app_state],
        outputs=[user_email_pengirim_input, user_app_password_input, email_input_info]
    )

    app.load(
        fn=update_email_inputs,
        inputs=[app_state],
        outputs=[user_email_pengirim_input, user_app_password_input, email_input_info]
    )

    kirim_email_btn.click(
        fn=gr_kirim_email_attachment,
        inputs=[email_tujuan, app_state, format_file, user_email_pengirim_input, user_app_password_input],
        outputs=[email_status_output]
    )
    
app.launch()