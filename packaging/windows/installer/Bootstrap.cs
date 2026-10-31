// The installer puts each host version in a separate retained directory.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

internal static class Bootstrap {
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    private static extern int MessageBox(IntPtr owner, string text, string caption, uint flags);

    private static bool IsRunning() {
        string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"AIStation-Desktop\ui-active.lock");
        if (!File.Exists(path)) return false;
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("The private application marker is not a regular file.");
        try {
            using (var lease = File.Open(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
                return false;
        } catch (IOException) { return true; }
    }

    [STAThread]
    private static int Main(string[] arguments) {
        try {
            if (arguments.Length == 1 && arguments[0] == "--is-running")
                return IsRunning() ? 2 : 0;
            if (arguments.Length != 0) throw new ArgumentException("Unsupported desktop operation.");
            string root = Path.GetDirectoryName(typeof(Bootstrap).Assembly.Location);
            string script = Path.Combine(root, "WindowsSetup.ps1");
            if (!File.Exists(script)) throw new FileNotFoundException("Please reinstall the complete AI Station package.");
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
            if (!File.Exists(powershell)) throw new FileNotFoundException("Built-in Windows PowerShell is unavailable.");
            var info = new ProcessStartInfo(powershell) {
                Arguments = "-NoLogo -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File \"" + script + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            Process.Start(info);
            return 0;
        } catch (Exception error) {
            MessageBox(IntPtr.Zero, error.Message, "AI Station", 0x10);
            return 1;
        }
    }
}
