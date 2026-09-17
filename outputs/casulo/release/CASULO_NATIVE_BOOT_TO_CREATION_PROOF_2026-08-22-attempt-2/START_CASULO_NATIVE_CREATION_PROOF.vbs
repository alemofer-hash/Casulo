Option Explicit
Dim shell, fso, releaseDir, scriptPath, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
releaseDir = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = releaseDir & "\CASULO_NATIVE_BOOT_TO_CREATION_PROOF.ps1"
If Not fso.FileExists(scriptPath) Then
  MsgBox "O launcher Native nao foi localizado.", 16, "Casulo"
  WScript.Quit 2
End If
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & scriptPath & Chr(34)
shell.Run command, 1, False
