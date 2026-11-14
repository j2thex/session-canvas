"""Tiny driver for headless Google Chrome (DevTools protocol over a hand-rolled WebSocket).

Python 3.9 standard library only; used by browser_check.py to click, type, take screenshots and
collect JavaScript errors. Chrome runs with its own throw-away profile, so the person's normal
Chrome windows, logins and history are never touched.
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import time
import urllib.request

CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


class WebSocket(object):
    def __init__(self, url, timeout=5):
        assert url.startswith('ws://')
        hostport, path = url[5:].split('/', 1)
        host, port = hostport.split(':')
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        self.buf = b''
        key = base64.b64encode(os.urandom(16)).decode()
        req = ('GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
               'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n') % (path, hostport, key)
        self.sock.sendall(req.encode())
        head = b''
        while b'\r\n\r\n' not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError('websocket handshake failed')
            head += chunk
        head, self.buf = head.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n', 1)[0]:
            raise RuntimeError('websocket refused: %r' % head[:200])

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise RuntimeError('websocket closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        data = text.encode('utf-8')
        n = len(data)
        hdr = bytearray([0x81])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack('>H', n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack('>Q', n)
        mask = os.urandom(4)
        hdr += mask
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
        self.sock.sendall(bytes(hdr) + masked)

    def recv(self):
        msg = b''
        while True:
            b1, b2 = self._read(2)
            op = b1 & 0x0f
            n = b2 & 0x7f
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
            if op == 8:
                raise RuntimeError('websocket closed by Chrome')
            if op == 9:      # ping -> pong
                self.sock.sendall(bytes([0x8a, 0x80]) + os.urandom(4))
                continue
            if op == 10:
                continue
            msg += payload
            if b1 & 0x80:
                return msg.decode('utf-8', 'replace')

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Browser(object):
    """One headless Chrome with one tab."""

    def __init__(self, workdir, port=9377, width=1600, height=1000, scale=1):
        self.workdir = workdir
        self.port = port
        self.profile = os.path.join(workdir, 'chrome-profile')
        shutil.rmtree(self.profile, ignore_errors=True)
        os.makedirs(self.profile, exist_ok=True)
        self.log = open(os.path.join(workdir, 'chrome.log'), 'wb')
        self.proc = subprocess.Popen([
            CHROME, '--headless=new', '--remote-debugging-port=%d' % port, '--user-data-dir=' + self.profile,
            '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-sync',
            '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
            '--disable-background-networking', '--disable-component-update', '--hide-scrollbars', '--mute-audio',
            '--window-size=%d,%d' % (width, height), 'about:blank'], stdout=self.log, stderr=self.log)
        self.ws = None
        self.msg_id = 0
        self.events = []
        deadline = time.time() + 25
        target = None
        while time.time() < deadline and target is None:
            try:
                with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % port, timeout=2) as r:
                    for t in json.loads(r.read().decode()):
                        if t.get('type') == 'page':
                            target = t
                            break
            except Exception:
                time.sleep(0.2)
        if target is None:
            self.close()
            raise RuntimeError('Chrome did not start (see %s)' % os.path.join(workdir, 'chrome.log'))
        self.ws = WebSocket(target['webSocketDebuggerUrl'])
        for domain in ('Page', 'Runtime', 'Log', 'Network'):
            self.call(domain + '.enable')
        self.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': scale, 'mobile': False})
        self.width, self.height = width, height

    # -- protocol --
    def call(self, method, params=None, timeout=45):
        self.msg_id += 1
        mid = self.msg_id
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                raise RuntimeError('Chrome did not answer %s within %ds (params %s)' % (method, timeout, json.dumps(params)[:200]))
            try:
                m = json.loads(self.ws.recv())
            except socket.timeout:
                if self.ws.buf:
                    raise RuntimeError('Chrome stopped in the middle of a message during %s' % method)
                continue                      # nothing yet: keep waiting until the deadline
            if m.get('id') == mid:
                if 'error' in m:
                    raise RuntimeError('%s: %s' % (method, m['error']))
                return m.get('result', {})
            self.events.append(m)

    def js(self, expr, wait=False, timeout=45):
        r = self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': bool(wait)}, timeout=timeout)
        if r.get('exceptionDetails'):
            d = r['exceptionDetails']
            raise RuntimeError('JS error: %s' % (d.get('exception', {}).get('description') or d.get('text')))
        return r.get('result', {}).get('value')

    def goto(self, url, ready='window.__canvasReady === true', timeout=40):
        self.call('Page.navigate', {'url': url})
        return self.wait(ready, timeout)

    def wait(self, expr, timeout=15, step=0.1):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js(expr):
                    return True
            except RuntimeError:
                pass
            time.sleep(step)
        return False

    def sleep(self, secs):
        """Wait while still reading events (so nothing is missed)."""
        end = time.time() + secs
        while time.time() < end:
            self.js('1')
            time.sleep(0.05)

    # -- input --
    def mouse(self, kind, x, y, button='left', buttons=1, clicks=1, mods=0, **extra):
        p = {'type': kind, 'x': x, 'y': y, 'button': button, 'buttons': buttons, 'clickCount': clicks, 'modifiers': mods}
        p.update(extra)
        self.call('Input.dispatchMouseEvent', p)

    def move(self, x, y):
        self.mouse('mouseMoved', x, y, button='none', buttons=0, clicks=0)

    def click(self, x, y, clicks=1, mods=0):
        self.move(x, y)
        for i in range(1, clicks + 1):
            self.mouse('mousePressed', x, y, clicks=i, mods=mods)
            self.mouse('mouseReleased', x, y, buttons=0, clicks=i, mods=mods)

    def drag(self, x0, y0, x1, y1, steps=12, mods=0, hold=0.0):
        self.move(x0, y0)
        self.mouse('mousePressed', x0, y0, mods=mods)
        for i in range(1, steps + 1):
            t = i / float(steps)
            self.mouse('mouseMoved', x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, clicks=0, mods=mods)
        if hold:
            self.sleep(hold)
        self.mouse('mouseReleased', x1, y1, buttons=0, mods=mods)

    def wheel(self, x, y, dx=0, dy=0, mods=0):
        self.mouse('mouseWheel', x, y, button='none', buttons=0, clicks=0, mods=mods, deltaX=dx, deltaY=dy)

    KEYS = {'Escape': 27, 'Enter': 13, 'Backspace': 8, 'Delete': 46, 'Tab': 9, 'ArrowLeft': 37, 'ArrowUp': 38,
            'ArrowRight': 39, 'ArrowDown': 40, '/': 191, '[': 219, ']': 221, '?': 191, '+': 187, '-': 189, '0': 48}

    def key(self, key, mods=0, text=None):
        """Press one key. `key` is a DOM key name ('Enter', 'f', '/', 'ArrowLeft'…)."""
        vk = self.KEYS.get(key)
        if vk is None and len(key) == 1:
            vk = ord(key.upper())
        p = {'key': key, 'windowsVirtualKeyCode': vk or 0, 'nativeVirtualKeyCode': vk or 0, 'modifiers': mods}
        if text is None and len(key) == 1 and not (mods & 6):
            text = key
        if key == 'Enter':
            text = '\r'
        down = dict(p, type='keyDown' if text else 'rawKeyDown')
        if text:
            down['text'] = text
            down['unmodifiedText'] = text
        self.call('Input.dispatchKeyEvent', down)
        self.call('Input.dispatchKeyEvent', dict(p, type='keyUp'))

    def type(self, text):
        self.call('Input.insertText', {'text': text})

    # -- output --
    def screenshot(self, path):
        r = self.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
        with open(path, 'wb') as fh:
            fh.write(base64.b64decode(r['data']))
        return path

    def set_scale(self, scale):
        self.call('Emulation.setDeviceMetricsOverride', {'width': self.width, 'height': self.height, 'deviceScaleFactor': scale, 'mobile': False})

    def problems(self):
        """JavaScript exceptions, console errors/warnings and failed requests seen so far."""
        out = []
        for m in self.events:
            meth, p = m.get('method'), m.get('params', {})
            if meth == 'Runtime.exceptionThrown':
                d = p.get('exceptionDetails', {})
                out.append('exception: %s' % (d.get('exception', {}).get('description') or d.get('text')))
            elif meth == 'Runtime.consoleAPICalled' and p.get('type') in ('error', 'warning', 'assert'):
                out.append('console.%s: %s' % (p.get('type'), ' '.join(str(a.get('value', a.get('description', ''))) for a in p.get('args', []))))
            elif meth == 'Log.entryAdded' and p.get('entry', {}).get('level') in ('error', 'warning'):
                e = p['entry']
                out.append('log.%s: %s %s' % (e.get('level'), e.get('text'), e.get('url', '')))
            elif meth == 'Network.loadingFailed' and not p.get('canceled'):
                out.append('request failed: %s' % p.get('errorText'))
        return out

    def close(self):
        try:
            if self.ws:
                try:
                    self.call('Browser.close')
                except Exception:
                    pass
                self.ws.close()
        finally:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=8)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            try:
                self.log.close()
            except Exception:
                pass
            shutil.rmtree(self.profile, ignore_errors=True)
