import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtUiTools import QUiLoader
import ffmpeg
import os
import platform
import subprocess
from PySide6 import QtGui

class VideoSplitterThread(QThread):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal()
    
    def __init__(self, source_dir, output_dir, duration):
        super().__init__()
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.duration = duration
        self.is_running = True
        self.current_process = None  # 添加变量来跟踪当前进程
        
    def run(self):
        try:
            # 打印完整路径信息
            self.log.emit(f"源文件夹: {os.path.abspath(self.source_dir)}")
            self.log.emit(f"输出文件夹: {os.path.abspath(self.output_dir)}")
            
            # 支持更多视频格式
            video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.m4v', '.webm')
            video_files = [f for f in os.listdir(self.source_dir) 
                          if f.lower().endswith(video_extensions)]
            
            # 打印找到的视频文件
            self.log.emit(f"找到的视频文件: {video_files}")
            
            if not video_files:
                self.log.emit("未找到支持的视频文件")
                self.finished.emit()
                return
            
            total_files = len(video_files)
            for i, video_file in enumerate(video_files):
                if not self.is_running:
                    break
                    
                input_path = os.path.abspath(os.path.join(self.source_dir, video_file))
                self.log.emit(f"正在处理文件: {input_path}")
                
                try:
                    self.split_video(input_path, i, total_files)
                except Exception as e:
                    self.log.emit(f"处理 {video_file} 时出错: {str(e)}")
                    
            self.finished.emit()
        except Exception as e:
            self.log.emit(f"运行时错误: {str(e)}")
            self.finished.emit()
        
    def split_video(self, input_path, file_index, total_files):
        try:
            # 转换路径为规范格式并处理中文字符
            input_path = str(Path(input_path).resolve())
            
            # 检查文件并输出详细信息
            self.log.emit(f"完整输入路径: {input_path}")
            self.log.emit(f"文件大小: {os.path.getsize(input_path) if os.path.exists(input_path) else '文件不存在'}")
            
            if not os.path.exists(input_path):
                self.log.emit(f"目录内容: {os.listdir(os.path.dirname(input_path))}")
                raise FileNotFoundError(f"找不到输入文件: {input_path}")
            
            # 测试 FFmpeg 是否能读取文件
            test_cmd = ['ffmpeg', '-i', input_path]
            result = subprocess.run(
                test_cmd, 
                capture_output=True, 
                text=True, 
                encoding='utf-8',  # 明确指定编码
                errors='ignore'
            )
            
            if "No such file or directory" in result.stderr:
                self.log.emit("FFmpeg 无法访问文件，尝试使用引号包裹路径")
                input_path = f'"{input_path}"'
            
            # 获取视频时长
            duration = 0
            for line in result.stderr.split('\n'):
                if 'Duration' in line:
                    time_str = line.split('Duration: ')[1].split(',')[0]
                    h, m, s = time_str.split(':')
                    duration = float(h) * 3600 + float(m) * 60 + float(s)
                    self.log.emit(f"视频时长: {duration}秒")
                    break
            
            segments = int(duration / self.duration)
            filename = Path(input_path).stem
            
            self.log.emit(f"开始分割第 {file_index + 1}/{total_files} 个文件: {filename}")
            self.log.emit(f"预计分割成 {segments + 1} 个片段")
            
            for i in range(segments + 1):
                if not self.is_running:
                    break
                    
                start_time = i * self.duration
                output_path = str(Path(self.output_dir) / f"{filename}_{i:03d}.mp4")
                
                try:
                    cmd = [
                        'ffmpeg',
                        '-i', input_path,
                        '-ss', str(start_time),
                        '-t', str(self.duration),
                        '-c:v', 'libx264',
                        '-c:a', 'aac',
                        '-y',
                        '-progress', 'pipe:1',
                        '-v', 'error',
                        output_path
                    ]
                    
                    # 在 Windows 上隐藏命令行窗口
                    startupinfo = None
                    if platform.system() == 'Windows':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = subprocess.SW_HIDE
                    
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True,
                        encoding='utf-8',
                        errors='ignore',
                        startupinfo=startupinfo
                    )
                    
                    self.log.emit(f"正在生成第 {i + 1}/{segments + 1} 个片段... (0%)")
                    
                    while True:
                        line = process.stdout.readline()
                        if not line and process.poll() is not None:
                            break
                            
                        if 'out_time=' in line:
                            try:
                                # 解析时间格式 HH:MM:SS.ms
                                time_str = line.split('=')[1].strip()
                                if time_str != 'N/A':
                                    h, m, s = time_str.split(':')
                                    current_time = float(h) * 3600 + float(m) * 60 + float(s)
                                    progress = min(100, (current_time / self.duration) * 100)
                                    self.log.emit(f"正在生成第 {i + 1}/{segments + 1} 个片段... ({progress:.1f}%)")
                            except:
                                pass  # 忽略解析错误
                    
                    if process.returncode != 0:
                        stderr = process.stderr.read()
                        if stderr.strip():
                            raise Exception(f"FFmpeg 错误: {stderr}")
                    else:
                        self.log.emit(f"正在生成第 {i + 1}/{segments + 1} 个片段... (100%)")
                    
                except Exception as e:
                    if 'N/A' not in str(e):  # 忽略 N/A 相关错误
                        self.log.emit(f"分割片段 {i + 1} 失败: {str(e)}")
                    continue
                
                # 更新总体进度条
                progress = int((file_index + (i + 1)/(segments + 1)) / total_files * 100)
                self.progress.emit(progress)
                
            if self.is_running:
                self.log.emit(f"文件 {filename} 分割完成")
            
        except Exception as e:
            self.log.emit(f"处理文件失败 {input_path}: {str(e)}")

    def stop(self):
        self.is_running = False
        # 终止当前 FFmpeg 进程
        if self.current_process:
            if platform.system() == 'Windows':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.current_process.pid)])
            else:
                self.current_process.terminate()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.load_ui()
        self.setup_connections()
        self.splitter_thread = None
        
        # 设置窗口图标
        icon_path = str(Path(__file__).parent / "logo_icon.ico")
        self.ui.setWindowIcon(QtGui.QIcon(icon_path))
        # 同时设置主窗口的图标
        self.setWindowIcon(QtGui.QIcon(icon_path))
        
        # 检查 FFmpeg 是否可用
        self.check_ffmpeg()
        
    def load_ui(self):
        try:
            loader = QUiLoader()
            ui_file = Path(__file__).parent / "main.ui"
            
            if not ui_file.exists():
                raise FileNotFoundError(f"UI file not found: {ui_file}")
            
            self.ui = loader.load(str(ui_file))
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载UI文件失败: {str(e)}")
            sys.exit(1)
        
    def setup_connections(self):
        self.ui.source_button.clicked.connect(
            lambda: self.select_folder(self.ui.source_path, True)  # True 表示是源目录
        )
        self.ui.output_button.clicked.connect(
            lambda: self.select_folder(self.ui.output_path, False)  # False 表示是输出目录
        )
        self.ui.start_button.clicked.connect(self.start_splitting)
        self.ui.stop_button.clicked.connect(self.stop_splitting)
        
        # 添加文本框变化监听
        self.ui.source_path.textChanged.connect(lambda: self.on_path_changed(True))
        self.ui.output_path.textChanged.connect(lambda: self.on_path_changed(False))

    def on_path_changed(self, is_source):
        """处理路径变化"""
        if is_source:
            path = self.ui.source_path.text()
            if os.path.exists(path):
                # 显示目录内容
                try:
                    files = [f for f in os.listdir(path) 
                            if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.m4v', '.webm'))]
                    self.ui.log_text.append(f"\n源目录内容:")
                    if files:
                        for file in files:
                            self.ui.log_text.append(f"- {file}")
                    else:
                        self.ui.log_text.append("(没有找到视频文件)")
                except Exception as e:
                    self.ui.log_text.append(f"读取目录失败: {str(e)}")
        else:
            path = self.ui.output_path.text()
            if not os.path.exists(path):
                try:
                    os.makedirs(path)
                    self.ui.log_text.append(f"已创建输出目录: {path}")
                except Exception as e:
                    self.ui.log_text.append(f"创建输出目录失败: {str(e)}")

    def select_folder(self, line_edit, is_source):
        """选择文件夹"""
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            line_edit.setText(str(Path(folder)))  # 这会触发 on_path_changed
            
    def start_splitting(self):
        source_dir = self.ui.source_path.text().strip()
        output_dir = self.ui.output_path.text().strip()
        duration = self.ui.duration_spinbox.value()
        
        if not source_dir or not output_dir:
            QMessageBox.warning(self, "警告", "请输入或选择源目录和输出目录")
            return
            
        if not os.path.exists(source_dir):
            QMessageBox.warning(self, "警告", "源目录不存在")
            return
            
        # 检查源目录中是否有视频文件
        video_files = [f for f in os.listdir(source_dir) 
                       if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.m4v', '.webm'))]
        if not video_files:
            QMessageBox.warning(self, "警告", "源目录中没有找到视频文件")
            return
            
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"创建输出目录失败: {str(e)}")
                return
            
        self.splitter_thread = VideoSplitterThread(source_dir, output_dir, duration)
        self.splitter_thread.progress.connect(self.ui.progress_bar.setValue)
        self.splitter_thread.log.connect(self.append_log)
        self.splitter_thread.finished.connect(self.on_splitting_finished)
        
        self.splitter_thread.start()
        
        self.ui.start_button.setEnabled(False)
        self.ui.stop_button.setEnabled(True)
        
    def stop_splitting(self):
        if self.splitter_thread and self.splitter_thread.isRunning():
            self.splitter_thread.stop()  # 使用新的 stop 方法
            self.splitter_thread.wait()
            self.append_log("分割已停止")
            self.ui.progress_bar.setValue(0)
            
        self.ui.start_button.setEnabled(True)
        self.ui.stop_button.setEnabled(False)
        
    def on_splitting_finished(self):
        if self.splitter_thread and self.splitter_thread.is_running:
            self.append_log("分割完成")  # 只在这里输出一次
        self.ui.start_button.setEnabled(True)
        self.ui.stop_button.setEnabled(False)
        
    def append_log(self, message):
        self.ui.log_text.append(message)
        
    def show(self):
        self.ui.show()
        
    def check_ffmpeg(self):
        try:
            # 先检查 ffmpeg 是否在系统路径中
            if platform.system() == 'Windows':
                where_cmd = 'where ffmpeg'
            else:
                where_cmd = 'which ffmpeg'
            
            result = subprocess.run(where_cmd, 
                                  shell=True,
                                  capture_output=True, 
                                  text=True)
                              
            if result.returncode != 0:
                raise FileNotFoundError("找不到 FFmpeg 可执行文件")
            
            # 获取 FFmpeg 版本信息
            version_cmd = ['ffmpeg', '-version']
            result = subprocess.run(version_cmd, 
                                  capture_output=True, 
                                  text=True,
                                  shell=True)
                              
            if result.returncode == 0:
                version_info = result.stdout.replace('\n', ' ').split(' ')[0]
                print(f"FFmpeg 版本信息: {version_info}")
            else:
                raise Exception("FFmpeg 命令执行失败")
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "错误",
                "FFmpeg 未正确安装或未添加到系统路径。\n"
                "请确保：\n"
                "1. 已下载并解压 FFmpeg\n"
                "2. 将 FFmpeg 的 bin 目录添加到系统环境变量 Path 中\n"
                "   当前 Path: " + os.environ.get('PATH', '') + "\n"
                "3. 重启应用程序\n"
                f"错误信息: {str(e)}"
            )
            sys.exit(1)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
