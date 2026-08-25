import sys
import time
import re
import os
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QTextEdit, 
    QVBoxLayout, QHBoxLayout, QWidget, QLabel, QLineEdit, QGroupBox,
    QTabWidget, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from mcrcon import MCRcon
import paramiko

# Alapértelmezett nyelvi struktúra (fallback esetére)
DEFAULT_LANGUAGES = {
    "en": {
        "label_language": "🌐 Language:",
        "window_title": "Palworld Server Controller & Configurator",
        "tab_control": "🎮 Server Control",
        "tab_settings": "⚙️ All Settings (.ini)",
        "rcon_group": "RCON Connection",
        "ssh_group": "SSH Connection (File Management & Restart)",
        "mod_group": "Player Moderation",
        "btn_info": "ℹ️ Info",
        "btn_players": "👥 Players",
        "btn_save": "💾 Save (RCON)",
        "btn_restart": "🔄 Restart (SSH)",
        "btn_timed_shutdown": "⏳ Shutdown (60s)",
        "btn_shutdown": "🛑 Instant Shutdown",
        "btn_kick": "👢 Kick (RCON)",
        "btn_ban": "🔨 Ban (RCON)",
        "btn_unban": "🔓 Unban (SSH)",
        "btn_broadcast": "📢 Send Broadcast",
        "btn_load_ini": "📥 Load all settings via SSH",
        "btn_save_ini": "💾 Stop Server -> Save via SSH -> Restart",
        "placeholder_broadcast": "Type system broadcast message...",
        "placeholder_steamid": "Enter Player SteamID / PlayerUID...",
        "placeholder_search": "Type an option name to search...",
        "col_key": "Setting Name (Option)",
        "col_value": "Value",
        "log_title": "Server Response / Log:"
    },
}

# Alapértelmezett hálózati & SSH beállítások (ha még nem létezik config.json)
DEFAULT_CONFIG = {
    "language": "en",
    "rcon_ip": "127.0.0.1",
    "rcon_port": "25575",
    "rcon_pass": "12345678",
    "ssh_host": "127.0.0.1",
    "ssh_port": "22",
    "ssh_user": "root",
    "ssh_pass": "12345678",
    "ini_path": "/home/steam/palsrv/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini"
}

class ConfigManager:
    """Beállítások és nyelvi fájlok kezeléséért felelős osztály."""
    def __init__(self, locales_dir="locales", config_file="config.json"):
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.locales_dir = os.path.join(base_dir, locales_dir)
        self.config_path = os.path.join(base_dir, config_file)
        
        self.ensure_locales_exist()
        self.config = self.load_config()
        
        self.current_lang = self.config.get("language", "en")
        self.translations = {}
        self.load_language(self.current_lang)

    def ensure_locales_exist(self):
        """Létrehozza a locales mappát és az alap nyelvi fájlokat, ha még nem léteznek."""
        if not os.path.exists(self.locales_dir):
            os.makedirs(self.locales_dir)
        
        for lang_code, data in DEFAULT_LANGUAGES.items():
            file_path = os.path.join(self.locales_dir, f"{lang_code}.json")
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

    def load_config(self):
        """Beolvassa a config.json-t. Ha nem létezik, létrehozza az alapértelmezett értékekkel."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, val in DEFAULT_CONFIG.items():
                        if key not in data:
                            data[key] = val
                    return data
            except Exception as e:
                print(f"Hiba a config.json betöltésekor: {e}")
        
        self.save_config_data(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    def save_config_data(self, data):
        """Közvetlen mentés a config.json fájlba."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Hiba a config mentésekor: {e}")

    def update_key(self, key, value):
        """Frissít egy adott kulcsot a konfigurációban és elmenti."""
        self.config[key] = value
        self.save_config_data(self.config)

    def get_sorted_languages(self):
        """Az Angolt (en) helyezi legelőre, a többi JSON-t ábécésorrendbe rendezi."""
        available = []
        if os.path.exists(self.locales_dir):
            for file_name in os.listdir(self.locales_dir):
                if file_name.endswith(".json"):
                    available.append(file_name[:-5])
        
        if "en" not in available:
            available.append("en")

        other_langs = sorted([lang for lang in available if lang != "en"])
        return ["en"] + other_langs

    def load_language(self, lang_code):
        """Betölti a kiválasztott nyelv JSON fájlját."""
        file_path = os.path.join(self.locales_dir, f"{lang_code}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
                    self.current_lang = lang_code
                    return
            except Exception as e:
                print(f"Hiba a(z) {lang_code} nyelvi fájl beolvasásakor: {e}")
        
        self.current_lang = "en"
        self.translations = DEFAULT_LANGUAGES.get("en", {})

    def tr(self, key):
        """Visszaadja a kulcshoz tartozó fordítást."""
        return self.translations.get(key, DEFAULT_LANGUAGES.get("en", {}).get(key, key))

class RestartWorker(QThread):
    """Háttérszál az SSH újraindítás kezelésére."""
    update_signal = pyqtSignal(str)

    def __init__(self, host, port, username, password):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    def run(self):
        time.sleep(2)
        self.update_signal.emit(f"🔐 SSH connection ({self.username}@{self.host}:{self.port}) -> 'palsrv.service' restart...")
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=self.host, 
                port=self.port, 
                username=self.username, 
                password=self.password, 
                timeout=10
            )
            
            _in, _out, _err = ssh.exec_command("systemctl restart palsrv.service")
            error_output = _err.read().decode().strip()
            
            if error_output:
                self.update_signal.emit(f"⚠️ SSH Response/Error: {error_output}")
            else:
                self.update_signal.emit("✅ 'systemctl restart palsrv.service' executed successfully!")
            ssh.close()
        except Exception as e:
            self.update_signal.emit(f"❌ SSH Error: {e}")

class PalworldGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg_mgr = ConfigManager()

        self.resize(1000, 850)

        try:
            self.setWindowIcon(QIcon("palworld.png"))
        except Exception:
            pass

        self.raw_ini_content = ""
        self.settings_dict = {}

        main_layout = QVBoxLayout()

        # Nyelvválasztó Fejléc
        lang_layout = QHBoxLayout()
        lang_layout.addStretch()
        
        self.label_lang = QLabel()
        lang_layout.addWidget(self.label_lang)
        
        self.combo_lang = QComboBox()
        self.combo_lang.blockSignals(True)
        
        sorted_langs = self.cfg_mgr.get_sorted_languages()
        target_index = 0
        
        for index, code in enumerate(sorted_langs):
            self.combo_lang.addItem(f"{code.upper()} ({code})", code)
            if code == self.cfg_mgr.current_lang:
                target_index = index

        self.combo_lang.setCurrentIndex(target_index)
        self.combo_lang.blockSignals(False)
        self.combo_lang.currentIndexChanged.connect(self.change_language_by_code)
        
        lang_layout.addWidget(self.combo_lang)
        main_layout.addLayout(lang_layout)

        self.tabs = QTabWidget()

        # Fül 1: Szerver Vezérlés
        self.tab_control = QWidget()
        self.setup_control_tab()
        self.tabs.addTab(self.tab_control, "")

        # Fül 2: ÖSSZES Beállítás (Dinamikus Táblázat)
        self.tab_settings = QWidget()
        self.setup_settings_tab()
        self.tabs.addTab(self.tab_settings, "")

        main_layout.addWidget(self.tabs)

        # Log Ablak
        self.label_log = QLabel()
        main_layout.addWidget(self.label_log)
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFixedHeight(150)
        main_layout.addWidget(self.output_text)

        widget = QWidget()
        widget.setLayout(main_layout)
        self.setCentralWidget(widget)

        # UI Szövegek frissítése
        self.retranslate_ui()
        
        # Konfiguráció változások automatikus mentésének bekötése
        self.bind_config_events()

    def bind_config_events(self):
        """Ha a felhasználó átír egy mezőt, az automatikusan mentődik a config.json-ba."""
        self.input_rcon_ip.textChanged.connect(lambda val: self.cfg_mgr.update_key("rcon_ip", val.strip()))
        self.input_rcon_port.textChanged.connect(lambda val: self.cfg_mgr.update_key("rcon_port", val.strip()))
        self.input_rcon_pass.textChanged.connect(lambda val: self.cfg_mgr.update_key("rcon_pass", val.strip()))
        
        self.input_ssh_host.textChanged.connect(lambda val: self.cfg_mgr.update_key("ssh_host", val.strip()))
        self.input_ssh_port.textChanged.connect(lambda val: self.cfg_mgr.update_key("ssh_port", val.strip()))
        self.input_ssh_user.textChanged.connect(lambda val: self.cfg_mgr.update_key("ssh_user", val.strip()))
        self.input_ssh_pass.textChanged.connect(lambda val: self.cfg_mgr.update_key("ssh_pass", val.strip()))
        
        self.input_ini_path.textChanged.connect(lambda val: self.cfg_mgr.update_key("ini_path", val.strip()))

    def change_language_by_code(self, index):
        lang_code = self.combo_lang.itemData(index)
        if lang_code:
            self.cfg_mgr.load_language(lang_code)
            self.cfg_mgr.update_key("language", lang_code)
            self.retranslate_ui()

    def retranslate_ui(self):
        """Minden GUI elemet lefordít a kiválasztott nyelvre."""
        tr = self.cfg_mgr.tr
        
        self.label_lang.setText(tr("label_language"))
        self.setWindowTitle(tr("window_title"))
        self.tabs.setTabText(0, tr("tab_control"))
        self.tabs.setTabText(1, tr("tab_settings"))

        self.rcon_group.setTitle(tr("rcon_group"))
        self.ssh_group.setTitle(tr("ssh_group"))
        self.mod_group.setTitle(tr("mod_group"))

        self.btn_info.setText(tr("btn_info"))
        self.btn_players.setText(tr("btn_players"))
        self.btn_save.setText(tr("btn_save"))
        self.btn_restart.setText(tr("btn_restart"))
        self.btn_timed_shutdown.setText(tr("btn_timed_shutdown"))
        self.btn_shutdown.setText(tr("btn_shutdown"))

        self.btn_kick.setText(tr("btn_kick"))
        self.btn_ban.setText(tr("btn_ban"))
        self.btn_unban.setText(tr("btn_unban"))

        self.btn_broadcast.setText(tr("btn_broadcast"))
        self.btn_load_ini.setText(tr("btn_load_ini"))
        self.btn_save_ini.setText(tr("btn_save_ini"))

        self.input_broadcast.setPlaceholderText(tr("placeholder_broadcast"))
        self.input_target_steamid.setPlaceholderText(tr("placeholder_steamid"))
        self.input_search.setPlaceholderText(tr("placeholder_search"))

        self.table_settings.setHorizontalHeaderLabels([tr("col_key"), tr("col_value")])
        self.label_log.setText(tr("log_title"))

    def setup_control_tab(self):
        layout = QVBoxLayout()
        cfg = self.cfg_mgr.config

        # 1. RCON Beállítások
        self.rcon_group = QGroupBox()
        rcon_layout = QHBoxLayout()

        rcon_layout.addWidget(QLabel("RCON IP:"))
        self.input_rcon_ip = QLineEdit(cfg.get("rcon_ip", ""))
        rcon_layout.addWidget(self.input_rcon_ip)

        rcon_layout.addWidget(QLabel("RCON Port:"))
        self.input_rcon_port = QLineEdit(cfg.get("rcon_port", ""))
        self.input_rcon_port.setFixedWidth(60)
        rcon_layout.addWidget(self.input_rcon_port)

        rcon_layout.addWidget(QLabel("RCON Pass:"))
        self.input_rcon_pass = QLineEdit(cfg.get("rcon_pass", ""))
        self.input_rcon_pass.setEchoMode(QLineEdit.EchoMode.Password)
        rcon_layout.addWidget(self.input_rcon_pass)

        self.rcon_group.setLayout(rcon_layout)
        layout.addWidget(self.rcon_group)

        # 2. SSH Beállítások
        self.ssh_group = QGroupBox()
        ssh_layout = QHBoxLayout()

        ssh_layout.addWidget(QLabel("SSH IP/Host:"))
        self.input_ssh_host = QLineEdit(cfg.get("ssh_host", ""))
        ssh_layout.addWidget(self.input_ssh_host)

        ssh_layout.addWidget(QLabel("SSH Port:"))
        self.input_ssh_port = QLineEdit(cfg.get("ssh_port", ""))
        ssh_layout.addWidget(self.input_ssh_port)

        ssh_layout.addWidget(QLabel("SSH User:"))
        self.input_ssh_user = QLineEdit(cfg.get("ssh_user", ""))
        ssh_layout.addWidget(self.input_ssh_user)

        ssh_layout.addWidget(QLabel("SSH Pass:"))
        self.input_ssh_pass = QLineEdit(cfg.get("ssh_pass", ""))
        self.input_ssh_pass.setEchoMode(QLineEdit.EchoMode.Password)
        ssh_layout.addWidget(self.input_ssh_pass)

        self.ssh_group.setLayout(ssh_layout)
        layout.addWidget(self.ssh_group)

        # 3. Szerver Vezérlő Gombok
        btn_layout = QHBoxLayout()

        self.btn_info = QPushButton()
        self.btn_info.clicked.connect(self.get_info)
        btn_layout.addWidget(self.btn_info)

        self.btn_players = QPushButton()
        self.btn_players.clicked.connect(self.get_players)
        btn_layout.addWidget(self.btn_players)

        self.btn_save = QPushButton()
        self.btn_save.clicked.connect(self.save_server)
        btn_layout.addWidget(self.btn_save)

        self.btn_restart = QPushButton()
        self.btn_restart.setStyleSheet("background-color: #d97706; color: white; font-weight: bold;")
        self.btn_restart.clicked.connect(self.restart_server)
        btn_layout.addWidget(self.btn_restart)

        self.btn_timed_shutdown = QPushButton()
        self.btn_timed_shutdown.setStyleSheet("background-color: #c2410c; color: white; font-weight: bold;")
        self.btn_timed_shutdown.clicked.connect(self.timed_shutdown)
        btn_layout.addWidget(self.btn_timed_shutdown)

        self.btn_shutdown = QPushButton()
        self.btn_shutdown.setStyleSheet("background-color: #8b0000; color: white; font-weight: bold;")
        self.btn_shutdown.clicked.connect(self.shutdown_server)
        btn_layout.addWidget(self.btn_shutdown)

        layout.addLayout(btn_layout)

        # 4. Moderációs Panel
        self.mod_group = QGroupBox()
        mod_layout = QHBoxLayout()

        self.input_target_steamid = QLineEdit()
        mod_layout.addWidget(self.input_target_steamid)

        self.btn_kick = QPushButton()
        self.btn_kick.clicked.connect(self.kick_player)
        mod_layout.addWidget(self.btn_kick)

        self.btn_ban = QPushButton()
        self.btn_ban.setStyleSheet("background-color: #b91c1c; color: white; font-weight: bold;")
        self.btn_ban.clicked.connect(self.ban_player)
        mod_layout.addWidget(self.btn_ban)

        self.btn_unban = QPushButton()
        self.btn_unban.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold;")
        self.btn_unban.clicked.connect(self.unban_player)
        mod_layout.addWidget(self.btn_unban)

        self.mod_group.setLayout(mod_layout)
        layout.addWidget(self.mod_group)

        # 5. Broadcast Üzenet
        bc_layout = QHBoxLayout()
        self.input_broadcast = QLineEdit()
        self.input_broadcast.returnPressed.connect(self.send_broadcast)
        bc_layout.addWidget(self.input_broadcast)

        self.btn_broadcast = QPushButton()
        self.btn_broadcast.clicked.connect(self.send_broadcast)
        bc_layout.addWidget(self.btn_broadcast)

        layout.addLayout(bc_layout)
        self.tab_control.setLayout(layout)

    def setup_settings_tab(self):
        layout = QVBoxLayout()
        cfg = self.cfg_mgr.config

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("INI Path:"))
        self.input_ini_path = QLineEdit(cfg.get("ini_path", ""))
        path_layout.addWidget(self.input_ini_path)

        self.btn_load_ini = QPushButton()
        self.btn_load_ini.setStyleSheet("font-weight: bold;")
        self.btn_load_ini.clicked.connect(self.load_ini_from_ssh)
        path_layout.addWidget(self.btn_load_ini)

        layout.addLayout(path_layout)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 Filter:"))
        self.input_search = QLineEdit()
        self.input_search.textChanged.connect(self.filter_table)
        search_layout.addWidget(self.input_search)
        layout.addLayout(search_layout)

        self.table_settings = QTableWidget()
        self.table_settings.setColumnCount(2)
        self.table_settings.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_settings.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table_settings)

        self.btn_save_ini = QPushButton()
        self.btn_save_ini.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; font-size: 14px; padding: 10px;")
        self.btn_save_ini.clicked.connect(self.save_ini_to_ssh)
        layout.addWidget(self.btn_save_ini)

        self.tab_settings.setLayout(layout)

    # --- RCON ÉS VEZÉRLŐ FUNKCIÓK ---
    def send_rcon_command(self, command: str) -> str:
        ip = self.input_rcon_ip.text().strip()
        port_str = self.input_rcon_port.text().strip()
        password = self.input_rcon_pass.text().strip()

        try:
            port = int(port_str)
            with MCRcon(ip, password, port=port, timeout=5) as mcr:
                return mcr.command(command)
        except Exception as e:
            return f"Error ({type(e).__name__}): {e}"

    def get_info(self):
        res = self.send_rcon_command("Info")
        self.output_text.setText(f"ℹ️ Server Info:\n{res}")

    def get_players(self):
        raw_response = self.send_rcon_command("ShowPlayers")
        if raw_response.startswith("Error"):
            self.output_text.setText(raw_response)
            return

        lines = raw_response.strip().split("\n")
        if len(lines) <= 1 or not lines[1].strip():
            self.output_text.setText("🟢 No players online currently.")
        else:
            formatted_text = "🎮 Online Players:\n" + "="*45 + "\n"
            for line in lines[1:]:
                if line.strip():
                    parts = line.split(",")
                    name = parts[0]
                    steam_id = parts[2] if len(parts) > 2 else "N/A"
                    formatted_text += f"• {name} | SteamID: {steam_id}\n"
            self.output_text.setText(formatted_text)

    def save_server(self):
        response = self.send_rcon_command("Save")
        self.output_text.setText(f"💾 Save Result:\n{response}")

    def send_broadcast(self):
        message = self.input_broadcast.text().strip()
        if not message:
            return
        response = self.send_rcon_command(f"Broadcast {message}")
        self.output_text.setText(f"📢 Broadcast Sent!\nResponse: {response}")
        self.input_broadcast.clear()

    def kick_player(self):
        target = self.input_target_steamid.text().strip()
        if not target:
            QMessageBox.warning(self, "Warning", "Please specify a SteamID!")
            return
        res = self.send_rcon_command(f"KickPlayer {target}")
        self.output_text.setText(f"👢 Kick Result:\n{res}")

    def ban_player(self):
        target = self.input_target_steamid.text().strip()
        if not target:
            QMessageBox.warning(self, "Warning", "Please specify a SteamID!")
            return
        res = self.send_rcon_command(f"BanPlayer {target}")
        self.output_text.setText(f"🔨 Ban Result:\n{res}")

    def unban_player(self):
        target = self.input_target_steamid.text().strip()
        if not target:
            QMessageBox.warning(self, "Warning", "Please specify a SteamID for unban!")
            return

        host = self.input_ssh_host.text().strip()
        port_str = self.input_ssh_port.text().strip()
        username = self.input_ssh_user.text().strip()
        password = self.input_ssh_pass.text().strip()
        
        banlist_path = "/home/steam/palsrv/Pal/Saved/SaveGames/BanList.txt"

        try:
            port = int(port_str)
            self.output_text.setText(f"🔓 Unbanning via SSH: {target}...")
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=host, port=port, username=username, password=password, timeout=10)

            cmd = f"sed -i '/{target}/d' {banlist_path}"
            _in, _out, _err = ssh.exec_command(cmd)
            err = _err.read().decode().strip()
            ssh.close()

            if err:
                self.output_text.setText(f"⚠️ Unban Error:\n{err}")
            else:
                self.output_text.setText(f"✅ SteamID ({target}) removed from BanList.txt!\nℹ️ A server restart may be required for changes to take effect.")

        except Exception as e:
            self.output_text.setText(f"❌ SSH Error during unban: {e}")

    def timed_shutdown(self):
        res = self.send_rcon_command("Shutdown 60 Server_shutting_down_in_60_seconds!")
        self.output_text.setText(f"⏳ Timed Shutdown (60s) Issued:\n{res}")

    def shutdown_server(self):
        self.output_text.setText("⏳ Saving before shutdown...")
        save_res = self.send_rcon_command("Save")
        exit_res = self.send_rcon_command("DoExit")
        self.output_text.setText(f"💾 Save: {save_res}\n🛑 Instant shutdown issued: {exit_res}")

    def restart_server(self):
        host = self.input_ssh_host.text().strip()
        port_str = self.input_ssh_port.text().strip()
        ssh_user = self.input_ssh_user.text().strip()
        password = self.input_ssh_pass.text().strip()

        try:
            port = int(port_str)
        except ValueError:
            self.output_text.setText("❌ Invalid SSH port number!")
            return

        self.output_text.setText("⏳ Restart sequence initiated...")
        self.send_rcon_command("Broadcast Server_restart_in_progress!")
        self.send_rcon_command("Save")
        self.send_rcon_command("DoExit")

        self.restart_thread = RestartWorker(host, port, ssh_user, password)
        self.restart_thread.update_signal.connect(self.output_text.append)
        self.restart_thread.start()

    # --- INI CONFIG & PARSER FUNKCIÓK ---
    def load_ini_from_ssh(self):
        host = self.input_ssh_host.text().strip()
        port_str = self.input_ssh_port.text().strip()
        username = self.input_ssh_user.text().strip()
        password = self.input_ssh_pass.text().strip()
        ini_path = self.input_ini_path.text().strip()

        try:
            port = int(port_str)
        except ValueError:
            self.output_text.setText("❌ Invalid SSH port!")
            return

        self.output_text.setText(f"📥 Downloading INI via SSH ({username}@{host}:{port})...")

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=host, port=port, username=username, password=password, timeout=10)

            sftp = ssh.open_sftp()
            with sftp.open(ini_path, "r") as f:
                content = f.read().decode('utf-8')
            sftp.close()
            ssh.close()

            self.raw_ini_content = content
            self.parse_all_settings(content)
            self.output_text.append(f"✅ Settings loaded! ({len(self.settings_dict)} options found)")

        except Exception as e:
            self.output_text.append(f"❌ Error loading INI: {e}")

    def parse_all_settings(self, content):
        match = re.search(r'OptionSettings=\((.*)\)', content, re.DOTALL)
        if not match:
            QMessageBox.critical(self, "Error", "No 'OptionSettings=(...)' block found in the INI file!")
            return

        settings_str = match.group(1)
        pairs = re.findall(r'([a-zA-Z0-9_]+)=("(?:[^"\\]|\\.)*"|[^,]+)', settings_str)

        self.settings_dict = {}
        self.table_settings.setRowCount(0)

        for row, (key, value) in enumerate(pairs):
            key = key.strip()
            value = value.strip()
            self.settings_dict[key] = value

            self.table_settings.insertRow(row)
            
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_settings.setItem(row, 0, key_item)

            val_item = QTableWidgetItem(value)
            self.table_settings.setItem(row, 1, val_item)

    def filter_table(self, text):
        for row in range(self.table_settings.rowCount()):
            item = self.table_settings.item(row, 0)
            if item:
                self.table_settings.setRowHidden(row, text.lower() not in item.text().lower())

    def save_ini_to_ssh(self):
        if not self.raw_ini_content or self.table_settings.rowCount() == 0:
            QMessageBox.warning(self, "Warning", "Please load settings first!")
            return

        new_settings_list = []
        for row in range(self.table_settings.rowCount()):
            key = self.table_settings.item(row, 0).text()
            value = self.table_settings.item(row, 1).text()
            new_settings_list.append(f"{key}={value}")

        new_option_settings = "OptionSettings=(" + ",".join(new_settings_list) + ")"

        updated_ini_content = re.sub(
            r'OptionSettings=\(.*\)',
            new_option_settings,
            self.raw_ini_content,
            flags=re.DOTALL
        )

        host = self.input_ssh_host.text().strip()
        port_str = self.input_ssh_port.text().strip()
        username = self.input_ssh_user.text().strip()
        password = self.input_ssh_pass.text().strip()
        ini_path = self.input_ini_path.text().strip()

        try:
            port = int(port_str)
        except ValueError:
            self.output_text.setText("❌ Invalid SSH port!")
            return

        self.output_text.setText("🛑 1/3: Saving & Stopping Server via RCON...")
        self.send_rcon_command("Broadcast Server_stopping_for_maintenance!")
        self.send_rcon_command("Save")
        self.send_rcon_command("DoExit")

        QApplication.processEvents()
        time.sleep(3)

        self.output_text.append("📤 2/3: Uploading updated INI via SSH/SFTP...")
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=host, port=port, username=username, password=password, timeout=10)

            sftp = ssh.open_sftp()
            with sftp.open(ini_path, "w") as f:
                f.write(updated_ini_content)
            sftp.close()
            ssh.close()

            self.output_text.append("✅ INI file updated successfully!")

            self.output_text.append("🔄 3/3: Restarting server via systemd (SSH)...")
            self.restart_thread = RestartWorker(host, port, username, password)
            self.restart_thread.update_signal.connect(self.output_text.append)
            self.restart_thread.start()

        except Exception as e:
            self.output_text.append(f"❌ Upload error: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PalworldGUI()
    window.show()
    sys.exit(app.exec())
