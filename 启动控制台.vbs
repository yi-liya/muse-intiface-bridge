' 暮瑟 MuSE 控制台 —— 双击启动，全程无任何黑框/命令窗口
' 用法: 双击本文件。关闭控制台窗口即退出程序。
Option Explicit

Dim fso, sh, base, script, pyw, f, i, found
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)

pyw = ""
For Each f In Array("311", "312", "313", "314")
    Dim p
    p = sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python\Python" & f & "\pythonw.exe")
    If fso.FileExists(p) Then
        pyw = p
        Exit For
    End If
Next

If pyw <> "" Then
    sh.CurrentDirectory = base
    sh.Run """" & pyw & """ """ & base & "\main.py""", 0, False
Else
    ' 没找到 pythonw, 回退到 py 启动器, 同样隐藏窗口
    sh.CurrentDirectory = base
    sh.Run "cmd /c py -3.11 """ & base & "\main.py""", 0, False
End If