import ctypes, json, sys, threading
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from ctypes import wintypes
from spritelens.web.run import _enable_dpi_awareness
from spritelens.web.desktop_shell import WindowControls
_enable_dpi_awareness()
import webview
css=Path('spritelens/web/static/desktop-shell.css').read_text(encoding='utf-8')
html='<style>'+css+'</style><div class="desktop-titlebar"><div class="window-drag-area">Synthetic title</div><div class="window-controls" style="width:138px">Controls</div></div>'
windows=[]
for mode in ['loaded_old','before_navigation']:
 w=webview.create_window('SpriteLens synthetic drag probe '+mode,html=html,width=960,height=540,frameless=True,easy_drag=False,hidden=True)
 c=WindowControls(w)
 def before(window):print(json.dumps({'before':window.title,'size':[window.native.Size.Width,window.native.Size.Height]}),flush=True)
 w.events.before_show += before
 w.events.before_show += c.install_native_frame
 if mode=='before_navigation':w.events.before_show += c.enable_native_drag
 else:
  def old_enable(window):
   from System import Action
   window.native.Invoke(Action(lambda:setattr(window.native.webview.CoreWebView2.Settings,'IsNonClientRegionSupportEnabled',True)))
  w.events.loaded += old_enable
 windows.append((mode,w,c))
def probe():
 try:
  from System import Action
  u=ctypes.WinDLL('user32',use_last_error=True)
  u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
  u.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
  u.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];u.SendMessageW.restype=ctypes.c_ssize_t
  cbtype=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
  u.EnumChildWindows.argtypes=[wintypes.HWND,cbtype,wintypes.LPARAM]
  for mode,w,c in windows:
   if not w.events.loaded.wait(25):raise RuntimeError('load timeout')
   result={'mode':mode,'hits':[]}
   def inspect():
    hwnd=w.native.Handle.ToInt64();rect=wintypes.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect))
    scale=w.native._scale
    x=rect.left+int(150*scale);y=rect.top+int(20*scale)
    point=(y&65535)<<16 | (x&65535)
    result.update(scale=scale,size=[rect.right-rect.left,rect.bottom-rect.top],setting=bool(w.native.webview.CoreWebView2.Settings.IsNonClientRegionSupportEnabled))
    @cbtype
    def child(handle,_):
     name=ctypes.create_unicode_buffer(256);u.GetClassNameW(handle,name,256)
     result['hits'].append({'class':name.value,'title_hit':u.SendMessageW(handle,0x84,0,point)})
     return True
    u.EnumChildWindows(hwnd,child,0)
   w.native.Invoke(Action(inspect))
   print(json.dumps(result),flush=True)
 finally:
  for _,w,_ in windows:w.destroy()
webview.start(probe,debug=False)
