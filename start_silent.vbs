' SpriteLens silent launcher: zero-window start via WScript.Shell.Run(0).
' Unlike start.bat (cmd flashes briefly), wscript never opens a console.
' Double-click this file, or point a desktop shortcut at wscript.exe with
' this file as the argument.
Option Explicit

Dim shell, fso, root, pythonw
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"

If fso.FileExists(pythonw) Then
    shell.CurrentDirectory = root
    ' 0 = hidden window, False = do not wait for exit
    shell.Run """" & pythonw & """ main.py", 0, False
Else
    MsgBox "venv not found: " & pythonw & vbCrLf & _
           "Run first:  python -m venv .venv" & vbCrLf & _
           "            .venv\Scripts\pip install -r requirements.txt", _
           16, "SpriteLens"
End If
