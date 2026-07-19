#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
局域网快传
==========

在一台电脑上运行本脚本，同一网络（Wi-Fi/路由器）下的其他电脑、手机
用浏览器打开提示的网址，即可互传文件和文字，无需安装任何东西。

用法:
    python lanshare.py                # 默认端口 8000，文件存到 ./shared
    python lanshare.py -p 9000 -d D:/传输

仅使用 Python 标准库，无需 pip 安装依赖。
注意：没有密码保护，只应在可信的家庭/办公室网络里使用。
"""

import argparse
import json
import os
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SHARE_DIR = "shared"
TEXT_FILE = ".lanshare_text.json"
_text_lock = threading.Lock()

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>局域网快传</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f2f4f8; color: #1f2430; padding: 16px; max-width: 720px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 8px 0 16px; }
  h1 small { font-size: 13px; color: #8a93a6; font-weight: normal; margin-left: 8px; }
  .card { background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 16px;
          box-shadow: 0 1px 3px rgba(20,30,60,.08); }
  .card h2 { font-size: 15px; margin-bottom: 12px; color: #4a5266; }
  #drop { border: 2px dashed #b9c2d4; border-radius: 10px; padding: 28px 16px;
          text-align: center; color: #7c86a0; cursor: pointer; transition: .15s; }
  #drop.over { border-color: #3b6cff; background: #eef3ff; color: #3b6cff; }
  #bar-wrap { display: none; margin-top: 12px; background: #e8ecf4; border-radius: 6px; overflow: hidden; }
  #bar { height: 10px; width: 0; background: #3b6cff; transition: width .2s; }
  #bar-label { font-size: 12px; color: #7c86a0; margin-top: 6px; display: none; }
  textarea { width: 100%; min-height: 84px; border: 1px solid #d5dbe7; border-radius: 8px;
             padding: 10px; font-size: 14px; resize: vertical; font-family: inherit; }
  .btns { margin-top: 10px; display: flex; gap: 10px; }
  button { border: 0; border-radius: 8px; padding: 9px 18px; font-size: 14px; cursor: pointer;
           background: #3b6cff; color: #fff; }
  button.ghost { background: #eef1f7; color: #3b4356; }
  ul { list-style: none; }
  li { display: flex; align-items: center; gap: 10px; padding: 11px 4px;
       border-bottom: 1px solid #eef1f6; }
  li:last-child { border-bottom: 0; }
  .fname { flex: 1; min-width: 0; word-break: break-all; font-size: 14px; }
  .fmeta { font-size: 12px; color: #98a1b3; margin-top: 2px; }
  a.dl { text-decoration: none; background: #eef3ff; color: #3b6cff; padding: 7px 14px;
         border-radius: 8px; font-size: 13px; white-space: nowrap; }
  .del { background: none; color: #c2c9d8; font-size: 16px; padding: 4px 6px; }
  .empty { color: #a7afc0; font-size: 14px; text-align: center; padding: 12px 0; }
  #toast { position: fixed; left: 50%; bottom: 30px; transform: translateX(-50%);
           background: #2a3040; color: #fff; padding: 10px 18px; border-radius: 20px;
           font-size: 13px; opacity: 0; pointer-events: none; transition: .3s; }
  #toast.show { opacity: .95; }
</style>
</head>
<body>
<h1>📡 局域网快传<small>同一网络下的设备打开本页即可互传</small></h1>

<div class="card">
  <h2>发送文件</h2>
  <div id="drop">点击选择文件，或把文件拖到这里<br>（可多选，手机上可直接选相册/文件）</div>
  <input id="fi" type="file" multiple hidden>
  <div id="bar-wrap"><div id="bar"></div></div>
  <div id="bar-label"></div>
</div>

<div class="card">
  <h2>文字剪贴板（两边同步，可传链接/文本）</h2>
  <textarea id="txt" placeholder="在任意设备粘贴文字，点保存；其他设备点复制即可取走"></textarea>
  <div class="btns">
    <button onclick="saveText()">保存</button>
    <button class="ghost" onclick="copyText()">复制</button>
  </div>
</div>

<div class="card">
  <h2>文件列表（点下载即可收取）</h2>
  <ul id="list"></ul>
  <div id="empty" class="empty">还没有文件，从任意设备上传试试</div>
</div>

<div id="toast"></div>

<script>
const $ = id => document.getElementById(id);
let toastTimer;
function toast(msg) {
  $('toast').textContent = msg;
  $('toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.remove('show'), 2200);
}
function fmtSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n/1024).toFixed(1) + ' KB';
  if (n < 1073741824) return (n/1048576).toFixed(1) + ' MB';
  return (n/1073741824).toFixed(2) + ' GB';
}
async function refresh() {
  try {
    const files = await (await fetch('/list')).json();
    const ul = $('list');
    ul.innerHTML = '';
    $('empty').style.display = files.length ? 'none' : 'block';
    for (const f of files) {
      const li = document.createElement('li');
      const enc = encodeURIComponent(f.name);
      li.innerHTML = '<div class="fname">' + f.name.replace(/</g,'&lt;') +
        '<div class="fmeta">' + fmtSize(f.size) + ' · ' + f.time + '</div></div>' +
        '<a class="dl" href="/files/' + enc + '" download>下载</a>' +
        '<button class="del" title="删除" onclick="del(\\'' + enc + '\\')">✕</button>';
      ul.appendChild(li);
    }
  } catch (e) { /* 服务已停止时静默 */ }
}
async function del(enc) {
  if (!confirm('删除这个文件？')) return;
  await fetch('/delete?name=' + enc, { method: 'POST' });
  refresh();
}
function uploadAll(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  let i = 0;
  const next = () => {
    if (i >= files.length) {
      $('bar-wrap').style.display = 'none';
      $('bar-label').style.display = 'none';
      toast('全部上传完成 ✓');
      refresh();
      return;
    }
    const f = files[i++];
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload?name=' + encodeURIComponent(f.name));
    $('bar-wrap').style.display = 'block';
    $('bar-label').style.display = 'block';
    xhr.upload.onprogress = e => {
      if (e.lengthComputable) {
        $('bar').style.width = (e.loaded / e.total * 100).toFixed(1) + '%';
        $('bar-label').textContent = '(' + i + '/' + files.length + ') ' + f.name +
          ' — ' + fmtSize(e.loaded) + ' / ' + fmtSize(e.total);
      }
    };
    xhr.onload = () => { $('bar').style.width = '0'; refresh(); next(); };
    xhr.onerror = () => { toast('上传失败: ' + f.name); next(); };
    xhr.send(f);
  };
  next();
}
$('drop').onclick = () => $('fi').click();
$('fi').onchange = e => { uploadAll(e.target.files); e.target.value = ''; };
$('drop').ondragover = e => { e.preventDefault(); $('drop').classList.add('over'); };
$('drop').ondragleave = () => $('drop').classList.remove('over');
$('drop').ondrop = e => {
  e.preventDefault();
  $('drop').classList.remove('over');
  uploadAll(e.dataTransfer.files);
};
async function loadText() {
  try {
    const d = await (await fetch('/text')).json();
    if (document.activeElement !== $('txt')) $('txt').value = d.text || '';
  } catch (e) {}
}
async function saveText() {
  await fetch('/text', { method: 'POST', body: $('txt').value });
  toast('已保存，其他设备可见');
}
function copyText() {
  $('txt').select();
  navigator.clipboard ? navigator.clipboard.writeText($('txt').value) : document.execCommand('copy');
  toast('已复制到剪贴板');
}
refresh();
loadText();
setInterval(refresh, 5000);
setInterval(loadText, 5000);
</script>
</body>
</html>"""


def safe_name(raw):
    name = os.path.basename(raw.replace("\\", "/")).strip().lstrip(".")
    return name or "file"


def unique_path(directory, name):
    base, ext = os.path.splitext(name)
    path, n = os.path.join(directory, name), 1
    while os.path.exists(path):
        path = os.path.join(directory, "%s (%d)%s" % (base, n, ext))
        n += 1
    return path


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))  # 不会真的发包，只为拿到本机出口 IP
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips) or ["127.0.0.1"]


class Handler(BaseHTTPRequestHandler):
    server_version = "LanShare/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[%s] %s %s" % (time.strftime("%H:%M:%S"),
                              self.address_string(), fmt % args))

    def _reply(self, code, body=b"", ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/":
            self._reply(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif url.path == "/list":
            files = []
            for name in sorted(os.listdir(SHARE_DIR)):
                if name.startswith("."):
                    continue
                p = os.path.join(SHARE_DIR, name)
                if os.path.isfile(p):
                    st = os.stat(p)
                    files.append({"name": name, "size": st.st_size,
                                  "time": time.strftime("%m-%d %H:%M",
                                                        time.localtime(st.st_mtime))})
            files.sort(key=lambda f: f["time"], reverse=True)
            self._reply(200, files)
        elif url.path == "/text":
            with _text_lock:
                text = ""
                tp = os.path.join(SHARE_DIR, TEXT_FILE)
                if os.path.exists(tp):
                    with open(tp, encoding="utf-8") as f:
                        text = json.load(f).get("text", "")
            self._reply(200, {"text": text})
        elif url.path.startswith("/files/"):
            name = safe_name(urllib.parse.unquote(url.path[len("/files/"):]))
            path = os.path.join(SHARE_DIR, name)
            if not os.path.isfile(path):
                self._reply(404, {"error": "not found"})
                return
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''%s" %
                             urllib.parse.quote(name))
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 256)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if url.path == "/upload":
            params = urllib.parse.parse_qs(url.query)
            name = safe_name(urllib.parse.unquote(params.get("name", ["file"])[0]))
            path = unique_path(SHARE_DIR, name)
            remaining = length
            with open(path, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(1024 * 256, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            if remaining > 0:  # 客户端中断，删掉残缺文件
                os.remove(path)
                self._reply(400, {"error": "incomplete"})
                return
            self.log_message("收到文件: %s (%d bytes)", os.path.basename(path), length)
            self._reply(200, {"ok": True, "name": os.path.basename(path)})
        elif url.path == "/text":
            text = self.rfile.read(length).decode("utf-8", "replace")
            with _text_lock:
                with open(os.path.join(SHARE_DIR, TEXT_FILE), "w",
                          encoding="utf-8") as f:
                    json.dump({"text": text}, f, ensure_ascii=False)
            self._reply(200, {"ok": True})
        elif url.path == "/delete":
            params = urllib.parse.parse_qs(url.query)
            name = safe_name(urllib.parse.unquote(params.get("name", [""])[0]))
            path = os.path.join(SHARE_DIR, name)
            if os.path.isfile(path):
                os.remove(path)
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "not found"})


def main():
    global SHARE_DIR
    parser = argparse.ArgumentParser(description="局域网快传")
    parser.add_argument("-p", "--port", type=int, default=8000, help="端口，默认 8000")
    parser.add_argument("-d", "--dir", default="shared", help="文件存放目录，默认 ./shared")
    args = parser.parse_args()
    SHARE_DIR = args.dir
    os.makedirs(SHARE_DIR, exist_ok=True)

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print("=" * 52)
    print("📡 局域网快传已启动，文件保存在: %s" % os.path.abspath(SHARE_DIR))
    print("在同一网络下的手机/电脑浏览器打开：")
    for ip in lan_ips():
        print("    http://%s:%d" % (ip, args.port))
    print("按 Ctrl+C 停止")
    print("=" * 52)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
