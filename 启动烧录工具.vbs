' ESP32-S3 固件烧录工具 —— 双击启动，全程无任何黑框/命令窗口
Option Explicit

Dim fso, sh, base, pyw, f, p
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)

pyw = ""
For Each f In Array("311", "312", "313", "314")
    p = sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python\Python" & f & "\pythonw.exe")
    If fso.FileExists(p) Then
        pyw = p
        Exit For
    End If
Next

If pyw <> "" Then
    sh.CurrentDirectory = base
    sh.Run """" & pyw & """ """ & base & "\烧录工具.py""", 0, False
Else
    sh.CurrentDirectory = base
    sh.Run "cmd /c py -3.11 """ & base & "\烧录工具.py""", 0, False
End If