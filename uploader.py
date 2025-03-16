import os
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QRadioButton, 
                             QButtonGroup, QTextEdit, QPushButton, QFileDialog,
                             QMessageBox, QGroupBox, QSizePolicy, QProgressBar, QDialog)
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtCore import Qt, QSettings, QThread, pyqtSignal, pyqtSlot

import pyszuru
import re
import requests
from requests.exceptions import RequestException
from urllib.parse import urlparse
import datetime  

DEBUG = True

def debug_print(message):
    if DEBUG:
        print(message)

def natural_sort_key(s):
    # Extract filename from file path
    filename = os.path.basename(s)
    # Convert the numeric part of the filename to an integer for comparison
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'(\d+)', filename)]

class UploadThread(QThread):
    # Define signals
    progress = pyqtSignal(int, int)  # (current progress, total)
    finished = pyqtSignal(int, int, list)  # (success count, total, failed list)
    error = pyqtSignal(str)  # error message
    tag_progress = pyqtSignal(int, int)  # (current tag progress, total tag count)

    def __init__(self, url, token, safety, tags, files):
        super().__init__()
        self.url = url
        self.token = token
        self.safety = safety
        self.tags = tags
        self.files = files
        self.is_cancelled = False

    def run(self):
        try:
            parsed_url = urlparse(self.url)
            if not parsed_url.scheme or not parsed_url.netloc:
                self.error.emit("URL format wrong,please enter prefix http:// or https://")
                return
        
            try:
                response = requests.head(
                    self.url, 
                    timeout=5,
                    allow_redirects=True
                )
                # status code check
                if response.status_code >= 400:
                    self.error.emit(f"server return: HTTP {response.status_code}")
                    return
                
            except RequestException as e:
                self.error.emit(f"can't connect to szurubooru: {str(e)}")
                return

            mybooru = pyszuru.API(
                self.url,
                username="root",
                token=self.token
            )
            
            total = len(self.files)
            success = 0
            failed = []

            # Process tags
            tag_count = len(self.tags)
            for i, t in enumerate(self.tags):
                if self.is_cancelled:
                    return
                
                self.tag_progress.emit(i + 1, tag_count)
                try:
                    mybooru.getTag(t)
                except Exception as e:
                    try:
                        mybooru.createTag(t)
                    except Exception as e:
                        debug_print(f"An upload error occurred: {e} while creating tag:{t}")
                        

            # Upload files
            for i, file_path in enumerate(self.files):
                if self.is_cancelled:
                    return
                    
                self.progress.emit(i + 1, total)
                try:
                    with open(file_path, "rb") as f:
                        file_token = mybooru.upload_file(f)

                    my_new_post = mybooru.createPost(file_token, self.safety)
                    my_new_post.tags = self.tags
                    my_new_post.push()
                    
                    success += 1
                except Exception as e:
                    debug_print(f"An upload error occurred: {e}, from {file_path}")
                    failed.append(f"{os.path.basename(file_path)}: {str(e)}")
            
            self.finished.emit(success, total, failed)
                
        except Exception as e:
            self.error.emit(str(e))

    def cancel(self):
        self.is_cancelled = True


class ProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upload Progress")
        self.setFixedSize(400, 150)
        # Set as modal dialog
        self.setWindowModality(Qt.WindowModal)
        layout = QVBoxLayout()
        
        # Tag processing progress
        self.tagLabel = QLabel("Processing tags...")
        layout.addWidget(self.tagLabel)
        self.tagProgressBar = QProgressBar()
        self.tagProgressBar.setRange(0, 100)
        layout.addWidget(self.tagProgressBar)
        
        # File upload progress
        self.fileLabel = QLabel("Preparing to upload files...")
        layout.addWidget(self.fileLabel)
        self.fileProgressBar = QProgressBar()
        self.fileProgressBar.setRange(0, 100)
        layout.addWidget(self.fileProgressBar)
        
        # Cancel button
        buttonLayout = QHBoxLayout()
        self.cancelButton = QPushButton("Cancel")
        buttonLayout.addStretch()
        buttonLayout.addWidget(self.cancelButton)
        layout.addLayout(buttonLayout)
        
        self.setLayout(layout)

    def updateTagProgress(self, current, total):
        if total > 0:
            percent = int(current / total * 100)
            self.tagProgressBar.setValue(percent)
            self.tagLabel.setText(f"Processing tags ({current}/{total})")

    def updateFileProgress(self, current, total):
        if total > 0:
            percent = int(current / total * 100)
            self.fileProgressBar.setValue(percent)
            self.fileLabel.setText(f"Uploading files ({current}/{total})")


class DropArea(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.files = []
        
        layout = QVBoxLayout()
        self.label = QLabel("Drag and drop files here or click to select files")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("border: 2px dashed #aaa; padding: 50px;")
        layout.addWidget(self.label)
        
        self.fileListText = QTextEdit()
        self.fileListText.setReadOnly(True)
        self.fileListText.setMaximumHeight(100)
        layout.addWidget(self.fileListText)
        
        self.selectButton = QPushButton("Select Files")
        self.selectButton.clicked.connect(self.selectFiles)
        layout.addWidget(self.selectButton)
        
        self.setLayout(layout)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        files = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path) and self.isImageFile(path):
                files.append(path)
        
        if files:
            self.files = files
            self.files.sort(key=natural_sort_key)
            self.updateFileList()
    
    def selectFiles(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Images", "", "Image Files (*.png *.jpg *.jpeg *.gif *.webp)")
        
        if files:
            self.files = files
            self.files.sort(key=natural_sort_key)
            self.updateFileList()
    
    def updateFileList(self):
        text = "\n".join([f"• {os.path.basename(f)}" for f in self.files])
        self.fileListText.setText(text)
        self.label.setText(f"{len(self.files)} files selected")
    
    def isImageFile(self, file_path):
        extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        return any(file_path.lower().endswith(ext) for ext in extensions)

    def getFiles(self):
        return self.files
    
    def clearFiles(self):
        self.files = []
        self.fileListText.clear()
        self.label.setText("Drag and drop files here or click to select files")


class SzurubooruUploader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.loadSettings()
    
    def initUI(self):
        self.setWindowTitle("Szurubooru Image Uploader")
        self.setGeometry(100, 100, 600, 700)
        
        mainWidget = QWidget()
        mainLayout = QVBoxLayout()
        
        # URL and Token input
        urlLayout = QHBoxLayout()
        urlLayout.addWidget(QLabel("Szurubooru URL:"))
        self.urlInput = QLineEdit()
        urlLayout.addWidget(self.urlInput)
        mainLayout.addLayout(urlLayout)
        
        tokenLayout = QHBoxLayout()
        tokenLayout.addWidget(QLabel("Token:"))
        self.tokenInput = QLineEdit()
        tokenLayout.addWidget(self.tokenInput)
        mainLayout.addLayout(tokenLayout)
        
        # Safety rating selection
        safetyGroup = QGroupBox("Safety Rating")
        safetyLayout = QHBoxLayout()
        
        self.safetyButtons = QButtonGroup()
        self.safeRadio = QRadioButton("Safe")
        self.unsafeRadio = QRadioButton("Unsafe")
        self.sketchyRadio = QRadioButton("Sketchy")
        
        self.safetyButtons.addButton(self.safeRadio, 0)
        self.safetyButtons.addButton(self.unsafeRadio, 1)
        self.safetyButtons.addButton(self.sketchyRadio, 2)
        
        self.safeRadio.setChecked(True)
        
        safetyLayout.addWidget(self.safeRadio)
        safetyLayout.addWidget(self.unsafeRadio)
        safetyLayout.addWidget(self.sketchyRadio)
        safetyGroup.setLayout(safetyLayout)
        mainLayout.addWidget(safetyGroup)
        
        # Tags input
        tagsLayout = QVBoxLayout()
        tagsLabel = QLabel("Tags (separated by spaces):")
        tagsLabel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)  # Set fixed size policy
        tagsLayout.addWidget(tagsLabel)
        self.tagsInput = QLineEdit()#QTextEdit()
        #self.tagsInput.setMaximumHeight(80)
        tagsLayout.addWidget(self.tagsInput)
        mainLayout.addLayout(tagsLayout)
        
        # Drop area
        mainLayout.addWidget(QLabel("Images:"))
        self.dropArea = DropArea()
        mainLayout.addWidget(self.dropArea)
        
        # Upload button
        self.uploadButton = QPushButton("Upload")
        self.uploadButton.clicked.connect(self.uploadImages)
        mainLayout.addWidget(self.uploadButton)
        
        #add statusBar
        self.statusBar = self.statusBar()
        self.statusBar.showMessage("Ready")

        mainWidget.setLayout(mainLayout)
        self.setCentralWidget(mainWidget)
    
    def loadSettings(self):
         # get program dir
        app_dir = os.path.dirname(os.path.abspath(__file__))
        # create ini path
        settings_file = os.path.join(app_dir, "settings.ini")
        # create instance 
        settings = QSettings(settings_file, QSettings.IniFormat)
        self.urlInput.setText(settings.value("url", ""))
        self.tokenInput.setText(settings.value("token", ""))
        safetyLevel = settings.value("safety", 0)
        
        if safetyLevel == 0:
            self.safeRadio.setChecked(True)
        elif safetyLevel == 1:
            self.unsafeRadio.setChecked(True)
        else:
            self.sketchyRadio.setChecked(True)
            
        self.tagsInput.setText(settings.value("tags", ""))
    
    def saveSettings(self):
        app_dir = os.path.dirname(os.path.abspath(__file__))
        settings_file = os.path.join(app_dir, "settings.ini")
        settings = QSettings(settings_file, QSettings.IniFormat)
        settings.setValue("url", self.urlInput.text())
        settings.setValue("token", self.tokenInput.text())
        settings.setValue("safety", self.safetyButtons.checkedId())
        settings.setValue("tags", self.tagsInput.text())
    
    def uploadImages(self):
        # Save current settings
        self.saveSettings()
        
        # Get values
        url = self.urlInput.text().strip()
        token = self.tokenInput.text().strip()
        
        safety_map = {
            0: "safe",
            1: "unsafe", 
            2: "sketchy"
        }
        safety = safety_map[self.safetyButtons.checkedId()]
        
        tags = self.tagsInput.text().strip().split()
        files = self.dropArea.getFiles()
        
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            QMessageBox.warning(self, "URL wrong", "enter prefix like http://或https://")
            return
        # Validate inputs
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter the Szurubooru URL")
            return
        
        if not token:
            QMessageBox.warning(self, "Input Error", "Please enter the Token")
            return
        
        if not files:
            QMessageBox.warning(self, "Input Error", "Please select at least one image file")
            return
        
        self.progress_dialog = ProgressDialog(self)
        self.progress_dialog.show()
        self.upload_thread = UploadThread(url, token, safety, tags, files)

        self.upload_thread.tag_progress.connect(self.progress_dialog.updateTagProgress)
        self.upload_thread.progress.connect(self.progress_dialog.updateFileProgress)
        self.upload_thread.finished.connect(self.onUploadFinished)
        self.upload_thread.error.connect(self.onUploadError)
        self.progress_dialog.cancelButton.clicked.connect(self.onCancelUpload)
        
        self.upload_thread.start()
        # Upload images
    def onUploadFinished(self, success, total, failed):
        self.progress_dialog.close()
        
        if success == total:
            #QMessageBox.information(self, "Upload Successful", f"Successfully uploaded {success} files")
            self.statusBar.showMessage(f"Upload Successful: {success}/{total} files")
            self.dropArea.clearFiles()
        else:
            # error_msg = "\n".join(failed)
            # QMessageBox.warning(
            #     self, 
            #     "Upload Result", 
            #     f"Successfully uploaded {success}/{total} files\n\nFailed files:\n{error_msg}"
            # )
            self.statusBar.showMessage(f"Upload Successful {success}/{total} files, failed {len(failed)}")
            if failed:
                self.writeErrorLog(failed)

    def writeErrorLog(self, failed_items):
        try:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(app_dir, "logs")
            
            
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = os.path.join(log_dir, f"upload_errors_{timestamp}.log")
            
            
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"=== error log {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
                for item in failed_items:
                    f.write(f"{item}\n")
            
            self.statusBar.showMessage(f"{self.statusBar.currentMessage()} | log: {os.path.basename(log_file)}")
            
        except Exception as e:
            self.statusBar.showMessage(f"{self.statusBar.currentMessage()} | can't write erro log: {str(e)}")

    def onUploadError(self, error_msg):
        self.progress_dialog.close()
        QMessageBox.critical(self, "Upload Error", f"An error occurred during upload:\n{error_msg}")

    def onCancelUpload(self):
            # reply = QMessageBox.question(
            #     self, 'Confirm Cancel', 
            #     "Are you sure you want to cancel the upload?", 
            #     QMessageBox.Yes | QMessageBox.No, 
            #     QMessageBox.No
            # )
            
            # if reply == QMessageBox.Yes:
            self.upload_thread.cancel()
            self.progress_dialog.close()
            QMessageBox.information(self, "Cancelled", "Upload operation has been cancelled")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SzurubooruUploader()
    window.show()
    sys.exit(app.exec_())